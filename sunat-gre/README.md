# Extractor de GRE (guías de remisión electrónicas)

Script para la consola de Microsoft Edge que descarga, dentro de su propia sesión de SUNAT, las guías de remisión (remitente, transportista y por eventos) y su detalle: bienes, peso, fechas, punto de partida (agencia), llegada, transportista, vehículo y conductor. Funciona junto con el [tablero de riesgo](../riesgo/README.md): el tablero arma la lista de búsquedas y el extractor la ejecuta.

- Archivo: [`extractor-gre.js`](extractor-gre.js) (versión 3.0.0).
- Usa solo la consulta autorizada de la pantalla de guías de SUNAT, con la sesión de quien lo ejecuta. No evade controles ni guarda la conexión.

## Dónde se ejecuta

1. Ingrese a SUNAT Operaciones en Línea y abra la pantalla de **consulta de guías de remisión**.
2. Pulse **F12** y vaya a la pestaña **Console**.
3. Arriba a la izquierda de la consola hay un selector que dice **«top»**. Cámbielo a **«iframeApplication (…)» – intranet.sunat.peru**. Si lo deja en «top», el extractor no se instala y muestra un aviso con estos pasos.
4. Pegue el script y pulse Enter. Aparece el panel «Extractor de GRE» a la derecha.

Para no pegarlo cada día, guárdelo una sola vez como *Snippet*: **Sources > Snippets > New snippet**, pegue el contenido y guarde. Luego, con el contexto en «iframeApplication», clic derecho en el snippet > **Run** (o Ctrl+Enter).

## Rutina diaria (unos minutos por la mañana)

1. En el tablero, pestaña **Alertas**, pulse **«Lista del día»**: se copia la lista (ayer y hoy de los compradores reincidentes, del importador y de los transportistas vigilados).
2. En SUNAT, ejecute el extractor (snippet) y pegue la lista en el cuadro de **«Lista del tablero»** del panel (Ctrl+V). El panel resume qué va a buscar.
3. Pulse **«▶ Buscar y descargar»**.
4. Si el panel pide conexión, abra **cualquier guía con «Ver»** en la pantalla de SUNAT (o pulse «Buscar»). La conexión se toma sola y la búsqueda continúa. Lo mismo ocurre si la conexión vence a mitad del proceso (dura aproximadamente una hora).
5. Al terminar se descargan dos archivos:
   - **JSON** (`GRE_<lista>_<fechas>_<hora>.json`): para integrarlo al tablero.
   - **Excel** (`GRE_<lista>_<fechas>_<hora>.xlsx`): para revisar (hojas Resumen, Guías, Bienes, Búsquedas, Errores y Control, y una hoja por cada lista de vehículos, conductores, documentos relacionados, etc.).

Para no volver a descargar lo que ya trajo el día anterior, antes de pulsar «Buscar y descargar» cargue el JSON anterior en **Más opciones > Cargar resultado anterior**. Cuando el tablero integre los resultados, la lista del día llevará las guías ya conocidas y esto no hará falta.

## Casos

En la ficha de cada caso del tablero, **«Buscar guías»** copia la lista de ese caso: las guías del comprador como destinatario y como remitente, desde 3 días antes hasta 15 días después de la venta, y las guías citadas en la factura (se consultan directo por su número). **«Guías de los casos altos»** hace lo mismo con todos los casos de nivel alto a la vez. Se pegan en el extractor igual que la lista del día.

Una guía en la que el comprador aparece como **remitente** después de la compra puede indicar que volvió a trasladar la máquina.

## Búsqueda manual

En el panel, **«Búsqueda manual»**: escriba uno o varios RUC, elija si el RUC es emisor, receptor o ambos, los tipos de guía y uno o más periodos. Si antes pulsa «Conectar» y hace una búsqueda en la pantalla de SUNAT, sus datos se copian solos al panel.

## Límite de 100 guías por consulta

SUNAT entrega como máximo 100 guías por consulta (código 2021). El extractor:

1. Divide el periodo en tramos de días según la cantidad de guías que va encontrando.
2. Si un solo día pasa de 100, lo consulta por bloques de 4 horas.
3. Si un bloque de 4 horas pasa de 100, lo consulta por tipo de guía.
4. Si aun así un tramo pasa de 100, lo anota en la hoja **Búsquedas** (resultado «Tramo de 4 horas con más de 100 guías») y en **Control** (`TRAMO_SUPERA_100`).

## Archivos que entrega

| Archivo | Para qué | Contenido |
|---|---|---|
| JSON | Tablero | Una entrada por guía: `clave`, `estado` (`con_detalle`, `ya_en_tablero`, `sin_detalle`, `no_procesada`), `citadaEnFactura`, fila del listado (estado actual en SUNAT), `detalle` completo y las búsquedas (y casos) que la encontraron. También las consultas hechas, los errores y el control de calidad. Nunca incluye la conexión. |
| Excel | Revisión | Resumen (con una fila por búsqueda), Guías (una fila por guía, con todos los campos del detalle), Bienes (una fila por bien), listas anidadas en hojas aparte, Búsquedas, Errores y Control. Los textos conservan los ceros a la izquierda. |
| CSV | Opcional | Los mismos datos en CSV (UTF-8 con BOM, separador «;»): **Más opciones > ⬇ CSV**. |

Las guías anuladas o con baja también se descargan, con su estado.

## Problemas frecuentes

| Qué pasa | Qué hacer |
|---|---|
| Aviso «contexto equivocado» | Cambie el selector de la consola de «top» a «iframeApplication (…)» y vuelva a ejecutar. |
| Pulso «Ver» y no pasa nada | La consola está en «top». Cámbiela a «iframeApplication» y vuelva a ejecutar el extractor. |
| «Failed to fetch» o «SUNAT no respondió» | El extractor repite una consulta de la propia pantalla para encontrar la causa y la muestra en el registro. Pulse **🔍 Diagnóstico**, luego «Buscar» o «Ver» en SUNAT, y revise qué consultas se ven. |
| HTTP 401 | La conexión venció: abra una guía con «Ver» y el proceso continúa solo. |
| HTTP 403 | La cuenta no tiene permiso para esa consulta: el proceso se detiene. |
| El navegador bloquea las descargas | Permita las descargas múltiples para el sitio, o use **⬇ Excel** / **⬇ JSON** del panel. |
| Se detuvo a mitad | Pulse otra vez «Buscar y descargar»: solo consulta lo que falta. |

## Seguridad

- La conexión (token) se toma de la propia pantalla de SUNAT, vive solo en memoria y se descarta al terminar. No se muestra, no se guarda en el navegador ni se exporta.
- Las consultas usan `credentials: "omit"` y `mode: "cors"`; no se modifica ni se evade CORS.
- La escucha de la pantalla de SUNAT es temporal y deja la página como estaba.
- El registro no muestra datos personales ni la conexión.
- Los JSON y Excel tienen información con reserva tributaria (art. 85 del Código Tributario): guárdelos en una carpeta privada y **no los suba sin cifrar** al repositorio.
