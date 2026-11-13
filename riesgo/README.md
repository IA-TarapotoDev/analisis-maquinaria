# Tablero de gestión de riesgo

Página para el Equipo de Gestión de Riesgo de la Intendencia de Aduana de Tarapoto. **Misión:** encontrar las máquinas importadas con el beneficio de la Amazonía que salieron de la ZTE a la ZTC sin solicitud de traslado, con 4 años o menos desde su importación, y reunir las pruebas para actuar. Cruza las guías de remisión con las DAM, los comprobantes emitidos, los XML de las facturas, el domicilio de los compradores y el cuaderno de control de la intendencia.

**Página publicada:** https://ia-tarapotodev.github.io/analisis-maquinaria/ (requiere clave de acceso).

## Protección de los datos

Los datos de origen tienen reserva tributaria (art. 85 del Código Tributario) y **no se versionan en este repositorio**. La página publicada lleva los datos comprimidos y cifrados con AES-256-GCM. La llave se deriva de la clave de acceso con PBKDF2-SHA256 (600 000 iteraciones). Sin la clave, el archivo publicado no revela el contribuyente, sus clientes ni los montos. El descifrado se hace en el navegador y la clave no se envía a ningún servidor. La clave se entrega al equipo por un canal interno; no la publique en el repositorio ni en issues.

## Cómo está organizado

El importador casi siempre cumple al vender: entrega dentro de la ZTE o pide el traslado. La salida la hace después el comprador (constructoras, transportistas y empresas de alquiler llevan sus máquinas a donde tengan obra) y ningún comprador pide traslados. Por eso el tablero parte de la **salida** que muestra una guía, de cualquier emisor, y no de la venta.

| Pestaña | Qué muestra |
|---|---|
| Resumen | La misión, las salidas detectadas por estado, la cola de búsqueda, el parque con beneficio, los tenedores con más riesgo, los **patrones**, el Excel de consultas y la **calidad de los datos** |
| Salidas | Un **expediente por máquina** que una guía lleva de la ZTE a la ZTC (del importador, del comprador o de un tercero). Muestra las pruebas, la última ubicación conocida, a quién requerir, los pasos que siguen, un borrador de requerimiento y las guías |
| Buscar | La **cola de búsqueda**, de la que más rinde a la que menos, con el botón que copia la lista para el extractor de GRE; los transportistas que ya llevaron máquinas; los otros importadores con maquinaria y beneficio (del cuaderno); las listas de rutina, y dónde queda el rastro cuando no hay guía |
| Parque | Las máquinas con beneficio del importador: su tenedor (si la venta está enlazada por serie), su último rastro en las guías y su antigüedad. Filtro «Rastro» para ver las que no tienen tenedor ni guía |
| Tenedores | Los compradores, ordenados por el riesgo de que muevan la máquina a la ZTC, con la parte del tiempo desde la compra que tiene guías consultadas y el botón para buscar sus guías |
| Ventas | Las ventas del importador con indicios (antes «Alertas»): casos por nivel, con «Ver factura», «Buscar guías» y la cadena de comprobantes |

La agrupación elegida en cada pestaña se recuerda en el navegador de quien la usa.

### Salidas: el expediente y sus pruebas

Cada guía con partida en la ZTE y llegada en la ZTC cuyos bienes nombran una máquina (excavadora, retroexcavadora, cargador, minicargador, motoniveladora, rodillo, tractor, cosechadora, trasplantadora, motocultor, autohormigonera, grúa, perforadora, grupo electrógeno o motor marino) abre o alimenta un expediente. No cuentan los repuestos que llevan esos nombres, como los rodillos inferiores o superiores del tren de rodaje o el turbocargador, ni el camión grúa (vehículo) ni la grúa de taller. La máquina se identifica por la serie de la guía; si la guía cita una factura del importador, por la serie del XML; las guías del transportista heredan los bienes de la guía que sustentan. Una guía sin serie se une a una máquina con serie del mismo dueño y tipo si están a 3 días o menos y coinciden en el destinatario, el lugar de llegada o el punto de partida; para el importador, que despacha muchas máquinas iguales desde el mismo almacén, no basta el punto de partida. Si la DAM resulta posterior a la salida, el enlace está mal: el expediente lo advierte y no usa esa DAM. Cuando la máquina parte de la zona de otra intendencia (Pucallpa, Iquitos), el expediente indica que la DAM y el traslado se confirman ahí. Si quien la movió figura en el cuaderno de la IA como importador con DAM de maquinaria, el expediente lista sus DAM del mismo tipo de máquina anteriores a la salida (minicargadores y cargadores se toman como una familia), para buscar ahí la serie; en el Excel esas salidas van con prioridad 1 y en la pestaña Salidas se filtran con «Otro importador con beneficio». También lista los traslados a la ZTC que ese importador pidió en el cuaderno entre 180 días antes y 30 días después de la salida, del mismo tipo de maquinaria (amarilla o agrícola): si la máquina está en uno de ellos, su salida tiene autorización. El expediente también advierte que la máquina puede no haber salido cuando la dirección de llegada contradice el distrito de la guía (nombra un lugar de la ZTE o es la misma del punto de partida) o cuando otra guía vigente posterior mueve la misma máquina dentro de la ZTE. Si en los 3 días siguientes una guía de transportista lleva la máquina dentro de la ZTE y ninguna guía de transportista la lleva a la ZTC, la guía a la ZTC probablemente no se usó: la salida no pasa a caso armado hasta confirmar que la máquina salió.

| Prueba | De dónde sale |
|---|---|
| Serie de la máquina | El rótulo «SERIE …», «S/N …», «N/S …», «VIN …» o «CHASIS …» de la guía (la serie termina antes de un «--» o del rótulo siguiente, como «-MOTOR») o la última palabra de 8 o más caracteres con letras y números que no sea el valor de otro rótulo (en «MODELO 416-ABC12345» el modelo es 416 y la serie, ABC12345). Una serie solo de números, como un chasis «1234567», se busca en otras guías sin otro dígito pegado |
| DAM con beneficio | Las DAM del importador (por PIN o motor), la consulta del equipo por serie o la hoja «Salidas por verificar» del Excel. Si la DAM anotada está en el cuaderno de la IA (ConsolidadoT), basta su número: la fecha, el importador y el beneficio se completan con el cuaderno |
| Dentro de los 4 años | Los 4 años se cuentan por año calendario: el de la DAM y los 3 siguientes (con DAM de 2022, la salida puede ser hasta 2025; en 2026 ya pasaron). La fecha de la DAM puede ser completa, mes y año («06/2022») o solo el año. Sin DAM conocida cuenta el año de la máquina: el que anota el equipo en «Año de la máquina» o, si no, el que declara la guía («AÑO 2013», «AÑO DE FABRICACIÓN: 2020»). Una salida pasados los 4 años se descarta: solo se trabajan máquinas de hasta 4 años |
| Sin solicitud de traslado | El cuaderno de traslados (por DAM y serie). Para una DAM del cuaderno anotada por el equipo: si el cuaderno no tiene traslado para esa DAM, cuenta como sin solicitud; si lo tiene, queda por confirmar que incluya la máquina. Si el equipo anota que la DAM es de otra intendencia («Intendencia de la DAM»: Pucallpa, Iquitos…) o la máquina partió de otra circunscripción, el traslado queda por confirmar en esa intendencia: no basta que no figure en el cuaderno de Tarapoto |
| Guía vigente a la ZTC | Guía emitida y no dada de baja. Si solo hay guías dadas de baja, el expediente queda como indicio |

Cada máquina conserva su número de expediente (S01, S02…) de una versión a otra si el generador recibe el JSON de la versión anterior con `--salidas-previas`: se reconoce por su serie o, si no la tiene, por sus guías. Las salidas nuevas toman el número siguiente.

Estados: **Caso armado** (las cinco pruebas: falta ubicar y verificar la máquina), **Indicio: guía dada de baja**, **Por completar** (dice qué falta y dónde conseguirlo), **Regresó a la ZTE** (una guía posterior la trae de vuelta) y **Descartada** (con solicitud de traslado, sin beneficio, salida pasados los 4 años de la DAM o, sin DAM conocida, del año de la máquina). La última ubicación es la llegada de la guía más reciente que nombra la máquina (el mismo día, la de número correlativo mayor); si las guías posteriores del tenedor ya se consultaron y ninguna la nombra, el expediente lo dice.

### Tenedores: puntaje de riesgo

Suma: ya movió maquinaria a la ZTC (4); guía a la ZTC dada de baja (3); domicilio fuera de la ZTE o mudado (3); zona de frontera con la ZTC, es decir Cajamarca, Huánuco, Utcubamba, Bagua, Tocache o Padre Abad (2); alquiler de maquinaria o consorcio (2); constructora o transporte (1); dos o más máquinas sin IGV (1, o 2 desde cuatro), y RUC reciente o no habido (1). La cobertura mide qué parte del tiempo desde la primera compra tiene guías consultadas del RUC como remitente, según las búsquedas de cada descarga del extractor.

### Cola de búsqueda

1. **Guías de remitente que cita un transportista hacia la ZTC**: la guía de transportista de la ZTE a la ZTC que no detalla la carga cita la guía del remitente; si esa no está descargada, se consulta directo por su número (primero las del importador, luego las de más peso). Las guías físicas (series 0001…) no están en el sistema de guías electrónicas y solo se cuentan.
2. **Guías de otros importadores con beneficio**: los que el cuaderno registra con DAM de maquinaria con beneficio y cuyas guías como remitente no están consultadas. La búsqueda de cada uno empieza en el reconocimiento físico de su primera DAM con beneficio de los últimos 4 años (desde ahí puede vender o trasladar la mercancía); si aún no tiene reconocimiento, en la fecha de su primera DAM. Si ya hay guías descargadas de una parte de ese periodo, se pide solo lo que falta. Van de 10 en 10, primero los que tienen más DAM de maquinaria.
3. **Guías de máquinas del importador que faltan** (series TP): consulta directa por número de las que no están descargadas, hasta 40 después de la última conocida y, hacia atrás, las necesarias para cubrir los últimos 4 años (según el ritmo con que la serie emite guías; si la primera conocida ya es anterior a ese plazo, no se retrocede). Los 40 posteriores van marcados: pueden no existir todavía, y el extractor deja de probar la serie cuando 10 seguidos no existen. Un hueco que SUNAT ya confirmó que no existe no se vuelve a pedir.
4. **Facturas de máquinas sin comprador identificado**: ventas de maquinaria sin serie enlazada (ni XML ni guía con la serie). La factura detallada trae la serie y dice quién compró cada máquina, aunque la venta no tenga indicios: un comprador de la ZTE que compró sin IGV no forma caso, pero su máquina puede terminar en la ZTC. Se descargan a mano del portal del importador; la lista «Comprobantes por descargar» (pestaña Ventas) las ordena por el riesgo del comprador (prioridades 4 a 6).
5. **Seguir las máquinas que ya salieron**: guías posteriores del tenedor, de quien la recibió y de quien recibió la última guía, si aún no están consultadas. Quien tiene varias máquinas se pide una sola vez, desde la salida más antigua y solo en las fechas que faltan.
6. **Tenedores con más riesgo** sin guías consultadas desde la compra. No entran los que emiten más de 100 guías en un día (grandes distribuidores): SUNAT no deja descargar esos días, así que sus máquinas se ubican por la serie en las guías de los transportistas y del importador.
7. **Transportistas que ya llevaron máquinas** y no están consultados en los últimos dos años.
8. **Excel de consultas**: lo que solo se puede ver en el sistema.

### Control de la DAM (cuaderno de la IA)

Para el riesgo solo importa si la DAM tiene el beneficio y si la serie tiene solicitud de traslado. Se lee la hoja **ConsolidadoT** (las hojas de los especialistas repiten lo mismo) y la hoja **Ingreso de DAM**:

| Estado | Cuándo | Qué hace el tablero |
|---|---|---|
| Con beneficio | La DAM tiene solicitud de regularización: «Resultado_solicitud» (columna AY) dice Procedente, No conforme (la diligencia no fue conforme, pero el beneficio se otorgó) o está vacío (en trámite), o la DAM está en Ingreso de DAM | Se siguen sus máquinas |
| Sin beneficio | «Resultado_solicitud» dice Improcedente o «Sin solicitud de reconocimiento», o la serie se importó sin código liberatorio ni TPI. Es lo mismo que no acogida, no desgravada, sin código liberatorio 4438 o sin solicitud: nunca se desgravó ni se devolvió el IGV de la Ley 27037, y la máquina puede circular fuera de la ZTE | Sus máquinas no se siguen: no forman casos ni aparecen en Máquinas; una salida sin beneficio se descarta. En el Excel basta «No» en «¿Con beneficio?», y el tablero también entiende esas palabras (una respuesta que empieza con «Sin» nunca se lee como «Sí») |
| Sin registro | DAM con destino Tarapoto que no está en el cuaderno | Dato faltante: sus casos quedan «por confirmar» hasta completarlo |

La diligencia, el reconocimiento físico, las RI, las NCN y los tributos no se usan. Una **solicitud de traslado** cuenta aunque esté en trámite, y vale solo para las series que cita (nunca para toda la DAM); las que no indican la serie se listan para completarlas en el cuaderno. «ZTE a ZTE pasando por ZTC» es tránsito, no salida. El cuaderno cubre las DAM con destino Tarapoto (271); las de otro destino aparecen sin registro (las controla esa intendencia).

### Guías de remisión (extractor de GRE)

El tablero no consulta a SUNAT: arma listas de búsqueda que se copian y se pegan en el panel del [extractor de GRE](../sunat-gre/README.md), que corre en la consola de Edge dentro de la sesión de SUNAT de quien lo usa.

| Botón | Qué busca |
|---|---|
| **Copiar la lista para el extractor** (pestaña Buscar, cola de búsqueda) | La búsqueda de cada paso de la cola: las guías de remitente que cita un transportista hacia la ZTC y las guías de máquinas del importador que faltan (consulta directa por número), las guías posteriores de quien movió o recibió una máquina que ya salió, y las guías como remitente de los tenedores con más riesgo |
| **Seguir la máquina** (ficha de cada salida) | Las guías como remitente del tenedor, de quien recibió la máquina y de quien recibió la última guía, desde 3 días antes de la salida hasta hoy, si aún no están consultadas |
| **Lista** (tablas de Buscar y ficha de cada tenedor) | Las guías de ese RUC como remitente: desde su primera compra (tenedor), desde el reconocimiento físico de su primera DAM con beneficio, solo las fechas que faltan descargar (otro importador) o de los últimos dos años (transportista) |
| **Lista del día** (pestaña Buscar, «Listas de rutina») | Ayer y hoy: los compradores **reincidentes** (con al menos un caso alto o medio) como remitentes y destinatarios, el importador como remitente y destinatario, y los **transportistas vigilados** (guías de remitente, transportista y por eventos) |
| **Buscar guías** (ficha de cada venta) | Las guías del comprador como destinatario y como remitente desde 3 días antes hasta 15 días después de la venta, y las guías citadas en la factura (XML), consultadas directo por su número |
| **Guías de los casos altos** (pestaña Buscar, «Listas de rutina») | Lo mismo que «Buscar guías», para todas las ventas de nivel alto a la vez |

Si el navegador no deja copiar, la lista se descarga como archivo y se abre en el extractor con «Abrir archivo de lista». El extractor devuelve un JSON (para integrarlo al tablero) y un Excel (para revisar); ambos tienen reserva tributaria y no se versionan sin cifrar.

El JSON vuelve al generador con `--guias` (uno o más archivos; también acepta el Excel del extractor; una guía repetida se lee una sola vez). Todas las guías se revisan para detectar salidas (ver «Salidas»). Además, cada guía se enlaza con la venta del importador que le corresponde:

| Enlace | Cuándo |
|---|---|
| Firme | La guía cita la factura (o la factura cita la guía), o sus bienes llevan la serie (8 últimos caracteres del PIN) o el motor de la máquina. Si la factura no trae la serie, la guía del importador o del comprador con una máquina del mismo tipo, de 5 días antes a 30 después de la venta, la identifica |
| Del transportista | La guía de transportista que cita una guía de remitente ya enlazada. Si esa guía de remitente se dio de baja, la del transportista tampoco cuenta como vigente |
| Probable | Guía del importador o del comprador con el mismo tipo de máquina, de 3 días antes a 30 después de la venta, cuando una sola venta encaja |

La zona de la partida y de la llegada sale del ubigeo de cada dirección. En el caso:

- **Llegada fuera de la ZTE** (guía vigente con llegada en la ZTC): es un indicio de salida por sí solo; si la máquina viene de una DAM con destino Tarapoto, el caso queda «Confirmada: guía de remisión con llegada fuera de la ZTE».
- **Destino cambiado**: una guía a la ZTC se dio de baja y otra lleva la máquina a la ZTE. El caso no baja de nivel.
- **Llegada en la ZTE** (todas las guías vigentes llegan a la ZTE y no hubo cambio de destino): un caso alto por ubicación (comprador de fuera o venta con IGV) pasa a medio, «Guía de remisión a la ZTE: verificar que la máquina siga ahí». No baja si hubo reemisión sin IGV, entrega fuera de la ZTE, venta a no domiciliado o solicitud de traslado.
- Si la única guía con la máquina se dio de baja, la ficha lo dice y sugiere pedir la guía con la que el comprador la recibió.
- **Traslados internos**: una guía del importador entre sus sedes de la ZTE («Traslado entre establecimientos») se muestra en la ficha, pero no cuenta como entrega al comprador ni baja el nivel del caso; si es la única, la ficha pide la guía de la entrega.
- **Exportaciones**: la guía a la ZTC de una venta exportada (con DAM de exportación) es el camino al puerto y no es por sí sola un indicio de salida.
- Para ubicar la máquina en la ZTE solo cuentan las guías desde 3 días antes de la venta.
- **Regreso a la ZTE**: si después de una guía a la ZTC hay otra que trae la máquina de vuelta a la ZTE, la ficha sugiere vigilar la anulación de la venta, un pedido de devolución de lo pagado por el traslado o una nueva venta sin IGV.

La ficha de cada caso y de cada máquina muestra sus guías (partida y llegada con su zona, emisor, destinatario, motivo, placas, bienes y cómo se enlazó) y la cronología las incluye. Solo se guardan las guías enlazadas a una venta o a una salida; las claves de todas las demás quedan como «conocidas», para que las listas nuevas no las descarguen otra vez. De cada descarga se guarda además qué RUC y qué fechas se consultaron completos: con eso el tablero calcula la cobertura de cada tenedor, importador y transportista. Una guía muestra a dónde se llevó la máquina, no dónde está hoy, y la llegada la declara quien la emite.

## Criterios de los casos

| Nivel | Cuándo |
|---|---|
| Alta | Venta de una máquina con beneficio con indicio de salida de la ZTE (comprador domiciliado en la ZTC, venta con IGV, reemisión sin IGV de una factura con IGV, entrega fuera de la ZTE o venta a no domiciliado sin DAM de exportación) sin solicitud de traslado que la respalde. Estados: confirmada sin solicitud de traslado (la serie del XML lleva a su DAM y la serie no tiene solicitud de traslado), solo con traslado de tránsito, DAM de Tarapoto que falta en el cuaderno (por confirmar), DAM de otro destino, serie fuera de las DAM del periodo, o por confirmar (falta el XML) |
| Media | Indicio de salida con **traslado probable** (por tipo de máquina y fecha, por confirmar con el XML); **guía de remisión a la ZTE** (verificar que la máquina siga ahí); comprador con RUC inscrito 180 días o menos antes de comprar; comprador no habido o con RUC no activo; anulación o reemisión cerca de un traslado de maquinaria |
| Baja | Flujo coherente: venta a no domiciliado con DAM de exportación, o salida con solicitud de traslado para la misma DAM y serie |

Las ventas de máquinas sin beneficio (importadas sin código liberatorio ni TPI, o con solicitud improcedente o sin solicitud de reconocimiento) no forman casos: pueden trasladarse o venderse a la ZTC sin riesgo aduanero. Las que se vendieron sin IGV a un comprador de la ZTC quedan anotadas en el patrón «Máquinas sin beneficio» (tributos internos).

Reglas de calidad:

- Se cuentan **ventas** (facturas vigentes): sin las anuladas con nota de crédito ni los **anticipos** que la factura final descuenta (valor + IGV − total).
- La factura que anula cada nota de crédito sale del XML de la nota; sin él, por cliente, moneda y monto.
- Las facturas de la serie de maquinaria por menos de USD 10 000 o S/ 34 000 (accesorios, implementos o pagos parciales) no forman casos.
- Cada traslado se asigna a tantas ventas como máquinas traslada y cada venta a un solo traslado. «ZTE a ZTE pasando por ZTC» es tránsito, no salida.
- El monto de cada traslado se contrasta con el 18 % (IGV + IPM) del CIF de su serie; los expedientes repetidos o que no cuadran se señalan y se cuentan una sola vez.
- En comprobantes con IGV, el monto mostrado es el valor de venta más el 18 % calculado.

Se retiraron, por no apuntar a la salida de la zona o por dar falsos positivos: establecimiento emisor inferido por la serie, valores unitarios atípicos, números de parte en varias subpartidas, repuestos y servicios con IGV o a no domiciliados, clientes con 3 o más máquinas, y las estadísticas generales de importación y ventas.

Los casos son indicios para el análisis de riesgo y no constituyen conclusiones. El domicilio fiscal es el vigente en la fecha del padrón: puede diferir del que tenía el cliente al comprar y del lugar donde opera la máquina.

## Regenerar la página

```bash
# 1. Datos → JSON (fuera del repositorio)
python3 -I riesgo/scripts/generar_datos.py DAMs.csv CPEs_EMITIDOS.txt CPE_DETALLE_EMITIDO.txt /ruta/privada/datos.json \
  --domicilios /ruta/privada/domicilios.csv --consulta-ruc lote1.zip lote2.zip \
  --facturas-xml /ruta/privada/xml --control-ia /ruta/privada/control.xlsm \
  --trazabilidad /ruta/privada/casos.csv --portal URL_DEL_PORTAL_DEL_EMISOR \
  --transportistas /ruta/privada/transportistas.txt --guias /ruta/privada/gre_*.json \
  --salidas-previas /ruta/privada/datos_anterior.json

# 2. JSON → página cifrada (la clave se lee de un archivo privado, no del repositorio)
CLAVE_TABLERO_ARCHIVO=/ruta/privada/clave.txt \
  python3 -I riesgo/scripts/cifrar.py /ruta/privada/datos.json riesgo/plantilla.html /ruta/privada/index.html

# 3. Publicar: copiar index.html a la raíz de la rama gh-pages (index.html)
```

### Excel de consultas

La primera hoja, **«Salidas por verificar»**, lista las máquinas que una guía lleva a la ZTC y que no se descartan solas. El equipo busca la serie en el sistema y anota: la serie (si la guía no la trae), la DAM, su año o fecha, el importador, si tiene el beneficio, si tiene solicitud de traslado, el expediente y la ubicación verificada. Con «Sí» en beneficio, «No» en traslado y 4 años o menos, el expediente pasa a caso armado. Cada fila se identifica por la clave de su guía principal y la serie de la máquina (una guía puede llevar varias máquinas), así que lo completado se conserva con `--previo`.

Las otras hojas vienen de que el cuaderno de la IA Tarapoto solo cubre las DAM con destino Tarapoto. `consultas_xlsx.py` reúne en el mismo Excel lo demás que conviene consultar en el sistema: las DAM con maquinaria y destino en otra intendencia (modalidad de pago o garantía, estado de la solicitud, diligencia, RI, NCN y traslado), las series vendidas que no están en las DAM del periodo y el PIN de cada serie de las DAM anteriores al periodo que tienen traslados de maquinaria. Las celdas grises vienen del tablero y las amarillas se completan.

```bash
# Arma el Excel (con --previo conserva lo que el equipo ya completó)
python3 -I riesgo/scripts/consultas_xlsx.py /ruta/privada/datos.json /ruta/privada/consultas_otras_intendencias.xlsx \
  [--previo /ruta/privada/consultas_completadas.xlsx]

# Lo adjunta cifrado a la página: se descarga desde Resumen, Buscar o Parque una vez abierta con la clave
CLAVE_TABLERO_ARCHIVO=/ruta/privada/clave.txt python3 -I riesgo/scripts/cifrar.py /ruta/privada/datos.json riesgo/plantilla.html \
  /ruta/privada/index.html --adjunto /ruta/privada/consultas_otras_intendencias.xlsx

# El Excel completado vuelve al generador
python3 -I riesgo/scripts/generar_datos.py ... --consultas /ruta/privada/consultas_completadas.xlsx
```

Con el Excel completado, el control de cada DAM consultada aparece en la ficha de sus máquinas («consulta a la intendencia de destino»). Una DAM con «Ninguno» en traslado confirma la venta fuera de la ZTE sin traslado. Una serie ubicada como importada por otro importador o comprada en el país baja de nivel: a «coherente» si se importó sin desgravación y se vendió con IGV. Una serie ubicada en una DAM anterior con beneficio y sin traslado queda en nivel alto. Un PIN de una DAM anterior que coincide con la serie de una factura confirma el traslado de esa venta. El Excel tiene datos de contribuyentes: no se versiona ni se publica sin cifrar.

Todas las opciones de `generar_datos.py` son opcionales salvo los tres archivos de origen y la salida.

### Fuentes opcionales

- **Domicilio fiscal:** `extraer_domicilios.py` toma del padrón reducido del RUC (público: https://www2.sunat.gob.pe/padron_reducido_ruc.zip) solo los RUC de los clientes. Cada cliente se ubica por el ubigeo de su domicilio en la ZTE o la ZTC (art. 3 de la Ley 27037, con las reglas de `mapas/scripts/05_tematicos.py` del repositorio TARAPOTO-Dev). `referencias/ubigeo_zte.csv` se genera con `scripts/zona_ubigeo.py` a partir de [jmcastagnetto/ubigeo-peru-aumentado](https://github.com/jmcastagnetto/ubigeo-peru-aumentado) (licencia MIT).
  ```bash
  python3 -I riesgo/scripts/extraer_domicilios.py padron_reducido_ruc.zip CPEs_EMITIDOS.txt /ruta/privada/domicilios.csv
  ```
- **Consulta múltiple de RUC** (`--consulta-ruc`, ZIP o TXT, hasta 100 RUC por consulta): actividad económica, fecha de inscripción y, si el padrón no lo trae, el domicilio. La consulta pública no muestra el domicilio de las personas naturales.
- **XML de las facturas** (`--facturas-xml`, archivos, carpetas o ZIP, también ZIP dentro de ZIP; los 7z y RAR se descomprimen antes): se leen facturas y notas de crédito (UBL 2.1). De cada ítem se extraen la serie de la máquina y del motor, el modelo, el año y la afectación del IGV; la máquina se enlaza con su DAM y el caso se confirma o se descarta. La nota de crédito indica con exactitud la factura que anula. El comprobante completo se puede ver desde la ficha («Ver factura»). La lista «Comprobantes por descargar del portal» (pestaña Ventas, con CSV) indica cuáles faltan: prioridad 1, casos de nivel alto; 2, traslados probables; 3, cadenas de anulación; 4 a 6, ventas de maquinaria sin serie enlazada, según el riesgo del comprador.
- **Cuaderno de control de la IA** (`--control-ia`, xlsx o xlsm): hojas ConsolidadoT (con la columna «Resultado_solicitud», que en el cuaderno actual se llama «Resultado_Solicud»), Ingreso de DAM, Traslados (con las series de cada DAM), ConsolidadoA2 y Complejidad. Las hojas de los especialistas, NCN y Hoja1 ya no se leen.
- **Transportistas vigilados** (`--transportistas`, TXT): un RUC por línea, opcionalmente seguido del nombre (`20123456789 TRANSPORTES EJEMPLO SAC`). Se ignoran las líneas vacías, las que empiezan con `#`, los repetidos y los RUC no válidos (se avisa el número de línea). Entran en la «Lista del día» de guías de remisión.
- **Casos documentados a mano** (`--trazabilidad`, CSV con `cpe, serie_maquina, serie_motor, modelo, ubicacion_entrega, direccion_entrega, fuente, nota`; `ubicacion_entrega` como «DISTRITO, PROVINCIA, DEPARTAMENTO»): por ejemplo, la representación impresa de una factura con el lugar de entrega.

Ninguno de estos archivos se versiona: todos tienen datos de contribuyentes.

### Formatos de entrada

- **DAM** (CSV, todas las aduanas de destino y regímenes; los casos usan el régimen 10, el depósito 70 y la exportación 40 completan la historia de cada máquina): `COD_ADUANA, ANN_PRESEN, COD_REGIMEN, NUM_DECLARACION, FEC_DECLARACION, COD_ADUDEST, NUM_DOCIDENT, NOM_RAZONSOCIAL, DIR_PARTIC, COD_TIPPARTIC, CANAL, NUM_PARTNANDI, NUM_SECSERIE, CNT_COMER, COD_UNICOMER, MTO_FOBDOL, MTO_FLETEDOL, MTO_SEGDOL, MTO_VALORADU, DES_COMER, DES_FORMAPRESEN, DES_MATECOMP, DES_USOAPLIC, DES_OTROSCARAC, COD_TIPCONVENIO, COD_CONVENIO`
- **CPE emitidos** (TXT con `|`, Latin-1, fechas MM/DD/AAAA): `ruc emisor | tipo cpe | serie | nro cpe | tipo cpe | tipo doc | doc/receptor | nombre receptor | moneda | valor venta | igv | importe total | fecha cpe | indicador estado`
- **Detalle de CPE** (TXT con `|`, Latin-1): `num_ruc | cod_cpe | num_serie_cpe | num_cpe | cod_tipo_cpe | cod_docide_recep | num_docide_recep | des_nombre_recep | fec_emision | moneda | ind_estado | ind_rechazo | cod_unidad | des_detalle_item | num_cant_item | mto_total_venta | mto_total_igv | observacion`
