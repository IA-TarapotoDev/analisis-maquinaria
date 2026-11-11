"""Genera los datos del tablero de gestión de riesgo: maquinaria importada con destino a la
Amazonía y su venta.

Fuentes obligatorias:
  1. DAM (CSV, una fila por serie; todos los regímenes y aduanas de destino del importador)
  2. CPE emitidos (TXT separado por «|», una fila por comprobante)
  3. Detalle de CPE emitidos (TXT separado por «|», una fila por ítem)

Fuentes opcionales:
  --domicilios    domicilio fiscal de los clientes (sale de extraer_domicilios.py, padrón reducido del RUC)
  --consulta-ruc  resultados de la consulta múltiple de RUC (actividad, fecha de inscripción, domicilio)
  --facturas-xml  XML (UBL 2.1) de los comprobantes del emisor: archivos, carpetas o ZIP
  --control-ia    cuaderno de control de la intendencia (xlsx/xlsm): solicitud de regularización (beneficio) y traslados
  --trazabilidad  casos documentados a mano (CSV: cpe, serie_maquina, serie_motor, modelo,
                  ubicacion_entrega, direccion_entrega, fuente, nota)
  --transportistas lista simple de transportistas vigilados (TXT: un RUC por línea, opcionalmente
                  seguido del nombre). Entran en la «Lista del día» de guías de remisión.
  --guias        JSON que descarga el extractor de GRE (uno o más). Cada guía se enlaza con su venta
                  (factura citada, serie de la máquina, o tipo de máquina, comprador y fecha) y su
                  punto de llegada (ZTE o ZTC) entra al caso.

Uso:
  python3 -I generar_datos.py DAMS.csv CPE_EMITIDOS.txt CPE_DETALLE.txt salida.json [opciones]

La unidad de seguimiento es la máquina (DAM y serie). Cada venta de maquinaria con indicios de
salida de la zona del beneficio es un caso. El caso reúne la venta, la cadena de comprobantes
(bajas, notas de crédito y reemisiones), la máquina enlazada por su número de serie, el control
de su DAM (tributos, NCN, regularización, RI y traslados) y las otras máquinas de la misma DAM.

Los archivos de origen y el JSON de salida contienen información con reserva tributaria: no se
versionan (ver .gitignore). El JSON se publica solo cifrado (ver cifrar.py).
"""
import argparse
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date, timedelta
from html import unescape as html_unescape
from collections import Counter
from itertools import combinations

import pandas as pd

ADUANAS = {"118": "Marítima del Callao", "235": "Aérea y Postal del Callao", "271": "Tarapoto",
           "226": "Iquitos", "217": "Pucallpa", "280": "Puerto Maldonado", "262": "Desaguadero"}
DESTINOS = {"271": "Tarapoto", "217": "Pucallpa", "280": "Puerto Maldonado", "226": "Iquitos", "": "Sin aduana de destino"}
CANALES = {"V": "Verde", "D": "Naranja", "F": "Rojo"}
MOTIVOS_NC = {  # Catálogo 09 SUNAT
    "01": "Anulación de la operación", "02": "Anulación por error en el RUC",
    "03": "Corrección por error en la descripción", "04": "Descuento global",
    "05": "Descuento por ítem", "06": "Devolución total", "07": "Devolución por ítem",
    "08": "Bonificación", "09": "Disminución en el valor", "10": "Otros conceptos",
    "11": "Ajustes de operaciones de exportación", "12": "Ajustes afectos al IVAP",
    "13": "Ajustes – montos y/o fechas de pago",
}
NC_ANULA = {"01", "02", "03", "06"}      # notas de crédito que dejan sin efecto toda la factura
AFECTACION = {"10": "Gravado", "11": "Gravado (retiro)", "20": "Exonerado", "21": "Exonerado (transferencia gratuita)",
              "30": "Inafecto", "40": "Exportación"}
LINEAS = {"FR": "Repuestos", "FS": "Servicio técnico", "FP": "Maquinaria", "FV": "Otros ingresos"}
HS_MAQ = {"8429", "8701", "8502", "8408", "8426", "8427", "8430", "8474", "8704", "8705"}
MENOR = {"USD": 10000, "PEN": 34000}   # valor de venta mínimo de un caso: debajo están anticipos, accesorios e implementos
TASA_IMP = 0.18      # IGV 16 % + IPM 2 % sobre el valor en aduana: lo que se paga al trasladar a la ZTC
CAT_MERC = {         # tipo de mercancía del cuaderno de traslados → tipos de máquina compatibles
    "MAQUINARIA AMARILLA": {"Excavadora", "Retroexcavadora", "Cargador frontal", "Minicargador", "Motoniveladora",
                            "Rodillo compactador", "Tractor de orugas"},
    "MAQUINARIA AGRICOLA": {"Tractor agrícola", "Implemento agrícola"},
    "MOTORES DIVERSOS": {"Motor diésel", "Motor marino", "Grupo electrógeno"},
}
MERCANCIA = {cat: m for m, cats in (("Maquinaria amarilla", ("Excavadora", "Retroexcavadora", "Cargador frontal", "Minicargador", "Motoniveladora",
                                                             "Rodillo compactador", "Tractor de orugas", "Martillo hidráulico")),
                                     ("Maquinaria agrícola", ("Tractor agrícola", "Implemento agrícola")),
                                     ("Motores y grupos electrógenos", ("Motor diésel", "Motor marino", "Grupo electrógeno"))) for cat in cats}
PUBLICO = re.compile(r"MUNICIPALIDAD|GOBIERNO REGIONAL|MINISTERIO|PROGRAMA |PROYECTO ESPECIAL|"
                     r"GERENCIA (SUB)?REGIONAL|GERENCIA TERRITORIAL|UNIVERSIDAD NACIONAL|EJERCITO|"
                     r"MARINA DE GUERRA|FUERZA AEREA|INSTITUTO NACIONAL|SERVICIO NACIONAL|"
                     r"PETROLEOS DEL PERU|SEGURO SOCIAL|ESSALUD|DIRECCION REGIONAL|UNIDAD EJECUTORA")
REVENDE = re.compile(r"VTA.*MAQUINARIA|VENTA.*MAQUINARIA|ALQUILER.*MAQUINARIA")
SIN_TRASLADO = {"NINGUNO", "NINGUNA", "NO", "SIN TRASLADO", "NO TIENE", "NO REGISTRA"}
NS = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
      "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper()).strip()


def cat_maquina(desc):
    d = norm(desc)
    reglas = [
        ("RETROEXCAVADORA", "Retroexcavadora"), ("EXCAVADORA", "Excavadora"),
        ("MINICARGADOR", "Minicargador"), ("CARGADOR", "Cargador frontal"),
        ("MOTONIVELADORA", "Motoniveladora"), ("RODILLO", "Rodillo compactador"),
        ("TRACTOR AGRIC", "Tractor agrícola"), ("TRACTOR", "Tractor de orugas"),
        ("GRUPO ELECTROGENO", "Grupo electrógeno"), ("MOTOR MARINO", "Motor marino"), ("MOTOR", "Motor diésel"),
        ("MARTILLO", "Martillo hidráulico"), ("RASTRA", "Implemento agrícola"),
        ("ROTOVATOR", "Implemento agrícola"), ("CORTADORA", "Implemento agrícola"),
        ("DISTRIBUIDOR DE CAL", "Implemento agrícola"),
    ]
    for clave, cat in reglas:
        if clave in d:
            return cat
    return "Otros"


def tipo_cliente(tdoc, doc, nombre):
    if tdoc == "0":
        return "No domiciliado"
    if PUBLICO.search(norm(nombre)):
        return "Entidad pública"
    if str(doc).startswith("10"):
        return "Persona natural"
    return "Empresa"


def r2(x):
    return None if x is None or pd.isna(x) else round(float(x), 2)


def fstr(x):
    return x.strftime("%Y-%m-%d") if x is not None and pd.notna(x) else ""


def claves_dam(x):
    """Números de DAM escritos a mano («118-2025-10-511887», «235-2017-10 14949») → aduana-año-régimen-número."""
    return [f"{a}-{b}-{c}-{int(d):06d}" for a, b, c, d in re.findall(r"(\d{3})-(\d{4})-(\d{2})[- ](\d{1,7})", str(x or ""))]


def leer_dams(ruta):
    m = pd.read_csv(ruta, dtype=str)
    for c in ["CNT_COMER", "MTO_FOBDOL", "MTO_FLETEDOL", "MTO_SEGDOL", "MTO_VALORADU"]:
        m[c] = pd.to_numeric(m[c])
    m["f"] = pd.to_datetime(m.FEC_DECLARACION)
    m["COD_REGIMEN"] = m.COD_REGIMEN.str.strip()
    m["dam"] = m.COD_ADUANA + "-" + m.ANN_PRESEN + "-" + m.COD_REGIMEN + "-" + m.NUM_DECLARACION.str.zfill(6)
    m["hs4"] = m.NUM_PARTNANDI.str[:4]
    m["cif_u"] = m.MTO_VALORADU / m.CNT_COMER
    m["conv"] = (m.COD_TIPCONVENIO.fillna("").str.strip() + "-" + m.COD_CONVENIO.fillna("").str.strip()).replace("-", "Sin beneficio")
    m["maq"] = m.hs4.isin(HS_MAQ) | (m.cif_u >= 15000)
    m["dest"] = m.COD_ADUDEST.fillna("").str.strip()
    return m


def datos_maquina(mq):
    """Tipo, marca, modelo e identificadores (PIN/VIN/serie, motor, año, horas) de cada serie de maquinaria."""
    mq = mq.copy()
    mq["cat"] = mq.DES_COMER.map(cat_maquina)
    partes = mq.DES_COMER.str.split(",")
    mq["marca"] = partes.str[1].str.strip()
    mq["modelo"] = partes.str[2].str.strip()
    txt = (mq.DES_FORMAPRESEN.fillna("") + " " + mq.DES_MATECOMP.fillna("") + " " + mq.DES_USOAPLIC.fillna("") + " " + mq.DES_OTROSCARAC.fillna(""))
    mq["pin"] = txt.str.extract(r"PIN(?: NUMBER)?[#: ]*\*?([A-Z0-9]{17})\*?", expand=False)
    vin = txt.str.extract(r"VIN[#: ]*([A-Z0-9]{17})", expand=False)
    sn = txt.str.extract(r"(?:SERIAL(?: NUMBER)?|S/N|SERIE|UNIQUE ID)[#: ]*([A-Z0-9]{8,20})", expand=False)
    mq["id"] = mq.pin.fillna(vin).fillna(sn).fillna("")
    mq["anio"] = txt.str.extract(r"A[ÑN]O DE (?:FABRIC?ACION|MANUFACTURA)[: ]*(\d{4})", expand=False).fillna("")
    mq["motor"] = txt.str.extract(r"(?:ENG(?:INE)?(?: S/N| NUMBER| #)?|NUMERO DE MOTOR)[: ]*([A-Z0-9]{8,12})", expand=False).fillna("")
    mq["horas"] = txt.str.extract(r"HOURS[: ]*([\d.,]+)\s*HRS", expand=False).fillna("")
    mq["usada"] = txt.str.contains(r"\bUSED\b|\bUSAD[OA]\b", regex=True) | (
        pd.to_numeric(mq.anio, errors="coerce") <= mq.f.dt.year - 2)
    return mq


def leer_cpe(ruta):
    e = pd.read_csv(ruta, sep="|", encoding="latin-1", dtype=str, index_col=False).iloc[:, :14]
    e.columns = ["ruc", "tipo", "serie", "nro", "tipo_ref", "tdoc", "doc", "nombre", "moneda",
                 "vv", "igv", "total", "fecha", "estado"]
    for c in ["vv", "igv", "total"]:
        e[c] = pd.to_numeric(e[c])
    e["f"] = pd.to_datetime(e.fecha, format="%m/%d/%Y")
    e["linea"] = e.serie.str[:2].map(LINEAS).fillna("Otra")
    e["cpe"] = e.tipo + "-" + e.serie + "-" + e.nro
    e["nombre"] = e.nombre.str.replace(r"\s+", " ", regex=True).str.strip()
    e["tcli"] = [tipo_cliente(t, d, n) for t, d, n in zip(e.tdoc, e.doc, e.nombre)]
    return e


def leer_detalle(ruta):
    dl = pd.read_csv(ruta, sep="|", encoding="latin-1", dtype=str, index_col=False)
    dl["cpe"] = dl.cod_cpe + "-" + dl.num_serie_cpe + "-" + dl.num_cpe
    return dl


def ubicador(r_ubi):
    """Devuelve una función (departamento, provincia, distrito) -> fila del ubigeo (o None)."""
    u = pd.read_csv(r_ubi, dtype=str).fillna("")
    u = u[u.ubigeo.str.fullmatch(r"\d{6}")]
    k = lambda x: " ".join(re.sub(r"[^A-Z ]", " ", norm(x)).split())
    por_3 = {(k(r.departamento), k(r.provincia), k(r.distrito)): r for r in u.itertuples()}
    por_2 = {}
    for r in u.itertuples():
        por_2.setdefault((k(r.departamento), k(r.distrito)), []).append(r)

    def buscar(dep, prov, dist):
        r = por_3.get((k(dep), k(prov), k(dist)))
        if r is None:
            c = por_2.get((k(dep), k(dist)), [])
            r = c[0] if len(c) == 1 else None
        return r
    return buscar


# ---------------------------------------------------------------- XML de los comprobantes

def fuentes_xml(rutas):
    """(nombre, bytes) de cada XML: archivos sueltos, carpetas (recursivo) y ZIP, también ZIP dentro de ZIP."""
    def de_zip(z):
        for n in z.namelist():
            if n.lower().endswith(".xml"):
                yield n, z.read(n)
            elif n.lower().endswith(".zip"):
                try:
                    yield from de_zip(zipfile.ZipFile(io.BytesIO(z.read(n))))
                except zipfile.BadZipFile:
                    print(f"Aviso: {n} no es un ZIP válido", file=sys.stderr)
    for r in rutas or []:
        if os.path.isdir(r):
            for raiz, _, archivos in os.walk(r):
                for a in sorted(archivos):
                    p = os.path.join(raiz, a)
                    if a.lower().endswith(".xml"):
                        with open(p, "rb") as f:
                            yield p, f.read()
                    elif zipfile.is_zipfile(p):
                        yield from de_zip(zipfile.ZipFile(p))
                    elif a.lower().endswith((".7z", ".rar")):
                        print(f"Aviso: {p} está comprimido en {a.rsplit('.', 1)[-1]}; descomprímalo antes", file=sys.stderr)
        elif zipfile.is_zipfile(r):
            yield from de_zip(zipfile.ZipFile(r))
        elif os.path.isfile(r):
            with open(r, "rb") as f:
                yield r, f.read()


def leer_facturas_xml(rutas):
    """Lee los comprobantes en XML (UBL 2.1 de SUNAT). Devuelve:
    - items: una fila por ítem con la serie de la máquina y del motor que el emisor escribe en la descripción
    - docs: el comprobante completo (cabecera, partes, ítems, tributos, totales, pago y documento que modifica)
      para mostrarlo en el tablero
    - errores: archivos que no se pudieron leer."""
    import xml.etree.ElementTree as ET
    tipos = {"Invoice": "01", "CreditNote": "07", "DebitNote": "08"}
    filas, docs, errores, repetidos = [], {}, [], []
    for nombre, contenido in fuentes_xml(rutas):
        try:
            raiz = ET.fromstring(contenido)
        except ET.ParseError:
            errores.append(os.path.basename(nombre))
            continue
        tag = raiz.tag.split("}")[-1]
        if tag not in tipos:      # constancias de recepción (CDR) y otros XML
            continue

        def t(p, n=raiz):
            return ((n.findtext(p, default="", namespaces=NS) if n is not None else "") or "").strip()

        def num(p, n=raiz):
            v = t(p, n)
            try:
                return float(v) if v else None
            except ValueError:
                return None
        tipo = tipos[tag]
        cpe = f"{tipo}-{t('cbc:ID')}"
        if cpe in docs:
            repetidos.append(cpe)
            continue
        sup = raiz.find("cac:AccountingSupplierParty/cac:Party", NS)
        reg = sup.find("cac:PartyLegalEntity/cac:RegistrationAddress", NS) if sup is not None else None
        cli = raiz.find("cac:AccountingCustomerParty/cac:Party", NS)
        dcli = cli.find("cac:PostalAddress", NS) if cli is not None else None
        if (dcli is None or not t("cac:AddressLine/cbc:Line", dcli)) and cli is not None:
            dcli = cli.find("cac:PartyLegalEntity/cac:RegistrationAddress", NS)
        id_cli = cli.find("cac:PartyIdentification/cbc:ID", NS) if cli is not None else None
        lineas = []
        for ln in raiz.findall("cac:InvoiceLine", NS) + raiz.findall("cac:CreditNoteLine", NS) + raiz.findall("cac:DebitNoteLine", NS):
            cant = next((x for x in (ln.find(f"cbc:{q}Quantity", NS) for q in ("Invoiced", "Credited", "Debited")) if x is not None), None)
            desc = [d.text.strip() for d in ln.findall("cac:Item/cbc:Description", NS) if d.text and d.text.strip()]
            precio_con = next((num("cbc:PriceAmount", p) for p in ln.findall("cac:PricingReference/cac:AlternativeConditionPrice", NS)
                               if t("cbc:PriceTypeCode", p) == "01"), None)
            afect = t("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReasonCode", ln)
            lineas.append({"n": t("cbc:ID", ln), "cant": float(cant.text) if cant is not None and cant.text else None,
                           "und": cant.get("unitCode", "") if cant is not None else "", "desc": desc,
                           "cod": t("cac:Item/cac:SellersItemIdentification/cbc:ID", ln),
                           "vu": num("cac:Price/cbc:PriceAmount", ln), "pu": precio_con, "valor": num("cbc:LineExtensionAmount", ln),
                           "igv": num("cac:TaxTotal/cbc:TaxAmount", ln), "afect": afect, "afect_t": AFECTACION.get(afect, "")})
            texto = norm(" / ".join(desc))
            busca = lambda pat: (re.search(pat, texto) or [None, ""])[1].strip()
            filas.append({"cpe": cpe, "f": t("cbc:IssueDate"), "mon": t("cbc:DocumentCurrencyCode"), "texto": " / ".join(desc),
                          "serie": busca(r"SERIE (?:DE )?MAQUINA[: ]*([A-Z0-9-]{5,20})") or busca(r"\bPIN[: ]*([A-Z0-9]{17})") or busca(r"\bVIN[: ]*([A-Z0-9]{17})"),
                          "motor": busca(r"SERIE (?:DE )?MOTOR[: ]*([A-Z0-9-]{5,20})"),
                          "modelo": busca(r"MODELO[: ]*([A-Z0-9.\- ]+?)(?: /|$)"), "marca": busca(r"MARCA[: ]*([A-Z0-9.\- ]+?)(?: /|$)"),
                          "anio": busca(r"ANO DE FABRICACION[: ]*(\d{4})"), "horas": busca(r"HORAS DE USO[: ]*([\d.,]+)"),
                          "afect": afect, "valor": num("cbc:LineExtensionAmount", ln)})
        pago = [{"id": t("cbc:PaymentMeansID", p), "monto": num("cbc:Amount", p), "f": t("cbc:PaymentDueDate", p)}
                for p in raiz.findall("cac:PaymentTerms", NS) if t("cbc:ID", p) == "FormaPago"]
        trib = [{"t": t("cac:TaxCategory/cac:TaxScheme/cbc:Name", s), "base": num("cbc:TaxableAmount", s), "monto": num("cbc:TaxAmount", s)}
                for s in raiz.findall("cac:TaxTotal/cac:TaxSubtotal", NS)]
        ref = raiz.find("cac:BillingReference/cac:InvoiceDocumentReference", NS)
        docs[cpe] = {
            "cpe": cpe, "tipo": tipo, "id": t("cbc:ID"), "f": t("cbc:IssueDate"), "hora": t("cbc:IssueTime"), "venc": t("cbc:DueDate"),
            "mon": t("cbc:DocumentCurrencyCode"), "oc": t("cac:OrderReference/cbc:ID"),
            "op": (raiz.find("cbc:InvoiceTypeCode", NS).get("listID", "") if raiz.find("cbc:InvoiceTypeCode", NS) is not None else ""),
            "emisor": {"ruc": t("cac:PartyIdentification/cbc:ID", sup), "nombre": t("cac:PartyLegalEntity/cbc:RegistrationName", sup),
                       "est": t("cbc:AddressTypeCode", reg), "dir": t("cac:AddressLine/cbc:Line", reg),
                       "lugar": ", ".join(x for x in (t("cbc:District", reg), t("cbc:CityName", reg), t("cbc:CountrySubentity", reg)) if x)},
            "cliente": {"doc": (id_cli.text or "").strip() if id_cli is not None else "", "tdoc": id_cli.get("schemeID", "") if id_cli is not None else "",
                        "nombre": t("cac:PartyLegalEntity/cbc:RegistrationName", cli), "dir": t("cac:AddressLine/cbc:Line", dcli),
                        "lugar": ", ".join(x for x in (t("cbc:District", dcli), t("cbc:CityName", dcli), t("cbc:CountrySubentity", dcli)) if x)},
            "notas": [n.text.strip() for n in raiz.findall("cbc:Note", NS) if n.text and n.text.strip()],
            "guias": [x.text.strip() for x in raiz.findall("cac:DespatchDocumentReference/cbc:ID", NS) if x.text],
            "pago": pago, "trib": trib, "lineas": lineas,
            "tot": {"valor": num("cac:LegalMonetaryTotal/cbc:LineExtensionAmount") or num("cac:RequestedMonetaryTotal/cbc:LineExtensionAmount"),
                    "igv": num("cac:TaxTotal/cbc:TaxAmount"), "dscto": num("cac:LegalMonetaryTotal/cbc:AllowanceTotalAmount"),
                    "total": num("cac:LegalMonetaryTotal/cbc:PayableAmount") or num("cac:RequestedMonetaryTotal/cbc:PayableAmount")},
            "ref": None if ref is None else {"id": t("cbc:ID", ref), "tipo": t("cbc:DocumentTypeCode", ref),
                                             "mot": t("cac:DiscrepancyResponse/cbc:ResponseCode"),
                                             "mot_t": t("cac:DiscrepancyResponse/cbc:Description")},
        }
        extra = {x.get("name"): (x.text or "").strip() for x in raiz.iter() if x.tag.split("}")[-1] == "Text" and x.get("name")}
        docs[cpe]["cliente"]["lugar_fac"] = extra.get("DisProDepCliente", "")
        docs[cpe]["emisor"]["sede"] = extra.get("DatosOfic", "")
    items = pd.DataFrame(filas, columns=["cpe", "f", "mon", "texto", "serie", "motor", "modelo", "marca", "anio", "horas", "afect", "valor"])
    return items, docs, errores, repetidos


# ---------------------------------------------------------------- cuaderno de control de la intendencia

def pares_traslado(num_dam, series):
    """(DAM, serie) de cada máquina de un traslado. La columna de series separa con «/» las series de cada DAM;
    si el traslado tiene una sola DAM, todas las series son suyas. Si no se puede asignar, devuelve []."""
    dams = claves_dam(num_dam)
    grupos = [g for g in (re.findall(r"\d+", x) for x in str(series or "").split("/")) if g]
    if len(dams) == 1:
        return [(dams[0], int(n)) for g in grupos for n in g]
    if dams and len(grupos) == len(dams):
        return [(d, int(n)) for d, g in zip(dams, grupos) for n in g]
    return []


def leer_control_ia(ruta, ruc):
    """Cuaderno de control de la intendencia (xlsx/xlsm), solo para el RUC indicado. Devuelve:
    - ctl: {dam: {"control": {...}}}: la solicitud de regularización de cada DAM y su resultado (beneficio)
    - traslados: lista de expedientes de traslado con sus pares (DAM, serie)
    - meta: verificación del art. 2 y complejidad.
    Criterio del equipo: si la DAM tiene solicitud de regularización, tiene el beneficio (aunque la diligencia esté
    pendiente o haya sido no conforme). No lo tiene si «Resultado_solicitud» dice Improcedente o «Sin solicitud de
    reconocimiento». La diligencia, el reconocimiento físico, las RI, las NCN y los tributos no se usan."""
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)

    def hoja(n):
        if n not in wb.sheetnames:
            return pd.DataFrame()
        rows = list(wb[n].iter_rows(values_only=True))
        h = next((i for i, r in enumerate(rows[:15]) if sum(isinstance(c, str) for c in r) >= 5), None)
        if h is None:
            return pd.DataFrame()
        cols = [str(c).strip() if c is not None else f"c{j}" for j, c in enumerate(rows[h])]
        return pd.DataFrame([r for r in rows[h + 1:] if any(c is not None for c in r)], columns=cols)
    txt = lambda v: "" if v is None or (not isinstance(v, str) and pd.isna(v)) else (v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v).strip())
    num = lambda v: float(v) if isinstance(v, (int, float)) and v == v else None
    del_ruc = lambda df, col: df[df[col].astype(str).str.contains(ruc)] if len(df) and col in df else df.iloc[0:0]
    ctl = {}
    # ConsolidadoT (las hojas de cada especialista repiten lo mismo y no se leen) y, para las DAM que aún no están
    # consolidadas, «Ingreso de DAM»: la solicitud ya se presentó, así que cuenta como con beneficio.
    for nombre in ("ConsolidadoT", "Ingreso de DAM"):
        ct = hoja(nombre)
        if not len(ct) or "Num_DAM" not in ct or "RUC_Importador" not in ct:
            continue
        # «Resultado_solicitud» (columna AY); en el cuaderno real la cabecera dice «Resultado_Solicud»
        col_res = next((c for c in ct.columns if re.sub(r"[^A-Z]", "", norm(c)).startswith("RESULTADOSOLIC")), None)
        if nombre == "ConsolidadoT" and not col_res:
            print("AVISO control IA: ConsolidadoT no tiene la columna «Resultado_solicitud»: todas sus DAM se toman con beneficio")
        for _, r in del_ruc(ct, "RUC_Importador").iterrows():
            for k in claves_dam(r.Num_DAM):
                if "control" in ctl.get(k, {}):
                    continue
                ctl.setdefault(k, {})["control"] = {"hoja": nombre, "nsol": txt(r.get("NroSolic_Reg")),
                                                    "resultado": txt(r.get(col_res)) if col_res else ""}
    meta = {"art2": [], "complejidad": None}
    vistos = set()
    for _, r in del_ruc(hoja("ConsolidadoA2"), "RUC_Importador").iterrows():
        inf = txt(r.get("Nro_Informe_Art.2"))
        if inf in vistos:
            continue
        vistos.add(inf)
        meta["art2"].append({"periodo": txt(r.get("Periodo_Verificacion")), "informe": inf, "f": txt(r.get("Fecha_Inform_Art2")),
                             "resultado": txt(r.get("RESULTADO")), "aduana": txt(r.get("Aduana_Jurisdiccion"))})
    if "Complejidad" in wb.sheetnames:
        filas_c = list(wb["Complejidad"].iter_rows(values_only=True))
        media = next((r[1] for r in filas_c if r and r[0] and "Media global" in str(r[0])), None)
        for r in filas_c:
            vals = [c for c in r if c is not None]
            for j, c in enumerate(vals[:-2]):
                if str(c).strip() == ruc and isinstance(vals[j + 1], (int, float)):
                    meta["complejidad"] = {"valor": round(float(vals[j + 1]), 3), "n": int(vals[j + 2]) if isinstance(vals[j + 2], (int, float)) else None,
                                           "media": round(float(media), 3) if isinstance(media, (int, float)) else None}
    # Alcance: toda la maquinaria con beneficio. Resumen por importador (sin series: el cuaderno no las trae)
    CLASES = {"MAQUINARIA AMARILLA": "amarilla", "MAQUINARIA AGRICOLA": "agricola", "MAQUINARIA DE USO INDUSTRIAL": "otras",
              "GRUPO ELECTROGENO": "otras", "MOTORES DIVERSOS": "otras", "MOTORES FUERA DE BORDA": "otras"}
    imp, ct = {}, hoja("ConsolidadoT")
    if len(ct) and "Tipo_Mercancia" in ct and "RUC_Importador" in ct:
        col_res = next((c for c in ct.columns if re.sub(r"[^A-Z]", "", norm(c)).startswith("RESULTADOSOLIC")), None)
        for _, r in ct.iterrows():
            clase, ruc_i, dams_ = CLASES.get(norm(r.get("Tipo_Mercancia"))), txt(r.get("RUC_Importador")), claves_dam(r.get("Num_DAM"))
            if not clase or not re.fullmatch(r"\d{11}", ruc_i) or not dams_:
                continue
            x = imp.setdefault(ruc_i, {"ruc": ruc_i, "nombre": re.sub(r"\s+", " ", txt(r.get("Nombre_Importador"))), "dams": 0, "amarilla": 0, "agricola": 0,
                                       "otras": 0, "sin_benef": 0, "anios": Counter(), "ciudades": Counter(), "tipos": Counter(), "tras": 0})
            x["dams"] += 1
            x[clase] += 1
            x["anios"][dams_[0].split("-")[1]] += 1
            x["ciudades"][txt(r.get("Ciudad_Mercancia")).title()] += 1
            if clase == "amarilla":
                x["tipos"][norm(r.get("Mercancía"))[:24].title()] += 1
            if col_res and norm(txt(r.get(col_res))).startswith(("IMPROCEDENTE", "SIN SOLICITUD")):
                x["sin_benef"] += 1
    tr_todos = hoja("Traslados")
    meta["traslados_maq"] = {"total": 0, "anios": "", "solicitantes": 0}
    if len(tr_todos) and "Tipo_Mercancia" in tr_todos:
        tm = tr_todos[tr_todos.Tipo_Mercancia.map(lambda v: norm(v) in ("MAQUINARIA AMARILLA", "MAQUINARIA AGRICOLA"))]
        am = tm[tm.Tipo_Mercancia.map(lambda v: norm(v) == "MAQUINARIA AMARILLA")]
        for ruc_i, n in Counter(txt(v) for v in tm.Doc_Solicitante).items():
            if ruc_i in imp:
                imp[ruc_i]["tras"] = n
        anios = sorted({txt(v)[:4] for v in am.Fecha_Expediente if txt(v)[:4].isdigit()})
        meta["traslados_maq"] = {"total": int(len(am)), "anios": f"{anios[0]} a {anios[-1]}" if anios else "",
                                 "solicitantes": len({txt(v) for v in am.Doc_Solicitante}),
                                 "no_importador": int(sum(1 for v in am.Doc_Solicitante if txt(v) not in imp))}
    meta["importadores"] = sorted(({**x, "anios": dict(sorted(x["anios"].items())), "ciudades": [k for k, _ in x["ciudades"].most_common(3)],
                                    "tipos": [k for k, _ in x["tipos"].most_common(3)]} for x in imp.values()),
                                  key=lambda x: -(x["amarilla"] * 3 + x["agricola"] + x["otras"]))
    traslados = []
    for _, r in del_ruc(hoja("Traslados"), "Doc_Solicitante").iterrows():
        traslados.append({"exp": txt(r.get("N_Expediente")), "f": txt(r.get("Fecha_Expediente"))[:10], "tipo": txt(r.get("Tipo_Traslado")),
                          "merc": txt(r.get("Tipo_Mercancia")), "cant": num(r.get("Cantidad_Trasladada")),
                          "monto": num(r.get("Monto_Pagado_Garantizado")), "doc": txt(r.get("Tipo_Documento")), "ndoc": txt(r.get("N_Documento")),
                          "ri": txt(r.get("Num_Res")), "ri_f": txt(r.get("Fecha_res"))[:10], "res": txt(r.get("Resultado")).capitalize(),
                          "dams": claves_dam(r.get("Num_DAM")), "pares": pares_traslado(r.get("Num_DAM"), r.get("Series_DAM"))})
    return ctl, traslados, meta


def leer_consultas(ruta):
    """Libro de consultas completado por el equipo (ver consultas_xlsx.py). Devuelve:
    - dam: {dam: {"control": {...}, "ncn": [...], "fuente": ...}} con el control informado por la IA de destino
    - series: {cpe: {...}} con la DAM ubicada para una serie que no estaba en las DAM del periodo
    - pin: [{exp, dam, serie, pin, motor}] de las DAM anteriores al periodo con traslados; pin_filas: filas por traslado"""
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)

    def filas(nombre):
        if nombre not in wb.sheetnames:
            return []
        rows = list(wb[nombre].iter_rows(values_only=True))
        if not rows:
            return []
        cab = [str(c or "").strip() for c in rows[0]]
        return [dict(zip(cab, r)) for r in rows[1:] if any(v not in (None, "") for v in r)]
    txt = lambda v: "" if v is None else (v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v).strip())

    def fch(v):
        if hasattr(v, "strftime"):
            return v.strftime("%Y-%m-%d")
        m_ = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", txt(v))
        return f"{m_[3]}-{int(m_[2]):02d}-{int(m_[1]):02d}" if m_ else txt(v)[:10]

    def num(v):
        if isinstance(v, (int, float)):
            return float(v)
        t_ = txt(v).replace("S/", "").replace("USD", "").replace(",", "").strip()
        return float(t_) if re.fullmatch(r"\d+(\.\d+)?", t_) else None
    out = {"dam": {}, "series": {}, "pin": [], "pin_filas": Counter()}
    llenar = ("Modalidad", "Monto de tributos", "Estado de la solicitud", "Resultado de la diligencia", "Fecha del reconocimiento físico",
              "Fecha de conclusión", "RI o RD", "NCN", "Traslado (expediente y fecha)", "Observaciones")
    for r in filas("DAM otras intendencias"):
        dam = (claves_dam(r.get("DAM")) or [""])[0]
        if not dam or not any(txt(r.get(c_)) for c_ in llenar):
            continue
        modal, sol = txt(r.get("Modalidad")), txt(r.get("Estado de la solicitud"))
        mon = {"S/": "PEN", "USD": "USD"}.get(txt(r.get("Moneda")).upper(), "") or \
            ("PEN" if norm(modal) == "CANCELADA" else "USD" if norm(modal).startswith("GARANTIA") else "")
        control = {"tipo": modal, "dilig": txt(r.get("Resultado de la diligencia")), "fin": "", "ri": txt(r.get("RI o RD")),
                   "ri_f": fch(r.get("Fecha de la RI")), "estado": "", "igv": None, "ipm": None, "adv": None,
                   "trib_total": num(r.get("Monto de tributos")), "mon": mon,
                   "sol_estado": sol,
                   "f_rf": fch(r.get("Fecha del reconocimiento físico")), "f_dil": fch(r.get("Fecha de conclusión")),
                   "tras_txt": txt(r.get("Traslado (expediente y fecha)")), "obs": txt(r.get("Observaciones"))}
        ncn = [{"ri": control["ri"], "ri_f": control["ri_f"], "peco": "", "amaz": txt(r.get("NCN")), "f": fch(r.get("Fecha de la NCN")),
                "total": num(r.get("Monto de la NCN (S/)")), "anulada": False}] if txt(r.get("NCN")) else []
        out["dam"][dam] = {"control": control, "ncn": ncn, "fuente": "Consulta del equipo a la intendencia de destino"}
    for r in filas("Series por ubicar"):
        fac = txt(r.get("Factura"))
        if fac and (txt(r.get("Resultado de la búsqueda")) or txt(r.get("DAM encontrada"))):
            out["series"]["01-" + fac] = {"resultado": txt(r.get("Resultado de la búsqueda")) or "DAM encontrada", "dam": txt(r.get("DAM encontrada")),
                                          "serie": txt(r.get("Serie de la DAM")), "intendencia": txt(r.get("Intendencia de destino")),
                                          "modalidad": txt(r.get("Modalidad")), "estado": txt(r.get("Estado de la solicitud")), "obs": txt(r.get("Observaciones"))}
    out["salidas"] = {}

    def anio_o_fecha(v):
        """«2022», 2022 o una fecha completa → «2022» o «2022-05-17»."""
        t_ = fch(v)
        m_ = re.fullmatch(r"(\d{4})(\.0)?", t_.strip())
        return m_[1] if m_ else t_
    for r in filas("Salidas por verificar"):
        clave = txt(r.get("Guía principal (clave)"))
        campos = {"serie": re.sub(r"[^A-Z0-9]", "", norm(txt(r.get("Serie (si la guía no la trae)")))), "dam": (claves_dam(r.get("DAM")) or [txt(r.get("DAM"))])[0],
                  "serie_dam": txt(r.get("Serie de la DAM")).split(".")[0], "f_dam": anio_o_fecha(r.get("Año o fecha de la DAM")), "imp": txt(r.get("Importador")),
                  "benef": txt(r.get("¿Con beneficio?")), "tras": txt(r.get("¿Tiene solicitud de traslado?")), "exp": txt(r.get("Expediente de traslado")),
                  "ubic": txt(r.get("Ubicación verificada (dirección y fecha)")), "obs": txt(r.get("Observaciones"))}
        if clave and any(campos.values()):
            out["salidas"][clave] = campos
    for r in filas("DAM 2024 de traslados"):
        exp_ = txt(r.get("Traslado"))
        out["pin_filas"][exp_] += 1
        if txt(r.get("PIN o serie de la máquina en la DAM")):
            out["pin"].append({"exp": exp_, "dam": txt(r.get("DAM")), "serie": txt(r.get("Serie de la DAM")),
                               "pin": txt(r.get("PIN o serie de la máquina en la DAM")), "motor": txt(r.get("Serie del motor en la DAM"))})
    return out


# ---------------------------------------------------------------- domicilio fiscal y actividad

def ruc_valido(ruc):
    """RUC peruano: prefijo 10, 15, 16, 17 o 20 y dígito verificador (módulo 11)."""
    if not re.fullmatch(r"(10|15|16|17|20)\d{9}", ruc or ""):
        return False
    dv = 11 - sum(p * int(d) for p, d in zip((5, 4, 3, 2, 7, 6, 5, 4, 3, 2), ruc)) % 11
    return {10: 0, 11: 1}.get(dv, dv) == int(ruc[10])


def leer_transportistas(ruta):
    """Lista simple de transportistas vigilados: un RUC por línea, opcionalmente seguido del nombre
    (separado por espacio, coma, punto y coma, barra vertical, tabulación o guion). Se ignoran las
    líneas vacías, los comentarios (#), los RUC repetidos y los no válidos (se avisa el número de línea)."""
    if not ruta:
        return []
    texto = None
    for cod in ("utf-8-sig", "latin-1"):
        try:
            with open(ruta, encoding=cod) as f:
                texto = f.read()
            break
        except UnicodeDecodeError:
            continue
    out, vistos = [], set()
    for i, ln in enumerate((texto or "").splitlines(), 1):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"^(?:RUC\W*)?(\d{11})(?:\s*[;,|\t-]\s*|\s+|$)(.*)$", ln, re.I)
        if not m or not ruc_valido(m.group(1)):
            print(f"AVISO transportistas: línea {i} ignorada (no empieza con un RUC válido de 11 dígitos)")
            continue
        if m.group(1) in vistos:
            continue
        vistos.add(m.group(1))
        out.append({"ruc": m.group(1), "nombre": m.group(2).strip().strip('"').strip()})
    return out


TIPO_GRE = {"09": "Remitente", "31": "Transportista"}
POR_GRE = {"factura citada en la guía": "por la factura citada en la guía", "serie de la máquina": "por la serie o el motor de la máquina",
           "guía del transportista": "de guías del transportista que siguen a otra guía", "guía citada en la factura": "por la guía citada en la factura",
           "tipo de máquina, comprador y fecha": "por tipo de máquina, comprador y fecha (probables)"}


def guias_xlsx(ruta):
    """Excel del extractor de GRE (hojas Resumen, Guías, Bienes, Documentos relacionados, Vehículos) → misma
    estructura que el JSON del extractor, para leer las dos descargas igual."""
    import openpyxl
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    hojas = {ws.title: list(ws.iter_rows(values_only=True)) for ws in wb.worksheets}
    wb.close()

    def tabla(nombre):
        filas = hojas.get(nombre) or []
        if not filas:
            return []
        cab = [str(x or "").strip() for x in filas[0]]
        idx = {}
        for i, c in enumerate(cab):
            idx.setdefault(c, i)
        return [{c: (r[i] if i < len(r) else None) for c, i in idx.items()} for r in filas[1:] if r and any(x is not None for x in r)]
    txt = lambda x: "" if x is None or str(x) == "None" else str(x).strip()
    res = {txt(r.get("Concepto")): txt(r.get("Valor")) for r in tabla("Resumen") if r.get("Concepto")}
    if not hojas.get("Guías"):
        return None
    bienes, docs, placas = {}, {}, {}
    COL_BIEN = {"N° orden": "numOrden", "Código bien": "codBien", "Descripción bien": "desBien", "Cantidad": "numCantidad",
                "Unidad medida": "codUniMedida", "Descripción unidad": "desUniMedida", "Código producto SUNAT": "codProductoSunat",
                "Subpartida": "codSubPartida", "GTIN": "codGtin", "Bien regulado": "indBienRegulado", "Documento relacionado": "docRelacionado",
                "Contenedor": "numContenedor", "Precinto": "numPrecinto"}
    for r in tabla("Bienes"):
        if txt(r.get("Descripción bien")):
            b = {api: txt(r.get(col)) for col, api in COL_BIEN.items() if txt(r.get(col))}
            b.update({k[5:]: txt(v) for k, v in r.items() if k.startswith("bien.") and txt(v)})
            bienes.setdefault(txt(r.get("Clave")), []).append(b)
    # Para «Ver guía»: los campos del detalle que el Excel trae como columnas («emision.fecEmision», «traslado.…»)
    # y las listas en hojas aparte (conductores, vehículos, proveedores…), con la misma ruta que en el JSON.
    SIN_VER_X = ("id", "codCpe", "numRuc", "codTipoCpe", "numSerie", "numCpe", "codEstado", "desEstado", "desTipoCpe", "auditoria")
    listas_ver = {}
    for nombre in hojas:
        filas_h = tabla(nombre)
        if not filas_h or "Colección" not in filas_h[0] or nombre == "Bienes":
            continue
        base_h = {"Clave", "RUC emisor", "Serie", "Número", "Guía completa", "Fecha emisión", "Colección", "Índice", "Índice padre"}
        for r in filas_h:
            col = txt(r.get("Colección"))
            if not col or col.split(".")[0].split("[")[0] in SIN_VER_X or col.startswith("traslado.bien"):
                continue
            # «traslado.vehiculo[].vehiculoSec» con índice padre «1» e índice «2» → «traslado.vehiculo[1].vehiculoSec[2]»
            partes, padre = col.split("[]"), txt(r.get("Índice padre"))
            idx = (padre.split("/") if padre else []) + [txt(r.get("Índice"))]
            pre = "".join(f"{a}[{i}]" for a, i in zip(partes, idx)) if len(partes) == len(idx) else f"{col.replace('[]', '')}[{'/'.join(idx)}]"
            listas_ver.setdefault(txt(r.get("Clave")), []).extend(
                [f"{pre}.{k}", txt(v)[:300]] for k, v in r.items() if k not in base_h and txt(v) and not k.endswith("[cantidad]"))
    for r in tabla("Documentos relacionados"):
        docs.setdefault(txt(r.get("Clave")), []).append({k: txt(r.get(k)) for k in ("codTipoDocumento", "desTipoDocumento", "numRuc", "numSerie", "numDocumento")})
    for r in tabla("Vehículos"):
        if txt(r.get("numPlaca")):
            placas.setdefault(txt(r.get("Clave")), []).append({"numPlaca": txt(r.get("numPlaca"))})

    def lugar(pre, r):
        return {"direccion": {"codUbigeo": txt(r.get(f"{pre} ubigeo")), "desDepartamento": txt(r.get(f"{pre} departamento")),
                              "desProvincia": txt(r.get(f"{pre} provincia")), "desDistrito": txt(r.get(f"{pre} distrito")),
                              "desDireccion": txt(r.get(f"traslado.{pre.lower()}.direccion.desDireccion")) or txt(r.get(f"{pre} dirección")),
                              "contribuyente": {"numRuc": txt(r.get(f"traslado.{pre.lower()}.direccion.contribuyente.numRuc"))}}}
    guias = []
    for r in tabla("Guías"):
        clave = txt(r.get("Clave"))
        if not clave:
            continue
        # «Consulta correcta»: SI (con detalle), YA_EN_TABLERO, NO o NO_PROCESADA (sin detalle). Sin la columna, se asume SI.
        con_detalle = txt(r.get("Consulta correcta")).upper() in ("", "SI", "SÍ")
        listado = {"codCpe": txt(r.get("Código CPE")), "rucEmisor": txt(r.get("RUC emisor")), "rucReceptor": txt(r.get("Receptor documento")),
                   "numSerie": txt(r.get("Serie")), "numCpe": txt(r.get("Número")), "desEstado": txt(r.get("Estado")),
                   "fecEmision": txt(r.get("Fecha emisión"))}
        if not con_detalle:
            guias.append({"clave": clave, "listado": listado, "detalle": None, "busquedas": []})
            continue
        peso = txt(r.get("Peso bruto"))
        try:
            peso = float(peso)
        except ValueError:
            peso = None
        guias.append({"clave": clave, "listado": listado,
                      "detalle": {"numRuc": txt(r.get("RUC emisor")), "codCpe": txt(r.get("Código CPE")), "numSerie": txt(r.get("Serie")),
                                  "numCpe": txt(r.get("Número")), "desEstado": txt(r.get("Estado")), "emision": {"fecEmision": txt(r.get("Fecha emisión"))},
                                  "emisor": {"desNombre": txt(r.get("Nombre emisor"))},
                                  "receptor": {"numDocIdentidad": txt(r.get("Receptor documento")), "desNombre": txt(r.get("Receptor nombre"))},
                                  "baja": {"desMotivo": txt(r.get("baja.desMotivo"))} if txt(r.get("baja.desMotivo")) else None,
                                  "docRelacionado": docs.get(clave, []),
                                  "traslado": {"desMotivoTraslado": txt(r.get("traslado.desMotivoTraslado")) or txt(r.get("Motivo traslado")),
                                               "desMotivoTrasladoOtros": txt(r.get("traslado.desMotivoTrasladoOtros")),
                                               "fecInicioTraslado": txt(r.get("Fecha inicio traslado")), "numPesoBruto": peso,
                                               "codUnidadMedidaPb": txt(r.get("Unidad peso")), "bien": bienes.get(clave, []),
                                               "vehiculo": placas.get(clave) or ([{"numPlaca": txt(r.get("Placa"))}] if txt(r.get("Placa")) else []),
                                               "partida": lugar("Partida", r), "llegada": lugar("Llegada", r)}},
                      "ver_c": [[k, txt(v)[:300]] for k, v in r.items() if k[:1].islower() and txt(v) and not k.endswith("[cantidad]")
                                and k.split(".")[0].split("[")[0] not in SIN_VER_X] + listas_ver.get(clave, []),
                      "busquedas": []})
    busq = []
    for r in tabla("Búsquedas"):
        m1, m2 = (re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", txt(r.get(c))) for c in ("Desde", "Hasta"))
        if m1 and m2 and norm(txt(r.get("Resultado"))).startswith("CORRECTA"):
            rol = "rucEmisor" if norm(txt(r.get("Buscado como"))).startswith("EMISOR") else "rucReceptor"
            busq.append({rol: txt(r.get("RUC")), "desde": f"{m1[3]}-{m1[2]}-{m1[1]}", "hasta": f"{m2[3]}-{m2[2]}-{m2[1]}", "tipo": "ok"})
    titulo = f"RUC {res.get('RUC consultados', '')} buscado como {res.get('Buscados como', '')}, {res.get('Periodos', '')}"
    if res.get("RUC consultados", "").isdigit() and int(res["RUC consultados"]) == 1:
        rucs = sorted({txt(r.get("RUC")) for r in tabla("Búsquedas") if txt(r.get("RUC"))})
        titulo = f"RUC {', '.join(rucs)} como {res.get('Buscados como', '')}, {res.get('Periodos', '')}"
    return {"formato": "GRE_EXTRACTOR_JSON", "version": res.get("Versión del extractor", ""), "busquedas": busq, "guias": guias,
            "pedido": {"titulo": titulo, "generado": res.get("Generado", "")[:10]}}


MAQ_GUIA = {"Excavadora", "Retroexcavadora", "Minicargador", "Cargador frontal", "Motoniveladora", "Rodillo compactador",
            "Tractor de orugas", "Tractor agrícola", "Grupo electrógeno", "Motor marino"}
NO_ES_MAQ = re.compile(r"\b(1:50|1/50|ESCALA|JUGUETE\w*|MINIATURA\w*|ANFO|BATERIA\w*|CELULAR\w*|NEUMATICO\w*|LLANTA\w*|REPUESTO\w*)\b")
PREFIJO_BIEN = re.compile(r"^(\d+\s*(UND|UNIDAD(ES)?|U)?\.?\s+|TRANSPORTE( EN CAMA BAJA)? DE (UNA |UN )?|SERVICIO DE (TRASLADO|TRANSPORTE) DE (UNA |UN )?|"
                          r"TRASLADO DE (UNA |UN )?)+")
SERIE_ROTULO = re.compile(r"(?:\bSERIE|\bS/N|\bPIN|\bVIN|\bCHASIS)\s*(?:DE\s+)?(?:LA\s+)?(?:MAQ(?:UINA|NA)?\.?)?\s*(?:NUMBER)?\s*[:#.\-*]*\s*([A-Z0-9][A-Z0-9\-]{4,19})")


def maquinas_en_bienes(bienes):
    """Máquinas que nombra una lista de bienes de una guía: [(tipo, descripción, serie)]. La serie sale del rótulo
    «SERIE …» o, si no lo hay, de la última palabra de 8 o más caracteres con letras y números (no el modelo ni el motor)."""
    out = []
    for b in bienes:
        n = norm(b)
        n2 = PREFIJO_BIEN.sub("", n)
        cat = cat_maquina(" ".join(n2.split()[:2]))
        if cat not in MAQ_GUIA or NO_ES_MAQ.search(n):
            continue
        m = SERIE_ROTULO.search(n)
        serie = m.group(1).strip("-") if m else ""
        if serie and (serie in ("MAQUINA", "MOTOR") or not re.search(r"\d", serie)):
            serie = ""
        if not serie:
            pal = re.findall(r"[A-Z0-9]+", n)
            for i in range(len(pal) - 1, -1, -1):
                w = pal[i]
                if len(w) >= 8 and sum(c.isdigit() for c in w) >= 3 and re.search(r"[A-Z]", w) \
                        and not {"MODELO", "MOD", "MOTOR", "POTENCIA", "MARCA", "PLACA"} & set(pal[max(0, i - 3):i]):
                    serie = w
                    break
        out.append((cat, b, re.sub(r"[^A-Z0-9]", "", serie)))
    return out


def leer_guias(rutas, r_ubi):
    """Guías de remisión electrónicas (GRE) que descarga el extractor de GRE (JSON «GRE_EXTRACTOR_JSON»).
    Admite varias descargas: una guía repetida (misma clave) se lee una sola vez, con las búsquedas de todas.
    La zona (ZTE o ZTC) de la partida y de la llegada sale del ubigeo de cada dirección.
    Devuelve (guías, meta); meta trae los archivos leídos y, por caso, el periodo consultado."""
    if not rutas:
        return [], None
    u = pd.read_csv(r_ubi, dtype=str).fillna("")
    zona_u = dict(zip(u.ubigeo, u.zona))
    limpio = lambda x: re.sub(r"\s+", " ", html_unescape(str(x or ""))).strip()

    def persona(d):
        d = d or {}
        return {"ruc": str(d.get("numDocIdentidad") or d.get("numRuc") or "").strip(),
                "nombre": limpio(d.get("desNombre") or d.get("desNomRazonSocial") or d.get("desRazonSocial") or d.get("desRuc"))}

    def lugar(p):
        d = (p or {}).get("direccion") or {}
        ub = str(d.get("codUbigeo") or "").strip()
        partes = []
        for x in (d.get("desDistrito"), d.get("desProvincia"), d.get("desDepartamento")):
            x = re.sub(r"^PROV\. CONST\. DEL ", "", limpio(x).upper())
            if x and (not partes or partes[-1] != x):
                partes.append(x)
        return {"u": ub, "lugar": ", ".join(partes),
                "zona": zona_u.get(ub, "Sin dato"), "dir": limpio(d.get("desDireccion"))[:140],
                "ruc": str(((d.get("contribuyente") or {}).get("numRuc")) or "").strip()}

    def fecha_listado(x):
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(x or ""))
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""

    # Datos para «Ver guía» en el tablero: el detalle completo en pares [ruta, valor] (sin la identificación, que va
    # en la cabecera, ni la auditoría) y los bienes como tabla. Así se ve todo lo que trae SUNAT, aunque cambien sus campos.
    def valor_ver(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "Sí" if v else "No"
        if isinstance(v, (int, float)):
            return f"{v:g}"
        return limpio(v)[:300]

    def plano(obj, ruta=""):
        if isinstance(obj, dict):
            return [x for k, v in obj.items() for x in plano(v, f"{ruta}.{k}" if ruta else k)]
        if isinstance(obj, list):
            if obj and all(not isinstance(x, (dict, list)) for x in obj):
                t = " | ".join(valor_ver(x) for x in obj if valor_ver(x))
                return [[ruta, t[:300]]] if t else []
            return [x for n, v in enumerate(obj, 1) for x in plano(v, f"{ruta}[{n}]")]
        t = valor_ver(obj)
        return [[ruta, t]] if t else []
    SIN_VER = {"id", "codCpe", "numRuc", "codTipoCpe", "numSerie", "numCpe", "codEstado", "desEstado", "desTipoCpe", "auditoria"}
    BIEN_TABLA = {"numOrden", "codBien", "desBien", "numCantidad", "codUniMedida", "desUniMedida"}

    def ver_guia(de, campos_excel=None):
        t = dict(de.get("traslado") or {})
        bienes = [[valor_ver(b.get("numOrden")) or str(n), valor_ver(b.get("codBien")), limpio(b.get("desBien"))[:500],
                   valor_ver(b.get("numCantidad")), valor_ver(b.get("desUniMedida") or b.get("codUniMedida")),
                   [x for k, v in b.items() if k not in BIEN_TABLA for x in plano(v, k)]]
                  for n, b in enumerate(t.pop("bien", None) or [], 1) if isinstance(b, dict)]
        campos = campos_excel if campos_excel else plano({**{k: v for k, v in de.items() if k not in SIN_VER and k != "traslado"}, "traslado": t})
        return {"c": campos[:400], "b": bienes}
    por, meta = {}, {"archivos": [], "busquedas": {}, "cobertura": {}}
    es_iso = lambda x: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", x))
    for ruta in rutas:
        if ruta.lower().endswith((".xlsx", ".xlsm")):
            d = guias_xlsx(ruta)
        else:
            with open(ruta, encoding="utf-8-sig") as f:
                d = json.load(f)
        if not isinstance(d, dict) or d.get("formato") != "GRE_EXTRACTOR_JSON":
            print(f"AVISO guías: {os.path.basename(ruta)} no es una descarga del extractor de GRE; se omite")
            continue
        p = d.get("pedido") or {}
        par = d.get("parametros") or {}
        titulo = limpio(p.get("titulo"))
        if par.get("rucs") and par.get("periodos") and (p.get("id") == "manual" or not titulo):
            dmy = lambda x: "/".join(reversed(str(x)[:10].split("-")))
            rol = {"ambos": " como emisor y destinatario", "emisor": " como emisor", "receptor": " como destinatario"}.get(par.get("rol"), "")
            titulo = (f"RUC {', '.join(par['rucs'])}{rol}, " + "; ".join(f"{dmy(x.get('desde'))} al {dmy(x.get('hasta'))}" for x in par["periodos"]))
        meta["archivos"].append({"titulo": titulo, "generado": str(p.get("generado") or "")[:10],
                                 "version": str(d.get("version") or ""), "guias": len(d.get("guias") or [])})
        # Cobertura: periodos consultados de cada RUC como emisor o como destinatario (solo búsquedas completas)
        hecho = str(d.get("generadoEn") or p.get("generado") or "")[:10]      # día de la descarga: lo posterior no está consultado
        for b in d.get("busquedas") or []:
            de_, ha_ = str(b.get("desde") or "")[:10], str(b.get("hasta") or "")[:10]
            if es_iso(hecho) and es_iso(ha_) and ha_ > hecho:
                ha_ = hecho
            if b.get("tipo") == "ok" and not b.get("incompleta") and es_iso(de_) and es_iso(ha_) and de_ <= ha_:
                for rol, k in (("emisor", "rucEmisor"), ("receptor", "rucReceptor")):
                    if b.get(k):
                        meta["cobertura"].setdefault(str(b[k]).strip(), {}).setdefault(rol, []).append([de_, ha_])
        for b in d.get("busquedas") or []:
            caso = str(b.get("caso") or "").strip()
            if not caso or b.get("grupo") not in ("caso", "citada"):
                continue
            x = meta["busquedas"].setdefault(caso, {"desde": "", "hasta": "", "incompleta": False, "n": 0})
            for k, fn in (("desde", min), ("hasta", max)):
                v = str(b.get(k) or "")[:10]
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                    x[k] = fn(x[k], v) if x[k] else v
            x["incompleta"] |= bool(b.get("incompleta")) or (b.get("tipo") != "dividida" and b.get("estadoHttp") not in (200, None))
        for g in d.get("guias") or []:
            clave = str(g.get("clave") or "").strip()
            if not clave:
                continue
            casos = {str(b.get("caso")).strip() for b in g.get("busquedas") or [] if b.get("caso")}
            de = g.get("detalle") or {}
            if clave in por and (por[clave]["_det"] or not de):
                por[clave]["casos"] |= casos
                continue
            lst = g.get("listado") or {}
            t = de.get("traslado") or {}
            mot = limpio(t.get("desMotivoTraslado"))
            otros = limpio(t.get("desMotivoTrasladoOtros"))
            if otros and (not mot or mot.startswith("Otros")):
                mot = f"Otros: {otros.lower()}" if mot else otros
            bienes = [limpio(b.get("desBien"))[:220] for b in t.get("bien") or [] if limpio(b.get("desBien"))]
            if not bienes and limpio(t.get("desBien")):
                bienes = [limpio(t.get("desBien"))[:220]]
            docs = []
            for x in de.get("docRelacionado") or []:
                num = str(x.get("numDocumento") or "").strip()
                if x.get("numSerie") and num.isdigit():
                    num = f"{str(x['numSerie']).strip()}-{int(num)}"
                docs.append({"t": str(x.get("codTipoDocumento") or ""), "nombre": limpio(x.get("desTipoDocumento")),
                             "ruc": str(x.get("numRuc") or "").strip(), "num": num})
            cod = str(de.get("codCpe") or lst.get("codCpe") or (clave.split("-")[1] if "-" in clave else ""))
            serie, num = (de.get("numSerie") or lst.get("numSerie") or ""), (de.get("numCpe") or lst.get("numCpe") or "")
            peso = t.get("numPesoBruto")
            por[clave] = {
                "clave": clave, "num": f"{serie}-{num}" if serie else clave.split("-", 2)[-1], "tipo": TIPO_GRE.get(cod, limpio(lst.get("desCortaCpe")) or cod),
                "f": str((de.get("emision") or {}).get("fecEmision") or "")[:10] or fecha_listado(lst.get("fecEmision")),
                "fi": str(t.get("fecInicioTraslado") or "")[:10], "estado": limpio(de.get("desEstado") or lst.get("desEstado")),
                "baja": limpio((de.get("baja") or {}).get("desMotivo")), "motivo": mot,
                "em": {"ruc": str(de.get("numRuc") or lst.get("rucEmisor") or clave.split("-")[0]), "nombre": limpio((de.get("emisor") or {}).get("desNombre"))},
                "de": persona(de.get("receptor")) if de.get("receptor") else {"ruc": str(lst.get("rucReceptor") or ""), "nombre": ""},
                "rem": persona(de.get("remitente")) if cod == "31" and de.get("remitente") else None,
                "p": lugar(t.get("partida")), "l": lugar(t.get("llegada")), "bienes": bienes[:10], "nb": len(t.get("bien") or []),
                "docs": docs, "placas": [str(v.get("numPlaca")) for v in t.get("vehiculo") or [] if v.get("numPlaca")],
                "peso": f"{peso:g} {t.get('codUnidadMedidaPb') or ''}".strip() if isinstance(peso, (int, float)) else "",
                "casos": casos, "_det": bool(de), **({"ver": ver_guia(de, g.get("ver_c"))} if de else {})}
    guias = sorted(por.values(), key=lambda g: (g["f"], g["clave"]))
    for g in guias:
        for c in g["casos"]:
            if c in meta["busquedas"]:
                meta["busquedas"][c]["n"] += 1
    for roles in meta["cobertura"].values():       # une los periodos que se tocan o se pisan
        for rol, tramos in roles.items():
            unidos = []
            for de_, ha_ in sorted(tramos):
                if unidos and de_ <= (date.fromisoformat(unidos[-1][1]) + timedelta(days=1)).isoformat():
                    unidos[-1][1] = max(unidos[-1][1], ha_)
                else:
                    unidos.append([de_, ha_])
            roles[rol] = unidos
    return guias, meta


def leer_consulta_ruc(rutas):
    """Resultados de la consulta múltiple de RUC de SUNAT (ZIP o TXT separados por «|»)."""
    partes = []
    for r in rutas or []:
        if zipfile.is_zipfile(r):
            z = zipfile.ZipFile(r)
            fuentes = [io.BytesIO(z.read(m)) for m in z.namelist() if m.lower().endswith(".txt")]
        else:
            fuentes = [r]
        for f in fuentes:
            t = pd.read_csv(f, sep="|", encoding="latin-1", dtype=str, index_col=False).fillna("")
            t.columns = [norm(c) for c in t.columns]
            t = t[[c for c in t.columns if c and not c.startswith("UNNAMED")]]
            t = t.apply(lambda col: col.str.strip().replace({"-": ""}))
            partes.append(t)
    if not partes:
        return pd.DataFrame(columns=["ruc"])
    t = pd.concat(partes, ignore_index=True)
    col = lambda *ns: next((c for c in t.columns if any(c.startswith(n) for n in ns)), None)
    out = pd.DataFrame({"ruc": t[col("NUMERORUC", "RUC")]})
    for destino, nombres in {"departamento_c": ("DEPARTAMENTO",), "provincia_c": ("PROVINCIA",), "distrito_c": ("DISTRITO",),
                             "direccion_c": ("DIRECCION",), "actividad": ("PRINCIPAL",), "actividad2": ("SECUNDARIO 1",),
                             "finsc": ("FECHA DE INSCRIPCION",), "tipo_contrib": ("TIPO DE CONTRIBUYENTE",),
                             "estado_c": ("ESTADO DEL CONTRIBUYENTE",), "condicion_c": ("CONDICION DEL CONTRIBUYENTE",)}.items():
        c = col(*nombres)
        out[destino] = t[c] if c else ""
    out["finsc"] = pd.to_datetime(out.finsc, format="%d/%m/%Y", errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    return out.drop_duplicates("ruc", keep="last")


def cargar_domicilios(r_dom, r_ubi, consultas=None):
    """Admite ubigeo o, si falta, departamento/provincia/distrito por nombre; y la actividad económica.
    Completa con la consulta múltiple de RUC: actividad, fecha de inscripción y, si el padrón no lo trae, el domicilio."""
    d = pd.read_csv(r_dom, dtype=str).fillna("")
    d.columns = [norm(c).lower().replace(" ", "_") for c in d.columns]
    c = leer_consulta_ruc(consultas)
    if len(c):
        d = d.merge(c, on="ruc", how="outer").fillna("")
        for a, b in (("departamento", "departamento_c"), ("provincia", "provincia_c"), ("distrito", "distrito_c"), ("direccion", "direccion_c"),
                     ("estado", "estado_c"), ("condicion", "condicion_c")):
            if a not in d:
                d[a] = ""
            sin = (d.get("ubigeo", "") == "") if a in ("departamento", "provincia", "distrito") else (d[a] == "")
            d.loc[sin, a] = d.loc[sin, b]
        d = d.drop(columns=[x for x in d.columns if x.endswith("_c")])
    u = pd.read_csv(r_ubi, dtype=str).fillna("")
    u = u[u.ubigeo.str.fullmatch(r"\d{6}")]
    for c in ["ubigeo", "departamento", "provincia", "distrito", "estado", "condicion", "direccion", "actividad", "actividad2", "finsc", "tipo_contrib"]:
        if c not in d:
            d[c] = ""
    d["ubigeo"] = d.ubigeo.str.strip().str.zfill(6).where(d.ubigeo.str.strip() != "", "")
    k = lambda x: re.sub(r"[^A-Z ]", " ", norm(x)).split()
    clave = lambda *xs: " | ".join(" ".join(k(x)) for x in xs)
    por_3 = {clave(a, b, c): g for g, a, b, c in zip(u.ubigeo, u.departamento, u.provincia, u.distrito)}
    por_2 = {}
    for g, a, c in zip(u.ubigeo, u.departamento, u.distrito):
        por_2.setdefault(clave(a, c), []).append(g)

    def ubigeo_por_nombre(r):
        if r.ubigeo or not r.distrito:
            return r.ubigeo
        g = por_3.get(clave(r.departamento, r.provincia, r.distrito))
        if g:
            return g
        c = por_2.get(clave(r.departamento, r.distrito), [])
        return c[0] if len(c) == 1 else ""
    d["ubigeo"] = [ubigeo_por_nombre(r) for r in d.itertuples()]
    d = d.drop(columns=["departamento", "provincia", "distrito"])
    d = d.merge(u, on="ubigeo", how="left").fillna("").rename(columns={"estado": "eruc"})
    d.loc[d.ubigeo == "", ["departamento", "provincia", "distrito", "zona"]] = ""
    d["zona"] = d.zona.where(d.zona != "", "Sin dato")
    return d.drop_duplicates("ruc").set_index("ruc")


# ---------------------------------------------------------------- tablero

def main(a):
    mt = leer_dams(a.dams)
    m = mt[mt.COD_REGIMEN == "10"].copy()        # importación para el consumo
    dep70 = mt[mt.COD_REGIMEN == "70"].copy()    # depósito aduanero: solo para la historia de la máquina
    exp40 = mt[mt.COD_REGIMEN == "40"].copy()    # exportación definitiva
    e = leer_cpe(a.cpe)
    dl = leer_detalle(a.detalle)
    ruc_imp = str(m.NUM_DOCIDENT.iloc[0]).strip()
    desde = min(m.f.min(), e.f.min()).normalize()
    k8 = lambda x: x[-8:] if isinstance(x, str) and len(x) >= 8 else ""
    dia = pd.Timedelta(days=1)

    # ---------- DAM y máquinas importadas ----------
    dec = m.groupby("dam").agg(f=("f", "first"), ad=("COD_ADUANA", "first"), dest=("dest", "first"), canal=("CANAL", "first"),
                               series=("NUM_SECSERIE", "size"), cif=("MTO_VALORADU", "sum"), nmaq=("maq", "sum"),
                               conv=("conv", lambda s: ", ".join(sorted(set(s))))).reset_index()
    mq = datos_maquina(m[m.maq])
    mq["s"] = mq.NUM_SECSERIE.astype(int)
    mq = mq.sort_values(["f", "dam", "s"])
    mq["key"] = mq.dam + "#" + mq.s.astype(str)
    mq["k8"] = mq.id.map(k8)
    dep_k8 = {}
    if len(dep70):
        for _, s in datos_maquina(dep70[dep70.maq]).sort_values("f").iterrows():
            if k8(s.id) and k8(s.id) not in dep_k8:
                dep_k8[k8(s.id)] = {"dam": s.dam, "f": fstr(s.f)}
    exportaciones = []
    if len(exp40):
        x40 = exp40.drop_duplicates(["dam", "DES_COMER"]).copy()
        x40["pin"] = x40.DES_COMER.str.extract(r"PIN[: ]*([A-Z0-9]{17})", expand=False).fillna("")
        x40["motor_x"] = x40.DES_COMER.str.extract(r"MOTOR[: ]*([A-Z0-9]{8,12})", expand=False).fillna("")
        x40["modelo_x"] = x40.DES_COMER.str.extract(r"MOD[.:]*\s*([A-Z0-9.]+?)(?:PIN|\s|,|$)", expand=False).fillna("")
        for _, s in x40.sort_values("f").iterrows():
            exportaciones.append({"dam": s.dam, "f": fstr(s.f), "ad": s.COD_ADUANA, "desc": norm(s.DES_COMER)[:80], "modelo": s.modelo_x,
                                  "pin": s.pin, "motor": s.motor_x, "fob": r2(s.MTO_FOBDOL), "maq": None, "venta": None})
    exp_k8 = {k8(x["pin"]): x for x in exportaciones if k8(x["pin"])}

    # ---------- Control de la intendencia: DAM, NCN y traslados ----------
    ctl, tras_todos, meta_ctl = leer_control_ia(a.control_ia, ruc_imp) if a.control_ia else ({}, [], {"art2": [], "complejidad": None})
    cons = leer_consultas(a.consultas) if a.consultas else {"dam": {}, "series": {}, "pin": [], "pin_filas": Counter(), "salidas": {}}
    for k, x in cons["dam"].items():
        if "control" not in ctl.get(k, {}):
            ctl[k] = x
    dams_periodo = set(dec.dam)
    tr = [t for t in tras_todos if t["f"] >= fstr(desde) or set(t["dams"]) & dams_periodo]
    claves_maq = set(mq.key)
    cif_key = dict(zip(mq.key, mq.MTO_VALORADU))
    cat_key = dict(zip(mq.key, mq["cat"]))
    tras_maq, tras_dam = {}, {}
    for i, t in enumerate(tr):
        t["i"] = i
        t["salida"] = norm(t["tipo"]) == "ZTE A ZTC"           # «ZTE a ZTE pasando por ZTC» es tránsito, no salida
        t["pago"] = "garantizado" if "FIANZA" in norm(t["doc"]) else "pagado"
        t["maqs"] = [f"{d}#{s}" for d, s in t["pares"] if f"{d}#{s}" in claves_maq]
        t["es_maq"] = bool(t["maqs"]) or bool(re.search(r"MAQUINARIA|MOTOR", norm(t["merc"])))
        t["obs"] = []
        for k in t["maqs"]:
            tras_maq.setdefault(k, []).append(i)
        for d in t["dams"]:
            tras_dam.setdefault(d, []).append(i)
    # Monto del traslado = 18 % del valor en aduana de la serie, en soles: sirve para detectar series mal registradas
    ratios = {t["i"]: t["monto"] / (cif_key[t["maqs"][0]] * TASA_IMP) for t in tr
              if t["monto"] and len(t["maqs"]) == 1 and t["cant"] == 1 and "LIQUIDACION" in norm(t["doc"]) and t["salida"]}
    tc = float(pd.Series(list(ratios.values())).median()) if len(ratios) >= 3 else None
    for t in tr:
        r = ratios.get(t["i"])
        if tc and r and abs(r / tc - 1) > 0.10:
            t["obs"].append(f"El monto (S/ {t['monto']:,.0f}) no cuadra con el 18 % del CIF de la serie registrada (unos S/ {cif_key[t['maqs'][0]] * TASA_IMP * tc:,.0f})")
    por_par = {}
    for t in tr:
        for k in t["maqs"]:
            por_par.setdefault(k, []).append(t["exp"])
    for t in tr:
        otros = sorted({x for k in t["maqs"] for x in por_par[k] if x != t["exp"]})
        if otros:
            t["obs"].append(f"Misma DAM y serie que el expediente {', '.join(x.split('-')[-1] for x in otros)}")
    # Expedientes repetidos (misma DAM, serie y RI): cuenta uno solo, el que cuadra con el 18 % del CIF
    grupos = {}
    for t in tr:
        if t["maqs"]:
            grupos.setdefault((tuple(sorted(t["maqs"])), t["ri"]), []).append(t)
    for g_ in grupos.values():
        g_.sort(key=lambda t: abs(ratios.get(t["i"], tc or 1) / (tc or 1) - 1))
        for t in g_[1:]:
            t["dup"] = True
    tras_salida = [t for t in tr if t["es_maq"] and t["salida"] and t["f"] >= fstr(desde) and not t.get("dup")]
    cat_t = {t["i"]: ({cat_key[k] for k in t["maqs"]} or CAT_MERC.get(norm(t["merc"]), set())) for t in tr}

    def control_dam(k):
        """Beneficio de la DAM según el cuaderno (o la consulta a la intendencia de destino). None: la DAM no está registrada."""
        x = ctl.get(k)
        if not x or "control" not in x:
            return None
        c = x["control"]
        consulta = bool(x.get("fuente"))
        res = c.get("sol_estado", "") if consulta else c.get("resultado", "")
        sin = norm(res).startswith(("IMPROCEDENTE", "SIN SOLICITUD"))
        sol = res.strip().capitalize() if res.strip() else ("Solicitud ingresada" if c.get("hoja") == "Ingreso de DAM" else "En trámite")
        return {"benef": not sin, "sol": sol, "nsol": c.get("nsol", ""),
                "fuente": x.get("fuente") or ("Cuaderno de control: Ingreso de DAM" if c.get("hoja") == "Ingreso de DAM" else "Cuaderno de control: ConsolidadoT"),
                "tras_txt": c.get("tras_txt", ""), "obs": c.get("obs", ""), "tras": tras_dam.get(k, [])}

    # ---------- Ventas de maquinaria y cadena de comprobantes ----------
    det_fp = dl[dl.num_serie_cpe.str.startswith("FP")].groupby("cpe").des_detalle_item.apply(
        lambda s: " + ".join(str(x).strip() for x in s if isinstance(x, str))).rename("desc")
    vm = e[e.linea == "Maquinaria"].merge(det_fp, left_on="cpe", right_index=True, how="left")
    vm["desc"] = vm.desc.fillna("").replace("", "(sin detalle)")
    vm["cat"] = vm.desc.map(cat_maquina)
    vm["usado"] = vm.desc.map(norm).str.contains(r"\bUSAD[OA]S?\b")
    facs = vm[vm.tipo == "01"]
    vig = facs[facs.estado == "0"]
    ncs = vm[(vm.tipo == "07") & (vm.estado == "0")]
    fx, facturas, xml_err, xml_rep = leer_facturas_xml(a.facturas_xml)
    por_cpe = vm.set_index("cpe")

    # Nota de crédito → factura que modifica: exacta con el XML de la NC; si no, por cliente, moneda y monto
    # (la factura anterior a la NC; la del mismo día solo si no hay otra, porque suele ser la reemisión)
    nc_ref, anulada_por = {}, {}
    for _, n in ncs.sort_values("f").iterrows():
        r = (facturas.get(n.cpe) or {}).get("ref")
        if r and f"01-{r['id']}" in por_cpe.index:
            nc_ref[n.cpe] = (f"01-{r['id']}", "XML de la nota de crédito")
        else:
            c = vig[(vig.doc == n.doc) & (vig.moneda == n.moneda) & (vig.f <= n.f) & ((n.f - vig.f).dt.days <= 365)
                    & ((vig.vv - n.vv).abs() <= (vig.vv * 0.005).clip(lower=1)) & ~vig.cpe.isin(list(anulada_por))]
            antes = c[c.f < n.f]
            c = antes if len(antes) else c
            if len(c):
                nc_ref[n.cpe] = (c.sort_values("f").cpe.iloc[-1], "mismo cliente, moneda y monto")
        if n.cpe in nc_ref and n.tipo_ref in NC_ANULA:
            anulada_por[nc_ref[n.cpe][0]] = n.cpe
    # Anticipos: la factura final descuenta lo ya facturado (valor + IGV − total). Una máquina, no dos.
    anticipo_de, anticipos = {}, {}
    vivas = vig[~vig.cpe.isin(list(anulada_por))]
    for _, fz in vivas[(vivas.vv + vivas.igv - vivas.total) > 1].sort_values("f").iterrows():
        dsc = fz.vv + fz.igv - fz.total
        c = vivas[(vivas.doc == fz.doc) & (vivas.moneda == fz.moneda) & (vivas.f <= fz.f) & (vivas.cpe != fz.cpe)
                  & ((fz.f - vivas.f).dt.days <= 365) & (vivas.vv <= dsc + 1) & ~vivas.cpe.isin(list(anticipo_de))].sort_values("f").tail(12)
        elegidas = None
        for n_ in (1, 2, 3):
            elegidas = next((g for g in combinations(c.itertuples(), n_) if abs(sum(x.vv for x in g) - dsc) <= 1), None)
            if elegidas:
                break
        if elegidas:
            anticipos[fz.cpe] = [x.cpe for x in elegidas]
            for x in elegidas:
                anticipo_de[x.cpe] = fz.cpe
    usadas = set()

    def reemision(o, f0, f1, mismo=True):
        c = vig[(vig.moneda == o.moneda) & (vig.cpe != o.name) & (vig.f >= f0) & (vig.f <= f1) & ~vig.cpe.isin(list(usadas))]
        c = c[(c.doc == o.doc)] if mismo else c[(c.doc != o.doc)]
        c = c[((c.vv - o.vv).abs() <= (0.10 if mismo else 0.02) * o.vv) & ((c["cat"] == o["cat"]) | (c["cat"] == "Otros") | (o["cat"] == "Otros"))]
        if not len(c):
            return None
        return c.assign(_d=(c.vv - o.vv).abs(), _t=(c.f - o.f).abs()).sort_values(["_d", "_t"]).iloc[0]
    cadenas = []
    anuladas = [(cpe, "Baja", None) for cpe in facs[facs.estado == "2"].sort_values("f").cpe] + \
               [(cpe, "Nota de crédito", nc) for cpe, nc in sorted(anulada_por.items(), key=lambda x: por_cpe.loc[x[1]].f)]
    for cpe, via, nc in anuladas:
        o = por_cpe.loc[cpe]
        fn = por_cpe.loc[nc].f if nc else o.f
        r = reemision(o, max(o.f, fn - 15 * dia), fn + 30 * dia)
        otro = None
        if r is not None:
            usadas.add(r.cpe)
        else:
            otro = reemision(o, fn - 3 * dia, fn + 30 * dia, mismo=False)
        cambio = "" if r is None else "con→sin" if o.igv > 0 and r.igv == 0 else "sin→con" if o.igv == 0 and r.igv > 0 else ""
        cadenas.append({"orig": cpe, "orig_f": fstr(o.f), "orig_igv": r2(o.igv), "via": via, "nc": nc or "",
                        "nc_f": fstr(por_cpe.loc[nc].f) if nc else "", "mot": por_cpe.loc[nc].tipo_ref if nc else "",
                        "enlace": nc_ref[nc][1] if nc else "", "reem": r.cpe if r is not None else "", "reem_f": fstr(r.f) if r is not None else "",
                        "reem_igv": r2(r.igv) if r is not None else None, "cambio": cambio,
                        "dias": int((r.f - fn).days) if r is not None else None, "otro": otro.cpe if otro is not None else ""})
    previa = {c["reem"]: c for c in cadenas if c["reem"]}

    def cadena_de(cpe):
        pasos, vistos = [], set()
        while cpe in previa and cpe not in vistos:
            vistos.add(cpe)
            pasos.insert(0, previa[cpe])
            cpe = previa[cpe]["orig"]
        return pasos
    # Máquinas vendidas: facturas vigentes que no se anularon con NC ni son anticipos de otra factura
    vend = vig[~vig.cpe.isin(list(anulada_por)) & ~vig.cpe.isin(list(anticipo_de))]

    # ---------- Domicilio fiscal y actividad de los compradores ----------
    dom = cargar_domicilios(a.domicilios, a.ubigeos, a.consulta_ruc) if a.domicilios else None
    info = dom.to_dict("index") if dom is not None else {}
    CAMPOS = ("zona", "departamento", "provincia", "distrito", "eruc", "condicion", "direccion", "actividad", "finsc")

    def domicilio(doc, tcli):
        if tcli == "No domiciliado":
            return {c: "" for c in CAMPOS} | {"zona": "Extranjero"}
        r = info.get(doc) or {}
        d = {c: r.get(c, "") for c in CAMPOS}
        d["zona"] = d["zona"] or "Sin dato"
        d["lugar"] = ", ".join(x for x in (d["distrito"], d["provincia"], d["departamento"]) if x)
        return d
    compradores = vend.groupby("doc").agg(nombre=("nombre", lambda s: s.value_counts().index[0]), tcli=("tcli", "first"),
                                          n=("cpe", "size"), primera=("f", "min"), ult=("f", "max")).reset_index()
    cli = {}
    for _, c in compradores.iterrows():
        d = domicilio(c.doc, c.tcli)
        dias_insc = (c.primera - pd.Timestamp(d["finsc"])).days if d["finsc"] else None
        cli[c.doc] = {"ruc": c.doc, "nombre": c.nombre, "tipo": c.tcli, **{k: d.get(k, "") for k in ("zona", "lugar", "direccion", "eruc", "condicion", "actividad", "finsc")},
                      "dep": d.get("departamento", "") or {"Extranjero": "Extranjero"}.get(d["zona"], "Sin dato"),
                      "rev": bool(REVENDE.search(norm(d["actividad"]))), "dias_insc": dias_insc,
                      "nuevo": dias_insc is not None and 0 <= dias_insc <= 180,
                      "no_habido": bool((d["eruc"] and d["eruc"] != "ACTIVO") or (d["condicion"] and d["condicion"] != "HABIDO")),
                      "n": int(c.n), "primera": fstr(c.primera), "ult": fstr(c.ult)}
    zona_doc = {k: v["zona"] for k, v in cli.items()}

    # ---------- Venta → máquina por número de serie (XML de la factura o caso documentado) ----------
    seriales = {}
    for _, it in fx[fx.serie != ""].iterrows():
        seriales.setdefault(it.cpe, []).append({"serie": it.serie, "motor": it.motor, "modelo": it.modelo, "anio": it.anio,
                                                "horas": it.horas, "afect": it.afect, "fuente": "XML de la factura"})
    manual = pd.read_csv(a.trazabilidad, dtype=str).fillna("") if a.trazabilidad else pd.DataFrame()
    entrega = {}
    if len(manual):
        buscar = ubicador(a.ubigeos)
        for _, c in manual.iterrows():
            if c.get("serie_maquina") and c.cpe not in seriales:
                seriales[c.cpe] = [{"serie": c.serie_maquina, "motor": c.get("serie_motor", ""), "modelo": c.get("modelo", ""), "anio": "",
                                    "horas": "", "afect": "", "fuente": c.get("fuente", "") or "Caso documentado"}]
            p = [x.strip() for x in str(c.get("ubicacion_entrega", "")).split(",")]
            ub = buscar(p[2], p[1], p[0]) if len(p) == 3 else None
            if c.get("ubicacion_entrega"):
                entrega[c.cpe] = {"lugar": c.ubicacion_entrega, "dir": c.get("direccion_entrega", ""), "zona": ub.zona if ub is not None else "Sin dato",
                                  "fuente": c.get("fuente", ""), "nota": c.get("nota", "")}
    buscar_u = ubicador(a.ubigeos)
    lugar_fac = {}
    for cpe, d_ in facturas.items():
        p_ = [x.strip() for x in d_["cliente"].get("lugar_fac", "").split("-")]
        if len(p_) >= 3 and all(p_[-2:]) and p_[0]:
            dist = "-".join(p_[:-2])
            ub = buscar_u(p_[-1], p_[-2], dist)
            lugar_fac[cpe] = {"lugar": f"{dist}, {p_[-2]}, {p_[-1]}" if ub is not None else ", ".join(x.strip(" .") for x in p_ if x.strip(" .")),
                              "zona": ub.zona if ub is not None else "Sin dato"}
    sedes = {}
    for d_ in facturas.values():
        if d_["emisor"].get("sede"):
            sedes.setdefault(d_["id"].split("-")[0], Counter())[d_["emisor"]["sede"]] += 1
    sede_de = {k: v.most_common(1)[0][0] for k, v in sedes.items()}
    lugar_sede = lambda x: (", ".join(y.strip().title() for y in x.split(" - ")[-2:]) if " - " in x else x).replace(" De ", " de ")

    # ---------- Guías de remisión: máquinas que aparecen en los bienes de cada guía ----------
    # Por la serie (los 8 últimos caracteres del PIN) o el motor. Si la factura no trae la serie, la guía del
    # importador o del comprador con esa máquina, del mismo tipo y cercana a la venta, la identifica.
    guias, gre_meta = leer_guias(a.guias, a.ubigeos)
    codigo = lambda x: re.sub(r"[^A-Z0-9]", "", norm(x))
    g_txt = [codigo(" ".join(g["bienes"])) for g in guias]
    g_f = [pd.Timestamp(g["f"]) if g["f"] else None for g in guias]
    maq_gre = {}
    if guias:
        for k, pin, motor in zip(mq.key, mq.id, mq.motor):
            cods = {c for c in (k8(pin), motor if len(motor) >= 8 else "") if c}
            for i, t in enumerate(g_txt):
                if cods and any(c in t for c in cods):
                    maq_gre.setdefault(k, []).append(i)
        sin_serie = vend[~vend.cpe.isin(list(seriales))]
        for k, idx in maq_gre.items():
            s = mq[mq.key == k].iloc[0]
            for i in sorted(idx, key=lambda i: guias[i]["estado"] == "Baja"):
                g = guias[i]
                rucs = {g["de"]["ruc"], g["em"]["ruc"]} - {ruc_imp, ""}
                c = sin_serie[sin_serie.doc.isin(list(rucs)) & (sin_serie["cat"] == s["cat"])]
                if g_f[i] is None or not len(c):
                    continue
                c = c.assign(d=(g_f[i] - c.f).dt.days)
                c = c[c.d.between(-5, 30)]
                if len(c):
                    cpe = c.loc[c.d.abs().idxmin()].cpe
                    seriales[cpe] = [{"serie": s.id, "motor": s.motor, "modelo": s.modelo, "anio": s.anio, "horas": "", "afect": "",
                                      "fuente": f"Guía de remisión {g['num']}"}]
                    sin_serie = sin_serie[sin_serie.cpe != cpe]
                    break
    venta_maq, maq_venta = {}, {}
    for cpe, lista in seriales.items():
        for s in lista:
            x = mq[mq.id.str.endswith(s["serie"])] if len(s["serie"]) >= 5 else mq.iloc[0:0]
            if not len(x) and len(s["motor"]) >= 5:
                x = mq[mq.motor == s["motor"]]
            s["maq"] = x.key.iloc[0] if len(x) else None
            if s["maq"]:
                venta_maq.setdefault(cpe, []).append(s["maq"])
                maq_venta.setdefault(s["maq"], []).append(cpe)

    # ---------- Guías de remisión → venta ----------
    # Enlace firme: la guía cita la factura (o la factura cita la guía), o sus bienes llevan la serie o el motor de la
    # máquina vendida. Enlace por tipo: guía del importador o del comprador con el mismo tipo de máquina, de 3 días antes
    # a 30 después de la venta, cuando solo una venta encaja. Las guías del transportista siguen a la guía que sustentan.
    gre_venta = {}
    enlazar = lambda cpe, i, por: gre_venta.setdefault(cpe, {}).setdefault(i, por)
    if guias:
        final_de = {c["orig"]: c["reem"] for c in cadenas if c["reem"]}

        def venta_final(cpe):
            vistos = set()
            while cpe in final_de and cpe not in vistos:
                vistos.add(cpe)
                cpe = final_de[cpe]
            return anticipo_de.get(cpe, cpe)
        vend_set = set(vend.cpe)
        por_clave = {g["clave"]: i for i, g in enumerate(guias)}
        for i, g in enumerate(guias):
            for d in g["docs"]:
                s_, _, n_ = d["num"].partition("-")
                if d["t"] == "01" and d["ruc"] == ruc_imp and n_.isdigit():
                    cpe = venta_final(f"01-{s_}-{int(n_)}")
                    if cpe in vend_set:
                        enlazar(cpe, i, "factura citada en la guía")
        for cpe, d_ in facturas.items():
            for gn in d_.get("guias", []):
                m_ = re.fullmatch(r"([A-Z][A-Z0-9]{3})-0*(\d{1,8})", gn.upper().replace(" ", ""))
                i = por_clave.get(f"{ruc_imp}-09-{m_.group(1)}-{m_.group(2)}") if m_ else None
                if i is not None and venta_final(cpe) in vend_set:
                    enlazar(venta_final(cpe), i, "guía citada en la factura")
        for cpe in vend_set:
            for k in venta_maq.get(cpe, []):
                for i in maq_gre.get(k, []):
                    enlazar(cpe, i, "serie de la máquina")
            cods = {codigo(s.get(x, "")) for s in seriales.get(cpe, []) for x in ("serie", "motor")}
            cods = {c for c in cods if len(c) >= 6}
            if cods:
                for i, t in enumerate(g_txt):
                    if any(c in t for c in cods):
                        enlazar(cpe, i, "serie de la máquina")
        ya = {i for d_ in gre_venta.values() for i in d_} | {i for idx in maq_gre.values() for i in idx}
        for i, g in enumerate(guias):
            if i in ya or g_f[i] is None:
                continue
            cats = {cat_maquina(" ".join(norm(b).split()[:2])) for b in g["bienes"]} - {"Otros"}
            rucs = {g["de"]["ruc"], g["em"]["ruc"]} - {ruc_imp, ""}
            if not cats or not (g["em"]["ruc"] == ruc_imp or g["em"]["ruc"] in set(vend.doc)):
                continue
            x = vend[vend.doc.isin(list(rucs)) & vend["cat"].isin(list(cats))]
            x = x[(g_f[i] - x.f).dt.days.between(-3, 30)]
            if len(x) == 1:
                enlazar(x.cpe.iloc[0], i, "tipo de máquina, comprador y fecha")
        for i, g in enumerate(guias):
            for d in g["docs"]:
                s_, _, n_ = d["num"].partition("-")
                j = por_clave.get(f"{d['ruc']}-09-{s_}-{int(n_)}") if d["t"] == "09" and n_.isdigit() else None
                if j is None:
                    continue
                g["sustenta"] = j
                for d_ in gre_venta.values():
                    if j in d_:
                        d_.setdefault(i, "guía del transportista")
        for g in guias:
            g["vig"] = g["estado"] != "Baja" and ("sustenta" not in g or guias[g["sustenta"]]["estado"] != "Baja")

    # Traslado del importador entre sus propias sedes de la ZTE: muestra por dónde pasó la máquina, no a dónde la llevó el
    # comprador. Se ve en la ficha, pero no cuenta para la zona de la entrega.
    interno = lambda g: norm(g["motivo"]).startswith("TRASLADO ENTRE ESTABLECIMIENTOS") and g["l"]["zona"] == "ZTE"

    def resumen_gre(cpe):
        gs = [guias[i] for i in gre_venta.get(cpe, {})]
        dias_v = lambda g: (pd.Timestamp(g["f"]) - por_cpe.loc[cpe].f).days if g["f"] else None
        ent = [g for g in gs if not interno(g) and not (g.get("sustenta") is not None and interno(guias[g["sustenta"]]))]
        vig = [g for g in ent if g["vig"]]
        zl = {g["l"]["zona"] for g in vig}
        ztc = "ZTC" in zl
        # Para ubicar la máquina en la ZTE solo cuentan las guías desde 3 días antes de la venta
        zl_post = {g["l"]["zona"] for g in vig if dias_v(g) is not None and dias_v(g) >= -3}
        ida = min((g["f"] for g in vig if g["p"]["zona"] == "ZTE" and g["l"]["zona"] == "ZTC" and g["f"]), default="")
        regreso = [g for g in vig if ida and g["p"]["zona"] == "ZTC" and g["l"]["zona"] == "ZTE" and g["f"] >= ida]
        return {"gs": gs, "ent": ent, "vig": vig, "ztc": ztc, "zte": zl_post == {"ZTE"} and zl <= {"ZTE"}, "regreso": regreso,
                "cambio": not ztc and any(not g["vig"] and g["l"]["zona"] == "ZTC" for g in ent),
                "desde_ztc": [g for g in vig if g["p"]["zona"] == "ZTC" and g not in regreso]}
    gre_res = {cpe: resumen_gre(cpe) for cpe in gre_venta}
    sin_gre = {"gs": [], "ent": [], "vig": [], "ztc": False, "zte": False, "cambio": False, "desde_ztc": [], "regreso": []}

    # ---------- Exportación de lo vendido a no domiciliados ----------
    exp_venta = {}
    for _, s in vend[vend.tdoc == "0"].sort_values("f").iterrows():
        cand = [x for x in exportaciones if not x["venta"] and 0 <= (pd.Timestamp(x["f"]) - s.f).days <= 90]
        if cand:
            cand[0]["venta"] = s.cpe
            exp_venta[s.cpe] = cand[0]

    # ---------- Traslados de maquinaria → venta probable (por tipo de máquina y fecha) ----------
    # Cada traslado se asigna a tantas ventas como máquinas traslada; cada venta, a un solo traslado.
    # Prioridad: venta exportada (no domiciliado con DAM de exportación), luego la más cercana en días.
    prob_venta, candidatos = {}, []
    for t in tr:
        t["venta"] = sorted({c for k in t["maqs"] for c in maq_venta.get(k, [])})   # venta de su máquina por número de serie
    resueltos = {t["i"] for t in tras_salida if t["venta"]}
    for t in tras_salida:
        if t["i"] in resueltos:
            continue
        tf = pd.Timestamp(t["f"])
        libres = vend[~vend.cpe.isin(list(venta_maq))]
        for _, x in libres[libres["cat"].isin(cat_t[t["i"]]) & ((libres.f - tf).dt.days.abs() <= 30)].iterrows():
            z = zona_doc.get(x.doc, "")
            if z in ("ZTC", "Extranjero") or x.igv > 0:
                dias = int((x.f - tf).days)
                candidatos.append((abs(dias) - (100 if x.cpe in exp_venta else 0) - (5 if z == "ZTC" else 0), t["i"], x.cpe, dias))
    cupo = {t["i"]: max(1, len(t["maqs"]) or int(t["cant"] or 1)) for t in tras_salida}
    for t in tr:
        t["prob"] = []
    for _, i, cpe, dias in sorted(candidatos):
        if cupo[i] > 0 and cpe not in prob_venta:
            cupo[i] -= 1
            prob_venta[cpe] = i
            tr[i]["prob"].append({"cpe": cpe, "dias": dias})
    limpio = lambda x: re.sub(r"[^A-Z0-9]", "", norm(x))
    coincide = lambda a_, b_: bool(a_ and b_) and (a_.endswith(b_) or b_.endswith(a_) or (min(len(a_), len(b_)) >= 8 and a_[-8:] == b_[-8:]))
    tras_ext = {}
    for t in tras_salida:
        pins = [limpio(p["pin"]) for p in cons["pin"] if p["exp"] == t["exp"]]
        if not pins:
            continue
        hall = {p["cpe"] for p in t["prob"] if any(coincide(pin, limpio(s["serie"])) for pin in pins for s in seriales.get(p["cpe"], []))}
        completo = len(pins) >= cons["pin_filas"].get(t["exp"], 0)
        for p in list(t["prob"]):
            if p["cpe"] in hall or completo:
                t["prob"].remove(p)
                prob_venta.pop(p["cpe"], None)
        for cpe in hall:
            tras_ext[cpe] = t["i"]
        t["venta"] = sorted(set(t["venta"]) | hall)
        t["pin_ext"] = [p["pin"] for p in cons["pin"] if p["exp"] == t["exp"]]
    # Anulaciones y reemisiones que coinciden con un traslado de maquinaria a la ZTC: la venta probable del traslado
    # es parte de la cadena, o la NC o la reemisión caen a 7 días o menos del traslado (mismo tipo de máquina y con indicio de salida)
    for c in cadenas:
        o = por_cpe.loc[c["orig"]]
        salida_c = zona_doc.get(o.doc, "") in ("ZTC", "Extranjero") or (c["orig_igv"] or 0) > 0 or (c["reem_igv"] or 0) > 0
        fechas = [pd.Timestamp(x) for x in (c["nc_f"], c["reem_f"]) if x] or [pd.Timestamp(c["orig_f"])]
        c["tras"] = [t["i"] for t in tras_salida if prob_venta.get(c["reem"]) == t["i"] or prob_venta.get(c["orig"]) == t["i"]
                     or {c["orig"], c["reem"]} & set(t["venta"])
                     or (t["i"] not in resueltos and c["reem"] not in venta_maq and o["cat"] in cat_t[t["i"]] and salida_c
                         and any(abs((pd.Timestamp(t["f"]) - x).days) <= 7 for x in fechas))]
        s_o = {x["serie"] for x in seriales.get(c["orig"], [])}
        s_r = {x["serie"] for x in seriales.get(c["reem"], [])}
        c["misma_serie"] = ", ".join(sorted(s_o & s_r)) if s_o and s_r else ""
        c["otra_serie"] = bool(s_o and s_r and not s_o & s_r)

    ctl_cache = {k: control_dam(k) for k in set(mq.dam) | set(ctl) if k in dams_periodo}

    # ---------- Casos: una venta de maquinaria con indicios ----------
    conv_key = dict(zip(mq.key, mq.conv))

    def con_beneficio(k):
        """Solo se siguen las máquinas con beneficio: la serie se importó con convenio (código liberatorio o TPI) y la
        solicitud de regularización de su DAM no es improcedente ni «sin solicitud de reconocimiento»."""
        c = ctl_cache.get(k.split("#")[0])
        return conv_key.get(k, "Sin beneficio") != "Sin beneficio" and not (c and not c["benef"])
    mq_dest = dict(zip(mq.key, mq.dest))
    sin_reg = lambda k: mq_dest.get(k) == "271" and ctl_cache.get(k.split("#")[0]) is None   # DAM de Tarapoto que no está en el cuaderno
    TEXTO = {"ztc": "Comprador domiciliado fuera de la ZTE", "igv": "Vendida con IGV", "cambio": "Reemitida sin IGV tras anular la factura con IGV",
             "entrega": "Entregada fuera de la ZTE (según la factura)", "nodom": "Vendida a no domiciliado sin DAM de exportación",
             "exp": "Vendida a no domiciliado, con DAM de exportación", "nuevo": "Comprador con RUC reciente",
             "no_habido": "Comprador no habido o con RUC no activo", "anul_tras": "Anulación o reemisión el día de un traslado de maquinaria",
             "dom_ztc": "Al comprar figuraba en la ZTE; hoy está domiciliado fuera",
             "gre_ztc": "Guía de remisión con llegada fuera de la ZTE", "gre_cambio": "Guía a la ZTC dada de baja y cambiada por otra a la ZTE",
             "gre_zte": "Guía de remisión con llegada en la ZTE"}
    casos = []
    for _, v in vend.sort_values("f").iterrows():
        c_ = cli.get(v.doc, {})
        z_hoy = c_.get("zona", "Sin dato")
        lug = lugar_fac.get(v.cpe)
        z = lug["zona"] if lug and lug["zona"] in ("ZTE", "ZTC") else z_hoy
        ch = cadena_de(v.cpe)
        ent = entrega.get(v.cpe)
        ex = exp_venta.get(v.cpe)
        gz = gre_res.get(v.cpe, sin_gre)
        mot = [k for k, ok in (
            ("ztc", z == "ZTC"), ("dom_ztc", z == "ZTE" and z_hoy == "ZTC"), ("igv", v.igv > 0), ("cambio", any(x["cambio"] == "con→sin" for x in ch)),
            ("entrega", bool(ent and ent["zona"] == "ZTC")), ("nodom", v.tdoc == "0" and not ex), ("exp", v.tdoc == "0" and bool(ex)),
            ("nuevo", bool(c_.get("nuevo")) and (v.f - pd.Timestamp(c_["finsc"])).days <= 180),
            ("no_habido", bool(c_.get("no_habido"))), ("anul_tras", any(x["tras"] for x in ch)), ("gre_ztc", gz["ztc"])) if ok]
        if not mot:
            continue
        maqs_v = venta_maq.get(v.cpe, [])
        maqs = [k for k in maqs_v if con_beneficio(k)]
        if maqs_v and not maqs:
            continue    # la máquina vendida no tiene el beneficio (importada sin él, improcedente o sin solicitud): no se sigue
        t_conf = sorted({i for k in maqs for i in tras_maq.get(k, []) if tr[i]["salida"]} | ({tras_ext[v.cpe]} if v.cpe in tras_ext else set()))
        cd_m = [ctl_cache.get(k.split("#")[0]) for k in maqs]
        tras_inf = [cd["tras_txt"] for cd in cd_m if cd and cd.get("tras_txt") and norm(cd["tras_txt"]) not in SIN_TRASLADO]
        sin_tras_inf = bool(maqs) and all(cd and cd.get("fuente") and norm(cd.get("tras_txt", "")) in SIN_TRASLADO for cd in cd_m)
        ext = cons["series"].get(v.cpe) if not maqs else None
        t_trans = sorted({i for k in maqs for i in tras_maq.get(k, []) if not tr[i]["salida"]})
        t_prob = [] if maqs or v.cpe not in prob_venta else [prob_venta[v.cpe]]
        dests = sorted({k.split("#")[0] for k in maqs})
        dest_m = sorted({mq.loc[mq.key == k, "dest"].iloc[0] for k in maqs})
        # Una venta exportada va a la ZTC para embarcarse: su guía a la ZTC no es por sí sola un indicio de salida
        salida = bool({"ztc", "igv", "cambio", "entrega", "nodom"} & set(mot)) or ("gre_ztc" in mot and "exp" not in mot)
        menor = v.vv < MENOR.get(v.moneda, 0) and not {"cambio", "nodom"} & set(mot)
        mot += [k for k, ok in (("gre_cambio", gz["cambio"]), ("gre_zte", gz["zte"] and not gz["cambio"])) if ok]
        if menor:
            continue
        xml = v.cpe in facturas
        if salida and (t_conf or tras_inf):
            nivel, estado = "Baja", "Regularizada: con solicitud de traslado" if t_conf else "Regularizada: traslado informado en la consulta"
        elif salida and maqs and any(sin_reg(k) for k in maqs):
            nivel, estado = "Alta", "Por confirmar: la DAM no está en el cuaderno de control"
        elif salida and maqs and (all(d == "271" for d in dest_m) or sin_tras_inf):
            nivel, estado = "Alta", ("Confirmada: guía de remisión con llegada fuera de la ZTE" if "gre_ztc" in mot else
                                     "Confirmada: solo tiene un traslado de tránsito" if t_trans else "Confirmada: sin solicitud de traslado")
        elif salida and maqs:
            nivel, estado = "Alta", f"DAM con destino {', '.join(DESTINOS.get(d, d) for d in dest_m)}: verificar con esa intendencia"
        elif salida and t_prob:
            nivel, estado = "Media", "Traslado probable: confirmar la serie"
        elif salida and ext:
            r_ = norm(ext["resultado"])
            if r_.startswith(("IMPORTADA POR OTRO", "COMPRA LOCAL")) and v.igv > 0 and (r_.startswith("COMPRA LOCAL") or norm(ext["modalidad"]).startswith("SIN DESGRAVACION")):
                nivel, estado = "Baja", f"Coherente: {ext['resultado'].lower()} sin beneficio y vendida con IGV (según la consulta)"
            elif r_.startswith(("IMPORTADA POR OTRO", "COMPRA LOCAL")):
                nivel, estado = "Media", f"Serie ubicada: {ext['resultado'].lower()} (sin beneficio de este importador)"
            elif r_.startswith("DAM ENCONTRADA") and norm(ext["modalidad"]).startswith("SIN DESGRAVACION"):
                nivel, estado = "Baja", "Coherente: importada sin beneficio (según la consulta)"
            elif r_.startswith("DAM ENCONTRADA"):
                nivel, estado = "Alta", f"DAM ubicada en la consulta: {ext['dam'] or 's/n'}" + (f" ({ext['intendencia']})" if ext["intendencia"] else "")
            else:
                nivel, estado = "Alta", "Serie no encontrada en la consulta"
        elif salida:
            nivel, estado = "Alta", ("Serie fuera de las DAM del periodo" if v.cpe in seriales else
                                     "El XML no indica la serie de la máquina" if v.cpe in facturas else "Por confirmar: falta el XML")
        elif {"nuevo", "no_habido", "anul_tras", "dom_ztc"} & set(mot):
            nivel, estado = "Media", ("Domicilio actual fuera de la ZTE: ubicar la máquina" if "dom_ztc" in mot else
                                      "Revisar al comprador" if not ch else "Revisar la cadena de comprobantes")
        else:
            nivel, estado = "Baja", ("Coherente: traslado y exportación, confirmados por serie" if t_conf and "exp" in mot else
                                     "Coherente: traslado y exportación" if t_prob else "Coherente: exportada" if "exp" in mot else "Seguimiento")
        # La guía de remisión lleva la máquina a la ZTE (sin otra guía a la ZTC ni cambio de destino): baja a nivel medio
        if ("gre_zte" in mot and "gre_cambio" not in mot and not {"cambio", "nodom", "entrega"} & set(mot) and not t_conf
                and (nivel == "Alta" or estado.startswith(("Domicilio actual", "Traslado probable")))):
            nivel, estado = "Media", "Guía de remisión a la ZTE: verificar que la máquina siga ahí"
        casos.append({"cpe": v.cpe, "f": fstr(v.f), "ruc": v.doc, "cli": v.nombre, "nivel": nivel, "estado": estado, "mot": mot,
                      "motivo": " · ".join(TEXTO[k] for k in mot), "mon": v.moneda, "vv": r2(v.vv), "igv": r2(v.igv), "tot": r2(v.total),
                      "zona": z, "zona_hoy": z_hoy, "lugar_fac": lug["lugar"] if lug else "", "zona_fac": lug["zona"] if lug else "",
                      "sede": lugar_sede((facturas.get(v.cpe) or {}).get("emisor", {}).get("sede") or sede_de.get(v.serie, "")),
                      "desc": v.desc, "cat": v["cat"], "merc": MERCANCIA.get(v["cat"], "Otros"), "maqs": maqs, "dams": dests, "series": seriales.get(v.cpe, []),
                      "cadena": ch, "anticipos": anticipos.get(v.cpe, []), "tras": t_conf, "transito": t_trans, "dam_ext": ext, "tras_prob": t_prob, "exp": ex["dam"] if ex else "", "entrega": ent, "xml": xml,
                      "gre": [{"i": i, "por": por} for i, por in sorted(gre_venta.get(v.cpe, {}).items(), key=lambda x: (guias[x[0]]["f"], guias[x[0]]["tipo"] != "Remitente", x[0]))],
                      "gre_bus": (gre_meta or {}).get("busquedas", {}).get(v.cpe[3:])})

    # ---------- Indicadores de cada máquina y de cada caso ----------
    maquinas = []
    for _, s in mq.iterrows():
        if not con_beneficio(s.key):
            continue    # sin beneficio (importada sin él, improcedente o sin solicitud de reconocimiento): no se sigue
        ex = exp_k8.get(s.k8)
        if ex:
            ex["maq"] = s.key
        t_ = tras_maq.get(s.key, [])
        mk = [k for k, ok in (("usada", s.usada), ("dep", s.k8 in dep_k8), ("exp", bool(ex)),
                              ("tras", any(tr[i]["salida"] for i in t_)), ("sinreg", sin_reg(s.key)),
                              ("venta", s.key in maq_venta), ("gre", s.key in maq_gre)) if ok]
        maquinas.append({"k": s.key, "dam": s.dam, "s": int(s.s), "f": fstr(s.f), "dest": s.dest, "canal": s.CANAL, "conv": s.conv,
                         "cat": s["cat"], "merc": MERCANCIA.get(s["cat"], "Otros"), "marca": s.marca, "modelo": s.modelo, "anio": s.anio, "pin": s.id, "motor": s.motor,
                         "usada": bool(s.usada), "horas": s.horas, "cant": r2(s.CNT_COMER), "cif": r2(s.MTO_VALORADU), "hs": s.NUM_PARTNANDI,
                         "dep": dep_k8.get(s.k8), "exp": {"dam": ex["dam"], "f": ex["f"], "ad": ex["ad"]} if ex else None,
                         "tras": t_, "ventas": maq_venta.get(s.key, []), "mk": mk})
    maq_por_k = {x["k"]: x for x in maquinas}
    ftx = lambda x: f"{x[8:10]}/{x[5:7]}/{x[:4]}" if x else "s/f"
    def nom(p_):
        n_ = (p_["nombre"] or p_["ruc"]).split(" - ")[-1].strip()
        return n_ if len(n_) <= 50 else n_[:50].rsplit(" ", 1)[0]
    num_g = lambda gs: " y ".join(", ".join(g["num"] for g in gs).rsplit(", ", 1))

    def acciones_gre(c):
        """Acciones que salen de las guías de remisión enlazadas con la venta (van primero)."""
        out, gz = [], gre_res.get(c["cpe"], sin_gre)
        pl_ = lambda n, uno, varios: f"{n} {uno if n == 1 else varios}"
        fuente = next((s_["fuente"] for s_ in c["series"] if s_["fuente"].startswith("Guía de remisión")), "")
        if fuente:
            out.append(f"La serie de la máquina se tomó de la {fuente[0].lower() + fuente[1:]}: la factura no la trae.")
        for g in [g for g in gz["vig"] if g["l"]["zona"] == "ZTC"]:
            if g["p"]["zona"] == "ZTC" and g in gz["regreso"]:
                continue
            base = (f"La guía {g['num']} del {ftx(g['f'])} ({g['tipo'].lower()}: {nom(g['em'])}) lleva la máquina de {g['p']['lugar'] or 's/d'} a "
                    f"{g['l']['lugar'] or 's/d'} (ZTC)")
            if c["nivel"] != "Alta":
                out.append(base + ".")
            elif g["p"]["zona"] == "ZTC":
                out.append(base + ": la máquina no pasó por la ZTE. " + ("Ubicar su DAM y verificar si se importó con el beneficio." if not c["maqs"]
                                                                          else "Requerir el sustento del beneficio aplicado a la DAM."))
            else:
                out.append(base + ": requerir el sustento de la salida de la ZTE.")
        for g in gz["regreso"][:1]:
            out.append(f"La guía {g['num']} del {ftx(g['f'])} ({(g['motivo'] or 'sin motivo').lower()}) regresa la máquina de {g['p']['lugar']} (ZTC) a "
                       f"{g['l']['lugar']} (ZTE) después de haber salido: vigilar si se anula la venta, si se pide la devolución de lo pagado por el "
                       "traslado o si la máquina se vuelve a vender en la ZTE sin IGV.")
        if gz["cambio"]:
            bajas = [g for g in gz["ent"] if not g["vig"] and g["l"]["zona"] == "ZTC"]
            rem = [g for g in bajas if g["estado"] == "Baja"]
            sig = [g for g in bajas if g["estado"] != "Baja"]
            vig = [g for g in gz["vig"] if g["tipo"] == "Remitente"] or gz["vig"]
            b0 = rem or bajas
            out.append(f"{'La guía' if len(b0) == 1 else 'Las guías'} {num_g(b0)} a {bajas[0]['l']['lugar']} (ZTC) {'se dio' if len(b0) == 1 else 'se dieron'} de baja"
                       + (f" ({rem[0]['baja'].lower()})" if rem and rem[0]["baja"] else "") + f" y {'la' if len(vig[:2]) == 1 else 'las'} {num_g(vig[:2])} {'lleva' if len(vig[:2]) == 1 else 'llevan'} la máquina a "
                       f"{vig[0]['l']['lugar']} ({vig[0]['l']['zona']}). "
                       + (f"Las guías del transportista {num_g(sig)} a {sig[0]['l']['lugar']} siguen emitidas. " if sig else "")
                       + "Verificar a dónde llegó la máquina: transportista, placas " + ", ".join(sorted({p_ for g in gz["gs"] for p_ in g["placas"]})[:4] or ["s/d"])
                       + ", peajes o visita.")
        internos = [g for g in gz["gs"] if interno(g) and g["estado"] != "Baja"]
        if internos and not gz["ent"]:
            g = max(internos, key=lambda g: g["f"])
            out.append(f"Solo hay traslados internos del importador: la guía {g['num']} del {ftx(g['f'])} lleva la máquina a su sede de {g['l']['lugar']}. "
                       "Falta la guía con la que se entregó al comprador: pedirla y ubicar la máquina.")
        if gz["ent"] and not gz["vig"]:
            bj = [g for g in gz["ent"] if g["estado"] == "Baja"] or gz["ent"]
            reemp = [g for g in guias if g["vig"] and g["em"]["ruc"] == bj[0]["em"]["ruc"] and g not in gz["gs"] and g["f"] and bj[0]["f"]
                     and abs((pd.Timestamp(g["f"]) - pd.Timestamp(bj[0]["f"])).days) <= 2 and g["l"]["u"] == bj[0]["l"]["u"]]
            out.append(f"{'La guía' if len(bj) == 1 else 'Las guías'} {num_g(bj)} con esta máquina {'se dio' if len(bj) == 1 else 'se dieron'} de baja"
                       + (f" y la {num_g(reemp[:2])}, que la reemplaza, ya no la incluye" if reemp else "")
                       + ": la máquina no viajó con esa guía. Pedir al comprador la guía con la que la recibió y ubicar la máquina.")
        if gz["zte"] and not gz["cambio"]:
            g = max(gz["vig"], key=lambda g: (g["tipo"] == "Remitente", g["f"]))
            otro = g["de"]["ruc"] not in ("", c["ruc"], g["em"]["ruc"])
            out.append(f"La guía {g['num']} del {ftx(g['f'])} ({nom(g['em'])}) lleva la máquina a {g['l']['lugar'] or 's/d'} (ZTE)"
                       + (f" para {nom(g['de'])}" if otro else "") + ": verificar en campo que siga ahí antes de cerrar el caso.")
        for g in [g for g in gz["desde_ztc"] if g["l"]["zona"] == "ZTE"][:1]:
            d_ = (pd.Timestamp(g["f"]) - pd.Timestamp(c["f"])).days
            out.append(f"Según la guía {g['num']}, la máquina partió de {g['p']['lugar']} (ZTC) {pl_(abs(d_), 'día', 'días') if d_ else 'el día'} "
                       f"{'después de la venta' if d_ > 0 else 'de la venta' if d_ == 0 else 'antes de la venta'}: al venderse no estaba en la ZTE"
                       + (". Buscar la DAM con la que ingresó la máquina." if not c["maqs"] and not c["dam_ext"] else "."))
        b_ = c.get("gre_bus")
        if b_ and not c["gre"] and c["nivel"] != "Baja":
            out.append(f"Se consultaron las guías del comprador del {ftx(b_['desde'])} al {ftx(b_['hasta'])} ({pl_(b_['n'], 'guía', 'guías')}): ninguna lleva "
                       "esta máquina. Pedir al comprador la guía con la que la recibió y dónde opera.")
        return out
    for c in casos:
        cl_ = cli.get(c["ruc"], {})
        mm = [maq_por_k[k] for k in c["maqs"]]
        cc = [ctl_cache.get(x["dam"]) for x in mm]
        c["mk"] = [k for k, ok in (
            ("igv", (c["igv"] or 0) > 0), ("ztc", c["zona"] == "ZTC"), ("zte", c["zona"] == "ZTE"), ("ext", c["zona"] == "Extranjero"),
            ("mudo", "dom_ztc" in c["mot"]),
            ("pub", cl_.get("tipo") == "Entidad pública"), ("pn", cl_.get("tipo") == "Persona natural"), ("rev", bool(cl_.get("rev"))),
            ("anul", bool(c["cadena"])), ("xml", c["xml"]), ("traza", bool(mm)), ("usada", any(x["usada"] for x in mm)),
            ("sinreg", any(sin_reg(x["k"]) for x in mm)), ("tras", bool(c["tras"])), ("trasp", bool(c["tras_prob"])), ("exp", bool(c["exp"])),
            ("gre_ztc", "gre_ztc" in c["mot"]), ("gre_cambio", "gre_cambio" in c["mot"]), ("gre_zte", "gre_zte" in c["mot"]), ("gre", bool(c["gre"]))) if ok]
        acc = []
        if not c["xml"] and not c["series"]:
            acc.append("Descargar el XML de la factura del portal del emisor para obtener la serie de la máquina y del motor.")
        elif not c["series"]:
            acc.append("El XML no trae la serie de la máquina: pedirla al emisor (guía de remisión, acta de entrega o ficha técnica).")
        elif not mm and c["dam_ext"] and norm(c["dam_ext"]["resultado"]).startswith("DAM ENCONTRADA"):
            x_ = c["dam_ext"]
            if c["nivel"] == "Alta":
                misma = [t for t in tr if x_["dam"] in t["dams"]]
                otras = sorted({p_["serie"] for t in misma for p_ in cons["pin"] if p_["exp"] == t["exp"] and p_["serie"] != x_["serie"]})
                acc.append(f"La consulta ubicó la máquina en la DAM {x_['dam']} serie {x_['serie'] or 's/d'} ({x_['intendencia'] or 's/d'}, "
                           f"{(x_['modalidad'] or 's/d').lower()}, solicitud {(x_['estado'] or 's/d').lower()}) y la venta no tiene solicitud de traslado: "
                           "requerir el sustento de la salida de la ZTE y los tributos (IGV e IPM)."
                           + (f" La misma DAM tiene el traslado {', '.join(t['exp'] for t in misma)}"
                              + (f" para las series {', '.join(otras)}" if otras else "") + ", pero no para esta." if misma else ""))
        elif not mm and c["tras"]:
            pass        # la serie coincide con el PIN de la DAM del traslado (consulta del equipo)
        elif not mm and c["dam_ext"] and norm(c["dam_ext"]["resultado"]).startswith("NO ENCONTRADA"):
            s0 = c["series"][0]
            acc.append(f"La consulta no encontró la serie {s0.get('serie') or 's/d'} en las DAM: pedir al comprador el documento con el que adquirió "
                       "la máquina (compra local o importación antigua).")
        elif not mm and c["nivel"] != "Baja":
            s0 = c["series"][0]
            t0 = tr[c["tras_prob"][0]] if c["tras_prob"] else None
            acc.append(f"Buscar la DAM por la serie {s0.get('serie') or 's/d'} y el motor {s0.get('motor') or 's/d'}: no está entre las DAM del importador "
                       f"del periodo (importada antes o comprada en el país)."
                       + (f" Compárela con la DAM {', '.join(t0['dams'])} del traslado {t0['exp']}." if t0 else ""))
        if "dom_ztc" in c["mot"]:
            acc.append(f"Al comprar figuraba en {c['lugar_fac']} (según la factura) y hoy su domicilio fiscal está en {cl_.get('lugar') or 'la ZTC'}: "
                       "ubicar la máquina (visita, guías de remisión o información de terceros).")
        for i in c.get("transito", []):
            acc.append(f"La máquina tiene el traslado {tr[i]['exp']} de tránsito (ZTE a ZTE pasando por la ZTC), pero se vendió a un comprador "
                       "de fuera de la ZTE: verificar su destino final.")
        for x, k in zip(mm, cc):
            if sin_reg(x["k"]):
                acc.append(f"Completar en el cuaderno de control (ConsolidadoT) la solicitud de regularización de la DAM {x['dam']}: sin ese dato "
                           "no se sabe si la máquina tiene el beneficio.")
            elif c["nivel"] == "Alta" and x["dest"] == "271" and not c.get("transito"):
                acc.append(f"Requerir el sustento de la salida de la ZTE de la máquina {x['pin'] or x['k']} (DAM {x['dam']} serie {x['s']}): "
                           "tiene el beneficio y no tiene solicitud de traslado para esta serie.")
            elif x["dest"] not in ("271", "") and (c["nivel"] == "Alta" or c["estado"].startswith("Guía de remisión a la ZTE")):
                acc.append(f"La DAM {x['dam']} tiene destino {DESTINOS.get(x['dest'], x['dest'])}: consultar en el sistema su control en destino y "
                           "sus traslados (está en el Excel de consultas a otras intendencias, en Resumen).")
        if "cambio" in c["mot"]:
            x = next(p for p in c["cadena"] if p["cambio"] == "con→sin")
            acc.append(f"Pedir el sustento de la {'baja' if x['via'] == 'Baja' else 'nota de crédito ' + x['nc']} de {x['orig']} (con IGV) y de su reemisión sin IGV.")
        if {"ztc", "entrega"} & set(c["mot"]) and not c["gre"] and c["nivel"] != "Baja":
            acc.append("Verificar dónde opera la máquina: visita, guías de remisión de la venta o información de terceros.")
        if c["tras_prob"]:
            acc.append("Confirmar con el XML si la máquina vendida es la del traslado probable (misma DAM y serie).")
        if "nuevo" in c["mot"] or "no_habido" in c["mot"]:
            acc.append("Verificar la existencia y la actividad del comprador (RUC reciente o no habido).")
        acc[:0] = acciones_gre(c)
        c["acc"] = acc
    orden = {"Alta": 0, "Media": 1, "Baja": 2}
    prio_estado = lambda s: (0 if s.startswith("Confirmada") else 1 if s.startswith("DAM con destino") else 2 if s.startswith("Por confirmar: la DAM")
                             else 3 if s.startswith("Serie") else 4 if s.startswith("El XML") else 5)
    casos.sort(key=lambda c: (orden[c["nivel"]], prio_estado(c["estado"]), -(c["tot"] or 0) * (3.4 if c["mon"] == "USD" else 1)))

    # ---------- Clientes compradores de maquinaria ----------
    for doc, c in cli.items():
        mios = vend[vend.doc == doc]
        cs = [x for x in casos if x["ruc"] == doc]
        c.update({"usd": r2(mios[mios.moneda == "USD"].vv.sum()), "pen": r2(mios[mios.moneda == "PEN"].vv.sum()),
                  "n_igv": int((mios.igv > 0).sum()), "alta": sum(x["nivel"] == "Alta" for x in cs), "media": sum(x["nivel"] == "Media" for x in cs),
                  "cpes": mios.sort_values("f").cpe.tolist()})
    ventas = []
    caso_de = {c["cpe"]: c["nivel"] for c in casos}
    for _, s in vm.sort_values("f").iterrows():
        est = "Dada de baja" if s.estado == "2" else "Anulada por NC" if s.cpe in anulada_por else "Vigente"
        ventas.append({"cpe": s.cpe, "f": fstr(s.f), "ruc": s.doc, "cli": s.nombre, "desc": s.desc, "cat": s["cat"], "mon": s.moneda,
                       "vv": r2(s.vv), "igv": r2(s.igv), "tot": r2(s.total), "est": est, "mot": s.tipo_ref if s.tipo == "07" else "",
                       "ref": nc_ref.get(s.cpe, ("", ""))[0], "nc": anulada_por.get(s.cpe, ""), "nivel": caso_de.get(s.cpe, "")})

    # ---------- Patrones ----------
    fecha_txt = lambda x: f"{x[8:10]}/{x[5:7]}/{x[:4]}" if x else "s/f"
    pl = lambda n, uno, varios: f"{n} {uno if n == 1 else varios}"
    modelo_key = dict(zip(mq.key, mq.modelo))
    maq_modelo = lambda k: modelo_key.get(k, "")
    pat = []
    if guias:
        con_gre = [c for c in casos if c["gre"]]

        def linea_g(g):
            return (f"{g['num']} del {fecha_txt(g['f'])} ({(g['em']['nombre'] or g['em']['ruc'])[:30].strip()}): {g['p']['lugar'] or 's/d'} → "
                    f"{g['l']['lugar'] or 's/d'} ({g['l']['zona']})" + (" — dada de baja" if g["estado"] == "Baja" else " — sustentada en una guía dada de baja" if not g["vig"] else ""))
        it = []
        for k, t_ in (("gre_ztc", "Llegada fuera de la ZTE"), ("gre_cambio", "Destino cambiado"), ("baja", "Guía dada de baja sin reemplazo"),
                      ("gre_zte", "Llegada en la ZTE")):
            for c in con_gre:
                gz = gre_res[c["cpe"]]
                if k in c["mot"] or (k == "baja" and gz["ent"] and not gz["vig"]):
                    gs = [guias[x["i"]] for x in c["gre"]]
                    gs = [g for g in gs if g["tipo"] == "Remitente"] or gs
                    it.append(f"{t_} · {c['cpe'][3:]} ({c['cli'][:30].strip()}, nivel {c['nivel'].lower()}"
                              + (f" · {c['estado'][:1].lower() + c['estado'][1:]}" if c["nivel"] == "Baja" else "")
                              + (f"; regresó a la ZTE el {fecha_txt(gz['regreso'][0]['f'])}" if gz["regreso"] else "") + "): " + "; ".join(linea_g(g) for g in gs[:3])
                              + (f"; y {len(gs) - 3} más" if len(gs) > 3 else ""))
        bus = gre_meta["busquedas"]
        sin_m = sorted(k for k in bus if not gre_venta.get("01-" + k))
        n_k = {k: sum(k in c["mot"] for c in casos) for k in ("gre_ztc", "gre_cambio", "gre_zte")}
        n_med = sum(c["estado"].startswith("Guía de remisión a la ZTE") for c in casos)
        pat.append({"id": "gre", "nivel": "Alta" if any(("gre_ztc" in c["mot"] or "gre_cambio" in c["mot"]) and c["nivel"] == "Alta" for c in casos) else "Info",
                    "t": "Guías de remisión de las máquinas vendidas", "items": it,
                    "txt": f"{len(guias):,} guías descargadas de SUNAT en {pl(len(gre_meta['archivos']), 'consulta', 'consultas')}"
                           f"{' (búsqueda por caso para ' + pl(len(bus), 'caso', 'casos') + ')' if bus else ''}; "
                           f"{pl(len(con_gre), 'venta tiene', 'ventas tienen')} la guía de su máquina: {n_k['gre_ztc']} con llegada fuera de la ZTE, "
                           f"{n_k['gre_cambio']} con destino cambiado y {n_k['gre_zte']} con llegada en la ZTE"
                           + (f" ({n_med} {'pasa' if n_med == 1 else 'pasan'} a nivel medio: verificar que la máquina siga ahí)" if n_med else "") + "."
                           + (f" En {pl(len(sin_m), 'caso consultado', 'casos consultados')} ninguna guía lleva la máquina: {', '.join(sin_m)}." if sin_m else ""),
                    "filtro": {"mk": "gre"}})
        dz = [(c, g) for c in con_gre for g in gre_res[c["cpe"]]["desde_ztc"][:1] if c["nivel"] != "Baja"]
        if dz:
            pat.append({"id": "gre_lima", "nivel": "Info", "t": "Máquinas que partieron de Lima o Callao después de la venta",
                        "items": [f"{c['cpe'][3:]} ({c['cli'][:30].strip()}, vendida el {fecha_txt(c['f'])}): guía {g['num']} del {fecha_txt(g['f'])}, "
                                  f"{g['p']['lugar']} → {g['l']['lugar']} ({g['l']['zona']})" + ("" if c["maqs"] else "; la serie no está en las DAM del periodo") for c, g in dz],
                        "txt": "La factura se emitió en una sede de la ZTE, pero la guía muestra que la máquina partió de la ZTC: al venderse no estaba en la zona. "
                               "Si la serie no está en las DAM del importador, buscar con qué DAM ingresó.",
                        "filtro": {"mk": "gre"}})
    zt = vend[vend.doc.map(lambda d: zona_doc.get(d, "")) == "ZTC"]
    n_mudo = sum(1 for c in casos if "dom_ztc" in c["mot"])
    if len(zt):
        top = zt.groupby("doc").size().sort_values(ascending=False)
        pat.append({"id": "ztc", "nivel": "Alta", "t": "Ventas de maquinaria a compradores de fuera de la ZTE",
                    "txt": f"{len(zt)} ventas de maquinaria a {zt.doc.nunique()} compradores con domicilio fiscal actual en la ZTC"
                           + (f" ({n_mudo} figuraban en la ZTE en su factura)" if n_mudo else "") + f"; {int((zt.igv == 0).sum())} sin IGV "
                           f"(venta exonerada a quien no está en la zona) y {int((zt.igv > 0).sum())} con IGV. Concentración: "
                           + "; ".join(f"{cli[d]['nombre']} ({n})" for d, n in top.head(4).items()) + ".",
                    "filtro": {"mot": "ztc"}})
    alta_sal = [c for c in casos if {"ztc", "igv", "cambio", "entrega", "nodom"} & set(c["mot"]) and "sin beneficio" not in c["estado"]]
    n_sb = sum(1 for c in casos if "sin beneficio" in c["estado"])
    n_ts = len(tras_salida)
    if alta_sal:
        pat.append({"id": "tras", "nivel": "Alta", "t": "Pocos traslados para tantas ventas con indicios de salida",
                    "txt": f"{len(alta_sal)} ventas de maquinaria con indicios de salida de la ZTE"
                           + (f" (sin contar {n_sb} de máquinas importadas sin beneficio)" if n_sb else "")
                           + f" frente a {n_ts} solicitudes de traslado de maquinaria a la ZTC "
                           f"en el periodo ({sum(len(t['maqs']) or int(t['cant'] or 0) for t in tras_salida)} máquinas). "
                           f"{sum(c['nivel'] == 'Alta' for c in casos)} casos de nivel alto siguen sin un traslado que los respalde.",
                    "filtro": {"nivel": "Alta"}})
    if tras_salida:
        def maq_tras(t):
            return ", ".join(cat_key[k].lower() + " " + maq_modelo(k) for k in t["maqs"]) or \
                pl(int(t["cant"] or 1), "máquina", "máquinas") + " de " + t["merc"].lower()

        def venta_tras(t):
            if t["venta"]:
                return ", ".join(f"{x[3:]} {cli.get(por_cpe.loc[x].doc, {}).get('nombre', '')[:28].strip()} (por serie)" for x in t["venta"])
            return ", ".join(f"{p['cpe'][3:]} {cli.get(por_cpe.loc[p['cpe']].doc, {}).get('nombre', '')[:28].strip()} (probable, {p['dias']:+d} d)"
                             for p in t["prob"]) or "sin venta enlazada"
        pat.append({"id": "probables", "nivel": "Info", "t": "Cada traslado de maquinaria y su venta",
                    "items": [f"{t['exp'].split('-')[-1]} del {fecha_txt(t['f'])} ({maq_tras(t)}) → {venta_tras(t)}" for t in tras_salida],
                    "txt": "«Por serie»: la factura (XML) lleva la serie de la máquina del traslado. «Probable»: propuesta por tipo de máquina y fecha "
                           "(días de la venta respecto del traslado), por confirmar con el XML.",
                    "filtro": {"mk": "tras"}})
    mudos = [c for c in casos if "dom_ztc" in c["mot"]]
    if mudos:
        por_cli = {}
        for c in mudos:
            por_cli.setdefault(c["ruc"], []).append(c)
        pat.append({"id": "mudos", "nivel": "Media", "t": "Compradores que figuraban en la ZTE al comprar y hoy están fuera",
                    "items": [f"{cs[0]['cli'][:40].strip()}: {pl(len(cs), 'venta', 'ventas')} ({', '.join(c['cpe'][3:] for c in cs)}) con domicilio en "
                              f"{', '.join(sorted({c['lugar_fac'] for c in cs}))} según la factura; hoy en {cli.get(k, {}).get('lugar', 'la ZTC')}"
                              + (f"; RUC inscrito el {fecha_txt(cli[k]['finsc'])}" if cli.get(k, {}).get("finsc", "") >= cs[0]["f"][:4] else "")
                              for k, cs in por_cli.items()],
                    "txt": "El domicilio del padrón es el de hoy; el de la factura, el del momento de la venta. Si el comprador se mudó, conviene ubicar la máquina.",
                    "filtro": {"mk": "mudo"}})
    exps = [c for c in casos if "exp" in c["mot"]]
    if exps or any("nodom" in c["mot"] for c in casos):
        pat.append({"id": "exp", "nivel": "Info", "t": "Ventas al exterior: flujo coherente",
                    "txt": f"{len(exps)} ventas de maquinaria a no domiciliados tienen DAM de exportación en los 90 días siguientes"
                           + (f"; {sum(1 for c in exps if c['tras_prob'] or c['tras'])} además con solicitud de traslado a la ZTC días antes"
                              + (f" ({sum(1 for c in exps if c['tras'])} confirmados por la serie de la factura)" if any(c['tras'] for c in exps) else "")
                              if exps else "")
                           + (f". Sin exportación: {sum('nodom' in c['mot'] for c in casos)}." if any('nodom' in c['mot'] for c in casos) else ". Ninguna venta a no domiciliados quedó sin exportación."),
                    "filtro": {"mot": "exp"}})
    coinc = [c for c in cadenas if c["tras"]]
    if coinc:
        txts = []
        for c in coinc:
            ts = [tr[i] for i in c["tras"]]
            txts.append(f"{c['orig'][3:]} → {('NC ' + c['nc'][3:] + ' → ') if c['nc'] else 'baja → '}{c['reem'][3:] or 'sin reemisión'} "
                        f"({fecha_txt(c['nc_f'] or c['reem_f'])}): " + "; ".join(
                            f"traslado {t['exp'].split('-')[-1]} del {fecha_txt(t['f'])} ({', '.join(cat_key[k].lower() + ' ' + maq_modelo(k) for k in t['maqs']) or t['merc'].lower()})"
                            + (f", venta probable {', '.join(p['cpe'][3:] for p in t['prob'])}" if t["prob"] else "") for t in ts))
        pat.append({"id": "anul_tras", "nivel": "Media", "t": "Anulación cerca de un traslado de maquinaria",
                    "txt": "; ".join(txts) + ". Con los XML de estas facturas se confirma qué máquina recibió cada comprador.",
                    "filtro": {"mot": "anul_tras"}})
    bj = [c for c in cadenas if c["via"] == "Baja"]
    nc_a = [c for c in cadenas if c["via"] != "Baja"]
    con_sin = [c for c in cadenas if c["cambio"] == "con→sin"]
    nc_re = sum(1 for c in nc_a if c["reem"])
    nc_otro = sum(1 for c in nc_a if not c["reem"] and c["otro"])
    med_b = pd.Series([c["dias"] for c in bj if c["dias"] is not None])
    con_sin_txt = "; ".join(c["orig"][3:] + " → " + c["reem"][3:] + (", misma máquina " + c["misma_serie"] + " según los XML" if c["misma_serie"] else "")
                            for c in con_sin)
    pat.append({"id": "hipotesis", "nivel": "Info", "t": "Anulaciones de facturas de maquinaria: ¿ligadas al traslado?",
                "items": [f"{pl(len(bj), 'factura dada de baja', 'facturas dadas de baja')}: {sum(1 for c in bj if c['reem'])} reemitidas al mismo cliente por el mismo valor "
                          f"(mediana: {pl(int(med_b.median()) if len(med_b) else 0, 'día', 'días')}).",
                          f"{pl(len(nc_a), 'anulada con nota de crédito', 'anuladas con nota de crédito')}: {nc_re} reemitidas al mismo cliente, {nc_otro} vendidas a otro "
                          f"cliente por el mismo tipo y valor y {len(nc_a) - nc_re - nc_otro} sin reemisión (anticipos que se consolidan en otra factura o ventas canceladas).",
                          f"Pasaron de con IGV a sin IGV: {len(con_sin)}{' (' + con_sin_txt + ')' if con_sin else ''}.",
                          f"Coinciden con un traslado de maquinaria: {len(coinc)}{' (' + ', '.join((c['reem'] or c['orig'])[3:] for c in coinc) + ')' if coinc else ''}."],
                "txt": f"La mayoría son correcciones del comprobante: la hipótesis no se sostiene en general, pero merece revisión en "
                       f"{pl(len(set(c['reem'] or c['orig'] for c in con_sin + coinc)), 'caso puntual', 'casos puntuales')}.",
                "filtro": {"mk": "anul"}})
    if seriales:
        con_serie = [c for c in casos if c["series"] or c["maqs"]]
        CATEG = (("Confirmada", "Confirmadas sin traslado de salida (DAM con destino Tarapoto)"),
                 ("DAM con destino", "De DAM con destino a otra intendencia amazónica"),
                 ("DAM ubicada", "Con DAM anterior al periodo ubicada en la consulta y sin traslado"),
                 ("Serie fuera", "Con una serie que no está en las DAM del importador del periodo"),
                 ("Coherente: importada por otro", "Importadas por otro importador sin beneficio y vendidas con IGV (según la consulta)"),
                 ("Guía de remisión a la ZTE", "Con guía de remisión a la ZTE (verificar que la máquina siga ahí)"),
                 ("Traslado probable", "Con traslado probable por confirmar"),
                 ("Regularizada", "Regularizadas con solicitud de traslado"),
                 ("Por confirmar: la DAM", "Con DAM de Tarapoto que no está en el cuaderno de control (completar el dato)"))
        cuenta = {}
        for c in con_serie:
            et = next((t for k, t in CATEG if c["estado"].startswith(k)), c["estado"])
            cuenta.setdefault(et, []).append(c["cpe"][3:])
        conf = [c for c in casos if c["estado"].startswith("Confirmada")]
        pat.append({"id": "serie", "nivel": "Alta" if conf else "Info", "t": "Trazabilidad por número de serie",
                    "items": [f"{k}: {len(cuenta[k])} ({', '.join(cuenta[k][:9])}{'…' if len(cuenta[k]) > 9 else ''})"
                              for k in [t for _, t in CATEG] + [x for x in cuenta if x not in [t for _, t in CATEG]] if k in cuenta],
                    "txt": f"{pl(len(facturas), 'XML leído', 'XML leídos')}; {len(venta_maq)} ventas enlazadas con su DAM por la serie de la máquina o del motor.",
                    "filtro": {"mk": "traza"}})
    # Fuera del seguimiento: máquinas sin beneficio. Dato faltante: DAM de Tarapoto que no está en el cuaderno. Traslados sin serie.
    dams_mq = set(mq.dam)
    fuera_ctl = sorted(k for k, c in ctl_cache.items() if c and not c["benef"] and k in dams_mq)
    fuera_conv = sorted({k.split("#")[0] for k in mq.key if conv_key.get(k) == "Sin beneficio"})
    sin_reg_d = sorted({x["dam"] for x in maquinas if sin_reg(x["k"])})
    tras_sin_serie = [{"exp": t["exp"], "f": t["f"], "tipo": t["tipo"], "merc": t["merc"], "dams": t["dams"], "cant": t["cant"]}
                      for t in tras_todos if not t["pares"] and (t["f"] >= fstr(desde) or set(t["dams"]) & dams_periodo)]
    if tras_sin_serie:
        print(f"AVISO traslados: {len(tras_sin_serie)} expedientes no indican la serie (completar en el cuaderno): "
              + ", ".join(t["exp"] for t in tras_sin_serie))
    if fuera_ctl or fuera_conv:
        n_fuera = int((~mq.key.map(con_beneficio)).sum())
        # No forman casos, pero se deja anotado lo que es materia de tributos internos: venta sin IGV a un comprador de la ZTC
        sin_igv_ztc = [v for _, v in vend.sort_values("f").iterrows() if venta_maq.get(v.cpe) and not any(con_beneficio(k) for k in venta_maq[v.cpe])
                       and not v.igv > 0 and zona_doc.get(v.doc) == "ZTC"]
        pat.append({"id": "fuera", "nivel": "Info", "t": "Máquinas sin beneficio: fuera del seguimiento",
                    **({"items": [f"Vendidas sin IGV a compradores de fuera de la ZTE (tributos internos, no aduaneros): "
                                  + "; ".join(f"{v.cpe[3:]} {v.nombre[:30].strip()} ({fecha_txt(fstr(v.f))})" for v in sin_igv_ztc)]} if sin_igv_ztc else {}),
                    "txt": f"{pl(n_fuera, 'serie de maquinaria no se sigue', 'series de maquinaria no se siguen')}: "
                           + "; ".join(x for x in (
                               pl(len(fuera_ctl), "DAM con solicitud improcedente o sin solicitud de reconocimiento", "DAM con solicitud improcedente o sin solicitud de reconocimiento") if fuera_ctl else "",
                               pl(len(fuera_conv), "DAM importada sin beneficio (sin código liberatorio ni TPI)", "DAM importadas sin beneficio (sin código liberatorio ni TPI)") if fuera_conv else "") if x)
                           + ". Nunca tuvieron el beneficio: pueden trasladarse o venderse a la ZTC sin riesgo aduanero."})
    if sin_reg_d:
        pat.append({"id": "sinreg", "nivel": "Media", "t": "DAM de Tarapoto que no están en el cuaderno de control",
                    "txt": f"{pl(len(sin_reg_d), 'DAM con maquinaria y destino Tarapoto no está', 'DAM con maquinaria y destino Tarapoto no están')} en ConsolidadoT "
                           f"ni en Ingreso de DAM: {', '.join(sin_reg_d[:12])}{'…' if len(sin_reg_d) > 12 else ''}. Completar el dato: sin él no se sabe si tienen el beneficio.",
                    "maq": {"mk": "sinreg"}})

    # ---------- Calidad de los datos ----------
    ftxt = lambda x: fecha_txt(fstr(x))
    n_dif = sum(1 for k, l in lugar_fac.items() if l["zona"] in ("ZTE", "ZTC") and cli.get((facturas[k]["cliente"]["doc"]), {}).get("zona") in ("ZTE", "ZTC")
                and l["zona"] != cli[facturas[k]["cliente"]["doc"]]["zona"])
    con_dom = sum(1 for c in cli.values() if c["zona"] in ("ZTE", "ZTC"))
    n_menor = int(sum(1 for _, v in vend.iterrows() if v.vv < MENOR.get(v.moneda, 0)))
    pn_sd = sum(c["n"] for c in cli.values() if c["zona"] == "Sin dato" and c["tipo"] == "Persona natural")
    est_xml = {}
    for d in facturas.values():
        est_xml.setdefault(d["id"].split("-")[0], set()).add(d["emisor"]["est"])
    multi_est = {k: sorted(v) for k, v in est_xml.items() if len(v) > 1}
    nc_inf = [c for c in cadenas if c["via"] != "Baja"]
    ncs_anula = ncs[ncs.tipo_ref.isin(NC_ANULA)]
    sin_271 = sorted({x["dam"] for x in maquinas if x["dest"] != "271"})
    obs_tras = []
    for g_ in grupos.values():
        if len(g_) > 1:
            k0 = g_[0]["maqs"][0]
            obs_tras.append(f"Expedientes {' y '.join(t['exp'].split('-')[-1] for t in g_)}: misma DAM y serie ({k0.replace('#', ', serie ')}) y misma RI "
                            f"{g_[0]['ri'].split('-SUNAT')[0]}" + "".join(f"; el monto de {t['exp'].split('-')[-1]} (S/ {t['monto']:,.0f}) no cuadra con el 18 % del CIF"
                                                                      for t in g_ if any(o.startswith('El monto') for o in t['obs'])) + ". Se cuenta uno solo")
    for t in tr:
        if not t.get("dup") and not any(t in g_ for g_ in grupos.values() if len(g_) > 1) and any(o.startswith("El monto") for o in t["obs"]):
            obs_tras.append(f"Expediente {t['exp'].split('-')[-1]}: {t['obs'][0].lower()}")
    calidad = {
        "confiable": [
            {"t": "DAM de importación", "d": f"{dec.dam.nunique():,} DAM y {len(m):,} series del régimen 10 ({ftxt(m.f.min())} a {ftxt(m.f.max())}); "
                                             f"{len(mq):,} series de maquinaria, {len(maquinas):,} con beneficio (las que se siguen). Depósito ({dep70.dam.nunique()} DAM) y exportación ({exp40.dam.nunique()} DAM) solo para la historia de cada máquina."},
            {"t": "Comprobantes emitidos", "d": f"{len(e):,} CPE y {len(dl):,} ítems de detalle ({ftxt(e.f.min())} a {ftxt(e.f.max())}); {len(vm):,} de la serie de maquinaria."},
        ] + ([{"t": "Sede emisora", "d": "Según los XML, cada serie corresponde a una sede: " + "; ".join(f"{k} {lugar_sede(v)}" for k, v in sorted(sede_de.items())) + "."}]
             if sede_de else []) + ([{"t": "XML de los comprobantes", "d": f"{len(facturas)} comprobantes leídos (UBL 2.1): {pl(sum(d['tipo'] == '01' for d in facturas.values()), 'factura', 'facturas')}"
                                                       f" y {pl(sum(d['tipo'] == '07' for d in facturas.values()), 'nota de crédito', 'notas de crédito')}"
                                                       + (f"; {len(xml_rep)} archivos repetidos se leyeron una sola vez" if xml_rep else "")
                                                       + f". {len(venta_maq)} ventas enlazadas con su DAM por la serie."}] if facturas else [])
          + ([{"t": "Consultas del equipo", "d": "Libro de consultas a otras intendencias: " + ", ".join(x for x in (
                  pl(len(cons["dam"]), "DAM con su control", "DAM con su control") if cons["dam"] else "",
                  pl(len(cons["series"]), "serie ubicada", "series ubicadas") if cons["series"] else "",
                  pl(len(cons["pin"]), "PIN de DAM anteriores al periodo", "PIN de DAM anteriores al periodo") if cons["pin"] else "") if x) + "."}]
             if cons["dam"] or cons["series"] or cons["pin"] else [])
          + ([{"t": "Cuaderno de control de la IA", "d": f"{sum(1 for k in ctl if k in dams_periodo)} DAM del periodo con solicitud de regularización "
                                                          f"(ConsolidadoT e Ingreso de DAM): {sum(1 for k, c in ctl_cache.items() if c and c['benef'])} con beneficio y "
                                                          f"{sum(1 for k, c in ctl_cache.items() if c and not c['benef'])} improcedentes o sin solicitud de reconocimiento; "
                                                          f"{len(tr)} expedientes de traslado."}] if ctl else [])
          + ([{"t": "Guías de remisión (GRE)", "d": f"{len(guias):,} guías descargadas de SUNAT con el extractor de GRE ("
                                                    + "; ".join(f"{x['titulo']}, {fecha_txt(x['generado'])}" for x in gre_meta["archivos"]) + "). "
                                                    + f"{len({i for d_ in gre_venta.values() for i in d_})} enlazadas con {len(gre_venta)} ventas. Enlaces: "
                                                    + ", ".join(f"{n} {POR_GRE.get(k, k)}" for k, n in Counter(p_ for d_ in gre_venta.values() for p_ in d_.values()).most_common()) + "."}]
             if guias else [])
          + ([{"t": "Domicilio fiscal y actividad", "d": f"Padrón reducido del RUC{' al ' + fecha_txt(str(dom.fecha_padron.iloc[0])) if dom is not None and 'fecha_padron' in dom and len(dom) else ''} "
                                                          f"y consulta múltiple de RUC: {con_dom} de {len(cli)} compradores de maquinaria ubicados en la ZTE o la ZTC."}] if dom is not None else []),
        "limites": [
            {"t": "Domicilio a la fecha del padrón", "d": "Es el vigente hoy: puede diferir del que tenía el comprador al comprar y del lugar donde opera la máquina. "
                                                            f"Cuando hay XML se usa el distrito impreso en la factura: en {n_dif} de {len(lugar_fac)} facturas está en otra zona que el domicilio actual."},
            {"t": "Personas naturales sin domicilio", "d": f"La consulta pública no muestra su domicilio: {pn_sd} ventas de maquinaria a personas naturales quedan sin zona."},
            {"t": "Venta y máquina sin XML", "d": "Sin el XML solo se puede proponer un traslado probable por tipo de máquina y fecha; el enlace firme es por número de serie."},
        ] + ([{"t": "Factura que anula cada nota de crédito", "d": f"{len(nc_inf)} de {len(ncs_anula)} notas de crédito de anulación enlazadas con su factura"
                                                                     + (f" ({n_x} por su XML, el resto por cliente, moneda y monto)." if (n_x := sum(1 for c in nc_inf if c['enlace'].startswith('XML'))) else
                                                                        " por cliente, moneda y monto; con el XML de la nota de crédito el enlace es exacto.")}] if len(ncs_anula) else [])
          + ([{"t": "Anticipos", "d": f"{len(anticipo_de)} facturas de anticipo se unieron con la factura final que las descuenta: cuentan como una sola máquina."}] if anticipo_de else [])
          + ([{"t": "Comprobantes menores", "d": f"{n_menor} facturas de la serie de maquinaria por menos de USD {MENOR['USD']:,} o S/ {MENOR['PEN']:,} "
                                                  f"(accesorios, implementos o pagos parciales) no forman casos."}] if n_menor else [])
          + ([{"t": "Control solo de destino Tarapoto", "d": f"El cuaderno cubre las DAM con destino 271. {len(sin_271)} DAM con maquinaria tienen otro destino "
                                                              f"(sobre todo Pucallpa) y no tienen datos de control aquí."}] if ctl else [])
          + ([{"t": "DAM de Tarapoto sin registro en el cuaderno", "d": f"{pl(len(sin_reg_d), 'DAM con maquinaria', 'DAM con maquinaria')} no están en ConsolidadoT ni en "
                                                                         f"Ingreso de DAM: {', '.join(sin_reg_d[:12])}{'…' if len(sin_reg_d) > 12 else ''}. Es un dato faltante; sus casos quedan «por confirmar»."}] if ctl and sin_reg_d else [])
          + ([{"t": "Traslados sin serie", "d": f"{pl(len(tras_sin_serie), 'expediente no indica', 'expedientes no indican')} la serie de la DAM, así que no se enlazan con ninguna "
                                                "máquina (el traslado vale solo para las series que cita): " + "; ".join(f"{t['exp']} ({', '.join(t['dams']) or 'sin DAM'})" for t in tras_sin_serie[:15])
                                                + ("…" if len(tras_sin_serie) > 15 else "") + ". Completarlas en el cuaderno."}] if tras_sin_serie else [])
          + ([{"t": "Registros de traslado a revisar", "d": ". ".join(obs_tras) + "."}] if obs_tras else [])
          + ([{"t": "Guías de remisión", "d": f"Solo se consultaron los compradores de {pl(len(gre_meta['busquedas']), 'caso', 'casos')}, de pocos días antes a "
                                              "dos semanas después de la venta; " + f"{sum(1 for g in guias if not g['nb'])} guías no detallan los bienes. "
                                              "La guía muestra a dónde se llevó la máquina, no dónde está hoy, y la llegada la declara quien la emite. "
                                              "El enlace «por tipo de máquina, comprador y fecha» es probable, no firme."
                                              + (" Algunas búsquedas quedaron incompletas: " + ", ".join(k for k, b in gre_meta["busquedas"].items() if b["incompleta"]) + "."
                                                 if any(b["incompleta"] for b in gre_meta["busquedas"].values()) else "")}] if guias else [])
          + ([{"t": "XML que no se pudieron leer", "d": f"{len(xml_err)}: {', '.join(xml_err[:10])}{' y otros' if len(xml_err) > 10 else ''}. Vuelva a descargarlos."}] if xml_err else []),
        "descartado": [
            {"t": "Sede inferida por el domicilio de los clientes", "d": "Se reemplazó por la sede que figura en los XML; se retiró la alerta de venta a otra circunscripción."},
            {"t": "Valoración y clasificación arancelaria", "d": "Valores unitarios atípicos y números de parte en varias subpartidas: no apuntan a la salida de la zona y daban muchos falsos positivos."},
            {"t": "Repuestos y servicios", "d": f"Con IGV ({int(((e.tipo == '01') & (e.estado == '0') & (e.igv > 0) & e.linea.isin(['Repuestos', 'Servicio técnico'])).sum()):,} facturas) o a no domiciliados: montos bajos y operación normal."},
            {"t": "Volumen de compras", "d": "Un cliente con 3 o más máquinas no es un indicio por sí solo; el número de máquinas queda como dato en Clientes."},
            {"t": "Maquinaria usada como alerta", "d": "Pasa a ser un indicador de la máquina."},
            {"t": "Diligencia, reconocimiento físico, RI, NCN y tributos", "d": "No se usan: para el riesgo basta saber si la DAM tiene el beneficio "
                                                                               "(solicitud de regularización, aunque la diligencia esté pendiente o sea no conforme) y si la serie tiene solicitud de traslado."},
            {"t": "Máquinas sin beneficio", "d": "Importadas sin código liberatorio ni TPI, o con solicitud improcedente o sin solicitud de reconocimiento: no se siguen."},
            {"t": "Estadísticas generales", "d": "Canal de control, fletes, subpartidas, ventas de repuestos y servicios: no ayudan a seguir la máquina."},
        ],
    }

    # ---------- Comprobantes por descargar (XML) ----------
    # 1: casos de nivel alto sin XML; 2: traslados probables por confirmar; 3: comprobantes de cadenas ligadas a un traslado o a un cambio de IGV
    pendientes = []
    def pendiente(cpe, prio, por):
        if cpe and cpe not in facturas and not any(p["cpe"] == cpe for p in pendientes):
            s_ = por_cpe.loc[cpe]
            pendientes.append({"cpe": cpe, "f": fstr(s_.f), "tot": r2(s_.total), "mon": s_.moneda, "cli": s_.nombre, "prio": prio, "por": por})
    for c in casos:
        if c["nivel"] == "Alta":
            pendiente(c["cpe"], 1, "Caso de nivel alto")
    for c in casos:
        if c["estado"].startswith("Traslado probable"):
            pendiente(c["cpe"], 2, "Confirmar el traslado probable")
    for c in coinc + con_sin:
        for x in (c["orig"], c["nc"], c["reem"]):
            pendiente(x, 3, "Cadena de anulación ligada a un traslado o a un cambio de IGV")
    for c in casos:
        if c["tras_prob"] and c["nivel"] == "Baja":
            pendiente(c["cpe"], 3, "Opcional: confirmar por serie el traslado de una exportación")

    # ---------- Salidas detectadas: máquinas que cruzan de la ZTE a la ZTC en cualquier guía descargada ----------
    # Un expediente por máquina. Pruebas: serie, DAM con beneficio, 4 años o menos, sin solicitud de traslado y
    # dónde está. La verificación del equipo (Excel, hoja «Salidas por verificar») completa lo que las guías no dicen.
    hoy = date.today()
    PLAZO = 4                                                    # años desde la importación en que la salida exige el traslado
    ubi_df = pd.read_csv(a.ubigeos, dtype=str).fillna("")
    circ_u = dict(zip(ubi_df.ubigeo, ubi_df.circunscripcion)) if "circunscripcion" in ubi_df else {}
    serie_maq = {}                                               # código (8 últimos del PIN, o motor) → máquina del importador
    for k, pin, motor in zip(mq.key, mq.id, mq.motor):
        for c in (k8(pin), motor if len(motor) >= 8 else ""):
            if c:
                serie_maq.setdefault(codigo(c), k)
    serie_venta = {}                                             # serie del XML → venta (máquinas que no están en las DAM del periodo)
    for cpe, lista in seriales.items():
        for s_ in lista:
            for x in (s_.get("serie"), s_.get("motor")):
                c = codigo(x or "")
                if len(c) >= 6:
                    serie_venta.setdefault(c, cpe)
    pin_tras = {}
    for p_ in cons["pin"]:
        c = codigo(p_["pin"])
        if len(c) >= 8:
            pin_tras[c[-8:]] = p_
    venta_guia = {i: cpe for cpe, d_ in gre_venta.items() for i in d_}
    casos_cpe = {c["cpe"]: c for c in casos}
    dueno = lambda g: (g["rem"] if g["tipo"] == "Transportista" and g.get("rem") and g["rem"]["ruc"] else g["em"])
    bienes_de = lambda i: guias[i]["bienes"] or (guias[guias[i]["sustenta"]]["bienes"] if guias[i].get("sustenta") is not None else [])
    g_txt2 = [codigo(" ".join(bienes_de(i))) for i in range(len(guias))]

    def maquinas_guia(i):
        """Máquinas de la guía: por la descripción y, además, las del importador nombradas solo por su serie."""
        out = [{"cat": c, "desc": b, "serie": s_} for c, b, s_ in maquinas_en_bienes(bienes_de(i))]
        t = g_txt2[i]
        for c, k in serie_maq.items():
            if c in t and not any(x["serie"] and (x["serie"].endswith(c) or c.endswith(x["serie"])) for x in out):
                out.append({"cat": cat_key.get(k, "Otros"), "desc": next((b for b in bienes_de(i) if c in codigo(b)), ""), "serie": c})
        cpe = venta_guia.get(i)
        s_x = [codigo(x.get("serie", "")) for x in seriales.get(cpe, [])] if cpe else []
        for x in out:                       # la guía cita la factura y no trae la serie: se toma la del XML de esa factura
            if not x["serie"] and len(s_x) == 1 and len(s_x[0]) >= 6:
                x["serie"] = s_x[0]
        return out
    canon = lambda sr: (sr[-8:] if len(sr) >= 8 and sr[-8:] in serie_maq else sr)
    grupos_s = {}
    for i, g in enumerate(guias):
        if not (g["p"]["zona"] == "ZTE" and g["l"]["zona"] == "ZTC") or not g["f"]:
            continue
        for x in maquinas_guia(i):
            k_ = canon(x["serie"]) if x["serie"] else f"sin:{dueno(g)['ruc']}|{x['cat']}"
            grupos_s.setdefault(k_, {"gs": [], "maq": x})["gs"].append(i)
            if x["serie"] and not grupos_s[k_]["maq"]["serie"]:
                grupos_s[k_]["maq"] = x
    # Una guía sin serie del mismo dueño, del mismo tipo de máquina y a 3 días o menos de otra con serie es la misma máquina
    for k_ in [k for k in grupos_s if k.startswith("sin:")]:
        ruc_d, cat_d = k_[4:].split("|")
        f_sin = [pd.Timestamp(guias[i]["f"]) for i in grupos_s[k_]["gs"]]
        cand = [k2 for k2, v in grupos_s.items() if not k2.startswith("sin:") and v["maq"]["cat"] == cat_d
                and any(dueno(guias[i])["ruc"] == ruc_d and min(abs((pd.Timestamp(guias[i]["f"]) - f).days) for f in f_sin) <= 3 for i in v["gs"])]
        if len(cand) == 1:
            grupos_s[cand[0]]["gs"] += grupos_s.pop(k_)["gs"]
    # Las guías sin serie de un mismo dueño y tipo se separan por viaje (más de 20 días entre guías = otra salida)
    for k_ in [k for k in grupos_s if k.startswith("sin:")]:
        gs_ = sorted(set(grupos_s[k_]["gs"]), key=lambda i: guias[i]["f"])
        viajes = [[gs_[0]]]
        for i in gs_[1:]:
            if (pd.Timestamp(guias[i]["f"]) - pd.Timestamp(guias[viajes[-1][-1]]["f"])).days > 20 or guias[i]["l"]["u"] != guias[viajes[-1][-1]]["l"]["u"]:
                viajes.append([i])
            else:
                viajes[-1].append(i)
        maq_ = grupos_s.pop(k_)["maq"]
        for n_, v in enumerate(viajes):
            grupos_s[f"{k_}|{n_}"] = {"gs": v, "maq": maq_}

    prov_zte = {}                                                # departamento → provincias que están (casi) enteras en la ZTE
    for (dep_, prov_), z_ in ubi_df.groupby(["departamento", "provincia"]).zona:
        if (z_ == "ZTE").mean() >= 0.5:
            prov_zte.setdefault(dep_, set()).add(prov_)

    def duda_direccion(g):
        """La llegada está en la ZTC según el distrito, pero la dirección nombra una provincia de la ZTE del mismo departamento."""
        fila_u = ubi_df[ubi_df.ubigeo == g["l"]["u"]]
        if not len(fila_u) or not g["l"]["dir"]:
            return ""
        dep_, prov_ = fila_u.departamento.iloc[0], fila_u.provincia.iloc[0]
        t = " " + " ".join(re.findall(r"[A-Z]+", norm(g["l"]["dir"]))) + " "
        hall = sorted(p_ for p_ in prov_zte.get(dep_, set()) if p_ != prov_ and len(p_) >= 4 and f" {p_} " in t)
        return ", ".join(x.title() for x in hall)

    cob_ruc = (gre_meta or {}).get("cobertura", {})

    def cobertura(ruc, desde_iso, rol="emisor"):
        """Parte del periodo [desde, hoy] con guías consultadas del RUC en ese rol (0 a 1) y los tramos consultados."""
        tramos = cob_ruc.get(ruc, {}).get(rol, [])
        d0, total = date.fromisoformat(desde_iso), max(1, (hoy - date.fromisoformat(desde_iso)).days + 1)
        dias = sum(max(0, (min(hoy, date.fromisoformat(h_)) - max(d0, date.fromisoformat(d_))).days + 1) for d_, h_ in tramos)
        return round(min(1.0, dias / total), 2), tramos

    def anios_entre(f_dam, f_sal):
        """Antigüedad al salir. f_dam puede ser una fecha o solo el año."""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f_dam or ""):
            return round((pd.Timestamp(f_sal) - pd.Timestamp(f_dam)).days / 365.25, 1)
        if re.fullmatch(r"\d{4}", (f_dam or "")[:4]) and len(f_dam) <= 7:
            return float(int(f_sal[:4]) - int(f_dam[:4]))
        return None
    si_no = lambda v: True if norm(v).startswith("SI") else False if norm(v).startswith("NO") else None
    salidas = []
    for k_, v in grupos_s.items():
        gs_ = sorted(set(v["gs"]), key=lambda i: (guias[i]["f"], guias[i]["tipo"] != "Remitente", i))
        vig = [i for i in gs_ if guias[i]["vig"]]
        base = vig or gs_
        g0 = guias[base[0]]
        ver = cons.get("salidas", {}).get(g0["clave"]) or next((cons.get("salidas", {}).get(guias[i]["clave"]) for i in gs_ if guias[i]["clave"] in cons.get("salidas", {})), None) or {}
        serie = "" if k_.startswith("sin:") else k_
        serie = serie or ver.get("serie", "")
        # Todas las guías que nombran la serie: para saber dónde quedó y si regresó
        todas = sorted(set(gs_) | ({i for i, t in enumerate(g_txt2) if serie in t} if len(serie) >= 6 else set()), key=lambda i: (guias[i]["f"], i))
        post = [i for i in todas if guias[i]["vig"] and guias[i]["f"] >= g0["f"]]
        regreso = next((guias[i] for i in post if guias[i]["p"]["zona"] == "ZTC" and guias[i]["l"]["zona"] == "ZTE"), None)
        g_ult = guias[post[-1]] if post else g0
        # DAM de la máquina
        dam = {"dam": "", "serie": "", "f": "", "imp": "", "benef": None, "fuente": ""}
        tras, tras_nota = None, ""
        cpe = (serie_venta.get(serie) or (serie_venta.get(serie[-8:]) if len(serie) >= 8 else None)) if serie else None
        cpe = cpe or next((venta_guia[i] for i in gs_ if i in venta_guia), None)
        k_m = serie_maq.get(serie[-8:]) if len(serie) >= 8 else serie_maq.get(serie)
        if k_m:
            fila_m = mq[mq.key == k_m].iloc[0]
            dam = {"dam": fila_m.dam, "serie": str(int(fila_m.s)), "f": fstr(fila_m.f), "imp": m.NOM_RAZONSOCIAL.iloc[0], "benef": bool(con_beneficio(k_m)),
                   "fuente": "DAM del importador" + ("" if con_beneficio(k_m) else ": importada sin beneficio")}
            t_m = [tr[j] for j in tras_maq.get(k_m, []) if tr[j]["salida"]]
            cpe = cpe or (maq_venta.get(k_m) or [None])[0]
            if t_m:
                tras, tras_nota = True, f"Solicitud de traslado {t_m[0]['exp']} del {ftx(t_m[0]['f'])}"
            elif fila_m.dest == "271":
                tras, tras_nota = False, "No figura en el cuaderno de traslados de la IA Tarapoto"
            elif fila_m.dest:
                tras_nota = f"La DAM tiene destino {DESTINOS.get(fila_m.dest, fila_m.dest)}: confirmar con esa intendencia"
        else:
            cpe = cpe or serie_venta.get(serie) or (serie_venta.get(serie[-8:]) if len(serie) >= 8 else None)
            ext = cons["series"].get(cpe) if cpe else None
            if ext:
                r_ = norm(ext["resultado"])
                sin_d = norm(ext["modalidad"]).startswith("SIN DESGRAVACION")
                if r_.startswith("DAM ENCONTRADA"):
                    dam = {"dam": ext["dam"], "serie": ext["serie"], "f": (re.findall(r"\d{3}-(\d{4})-", ext["dam"]) or [""])[0], "imp": m.NOM_RAZONSOCIAL.iloc[0],
                           "benef": not sin_d, "fuente": "Consulta del equipo" + (f" ({ext['intendencia']})" if ext["intendencia"] else "")}
                    tras, tras_nota = False, "No figura en el cuaderno de traslados de la IA Tarapoto"
                elif r_.startswith(("IMPORTADA POR OTRO", "COMPRA LOCAL")):
                    dam = {"dam": ext["dam"], "serie": ext["serie"], "f": (re.findall(r"\d{3}-(\d{4})-", ext["dam"]) or [""])[0], "imp": "Otro importador",
                           "benef": False if sin_d or r_.startswith("COMPRA LOCAL") else None, "fuente": f"Consulta del equipo: {ext['resultado'].lower()}"}
            c_ = casos_cpe.get(cpe) if cpe else None
            if pin_tras.get(serie[-8:] if len(serie) >= 8 else serie) or (c_ and c_["tras"]):
                p_ = pin_tras.get(serie[-8:] if len(serie) >= 8 else serie) or {}
                tras, tras_nota = True, f"Solicitud de traslado {p_.get('exp') or tr[c_['tras'][0]]['exp']}"
        # La salida no partió de la circunscripción de la IA Tarapoto: el traslado se pudo pedir en otra intendencia
        circ = circ_u.get(g0["p"]["u"], "")
        if tras is False and circ and circ != "IA TARAPOTO":
            tras, tras_nota = None, f"No figura en el cuaderno de Tarapoto, pero la máquina partió de la circunscripción de la {circ}: confirmar ahí"
        if ver:                             # lo que verificó el equipo manda sobre lo deducido
            if ver.get("dam") or ver.get("f_dam") or ver.get("imp"):
                dam.update({"dam": ver.get("dam") or dam["dam"], "serie": ver.get("serie_dam") or dam["serie"], "f": ver.get("f_dam") or dam["f"],
                            "imp": ver.get("imp") or dam["imp"], "fuente": "Verificación del equipo"})
            if si_no(ver.get("benef", "")) is not None:
                dam["benef"], dam["fuente"] = si_no(ver["benef"]), "Verificación del equipo"
            if si_no(ver.get("tras", "")) is not None:
                tras = si_no(ver["tras"])
                tras_nota = (f"Solicitud de traslado {ver.get('exp', '')}".strip() if tras else "Sin solicitud de traslado") + " (verificación del equipo)"
        edad = anios_entre(dam["f"], g0["f"])
        plazo = None if edad is None else edad <= PLAZO
        mov, rec = dueno(g0), g0["de"]
        venta_m = norm(g0["motivo"]).startswith("VENTA")
        ten = rec if venta_m and rec["ruc"] else mov
        ubic = {"lugar": g_ult["l"]["lugar"], "dir": g_ult["l"]["dir"], "zona": g_ult["l"]["zona"], "f": g_ult["f"], "dias": (hoy - date.fromisoformat(g_ult["f"])).days,
                "guia": g_ult["num"], "rec": g_ult["de"], "verif": ver.get("ubic", "")}
        c_ = casos_cpe.get(cpe) if cpe else None
        exportada = bool(c_ and c_.get("exp"))
        recs = [{"ruc": r, "nombre": n_} for r, n_ in {guias[i]["de"]["ruc"]: guias[i]["de"]["nombre"] for i in gs_ if guias[i]["de"]["ruc"]}.items()]
        quienes = [(ten, "tenedor")] + [(r_, "quien la recibió") for r_ in recs if r_["ruc"] != ten["ruc"]]
        quienes = [(q, rol) for q, rol in quienes if ruc_valido(q["ruc"]) and q["ruc"] != ruc_imp]
        seguir = [{"ruc": q["ruc"], "nombre": q["nombre"], "rol": rol} for q, rol in quienes if cobertura(q["ruc"], g0["f"])[0] < 0.9]
        cubiertos = [(q, max((h_ for _, h_ in cobertura(q["ruc"], g0["f"])[1]), default="")) for q, rol in quienes if cobertura(q["ruc"], g0["f"])[0] >= 0.9]
        if mov["ruc"] == ruc_imp and vig:   # envío del propio importador: la máquina está donde el comprador; lo que falta no es ubicarla
            seguir, cubiertos = [], []
        # Estado del expediente
        falta, pasos = [], []
        if dam["benef"] is False:
            estado, motivo = "Descartada", ("Sin beneficio: " + (dam["fuente"] or "importada sin el beneficio")).replace("DAM del importador: importada sin beneficio", "importada sin el beneficio")
        elif tras is True:
            estado, motivo = "Descartada", tras_nota
        elif plazo is False:
            estado, motivo = "Descartada", f"Salió {edad:g} años después de la importación (más de {PLAZO})"
        elif regreso is not None:
            estado, motivo = "Regresó a la ZTE", f"Volvió el {ftx(regreso['f'])} con la guía {regreso['num']} ({regreso['l']['lugar']})"
        else:
            if not vig:
                falta.append("confirmar a dónde llegó: la guía a la ZTC se dio de baja")
            if not serie:
                falta.append("la serie de la máquina")
            if dam["benef"] is None:
                falta.append("la DAM y si tiene el beneficio" if serie else "la DAM (primero hace falta la serie)")
            elif plazo is None:
                falta.append("la fecha de la DAM, para medir los 4 años")
            if tras is None:
                falta.append("confirmar que no hay solicitud de traslado")
            estado = "Caso armado" if not falta else "Indicio: guía dada de baja" if not vig else "Por completar"
            motivo = ("Con beneficio, sin solicitud de traslado y dentro de los 4 años: ubicar y verificar la máquina" if not falta else "Falta " + "; ".join(falta))
            if not serie:
                pasos.append(f"Pedir la serie a {nom(ten)}: la guía no la indica. Revise «Ver guía» por si aparece en otro campo, o requiérale la factura o la ficha técnica.")
            elif dam["benef"] is None:
                pasos.append(f"Buscar en el sistema la DAM de la serie {serie} y anotarla en el Excel de consultas (hoja «Salidas por verificar»): DAM, fecha, importador y si tiene el beneficio.")
            if tras is None and dam["benef"] is not False:
                pasos.append((tras_nota + ".") if tras_nota else "Confirmar en el cuaderno o en el sistema que la serie no tiene solicitud de traslado y anotarlo en el Excel.")
            if not vig:
                pasos.append("La guía a la ZTC se dio de baja. Descargar las guías posteriores del comprador y del transportista para ver a dónde llegó la máquina.")
            pasos.append(f"Última ubicación conocida: {ubic['lugar']}" + (f" ({ubic['dir']})" if ubic["dir"] else "") + f", el {ftx(ubic['f'])} (hace {ubic['dias']} días), "
                         f"recibida por {(nom(ubic['rec']) if ubic['rec']['ruc'] or ubic['rec']['nombre'] else nom(ten)).rstrip('.')}.")
            if cubiertos:
                pasos.append("Las guías de " + " y de ".join(f"{nom(q).rstrip('.')} (hasta el {ftx(h_)})" for q, h_ in cubiertos) + " ya están consultadas y ninguna posterior "
                             "nombra esta máquina: o sigue donde la dejó la última guía o se movió sin guía. Corresponde requerir al tenedor que informe dónde está.")
            if seguir:
                pasos.append("Para actualizar la ubicación, descargue las guías posteriores de " + " y de ".join(nom(q).rstrip(".") for q in seguir) + " (botón «Seguir la máquina»).")
            if estado == "Caso armado":
                pasos.append("Con la ubicación confirmada, programar la verificación física y el requerimiento al tenedor.")
            duda = duda_direccion(g0) if vig else ""
            if duda:
                pasos.insert(0, f"Ojo: el distrito de llegada de la guía es {g0['l']['lugar']} (ZTC), pero la dirección nombra {duda}, que está en la ZTE. "
                                "El distrito puede estar mal puesto y la máquina no haber salido: confirmarlo antes de seguir.")
        if exportada and estado not in ("Descartada",):
            pasos.insert(0, f"La venta {cpe[3:]} es a un no domiciliado y tiene DAM de exportación {c_['exp']}: confirmar que la salida corresponde a esa exportación y que tuvo su traslado.")
        transp = {}
        for i in gs_:
            if guias[i]["tipo"] == "Transportista":
                transp[guias[i]["em"]["ruc"]] = guias[i]["em"]["nombre"]
        salidas.append({
            "clave": g0["clave"], "f": g0["f"], "estado": estado, "motivo": motivo, "falta": falta, "pasos": pasos,
            "maq": {"cat": v["maq"]["cat"], "desc": v["maq"]["desc"][:160], "serie": serie, "k": k_m if k_m and k_m in maq_por_k else None},
            "mov": mov, "rec": rec, "ten": ten, "motivo_g": g0["motivo"], "evid": "vigente" if vig else "baja",
            "p": g0["p"]["lugar"], "l": g0["l"]["lugar"], "ubic": ubic, "regreso": {"f": regreso["f"], "guia": regreso["num"], "lugar": regreso["l"]["lugar"]} if regreso is not None else None,
            "dam": dam, "edad": edad, "tras": tras, "tras_nota": tras_nota, "cpe": cpe if cpe in casos_cpe else None, "venta": cpe or "",
            "exportada": c_["exp"] if exportada else "", "cliente": next((r for r in (ten["ruc"], mov["ruc"], rec["ruc"]) if r in cli), None),
            "pruebas": {"serie": bool(serie) or None, "dam": dam["benef"], "plazo": plazo, "tras": (not tras) if tras is not None else None, "salida": bool(vig)},
            "recs": recs, "seguir": seguir,
            "transp": [{"ruc": r, "nombre": n_} for r, n_ in transp.items()], "placas": sorted({pl_ for i in gs_ for pl_ in guias[i]["placas"]})[:6],
            "gs": sorted(set(gs_) | set(post), key=lambda i: (guias[i]["f"], i)), "ver": bool(ver), "obs": ver.get("obs", "")})
    ORDEN_S = {"Caso armado": 0, "Indicio: guía dada de baja": 1, "Por completar": 2, "Regresó a la ZTE": 3, "Descartada": 4}
    salidas.sort(key=lambda x: (ORDEN_S[x["estado"]], len(x["falta"]), [-ord(c) for c in x["f"]]))
    for n_, x in enumerate(salidas, 1):
        x["id"] = f"S{n_:02d}"

    # Patrón de cabecera: quién saca las máquinas
    vivas = [x for x in salidas if x["estado"] != "Descartada"]
    if salidas:
        n_imp = sum(1 for x in vivas if x["mov"]["ruc"] == ruc_imp)
        ti_ = meta_ctl.get("traslados_maq", {})
        pat.insert(0, {"id": "salidas", "nivel": "Alta" if any(x["estado"] == "Caso armado" for x in salidas) else "Media", "ir": "salidas",
                       "t": "Quién saca las máquinas de la ZTE",
                       "items": [f"{x['id']} · {x['estado']}: {x['maq']['cat'].lower()}" + (f" {x['maq']['serie']}" if x["maq"]["serie"] else " sin serie")
                                 + f", {x['p']} → {x['l']} el {fecha_txt(x['f'])}; la movió {nom(x['mov'])}" for x in vivas[:8]],
                       "txt": f"{pl(len(salidas), 'máquina cruza', 'máquinas cruzan')} de la ZTE a la ZTC en las guías descargadas: {len(salidas) - len(vivas)} descartadas "
                              f"(con solicitud de traslado o sin beneficio) y {len(vivas)} por trabajar, de las cuales {n_imp} las envió el importador y "
                              f"{len(vivas) - n_imp} las movió el comprador o un tercero."
                              + (f" En el cuaderno, los {ti_['total']} traslados de maquinaria amarilla ({ti_['anios']}) los pidieron {ti_['solicitantes']} importadores; "
                                 "ningún comprador pidió uno." if ti_.get("total") and not ti_.get("no_importador") else "")})

    # ---------- Parque: quién tiene cada máquina con beneficio y su último rastro ----------
    sal_maq = {x["maq"]["k"]: x["id"] for x in salidas if x["maq"]["k"]}
    for x in maquinas:
        cpe_m = (maq_venta.get(x["k"]) or [None])[0]
        x["ten"] = por_cpe.loc[cpe_m].doc if cpe_m and cpe_m in por_cpe.index else ""
        idx = [i for i in maq_gre.get(x["k"], []) if guias[i]["vig"] and guias[i]["f"]]
        if idx:
            g = guias[max(idx, key=lambda i: (guias[i]["f"], i))]
            x["ult"] = {"f": g["f"], "lugar": g["l"]["lugar"], "zona": g["l"]["zona"], "guia": g["num"], "rec": g["de"]["nombre"][:50], "dias": (hoy - date.fromisoformat(g["f"])).days}
        else:
            x["ult"] = None
        x["edad"] = round((hoy - date.fromisoformat(x["f"])).days / 365.25, 1)
        x["sal"] = sal_maq.get(x["k"], "")
        if x["ten"] or x["ult"]:
            pass
        x["mk"] = x["mk"] + (["sal"] if x["sal"] else []) + ([] if x["ten"] or x["ult"] else ["sinrastro"])

    # ---------- Tenedores: riesgo de que muevan la máquina y cobertura de sus guías ----------
    def perfil_cli(c):
        act, n_ = norm(c.get("actividad", "")), norm(c["nombre"])
        return ("Entidad pública" if c["tipo"] == "Entidad pública" else "No domiciliado" if c["tipo"] == "No domiciliado"
                else "Consorcio" if n_.startswith("CONSORCIO") else "Alquiler de maquinaria" if "ALQUILER" in act
                else "Constructora o ingeniería" if "CONSTRUCCION" in act or "INGENIERIA" in act else "Transporte" if "TRANSPORTE" in act
                else "Persona natural" if c["tipo"] == "Persona natural" else "Otros")
    FRONTERA_DEP, FRONTERA_PROV = {"CAJAMARCA", "HUANUCO"}, {"UTCUBAMBA", "BAGUA", "TOCACHE", "PADRE ABAD"}
    for doc, c in cli.items():
        cs = [x for x in casos if x["ruc"] == doc]
        partes = [x.strip() for x in c.get("lugar", "").split(",")]
        c["perfil"] = perfil_cli(c)
        frontera = c["zona"] == "ZTE" and (c.get("dep") in FRONTERA_DEP or (len(partes) > 1 and partes[1] in FRONTERA_PROV))
        sal_c = [x for x in salidas if doc in (x["mov"]["ruc"], x["rec"]["ruc"], x["ten"]["ruc"])]
        n_sin = c["n"] - c.get("n_igv", 0)
        pts, por = 0, []
        if any(x["estado"] not in ("Descartada",) for x in sal_c):
            pts, por = pts + 4, por + ["ya movió maquinaria a la ZTC"]
        elif sal_c:
            pts, por = pts + 1, por + ["movió maquinaria a la ZTC (salida descartada)"]
        if any("gre_cambio" in x["mot"] for x in cs):
            pts, por = pts + 3, por + ["guía a la ZTC dada de baja"]
        if c["zona"] == "ZTC" or any("dom_ztc" in x["mot"] for x in cs):
            pts, por = pts + 3, por + ["domicilio fuera de la ZTE"]
        if frontera:
            pts, por = pts + 2, por + ["zona de frontera con la ZTC"]
        if c["perfil"] in ("Alquiler de maquinaria", "Consorcio"):
            pts, por = pts + 2, por + [c["perfil"].lower()]
        elif c["perfil"] in ("Constructora o ingeniería", "Transporte"):
            pts, por = pts + 1, por + [c["perfil"].lower()]
        if n_sin >= 2:
            pts, por = pts + (2 if n_sin >= 4 else 1), por + [f"{n_sin} máquinas sin IGV"]
        if c.get("nuevo") or c.get("no_habido"):
            pts, por = pts + 1, por + ["RUC reciente o no habido"]
        if c["perfil"] in ("Entidad pública", "No domiciliado") or n_sin <= 0:
            pts = min(pts, 1) if not sal_c else pts
        c["cob"], c["cob_t"] = cobertura(doc, c["primera"]) if ruc_valido(doc) else (None, [])
        c.update({"riesgo": pts, "porque": por, "frontera": frontera, "n_sin": n_sin, "salidas": [x["id"] for x in sal_c], "gre_ok": ruc_valido(doc)})

    # ---------- Dónde buscar ahora: la cola de búsquedas, de más a menos rendidora ----------
    cola = []
    # 1. Guías de máquinas del importador (series TP): comprador, serie y lugar de entrega de cada máquina
    tp = {}
    for g in guias:
        if g["em"]["ruc"] == ruc_imp and re.fullmatch(r"TP\d{2}-\d+", g["num"]):
            tp.setdefault(g["num"].split("-")[0], set()).add(int(g["num"].split("-")[1]))
    faltan_tp = [(sr, n_) for sr, nums in sorted(tp.items()) for n_ in range(max(1, min(nums) - 60), max(nums) + 41) if n_ not in nums]
    if tp:
        cola.append({"id": "tp", "t": "Guías de máquinas del importador que faltan", "n": len(faltan_tp), "u": "guías por consultar",
                     "por": "Cada guía de las series " + ", ".join(sorted(tp)) + " trae la serie de la máquina, el comprador y el lugar de entrega. "
                            f"Hay {sum(len(v) for v in tp.values())} descargadas; con las que faltan se sabe quién tiene cada máquina.",
                     "busquedas": [{"etiqueta": f"Guía de máquinas {sr}-{n_}", "grupo": "importador", "directa": {"rucEmisor": ruc_imp, "codCpe": "09", "serie": sr, "numero": str(n_)}}
                                   for sr, n_ in faltan_tp]})
    # 2. Seguir las máquinas que ya salieron: guías posteriores de quien la tiene y de quien la recibió
    seg, vistos = [], set()
    for x in salidas:
        if x["estado"] in ("Descartada", "Regresó a la ZTE"):
            continue
        for quien in x["seguir"]:           # vacío si es un envío del propio importador: ahí la máquina está donde el comprador
            etq = quien["rol"]
            if quien["ruc"] not in vistos:
                vistos.add(quien["ruc"])
                seg.append({"etiqueta": f"{x['id']}: guías de {nom(quien)} ({etq}) desde la salida", "caso": x["id"], "grupo": "salida",
                            "rucEmisor": quien["ruc"], "desde": (date.fromisoformat(x["f"]) - timedelta(days=3)).isoformat(), "hasta": "hoy"})
    if seg:
        cola.append({"id": "seguir", "t": "Seguir las máquinas que ya salieron", "n": len(seg), "u": "RUC por consultar",
                     "por": "Para armar el caso hay que ubicar la máquina. Las guías posteriores de quien la tiene muestran si se movió otra vez o si regresó.",
                     "busquedas": seg})
    # 3. Tenedores con más riesgo y sin guías consultadas
    top = sorted((c for c in cli.values() if c["gre_ok"] and c["riesgo"] >= 4 and (c["cob"] or 0) < 0.8), key=lambda c: (-c["riesgo"], -c["n_sin"], c["primera"]))[:15]
    if top:
        cola.append({"id": "tenedores", "t": "Guías de los tenedores con más riesgo", "n": len(top), "u": "RUC por consultar",
                     "por": "Compradores que más probablemente muevan la máquina fuera de la zona (frontera, alquiler, constructoras, domicilio en la ZTC) y cuyas guías "
                            "como remitentes no se han consultado desde la compra. La lista completa está en «Tenedores».",
                     "busquedas": [{"etiqueta": f"Tenedor {c['ruc']} {c['nombre'][:30]}: guías como remitente desde la compra", "grupo": "tenedor", "rucEmisor": c["ruc"],
                                    "desde": (date.fromisoformat(c["primera"]) - timedelta(days=3)).isoformat(), "hasta": "hoy"} for c in top]})
    # 4. Transportistas que ya llevaron máquinas y no están consultados en los últimos dos años
    hace2 = (hoy - timedelta(days=730)).isoformat()
    tr_maq = Counter()
    nombres_t = {}
    for i, g in enumerate(guias):
        if g["tipo"] == "Transportista" and g["em"]["ruc"] != ruc_imp and (i in venta_guia or maquinas_en_bienes(bienes_de(i)) or any(c in g_txt2[i] for c in serie_maq)):
            tr_maq[g["em"]["ruc"]] += 1
            nombres_t[g["em"]["ruc"]] = g["em"]["nombre"]
    tr_pend = [(r, n_) for r, n_ in tr_maq.most_common() if ruc_valido(r) and cobertura(r, hace2)[0] < 0.8]
    transportistas_maq = [{"ruc": r, "nombre": nombres_t[r], "guias": n_, "cob": cobertura(r, hace2)[0]} for r, n_ in tr_maq.most_common(40)]
    if tr_pend:
        cola.append({"id": "transportistas", "t": "Transportistas que ya llevaron máquinas", "n": len(tr_pend[:15]), "u": "RUC por consultar",
                     "por": "Sus guías de transportista muestran máquinas de cualquier dueño. Así aparecieron las salidas que no hizo el importador.",
                     "busquedas": [{"etiqueta": f"Transportista {r} {nombres_t[r][:30]} ({n_} guías con máquinas)", "grupo": "transportista", "rucEmisor": r,
                                    "desde": hace2, "hasta": "hoy"} for r, n_ in tr_pend[:15]]})
    # 5. Lo que se completa en el sistema (Excel de consultas)
    n_ver = sum(1 for x in salidas if x["estado"] in ("Por completar", "Indicio: guía dada de baja"))
    if n_ver:
        cola.append({"id": "excel", "t": "Completar las salidas en el Excel de consultas", "n": n_ver, "u": "máquinas por verificar", "excel": True,
                     "por": "Hoja «Salidas por verificar»: la DAM de cada serie, si tiene el beneficio y si tiene solicitud de traslado. Con eso el expediente pasa a caso armado o se descarta."})
    # Otros importadores con maquinaria y beneficio (cuaderno): cobertura de sus guías como remitentes
    importadores = []
    for x in meta_ctl.get("importadores", []):
        anios_ok = sum(n_ for a_, n_ in x["anios"].items() if a_.isdigit() and int(a_) >= hoy.year - PLAZO)
        if anios_ok and x["amarilla"] + x["agricola"] > 0:
            importadores.append({**x, "en_plazo": anios_ok, "cob": cobertura(x["ruc"], hace2)[0] if ruc_valido(x["ruc"]) else None, "es": x["ruc"] == ruc_imp})

    # ---------- Salida ----------
    dams = {}
    for k in sorted(set(mq.dam)):
        d = dec[dec.dam == k].iloc[0]
        dams[k] = {"f": fstr(d.f), "ad": d.ad, "dest": d.dest, "canal": d.canal, "conv": d.conv, "series": int(d.series), "nmaq": int(d.nmaq),
                   "cif": r2(d.cif), "ctl": ctl_cache.get(k), "maqs": [x for x in mq[mq.dam == k].key if con_beneficio(x)]}
    vend_z = {z: int(sum(1 for d in vend.doc if zona_doc.get(d, "Sin dato") == z)) for z in ("ZTE", "ZTC", "Extranjero", "Sin dato")}
    mqb = mq[mq.key.map(con_beneficio)]     # solo las máquinas con beneficio se siguen
    # Guías: solo las enlazadas con una venta o con una máquina; el resto queda en «claves» (el extractor no las vuelve a descargar)
    usadas_g = sorted({x["i"] for c in casos for x in c["gre"]} | {i for k, idx in maq_gre.items() if k in maq_por_k for i in idx}
                      | {i for x in salidas for i in x["gs"]})
    nuevo_i = {i: n for n, i in enumerate(usadas_g)}
    for c in casos:
        for x in c["gre"]:
            x["i"] = nuevo_i[x["i"]]
    for x in maquinas:
        x["gre"] = [nuevo_i[i] for i in maq_gre.get(x["k"], [])]
    for x in salidas:
        x["gs"] = [nuevo_i[i] for i in x["gs"]]
    guias_out = []
    for i in usadas_g:
        g = {k: v for k, v in guias[i].items() if k not in ("_det", "sustenta", "casos")}
        g["casos"] = sorted(guias[i]["casos"])
        if guias[i].get("sustenta") in nuevo_i:
            g["sustenta"] = nuevo_i[guias[i]["sustenta"]]
        guias_out.append(g)
    datos = {
        "meta": {"contribuyente": m.NOM_RAZONSOCIAL.iloc[0], "ruc": ruc_imp, "desde": fstr(desde)[:7], "hasta": fstr(max(m.f.max(), e.f.max()))[:7],
                 "generado": date.today().isoformat(), "portal": a.portal or "", "dam_hasta": fstr(m.f.max()), "cpe_hasta": fstr(e.f.max()),
                 "aduanas": ADUANAS, "destinos": DESTINOS, "canales": CANALES, "motivos": MOTIVOS_NC, "texto": TEXTO,
                 "padron": str(dom.fecha_padron.iloc[0]) if dom is not None and "fecha_padron" in dom and len(dom) else "", "xml_err": xml_err},
        "kpi": {"maq_series": len(maquinas), "maq_uds": int(mqb.CNT_COMER.sum()), "maq_cif": r2(mqb.MTO_VALORADU.sum()), "maq_dams": int(mqb.dam.nunique()),
                "por_dest": [{"cod": k, "series": int((mqb.dest == k).sum()), "dams": int(mqb[mqb.dest == k].dam.nunique()),
                              "ctl": int(sum(1 for d in set(mqb[mqb.dest == k].dam) if ctl_cache.get(d)))} for k in mqb.dest.value_counts().index],
                "vend": int(len(vend)), "vend_z": vend_z, "vend_igv": int((vend.igv > 0).sum()), "anuladas": len(anulada_por), "bajas": len(bj),
                "casos": {n: sum(c["nivel"] == n for c in casos) for n in ("Alta", "Media", "Baja")},
                "alta_sin_xml": sum(1 for c in casos if c["nivel"] == "Alta" and not c["xml"]),
                "tras_salida": n_ts, "tras_maq": sum(len(t["maqs"]) or int(t["cant"] or 0) for t in tras_salida),
                "ben_dams": sum(1 for k, c in ctl_cache.items() if c and c["benef"] and k in dams_mq),
                "fuera_dams": len(set(fuera_ctl) | set(fuera_conv)), "fuera_series": int((~mq.key.map(con_beneficio)).sum()),
                "sinreg_dams": len(sin_reg_d), "tras_sin_serie": len(tras_sin_serie), "tc": r2(tc),
                "salidas": dict(Counter(x["estado"] for x in salidas)),
                "parque": {"total": len(maquinas), "con_ten": sum(1 for x in maquinas if x["ten"]), "con_rastro": sum(1 for x in maquinas if x["ult"]),
                           "sin_rastro": sum(1 for x in maquinas if not x["ten"] and not x["ult"])},
                "cobertura": {"tenedores": sum(1 for c in cli.values() if c["gre_ok"]), "consultados": sum(1 for c in cli.values() if c["gre_ok"] and (c["cob"] or 0) >= 0.8),
                              "parcial": sum(1 for c in cli.values() if c["gre_ok"] and 0 < (c["cob"] or 0) < 0.8)},
                "tras_ia": meta_ctl.get("traslados_maq", {}), "plazo": PLAZO},
        "maquinas": maquinas, "dams": dams, "traslados": tr, "casos": casos, "ventas": ventas, "cadenas": cadenas,
        "clientes": cli, "facturas": facturas, "patrones": pat, "calidad": calidad, "pendientes": pendientes,
        "exportaciones": [x for x in exportaciones if x["maq"] or x["venta"]], "control": {"art2": meta_ctl.get("art2", []), "complejidad": meta_ctl.get("complejidad"), "tras_sin_serie": tras_sin_serie,
                                                                               "sin_registro": sin_reg_d},
        "transportistas": leer_transportistas(a.transportistas),
        "salidas": salidas, "cola": cola, "importadores": importadores, "transportistas_maq": transportistas_maq,
        "guias": guias_out,
        # «claves»: guías que el extractor no vuelve a descargar. Solo las que tienen detalle: las no procesadas o con
        # error se vuelven a pedir en la siguiente lista del día o del caso.
        "gre": {"claves": [g["clave"] for g in guias if g["_det"]], "archivos": gre_meta["archivos"], "busquedas": gre_meta["busquedas"]} if guias else {},
    }
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    n = datos["kpi"]["casos"]
    print(f"OK {a.salida}: {len(casos)} casos (alta {n['Alta']}, media {n['Media']}, baja {n['Baja']}); {len(maquinas)} máquinas; "
          f"{len(cli)} compradores; {len(facturas)} XML; {len(pendientes)} comprobantes por descargar; "
          f"{len(datos['transportistas'])} transportistas vigilados; {len(guias)} guías ({len(guias_out)} enlazadas); "
          f"salidas: {dict(Counter(x['estado'] for x in salidas))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for x in ("dams", "cpe", "detalle", "salida"):
        ap.add_argument(x)
    ap.add_argument("--domicilios")
    ap.add_argument("--ubigeos", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "referencias", "ubigeo_zte.csv"))
    ap.add_argument("--portal", help="URL del portal público de comprobantes del emisor (va cifrada dentro de los datos)")
    ap.add_argument("--consulta-ruc", nargs="*", default=[], help="Resultados de la consulta múltiple de RUC de SUNAT (ZIP o TXT)")
    ap.add_argument("--trazabilidad", help="CSV de casos: cpe, serie_maquina, serie_motor, modelo, ubicacion_entrega (DISTRITO, PROVINCIA, DEPARTAMENTO), direccion_entrega, fuente, nota")
    ap.add_argument("--facturas-xml", nargs="*", default=[], help="XML de comprobantes del emisor (archivos, carpetas o ZIP)")
    ap.add_argument("--consultas", help="Libro de consultas a otras intendencias completado por el equipo (ver consultas_xlsx.py)")
    ap.add_argument("--control-ia", help="Cuaderno de control de la intendencia (xlsx/xlsm): control en destino, NCN, RI y traslados")
    ap.add_argument("--guias", nargs="*", default=[], help="JSON que descarga el extractor de GRE (uno o más; las guías repetidas se leen una sola vez)")
    ap.add_argument("--transportistas", help="Transportistas vigilados (TXT: un RUC por línea, opcionalmente con el nombre); entran en la «Lista del día» de guías")
    main(ap.parse_args())
