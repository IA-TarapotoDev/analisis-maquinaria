#!/usr/bin/env python3
"""Arma la extensión de Edge «Gestión de Riesgo · SUNAT».

Copia el extractor (extractor-gre.js) dentro de la carpeta extension/ (la extensión lo trae consigo: Edge no deja cargar código de
internet) y crea el ZIP que se descarga desde la página. Uso:

    python3 armar_extension.py [--zip ruta/gestion-riesgo-sunat.zip]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(AQUI, 'extension')
ARCHIVOS = ['manifest.json', 'arranque.js', 'extractor-gre.js', 'puente_sunat_main.js', 'puente_sunat.js', 'puente_pagina.js', 'fondo.js',
            'icono16.png', 'icono48.png', 'icono128.png']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', default=os.path.join(AQUI, 'gestion-riesgo-sunat.zip'))
    a = ap.parse_args()
    shutil.copyfile(os.path.join(AQUI, 'extractor-gre.js'), os.path.join(CARPETA, 'extractor-gre.js'))
    with open(os.path.join(CARPETA, 'manifest.json'), encoding='utf-8') as f:
        manifiesto = json.load(f)
    # Todo lo que nombra el manifiesto existe, y nada más se empaqueta
    nombrados = {manifiesto['background']['service_worker'], *manifiesto['icons'].values()}
    for cs in manifiesto['content_scripts']:
        nombrados.update(cs['js'])
    faltan = sorted(n for n in nombrados if not os.path.exists(os.path.join(CARPETA, n)))
    if faltan:
        raise SystemExit(f'Faltan archivos de la extensión: {", ".join(faltan)}')
    if not nombrados <= set(ARCHIVOS):
        raise SystemExit(f'El manifiesto nombra archivos que no se empaquetan: {sorted(nombrados - set(ARCHIVOS))}')
    if shutil.which('node'):
        for n in ARCHIVOS:
            if n.endswith('.js'):
                r = subprocess.run(['node', '--check', os.path.join(CARPETA, n)], capture_output=True, text=True)
                if r.returncode:
                    raise SystemExit(f'{n} tiene un error de sintaxis:\n{r.stderr[-800:]}')
    with open(os.path.join(AQUI, 'extractor-gre.js'), encoding='utf-8') as f:
        version_extractor = re.search(r"const VERSION = '([^']+)'", f.read()).group(1)
    os.makedirs(os.path.dirname(os.path.abspath(a.zip)), exist_ok=True)
    with zipfile.ZipFile(a.zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in ARCHIVOS:
            z.write(os.path.join(CARPETA, n), f'gestion-riesgo-sunat/{n}')
    print(f'OK extensión {manifiesto["version"]} con el extractor {version_extractor}: {a.zip} ({os.path.getsize(a.zip):,} bytes)')


if __name__ == '__main__':
    main()
