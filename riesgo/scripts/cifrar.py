"""Cifra el JSON del tablero dentro de la plantilla HTML.

Uso:
  CLAVE_TABLERO_ARCHIVO=/ruta/clave.txt python3 -I cifrar.py datos.json ../plantilla.html index.html [--adjunto archivo ...]

Cada --adjunto (por ejemplo, el Excel de consultas) viaja cifrado dentro de los datos y se descarga desde la
página una vez abierta con la clave.

La clave se lee del archivo indicado en CLAVE_TABLERO_ARCHIVO (o se pide por
teclado). El JSON se comprime con gzip y se cifra con AES-256-GCM; la llave se
deriva de la clave con PBKDF2-SHA256 (600 000 iteraciones y sal aleatoria). El
navegador lo descifra con la Web Crypto API, sin enviar la clave a ningún
servidor.
"""
import base64
import getpass
import gzip
import json
import os
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERACIONES = 600_000


def main(r_json, r_plantilla, salida, adjuntos=()):
    ruta_clave = os.environ.get("CLAVE_TABLERO_ARCHIVO")
    clave = open(ruta_clave, encoding="utf-8").read().strip() if ruta_clave else getpass.getpass("Clave: ")
    if len(clave) < 16:
        sys.exit("La clave debe tener al menos 16 caracteres.")
    datos = open(r_json, "rb").read()
    obj = json.loads(datos)  # valida
    if adjuntos:
        obj["adjuntos"] = {}
        for r in adjuntos:
            with open(r, "rb") as f:
                obj["adjuntos"][os.path.basename(r)] = base64.b64encode(f.read()).decode("ascii")
        datos = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sal, iv = os.urandom(16), os.urandom(12)
    llave = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACIONES).derive(clave.encode("utf-8"))
    cifrado = AESGCM(llave).encrypt(iv, gzip.compress(datos, 9), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    carga = json.dumps({"v": 1, "it": ITERACIONES, "s": b64(sal), "i": b64(iv), "c": b64(cifrado)})
    html = open(r_plantilla, encoding="utf-8").read()
    if html.count("__CIFRADO__") != 1:
        sys.exit("La plantilla debe contener una sola marca __CIFRADO__.")
    with open(salida, "w", encoding="utf-8") as f:
        f.write(html.replace("__CIFRADO__", carga))
    print(f"OK {salida}: {len(datos):,} bytes de datos → {len(cifrado):,} bytes cifrados")


if __name__ == "__main__":
    args, adjuntos = sys.argv[1:], []
    while "--adjunto" in args:
        i = args.index("--adjunto")
        if i + 1 >= len(args):
            sys.exit(__doc__)
        adjuntos.append(args[i + 1])
        del args[i:i + 2]
    if len(args) != 3:
        sys.exit(__doc__)
    main(*args, adjuntos=adjuntos)
