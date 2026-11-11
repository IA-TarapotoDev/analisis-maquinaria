# Análisis de maquinaria

Herramientas del Equipo de Gestión de Riesgo de la Intendencia de Aduana de Tarapoto para seguir la maquinaria importada con destino a la Amazonía y su venta.

| Carpeta | Qué es |
|---|---|
| [`riesgo/`](riesgo/README.md) | Tablero de riesgo: cruza las DAM, los comprobantes emitidos, los XML de las facturas, el domicilio de los compradores, el cuaderno de control de la intendencia y las guías de remisión. Arma los casos por máquina y la página cifrada |
| [`sunat-gre/`](sunat-gre/README.md) | Extractor de guías de remisión electrónicas (GRE): corre en la consola del navegador, dentro de la sesión de SUNAT de quien lo usa, y descarga las guías que pide el tablero |

**Página publicada:** https://ia-tarapotodev.github.io/analisis-maquinaria/ (requiere clave de acceso).

## Protección de los datos

Los datos de origen tienen reserva tributaria (art. 85 del Código Tributario) y **no se versionan en este repositorio**: ni las DAM, ni los comprobantes, ni los XML, ni las guías, ni los JSON o Excel que se generan. La página publicada lleva los datos cifrados (AES-256-GCM, llave derivada de la clave de acceso con PBKDF2-SHA256). La clave se entrega al equipo por un canal interno; no la publique en el repositorio ni en issues.

## Origen

El tablero y el extractor se desarrollaron en el repositorio `IA-TarapotoDev/TARAPOTO-Dev` (carpetas `riesgo/` y `sunat-gre/`), donde queda su historial de cambios. Aquí empiezan con la versión del 11/11/2026.
