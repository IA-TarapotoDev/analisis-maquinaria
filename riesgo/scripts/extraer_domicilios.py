"""Extrae el domicilio fiscal de los clientes desde el padrón reducido del RUC de SUNAT.

Uso:
  python3 -I extraer_domicilios.py PADRON CPE_EMITIDOS.txt domicilios.csv

PADRON puede ser:
  - padron_reducido_ruc.zip tal como se descarga de https://www2.sunat.gob.pe/padron_reducido_ruc.zip
  - el TXT descomprimido (separado por "|", Latin-1)
  - un CSV propio con, al menos, las columnas RUC y UBIGEO (y opcionalmente ESTADO, CONDICION y DIRECCION)

Solo se conservan los RUC que aparecen como receptores en los CPE emitidos. La salida
contiene: ruc, estado, condicion, ubigeo, direccion, fecha_padron.
"""
import csv
import io
import os
import sys
import zipfile
from datetime import date, datetime

import pandas as pd

# Posiciones del padrón reducido (cabecera: RUC|NOMBRE O RAZÓN SOCIAL|ESTADO DEL CONTRIBUYENTE|
# CONDICIÓN DE DOMICILIO|UBIGEO|TIPO DE VÍA|NOMBRE DE VÍA|CÓDIGO DE ZONA|TIPO DE ZONA|NÚMERO|INTERIOR|
# LOTE|DEPARTAMENTO|MANZANA|KILÓMETRO|)
P_RUC, P_ESTADO, P_COND, P_UBIGEO = 0, 2, 3, 4
P_TVIA, P_NVIA, P_CZONA, P_TZONA, P_NUM, P_INT, P_LOTE, P_DPTO, P_MZ, P_KM = range(5, 15)


def limpio(v):
    v = (v or "").strip()
    return "" if v in ("-", "--", "----") else v


def direccion(f):
    partes = [f"{limpio(f[P_TVIA])} {limpio(f[P_NVIA])}".strip()]
    for etiqueta, i in (("NRO.", P_NUM), ("INT.", P_INT), ("DPTO.", P_DPTO), ("MZA.", P_MZ), ("LOTE", P_LOTE), ("KM.", P_KM)):
        if limpio(f[i]):
            partes.append(f"{etiqueta} {limpio(f[i])}")
    zona = f"{limpio(f[P_CZONA])} {limpio(f[P_TZONA])}".strip()
    if zona:
        partes.append(zona)
    return " ".join(p for p in partes if p)


def rucs_clientes(r_cpe):
    e = pd.read_csv(r_cpe, sep="|", encoding="latin-1", dtype=str, index_col=False).iloc[:, :14]
    e.columns = ["ruc", "tipo", "serie", "nro", "tipo_ref", "tdoc", "doc", "nombre", "moneda", "vv", "igv", "total", "fecha", "estado"]
    return set(e[(e.tdoc == "6") & e.doc.str.fullmatch(r"\d{11}")].doc)


def lineas_padron(ruta):
    """Devuelve (fecha del padrón, iterador de líneas de texto)."""
    if zipfile.is_zipfile(ruta):
        z = zipfile.ZipFile(ruta)
        miembro = max((m for m in z.infolist() if m.filename.lower().endswith(".txt")), key=lambda m: m.file_size)
        fecha = date(*miembro.date_time[:3])
        return fecha, io.TextIOWrapper(z.open(miembro), encoding="latin-1", newline="")
    fecha = datetime.fromtimestamp(os.path.getmtime(ruta)).date()
    return fecha, open(ruta, encoding="latin-1", newline="")


def main(r_padron, r_cpe, salida):
    rucs = rucs_clientes(r_cpe)
    fecha, lineas = lineas_padron(r_padron)
    cabecera = next(lineas)
    filas = []
    if "|" in cabecera and "UBIGEO" in cabecera.upper() and cabecera.upper().startswith("RUC|"):
        for ln in lineas:
            ruc = ln[:11]
            if ruc not in rucs:
                continue
            f = ln.rstrip("\r\n").split("|")
            f += [""] * (15 - len(f))
            filas.append({"ruc": ruc, "estado": limpio(f[P_ESTADO]), "condicion": limpio(f[P_COND]),
                          "ubigeo": limpio(f[P_UBIGEO]).zfill(6) if limpio(f[P_UBIGEO]) else "",
                          "direccion": direccion(f), "fecha_padron": fecha.isoformat()})
    else:  # CSV propio
        sep = max([",", ";", "|", "\t"], key=cabecera.count)
        lector = csv.DictReader(lineas, fieldnames=[c.strip().upper() for c in cabecera.rstrip("\r\n").split(sep)], delimiter=sep)
        for r in lector:
            ruc = (r.get("RUC") or "").strip()
            if ruc in rucs:
                filas.append({"ruc": ruc, "estado": (r.get("ESTADO") or "").strip(), "condicion": (r.get("CONDICION") or "").strip(),
                              "ubigeo": (r.get("UBIGEO") or "").strip().zfill(6), "direccion": (r.get("DIRECCION") or "").strip(),
                              "fecha_padron": fecha.isoformat()})
    pd.DataFrame(filas, columns=["ruc", "estado", "condicion", "ubigeo", "direccion", "fecha_padron"]).drop_duplicates("ruc").to_csv(salida, index=False)
    print(f"OK {salida}: {len(filas)} de {len(rucs)} RUC de clientes encontrados en el padrón del {fecha.isoformat()}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
