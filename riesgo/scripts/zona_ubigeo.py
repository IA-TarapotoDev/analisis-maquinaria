"""Clasifica cada distrito (ubigeo INEI) en ZTE o ZTC según el art. 3 de la Ley 27037 y le asigna su circunscripción aduanera.

Usa las mismas reglas que los mapas (mapas/scripts/05_tematicos.py del repositorio TARAPOTO-Dev): ámbito según el
anexo de SUNAT «Jurisdicción en la Ley de Promoción de la Amazonía – Ley N.° 27037,
art. 3» (procedimiento RECA-PE.05.01), con Cutervo como ZTC.

Uso:
  python3 -I zona_ubigeo.py ubigeo_distrito.csv ../referencias/ubigeo_zte.csv

ubigeo_distrito.csv: tabla de ubigeos INEI de jmcastagnetto/ubigeo-peru-aumentado (licencia MIT).
"""
import sys
import unicodedata

import pandas as pd


def clave(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").split())


ZTE_DEP = {"LORETO", "MADRE DE DIOS", "UCAYALI", "AMAZONAS", "SAN MARTIN"}
ZTE_PROV = {("HUANUCO", "LEONCIO PRADO"), ("HUANUCO", "PUERTO INCA"), ("HUANUCO", "MARAÑON"), ("HUANUCO", "PACHITEA"),
            ("CAJAMARCA", "JAEN"), ("CAJAMARCA", "SAN IGNACIO"),
            ("PASCO", "OXAPAMPA"), ("JUNIN", "CHANCHAMAYO"), ("JUNIN", "SATIPO"), ("CUSCO", "LA CONVENCION")}
ZTE_DIS = {("HUAMALIES", "MONZON"), ("HUANCABAMBA", "EL CARMEN DE LA FRONTERA"), ("PATAZ", "ONGON"),
           ("HUANUCO", "HUANUCO"), ("HUANUCO", "AMARILIS"), ("HUANUCO", "PILLCO MARCA"), ("HUANUCO", "CHINCHAO"),
           ("HUANUCO", "CHURUBAMBA"), ("HUANUCO", "SANTA MARIA DEL VALLE"),
           ("AMBO", "AMBO"), ("AMBO", "CONCHAMARCA"), ("AMBO", "TOMAY KICHWA"),
           ("HUANTA", "SIVIA"), ("HUANTA", "AYAHUANCO"), ("LA MAR", "AYNA"), ("LA MAR", "SAN MIGUEL"), ("LA MAR", "SANTA ROSA"),
           ("TAYACAJA", "HUACHOCOLPA"), ("TAYACAJA", "TINTAY PUNCU"),
           ("CALCA", "YANATILE"), ("PAUCARTAMBO", "KOSÑIPATA"), ("QUISPICANCHI", "CAMANTI"), ("QUISPICANCHI", "MARCAPATA"),
           ("CARABAYA", "COASA"), ("CARABAYA", "AYAPATA"), ("CARABAYA", "ITUATA"), ("CARABAYA", "OLLACHEA"), ("CARABAYA", "SAN GABAN"),
           ("SANDIA", "SAN JUAN DEL ORO"), ("SANDIA", "LIMBANI"), ("SANDIA", "YANAHUAYA"), ("SANDIA", "PHARA"),
           ("SANDIA", "ALTO INAMBARI"), ("SANDIA", "SANDIA"), ("SANDIA", "PATAMBUCO")}
ZTE_DEP_K = {clave(x) for x in ZTE_DEP}
ZTE_PROV_K = {(clave(a), clave(b)) for a, b in ZTE_PROV}
ZTE_DIS_K = {(clave(a), clave(b)) for a, b in ZTE_DIS}


def circunscripcion(dep, prov, dis):
    """Circunscripción aduanera de cada distrito: mismas reglas que mapas/scripts/05_tematicos.py (R.S. 000980 y modif.)."""
    if dep == "TUMBES" or (prov == "TALARA" and dis in ("MANCORA", "LOS ORGANOS")): return "IA TUMBES"
    if dep == "PIURA": return "IA PAITA"
    if dep == "CAJAMARCA":
        return "IA PAITA" if prov in ("SANTA CRUZ", "CHOTA", "CUTERVO", "SAN IGNACIO", "JAEN", "HUALGAYOC") else "IA SALAVERRY"
    if dep == "LAMBAYEQUE": return "IA CHICLAYO"
    if dep == "LA LIBERTAD": return "IA SALAVERRY"
    if dep == "ANCASH": return "IA CHIMBOTE"
    if (dep == "PASCO" and prov in ("PASCO", "DANIEL ALCIDES CARRION")) or \
       (dep == "LIMA" and prov in ("CAJATAMBO", "HUARAL", "OYON", "BARRANCA", "HUAURA")) or \
       (dep == "LIMA" and prov == "LIMA" and dis == "ANCON"): return "IA CHANCAY"
    if dep in ("LIMA", "CALLAO", "JUNIN", "PASCO"): return "IA MARITIMA DEL CALLAO"
    if dep in ("ICA", "AYACUCHO", "HUANCAVELICA"): return "IA PISCO"
    if dep == "AREQUIPA": return "IA MOLLENDO"
    if dep == "MOQUEGUA": return "IA ILO"
    if dep == "TACNA": return "IA TACNA"
    if dep == "PUNO": return "IA PUNO"
    if dep in ("CUSCO", "APURIMAC"): return "IA CUSCO"
    if dep == "MADRE DE DIOS": return "IA PUERTO MALDONADO"
    if dep in ("UCAYALI", "HUANUCO"): return "IA PUCALLPA"
    if dep in ("SAN MARTIN", "AMAZONAS"): return "IA TARAPOTO"
    if dep == "LORETO": return "IA TARAPOTO" if prov in ("ALTO AMAZONAS", "DATEM DEL MARANON") else "IA IQUITOS"
    return ""


def main(entrada, salida):
    u = pd.read_csv(entrada, dtype=str)
    u = u[u.inei.fillna("").str.fullmatch(r"\d{6}")]  # descarta distritos sin código INEI
    u["dep_k"], u["prov_k"], u["dis_k"] = u.departamento.map(clave), u.provincia.map(clave), u.distrito.map(clave)
    pares_prov = set(zip(u.dep_k, u.prov_k))
    pares_dis = set(zip(u.prov_k, u.dis_k))
    faltan = [p for p in ZTE_PROV_K if p not in pares_prov] + [p for p in ZTE_DIS_K if p not in pares_dis]
    if faltan:
        sys.exit(f"Reglas sin coincidencia en la tabla de ubigeos: {faltan}")
    u["zona"] = ["ZTE" if d in ZTE_DEP_K or (d, p) in ZTE_PROV_K or (p, s) in ZTE_DIS_K else "ZTC"
                 for d, p, s in zip(u.dep_k, u.prov_k, u.dis_k)]
    u["circunscripcion"] = [circunscripcion(d, p, s) for d, p, s in zip(u.dep_k, u.prov_k, u.dis_k)]
    assert (u.circunscripcion != "").all(), u[u.circunscripcion == ""]
    out = u[["inei", "departamento", "provincia", "distrito", "zona", "circunscripcion"]].rename(columns={"inei": "ubigeo"}).sort_values("ubigeo")
    out.to_csv(salida, index=False)
    print(out.groupby("zona").size().to_dict())
    print(out[out.zona == "ZTE"].groupby("departamento").size().to_dict())
    print(out.groupby("circunscripcion").size().to_dict())


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
