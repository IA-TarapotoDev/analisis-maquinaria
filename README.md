# Análisis de maquinaria

Herramientas del Equipo de Gestión de Riesgo de la Intendencia de Aduana de Tarapoto para seguir la maquinaria importada con destino a la Amazonía y su venta.

| Carpeta | Qué es |
|---|---|
| [`riesgo/`](riesgo/README.md) | Tablero de riesgo anterior (retirado el 19/11/2026): cruzaba las DAM, los comprobantes emitidos, los XML de las facturas, el domicilio de los compradores, el cuaderno de control de la intendencia y las guías de remisión. Sus reglas pasaron al módulo Maquinaria del sitio nuevo; queda como referencia |
| [`sunat-gre/`](sunat-gre/README.md) | Extractor de guías de remisión electrónicas (GRE): corre en la consola del navegador, dentro de la sesión de SUNAT de quien lo usa, y descarga las guías que pide la lista del día de cada módulo |

**Página publicada:** https://ia-tarapotodev.github.io/analisis-maquinaria/ — ahora es el sitio **Gestión de Riesgo · IA Tarapoto** (módulos Envíos y Maquinaria), sin clave de página: se entra con el usuario de Supabase y la frase de cifrado, y los datos viven cifrados en la base. Su código está en el repositorio privado `contrabando`. Cuando exista el repositorio `ia-tarapotodev.github.io`, el sitio pasará a https://ia-tarapotodev.github.io/. El tablero cifrado con clave, `/envios/` y `/envios/nuevo/` se retiraron (las dos últimas llevan al sitio nuevo).

## Protección de los datos

Los datos de origen tienen reserva tributaria (art. 85 del Código Tributario) y **no se versionan en este repositorio**: ni las DAM, ni los comprobantes, ni los XML, ni las guías, ni los JSON o Excel que se generan. La página publicada no lleva datos: lo que se carga se cifra en la computadora (AES-256-GCM, llave derivada de la frase de cifrado con PBKDF2-SHA256) y se guarda así en la base. La frase no sale de la computadora; no la publique en el repositorio ni en issues.

## Origen

El tablero y el extractor se desarrollaron en el repositorio `IA-TarapotoDev/TARAPOTO-Dev` (carpetas `riesgo/` y `sunat-gre/`), donde queda su historial de cambios. Aquí empiezan con la versión del 11/11/2026.
