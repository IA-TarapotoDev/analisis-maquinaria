# Extractor de GRE (guías de remisión electrónicas)

Script para la consola de Microsoft Edge que descarga, dentro de su propia sesión de SUNAT, las guías de remisión (remitente, transportista y por eventos) y su detalle: bienes, peso, fechas, punto de partida (agencia), llegada, transportista, vehículo y conductor. Funciona junto con el [tablero de riesgo](../riesgo/README.md): el tablero arma la lista de búsquedas y el extractor la ejecuta.

- Archivo: [`extractor-gre.js`](extractor-gre.js) (versión 3.4.0).
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

**Si la descarga se corta** (tope de tiempo o sesión de SUNAT vencida): cargue el JSON en la página que armó la lista, vuelva a copiar la lista del día y péguela en el extractor (después de volver a entrar a SUNAT). La lista nueva lleva todo lo ya descargado («ya en el tablero» y anclas): solo se pide lo que falta. «Más opciones > Cargar resultado anterior» solo sirve para listas que no llevan las guías conocidas.

**Ventana fija** (desde la versión 3.4.0): la lista del día de la página de envíos busca **de ayer 08:00 a hoy 08:00, nada más**. Como la ventana no cambia durante el día, volver a correr la lista no trae guías nuevas: solo completa lo que faltó, y termina.

## Casos

En la ficha de cada caso del tablero, **«Buscar guías»** copia la lista de ese caso: las guías del comprador como destinatario y como remitente, desde 3 días antes hasta 15 días después de la venta, y las guías citadas en la factura (se consultan directo por su número). **«Guías de los casos altos»** hace lo mismo con todos los casos de nivel alto a la vez. Se pegan en el extractor igual que la lista del día.

Una guía en la que el comprador aparece como **remitente** después de la compra puede indicar que volvió a trasladar la máquina.

## Consultas por número

Algunas listas del tablero piden guías directo por su número: las citadas en una factura, las que cita un transportista y las guías de máquinas del importador que faltan (series TP). Si SUNAT responde que la guía no existe (con cualquier código: 404, 400, 422, 500 o un mensaje de error), el extractor lo anota como **«no existe»** y sigue: no lo reintenta ni lo cuenta como error, así que no detiene la descarga. La detención tras 8 errores seguidos queda solo para las fallas reales de conexión o de SUNAT.

El tablero marca los números posteriores a la última guía conocida de cada serie, que pueden no existir todavía. Cuando **10 seguidos** de esos números no existen, el extractor da la serie por terminada y no consulta los siguientes («no consultada: fin de la serie»). Los huecos entre guías conocidas se consultan siempre. En el JSON, esas guías salen con `estado` `no_existe` o `no_consultada`; el tablero no vuelve a pedir un hueco que SUNAT confirmó que no existe.

## Búsqueda manual

En el panel, **«Búsqueda manual»**: escriba uno o varios RUC, elija si el RUC es emisor, receptor o ambos, los tipos de guía y uno o más periodos. Si antes pulsa «Conectar» y hace una búsqueda en la pantalla de SUNAT, sus datos se copian solos al panel.

## Límite de 100 guías por consulta

SUNAT entrega como máximo 100 guías por consulta (código 2021). El extractor:

1. Divide el periodo en tramos de días según la cantidad de guías que va encontrando.
2. Si un solo día pasa de 100, lo consulta por bloques de 4 horas.
3. Si un bloque de 4 horas pasa de 100, lo consulta por tipo de guía.
4. Si aun así un bloque de 4 horas pasa de 100, pide sus guías **una por una por su número** (la consulta por número no tiene el límite de 100). Los números de cada serie son correlativos: con las guías de esa serie de antes y de después del bloque, se sabe exactamente qué números se emitieron dentro. Si no hay guía después (el bloque es el último del periodo), sigue hasta salir del bloque o hasta que 10 números seguidos no existan; si no hay guía antes, retrocede hasta quedar antes del bloque.
5. Lo hecho queda en la hoja **Por número** del Excel: serie, bloques, números pedidos, guardados, que no existen y los que quedaron por pedir. El bloque sigue anotado en **Búsquedas** («Tramo de 4 horas con más de 100 guías»).

Límites:
- Una serie que no aparece en ninguna guía conocida no se puede rellenar: no se sabe que existe. Para evitarlo, la lista puede traer **anclas**: la última guía conocida de cada serie en días anteriores.
- Las búsquedas por destinatario no se rellenan: sus guías son de muchos emisores, cada uno con su numeración.
- Pedir por número cuesta lo mismo que abrir una guía (alrededor de 1 segundo): un emisor con 700 guías al día toma unos 12 minutos por día.

## Opciones (Más opciones)

| Opción | Qué hace |
|---|---|
| Pedir por número los bloques de más de 100 | Activada por omisión (punto 4 de arriba). |
| Solo lista | Cuenta las guías sin abrirlas (diagnóstico rápido). Los bloques de más de 100 se estiman por la numeración, sin pedirlos. |
| Tope de tiempo (minutos) | Al llegar, se detiene, guarda y descarga lo obtenido; lo que faltó queda anotado en el resumen. 0 = sin tope. |
| Guardar solo las que llegan a… | Destino por ubigeo: departamento (nombre o código: «San Martín» o «22»), provincia («1602») o distrito («220901»); varios, separados por comas. Las guías se abren igual (el listado no trae el destino), pero las que llegan a otro departamento no se guardan: solo se cuentan y quedan anotadas para no volver a abrirlas. |

Si la lista trae sus propias opciones (`opciones: { soloLista, rellenar, topeMin, deptoLlegada, destinoNombre }`), mandan las de la lista.

Cada búsqueda de la lista tiene `desde` y `hasta`: una fecha (`AAAA-MM-DD`, `hoy`, `ayer`, `hoy-N`) o, desde la versión 3.4.0, una fecha con hora (`2026-11-18T08:00`, `ayer 08:00`). Con hora, la hora final no se incluye y el primer y el último día se consultan solo en sus bloques de 4 horas de SUNAT (00, 04, 08, 12, 16 y 20 h; otra hora se redondea hacia afuera): «de ayer 08:00 a hoy 08:00» es ayer de 08:00 a 23:59 y hoy de 00:00 a 07:59. La lista puede traer `ventana: { desde, hasta }`, que se copia al JSON para que la página sepa qué periodo cubrió la descarga. La lista también puede traer `prioridad` (documentos: las guías cuyo destinatario figura en el listado con uno de ellos se abren primero; la lista solo se usa en memoria y no se exporta) y `anclas` (`{ rucEmisor, codCpe, serie, numero, fecha }`).

Si se detiene a mitad de la búsqueda, conserva las guías ya encontradas (sin abrir) y se pueden descargar con ⬇ JSON o ⬇ Excel.

## Archivos que entrega

| Archivo | Para qué | Contenido |
|---|---|---|
| JSON | Tablero | Una entrada por guía: `clave`, `estado` (`con_detalle`, `ya_en_tablero`, `no_existe`, `no_consultada`, `sin_detalle`, `no_procesada`, `solo_listado` y `fuera_de_destino`, que trae solo la clave, la fecha y hora de emisión y el ubigeo de llegada), `citadaEnFactura`, fila del listado (estado actual en SUNAT), `detalle` completo y las búsquedas (y casos) que la encontraron. También las consultas hechas, lo pedido por número (`relleno`), los errores y el control de calidad. Nunca incluye la conexión ni la lista de prioridad. |
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
| Se detuvo a mitad | Lo encontrado se conserva (⬇ JSON o ⬇ Excel). Pulse otra vez «Buscar y descargar»: solo consulta lo que falta. |
| Muchas guías «no existe» en una consulta por número | Es normal al final de cada serie: son números que aún no se emiten. No detienen la descarga (desde la versión 3.1.0). |

## Seguridad

- La conexión (token) se toma de la propia pantalla de SUNAT, vive solo en memoria y se descarta al terminar. No se muestra, no se guarda en el navegador ni se exporta.
- Las consultas usan `credentials: "omit"` y `mode: "cors"`; no se modifica ni se evade CORS.
- La escucha de la pantalla de SUNAT es temporal y deja la página como estaba.
- El registro no muestra datos personales ni la conexión.
- Los JSON y Excel tienen información con reserva tributaria (art. 85 del Código Tributario): guárdelos en una carpeta privada y **no los suba sin cifrar** al repositorio.
