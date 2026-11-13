"""Arma el libro Excel de consultas a otras intendencias a partir del JSON del tablero.

Uso:
  python3 -I consultas_xlsx.py datos.json consultas.xlsx [--previo consultas_completadas.xlsx]

Con --previo, lo que el equipo ya completó (celdas amarillas) pasa al libro nuevo, fila por fila.

El libro es una lista de trabajo para el equipo de gestión de riesgo:
  - DAM otras intendencias: DAM con maquinaria y beneficio cuyo destino no es Tarapoto. El cuaderno de la
    intendencia no tiene su control; el equipo consulta la modalidad (pago o garantía), el estado de la
    solicitud, la diligencia, la RI y la NCN.
  - Series por ubicar: máquinas vendidas cuya serie no está en las DAM del importador del periodo.
  - DAM 2024 de traslados: DAM anteriores al periodo con traslados de maquinaria; el PIN de cada serie
    confirma o descarta la venta probable.
  - Salidas por verificar: máquinas que una guía de remisión lleva de la ZTE a la ZTC. El equipo anota la DAM
    de la serie, si tiene el beneficio, si tiene solicitud de traslado, el año de la máquina y dónde se verificó.
Las celdas grises vienen del tablero y las amarillas se completan. El libro completado se devuelve al
generador con «generar_datos.py ... --consultas consultas.xlsx».

El libro contiene información con reserva tributaria: no se versiona. Se publica solo dentro de la página
cifrada (ver cifrar.py --adjunto).
"""
import json
import sys
from datetime import date

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HOJA_DAM, HOJA_SERIES, HOJA_2024 = "DAM otras intendencias", "Series por ubicar", "DAM 2024 de traslados"
HOJA_SALIDAS = "Salidas por verificar"
LISTAS = {
    "modalidad": ["Cancelada", "Garantía art. 160", "Carta fianza", "Sin desgravación", "Otra"],
    "moneda": ["S/", "USD"],
    "solicitud": ["Pendiente", "En trámite", "Concluida", "Improcedente", "Sin solicitud"],
    "diligencia": ["Conforme", "No conforme", "Pendiente", "Sin diligencia"],
    "busqueda": ["DAM encontrada", "Importada por otro importador", "Compra local", "No encontrada"],
    "intendencia": ["Tarapoto", "Pucallpa", "Puerto Maldonado", "Iquitos", "Sin destino amazónico"],
    "si_no": ["Sí", "No"],
}
FUENTE = "Arial"
GRIS = PatternFill("solid", fgColor="F2F2F2")
AMARILLO = PatternFill("solid", fgColor="FFF2CC")
CABECERA = PatternFill("solid", fgColor="12302E")
CABECERA_LLENAR = PatternFill("solid", fgColor="7F6000")
BORDE = Border(*(Side(style="thin", color="D9D9D9"),) * 4)


def fecha(x):
    try:
        return date.fromisoformat(x[:10]) if x else None
    except ValueError:
        return None


def previo_de(ruta):
    """Celdas amarillas de un libro ya completado: {hoja: {clave de la fila: {columna: valor}}}."""
    from openpyxl import load_workbook
    wb = load_workbook(ruta, data_only=True)
    claves = {HOJA_DAM: ("DAM",), HOJA_SERIES: ("Factura",), HOJA_2024: ("Traslado", "DAM", "Serie de la DAM"),
              HOJA_SALIDAS: ("Guía principal (clave)", "Serie de la máquina (guía)")}
    out = {}
    for hoja, campos in claves.items():
        if hoja not in wb.sheetnames:
            continue
        ws = wb[hoja]
        cab = [c.value for c in ws[1]]
        llenar = [j for j, c in enumerate(ws[1]) if c.fill and c.fill.fgColor and str(c.fill.fgColor.rgb).endswith("7F6000")]
        for fila in ws.iter_rows(min_row=2, values_only=True):
            clave = tuple(str(fila[cab.index(c_)] or "") for c_ in campos if c_ in cab)
            vals = {cab[j]: fila[j] for j in llenar if j < len(fila) and fila[j] not in (None, "")}
            if vals:
                out.setdefault(hoja, {})[clave] = vals
    return out


def hoja_tabla(wb, nombre, cols, filas, listas=None, formulas=None, previo=None, clave=None):
    """cols: [(título, ancho, tipo)] con tipo «dato», «llenar» o «formula»; filas: listas de valores de las columnas «dato»."""
    ws = wb.create_sheet(nombre)
    for j, (t, ancho, tipo) in enumerate(cols, 1):
        c = ws.cell(row=1, column=j, value=t)
        c.font = Font(name=FUENTE, bold=True, color="FFFFFF", size=10)
        c.fill = CABECERA_LLENAR if tipo == "llenar" else CABECERA
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = ancho
    ws.row_dimensions[1].height = 42
    n_dato = sum(1 for _, _, tipo in cols if tipo == "dato")
    for i, fila in enumerate(filas, 2):
        for j, (t, _, tipo) in enumerate(cols, 1):
            c = ws.cell(row=i, column=j)
            if tipo == "dato":
                c.value = fila[j - 1] if j - 1 < n_dato else None
                c.fill = GRIS
            elif tipo == "llenar":
                c.fill = AMARILLO
                c.value = (previo or {}).get(clave(fila) if clave else None, {}).get(t)
            elif tipo == "formula":
                c.value = formulas[t].format(f=i)
            c.font = Font(name=FUENTE, size=10, bold=(tipo == "formula"))
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = BORDE
            if isinstance(c.value, date) or "Fecha" in t:
                c.number_format = "dd/mm/yyyy"
            elif "Monto" in t or "CIF" in t:
                c.number_format = "#,##0.00"
    ultima = max(2, len(filas) + 1)
    for j, (t, _, tipo) in enumerate(cols, 1):
        lista = (listas or {}).get(t)
        if lista:
            dv = DataValidation(type="list", formula1='"' + ",".join(LISTAS[lista]) + '"', allow_blank=True, showErrorMessage=True,
                                errorTitle="Valor no válido", error="Elija un valor de la lista.")
            ws.add_data_validation(dv)
            dv.add(f"{get_column_letter(j)}2:{get_column_letter(j)}{ultima}")
        elif tipo == "llenar" and "Fecha" in t:
            dv = DataValidation(type="date", operator="between", formula1="DATE(2010,1,1)", formula2="DATE(2035,12,31)", allow_blank=True,
                                showErrorMessage=True, errorTitle="Fecha no válida", error="Escriba la fecha como dd/mm/aaaa.")
            ws.add_data_validation(dv)
            dv.add(f"{get_column_letter(j)}2:{get_column_letter(j)}{ultima}")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ultima}"
    imprimir(ws)
    return ws


def imprimir(ws):
    """Hoja apaisada y ajustada al ancho de la página al imprimir."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def main(r_json, salida, r_previo=None):
    d = json.load(open(r_json, encoding="utf-8"))
    previo = previo_de(r_previo) if r_previo else {}
    maq = {m["k"]: m for m in d["maquinas"]}
    casos = {c["cpe"]: c for c in d["casos"]}
    cli = d["clientes"]
    destinos, aduanas = d["meta"]["destinos"], d["meta"]["aduanas"]
    folio = lambda c: c[3:]
    fx = lambda x: f"{x[8:10]}/{x[5:7]}/{x[:4]}" if x else ""

    # ---------- DAM de otras intendencias con beneficio ----------
    filas = []
    for k, x in d["dams"].items():
        if x["dest"] in ("271", "") or "C-" not in (x["conv"] or ""):
            continue
        ms = [maq[m] for m in x["maqs"] if m in maq]
        ventas = sorted({v for m in ms for v in m["ventas"]})
        cs = [casos[v] for v in ventas if v in casos]
        exp = [m["exp"]["dam"] for m in ms if m.get("exp")]
        if cs and any(c["nivel"] in ("Alta", "Media") for c in cs):
            prio, por = 1, "Máquina vendida con indicios de salida de la ZTE: " + "; ".join(f"{folio(c['cpe'])} ({c['nivel'].lower()})" for c in cs)
        elif ventas or exp:
            prio, por = 2, ("Máquina exportada (DAM " + ", ".join(exp) + "): confirmar que el beneficio se regularizó") if exp else \
                "Máquina vendida (enlazada por serie): confirmar el control de la DAM"
        else:
            prio, por = 3, "Completar el control (no está en el cuaderno de Tarapoto)"
        txt_m = "; ".join(f"{m['cat']} {m['marca'] or ''} {m['modelo'] or ''} · PIN {m['pin'] or 's/d'}".replace("  ", " ") for m in ms[:6]) + \
            (f"; y {len(ms) - 6} más" if len(ms) > 6 else "")
        txt_v = "; ".join(f"{folio(v)} ({fx(casos[v]['f'])}, {casos[v]['cli'][:40].strip()}, {casos[v].get('lugar_fac') or cli.get(casos[v]['ruc'], {}).get('lugar', '')})"
                          if v in casos else folio(v) for v in ventas)
        filas.append([prio, por, k, fecha(x["f"]), aduanas.get(x["ad"], x["ad"]), f"{x['dest']} · {destinos.get(x['dest'], '')}",
                      {"V": "Verde", "D": "Naranja", "F": "Rojo"}.get(x["canal"], x["canal"]),
                      x["conv"].replace("C-", "Código liberatorio ").replace("I-", "TPI "), len(ms), txt_m,
                      round(sum(m["cif"] or 0 for m in ms), 2), txt_v, ", ".join(sorted({c["nivel"] for c in cs})) or ""])
    filas.sort(key=lambda r: (r[0], -(r[3].toordinal() if r[3] else 0)))
    cols_dam = [("Prioridad", 9, "dato"), ("Por qué consultarla", 38, "dato"), ("DAM", 20, "dato"), ("Fecha de numeración", 12, "dato"),
                ("Aduana de despacho", 16, "dato"), ("Intendencia de destino", 16, "dato"), ("Canal", 9, "dato"), ("Beneficio", 15, "dato"),
                ("Series de maquinaria", 10, "dato"), ("Máquinas (tipo, marca, modelo y PIN)", 46, "dato"), ("CIF de la maquinaria (USD)", 14, "dato"),
                ("Ventas enlazadas por serie", 40, "dato"), ("Nivel del caso", 9, "dato"),
                ("Modalidad", 16, "llenar"), ("Monto de tributos", 13, "llenar"), ("Moneda", 8, "llenar"), ("Estado de la solicitud", 14, "llenar"),
                ("Resultado de la diligencia", 14, "llenar"), ("Fecha del reconocimiento físico", 13, "llenar"), ("Fecha de conclusión", 13, "llenar"),
                ("RI o RD", 24, "llenar"), ("Fecha de la RI", 12, "llenar"), ("NCN", 18, "llenar"), ("Fecha de la NCN", 12, "llenar"),
                ("Monto de la NCN (S/)", 13, "llenar"), ("Traslado (expediente y fecha)", 22, "llenar"), ("Observaciones", 36, "llenar")]
    listas_dam = {"Modalidad": "modalidad", "Moneda": "moneda", "Estado de la solicitud": "solicitud", "Resultado de la diligencia": "diligencia"}

    # ---------- Series que no están en las DAM del periodo ----------
    filas_s = []
    for c in d["casos"]:
        if not c["series"] or c["maqs"] or c["tras_prob"] or c["tras"]:     # c["tras"] sin máquina: confirmada con el PIN de la DAM del traslado
            continue
        s = c["series"][0]
        lugar = c.get("lugar_fac") or cli.get(c["ruc"], {}).get("lugar", "")
        filas_s.append([1 if c["nivel"] == "Alta" else 2, folio(c["cpe"]), fecha(c["f"]), c["cli"].strip(), lugar,
                        " ".join(x for x in (c["desc"], s.get("modelo") and "modelo " + s["modelo"]) if x),
                        s["serie"], s.get("motor", ""), s.get("anio", ""), c["nivel"]])
    filas_s.sort(key=lambda r: (r[0], r[1]))
    cols_s = [("Prioridad", 9, "dato"), ("Factura", 11, "dato"), ("Fecha de venta", 12, "dato"), ("Comprador", 34, "dato"),
              ("Lugar en la factura", 26, "dato"), ("Máquina", 34, "dato"), ("Serie de la máquina", 20, "dato"), ("Serie del motor", 16, "dato"),
              ("Año de fabricación", 10, "dato"), ("Nivel del caso", 9, "dato"),
              ("Resultado de la búsqueda", 20, "llenar"), ("DAM encontrada", 20, "llenar"), ("Serie de la DAM", 9, "llenar"),
              ("Intendencia de destino", 16, "llenar"), ("Modalidad", 16, "llenar"), ("Estado de la solicitud", 14, "llenar"), ("Observaciones", 36, "llenar")]
    listas_s = {"Resultado de la búsqueda": "busqueda", "Intendencia de destino": "intendencia", "Modalidad": "modalidad", "Estado de la solicitud": "solicitud"}

    # ---------- DAM anteriores al periodo con traslados de maquinaria ----------
    filas_t = []
    for t in d["traslados"]:
        if not (t["es_maq"] and t["salida"] and not t["maqs"] and t["f"] >= d["meta"]["desde"]):
            continue
        # Ventas ya confirmadas con el PIN (consulta anterior) y ventas probables: las dos alimentan la comparación de la columna J
        conf = list(t.get("venta") or [])
        ventas = list(dict.fromkeys(conf + [p["cpe"] for p in t.get("prob", [])]))
        txt_v = "; ".join((f"{folio(v)} ({casos[v]['cli'][:30].strip()})" if v in casos else folio(v)) + (" — confirmada por el PIN" if v in conf else "")
                          for v in ventas)
        series_fac = "; ".join(f"{folio(v)}: {s['serie']}" for v in ventas for s in (casos.get(v, {}).get("series") or []))
        for dam, serie in t.get("pares") or [[x, ""] for x in t["dams"]]:
            filas_t.append([t["exp"], fecha(t["f"]), t["ri"], dam, serie, txt_v, series_fac])
    cols_t = [("Traslado", 22, "dato"), ("Fecha del traslado", 12, "dato"), ("RI", 24, "dato"), ("DAM", 20, "dato"), ("Serie de la DAM", 9, "dato"),
              ("Ventas probables", 36, "dato"), ("Series en las facturas", 40, "dato"),
              ("PIN o serie de la máquina en la DAM", 24, "llenar"), ("Serie del motor en la DAM", 18, "llenar"),
              ("¿Coincide con una factura?", 12, "formula"), ("Observaciones", 30, "llenar")]
    formulas_t = {"¿Coincide con una factura?": '=IF(H{f}="","",IF(ISNUMBER(SEARCH(TRIM(H{f}),G{f})),"Sí","No"))'}

    # ---------- Salidas detectadas en las guías: lo que falta para armar el caso ----------
    filas_x = []
    PRIO_X = {"Caso armado": 1, "Indicio: guía dada de baja": 1, "Por completar": 2, "Regresó a la ZTE": 3, "Descartada": 4}
    nombre_ruc = lambda q: f"{q['nombre'].strip()} ({q['ruc']})" if q.get("ruc") else q.get("nombre", "")
    for x in d.get("salidas", []):
        if x["estado"] == "Descartada" and not x.get("ver"):
            continue                        # descartadas por los datos del tablero (con traslado o sin beneficio): no hay nada que completar
        nums = ", ".join(d["guias"][i]["num"] for i in x["gs"][:6]) + (f" y {len(x['gs']) - 6} más" if len(x["gs"]) > 6 else "")
        prio_x = 1 if x.get("imp_c") and x["estado"] == "Por completar" else PRIO_X.get(x["estado"], 3)   # la movió otro importador con beneficio
        dam_tab = ((x["dam"]["dam"] + (" serie " + x["dam"]["serie"] if x["dam"]["serie"] else "")) if x["dam"]["fuente"] not in ("", "Verificación del equipo")
                   else ("Revisar las DAM del importador: " + ", ".join(x["dams_cand"])) if x.get("dams_cand") and x["dam"]["benef"] is None else "")
        if "uaderno de la IA" in (x["dam"].get("fuente") or ""):          # DAM completada con el cuaderno de la IA
            d_ = x["dam"]
            dam_tab = (f"{d_['dam']} (cuaderno de la IA: " + (f"del {fx(d_['f'])}, " if len(d_.get("f") or "") == 10 else "")
                       + ("con beneficio" if d_["benef"] else "sin beneficio" if d_["benef"] is False else "beneficio por confirmar")
                       + (", sin solicitud de traslado" if x["tras"] is False else "") + ")")
        if x.get("tras_cand"):              # traslados que pidió ese importador cerca de la salida: la máquina puede estar en uno
            dam_tab = (dam_tab + ". " if dam_tab else "") + "Traslados del importador cerca de la salida: " + ", ".join(x["tras_cand"])
        filas_x.append([prio_x, x["id"], x["estado"], f"{x['maq']['cat']}: {x['maq']['desc']}"[:150], x["maq"]["serie"],
                        nombre_ruc(x["mov"]), nombre_ruc(x["rec"]), fecha(x["f"]), x["p"],
                        f"{x['ubic']['lugar']}" + (f" · {x['ubic']['dir']}" if x["ubic"]["dir"] else "") + f" (al {fx(x['ubic']['f'])})",
                        nums, x["clave"], (("Falta " + "; ".join(x["falta"])) if x["falta"] else x["motivo"])
                        + "".join(f". {p_}" for p_ in x.get("pasos", []) if p_.startswith("Ojo")), dam_tab])     # avisos: puede que no haya salido
    filas_x.sort(key=lambda r: (r[0], r[1]))
    cols_x = [("Prioridad", 9, "dato"), ("Expediente", 10, "dato"), ("Estado", 16, "dato"), ("Máquina", 40, "dato"), ("Serie de la máquina (guía)", 20, "dato"),
              ("Quién la movió", 32, "dato"), ("Quién la recibió", 32, "dato"), ("Fecha de salida", 12, "dato"), ("Partida", 24, "dato"),
              ("Última ubicación conocida", 44, "dato"), ("Guías", 26, "dato"), ("Guía principal (clave)", 26, "dato"), ("Qué falta", 40, "dato"),
              ("DAM según el tablero", 22, "dato"),
              ("Serie (si la guía no la trae)", 20, "llenar"), ("DAM", 20, "llenar"), ("Serie de la DAM", 9, "llenar"), ("Año o fecha de la DAM", 13, "llenar"), ("Año de la máquina", 10, "llenar"),
              ("Importador", 28, "llenar"), ("¿Con beneficio?", 11, "llenar"), ("¿Tiene solicitud de traslado?", 12, "llenar"),
              ("Expediente de traslado", 22, "llenar"), ("Ubicación verificada (dirección y fecha)", 36, "llenar"), ("Observaciones", 40, "llenar")]
    listas_x = {"¿Con beneficio?": "si_no", "¿Tiene solicitud de traslado?": "si_no"}

    # ---------- Libro ----------
    wb = Workbook()
    ws = wb.active
    ws.title = "Instrucciones"
    hoja_tabla(wb, HOJA_SALIDAS, cols_x, filas_x, listas_x, previo=previo.get(HOJA_SALIDAS), clave=lambda r: (str(r[11]), str(r[4] or "")))
    hoja_tabla(wb, HOJA_DAM, cols_dam, filas, listas_dam, previo=previo.get(HOJA_DAM), clave=lambda r: (str(r[2]),))
    hoja_tabla(wb, HOJA_SERIES, cols_s, filas_s, listas_s, previo=previo.get(HOJA_SERIES), clave=lambda r: (str(r[1]),))
    wt = hoja_tabla(wb, HOJA_2024, cols_t, filas_t, None, formulas_t, previo=previo.get(HOJA_2024), clave=lambda r: (str(r[0]), str(r[3]), str(r[4])))
    wt["J1"].comment = Comment("Se calcula solo: compara el PIN escrito en la columna H con las series de las facturas (columna G).", "Tablero")

    f = lambda **k: Font(name=FUENTE, size=k.pop("size", 10), **k)
    ws.column_dimensions["A"].width = 34
    for col in "BCDEFGHIJKL":
        ws.column_dimensions[col].width = 16
    ws.column_dimensions["M"].width = 22
    ws.column_dimensions["N"].width = 30
    imprimir(ws)
    filas_i = [
        ("Consultas a otras intendencias", f(size=14, bold=True)),
        (f"Lista de trabajo del tablero de riesgo de {d['meta']['contribuyente']} (RUC {d['meta']['ruc']}), generada el "
         f"{fx(d['meta']['generado'])}. Contiene información con reserva tributaria (art. 85 del Código Tributario): no la publique "
         "ni la suba al repositorio.", f(italic=True)),
        ("", None),
        ("Cómo usarla", f(size=12, bold=True)),
        ("1. Consulte cada DAM en el sistema: modalidad de la desgravación (pago o garantía), estado de la solicitud, "
         "diligencia en destino, RI y NCN.", f()),
        ("2. Complete solo las celdas amarillas. Las grises vienen del tablero: no las cambie.", f()),
        ("3. Use las listas desplegables cuando las haya. Escriba las fechas como dd/mm/aaaa y los montos sin símbolo. En «Traslado» "
         "escriba el expediente y la fecha; si la DAM no tiene traslado, escriba «Ninguno».", f()),
        ("4. Empiece por la prioridad 1 (máquinas ya vendidas con indicios de salida). La prioridad 3 completa el registro "
         "cuando tenga tiempo; puede dejar filas en blanco.", f()),
        ("5. Devuelva el archivo completado por el chat del tablero, no por el repositorio. El tablero lo incorpora: la ficha de "
         "cada máquina mostrará el control de su DAM, y los casos se confirman o se descartan.", f()),
        ("6. Hoja «Salidas por verificar» (la primera): cada fila es una máquina que una guía lleva de la ZTE a la ZTC. Busque su serie en el "
         "sistema y anote la DAM, el importador, si tiene el beneficio y si tiene solicitud de traslado. En «¿Con beneficio?» elija «No» si la DAM "
         "no está acogida a la Ley 27037 (no desgravada, sin código liberatorio 4438 o sin solicitud): nunca se desgravó ni se devolvió el IGV, "
         "la máquina puede circular fuera de la ZTE y el expediente se descarta. El año se toma del número de la DAM "
         "(118-2024-10-…): anote la fecha solo si la tiene. Si la DAM está en el cuaderno de la IA Tarapoto, basta su número: el tablero completa "
         "la fecha, el importador, el beneficio y si tiene solicitud de traslado. Con «Sí» en beneficio y «No» en traslado, y la salida dentro "
         "de los 4 años (por año calendario: el de la DAM y los 3 siguientes; con DAM de 2022, hasta 2025), el expediente pasa a caso armado. "
         "La fecha de la DAM puede ser completa, mes y año (06/2022) o solo el año. Si conoce el año de la máquina (fabricación o modelo), "
         "anótelo en «Año de la máquina»: sin DAM conocida, cuenta ese año, y pasados los 4 años la salida se descarta.", f()),
        ("", None),
        ("Leyenda", f(size=12, bold=True)),
    ]
    for i, (texto, fuente) in enumerate(filas_i, 1):
        c = ws.cell(row=i, column=1, value=texto or None)
        if fuente:
            c.font = fuente
        largo = len(texto or "") > 60
        c.alignment = Alignment(wrap_text=largo, vertical="top")
        if largo:
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=8)
            ws.row_dimensions[i].height = 15 * (1 + len(texto) // 140)
    ws["A13"], ws["B13"] = "Dato del tablero (no cambiar)", None
    ws["A13"].fill, ws["A13"].font = GRIS, f()
    ws["A14"] = "Celda para completar"
    ws["A14"].fill, ws["A14"].font = AMARILLO, f()
    ws["A15"] = "Se calcula sola"
    ws["A15"].font = f(bold=True)

    ws["A16"] = "Avance"
    ws["A16"].font = f(size=12, bold=True)
    for j, t in enumerate(["Hoja", "Filas", "Completadas", "Avance"], 1):
        c = ws.cell(row=17, column=j, value=t)
        c.font, c.fill = f(bold=True, color="FFFFFF"), CABECERA
    avance = [(HOJA_SALIDAS, "B", "T"), (HOJA_DAM, "C", "N"), (HOJA_SERIES, "B", "K"), (HOJA_2024, "A", "H")]
    for i, (h, col_id, col_llena) in enumerate(avance, 18):
        ws.cell(row=i, column=1, value=h).font = f()
        ws.cell(row=i, column=2, value=f"=COUNTA('{h}'!{col_id}2:{col_id}1000)").font = f()
        ws.cell(row=i, column=3, value=f"=COUNTA('{h}'!{col_llena}2:{col_llena}1000)").font = f()
        c = ws.cell(row=i, column=4, value=f"=IF(B{i}=0,0,C{i}/B{i})")
        c.font, c.number_format = f(), "0%"
    ws["A22"] = "Completadas: filas con la celda clave llena (¿Con beneficio?, Modalidad, Resultado de la búsqueda o PIN)."
    ws["A22"].font = f(italic=True, color="595959")

    ws["A23"] = "Ejemplo de una fila completada en «DAM otras intendencias» (valores de muestra, no son datos reales)"
    ws["A23"].font = f(size=12, bold=True)
    ejemplo = [("Modalidad", "Garantía art. 160"), ("Monto de tributos", 36675.0), ("Moneda", "USD"), ("Estado de la solicitud", "Concluida"),
               ("Resultado de la diligencia", "Conforme"), ("Fecha del reconocimiento físico", date(2026, 3, 14)),
               ("Fecha de conclusión", date(2026, 4, 2)), ("RI o RD", "000123-2026-SUNAT/3U0000"), ("Fecha de la RI", date(2026, 4, 5)),
               ("NCN", ""), ("Fecha de la NCN", ""), ("Monto de la NCN (S/)", ""), ("Traslado (expediente y fecha)", "Ninguno"),
               ("Observaciones", "Garantía liberada; sin traslado registrado")]
    for j, (t, v) in enumerate(ejemplo, 1):
        c = ws.cell(row=24, column=j, value=t)
        c.font, c.fill, c.alignment = f(bold=True, color="FFFFFF"), CABECERA_LLENAR, Alignment(wrap_text=True, vertical="center")
        c = ws.cell(row=25, column=j, value=v if v != "" else None)
        c.font, c.fill, c.alignment = f(), AMARILLO, Alignment(wrap_text=True, vertical="top")
        if isinstance(v, date):
            c.number_format = "dd/mm/yyyy"
        elif isinstance(v, float):
            c.number_format = "#,##0.00"
    ws.row_dimensions[24].height = 42
    ws.row_dimensions[25].height = 30

    ws["A27"] = "Valores de las listas"
    ws["A27"].font = f(size=12, bold=True)
    for i, (t, lista) in enumerate([("Modalidad", "modalidad"), ("Estado de la solicitud", "solicitud"), ("Resultado de la diligencia", "diligencia"),
                                    ("Resultado de la búsqueda", "busqueda"), ("Intendencia de destino", "intendencia"),
                                    ("¿Con beneficio? y ¿Tiene solicitud de traslado?", "si_no")], 28):
        ws.cell(row=i, column=1, value=t).font = f(bold=True)
        ws.cell(row=i, column=2, value=" · ".join(LISTAS[lista])).font = f()
    wb.save(salida)
    print(f"OK {salida}: {len(filas_x)} salidas por verificar, {len(filas)} DAM ({sum(1 for r in filas if r[0] == 1)} de prioridad 1), "
          f"{len(filas_s)} series por ubicar, {len(filas_t)} series de DAM 2024")


if __name__ == "__main__":
    args = sys.argv[1:]
    previo = None
    if "--previo" in args:
        i = args.index("--previo")
        previo = args[i + 1] if i + 1 < len(args) else sys.exit(__doc__)
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    main(*args, r_previo=previo)
