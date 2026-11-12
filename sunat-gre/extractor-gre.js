/* =====================================================================
 * EXTRACTOR DE GRE – Guías de Remisión Electrónica (SUNAT, uso autorizado)
 * Versión 3.0.0
 *
 * Dónde ejecutarlo:
 *   Microsoft Edge > DevTools (F12) > Console > selector de contexto
 *   «iframeApplication (…) – intranet.sunat.peru». En «top» (e-menu.sunat.peru)
 *   no funciona: el script lo detecta y explica cómo cambiarlo.
 *
 * Uso diario, con el tablero de riesgo:
 *   1. En el tablero, «Lista del día» (o «Buscar guías» en un caso) copia la lista.
 *   2. Aquí, pegue la lista en el panel y pulse «Buscar y descargar».
 *   3. Si el panel lo pide, abra cualquier guía con «Ver» en la pantalla de SUNAT.
 *   4. Al terminar se descargan el JSON (para el tablero) y el Excel (para revisar).
 *   También hay una búsqueda manual: RUC, rol, tipos de guía y periodos.
 *
 * Qué hace por dentro:
 *   - Toma la conexión (token) de la propia pantalla de SUNAT: no hay que copiar nada.
 *   - Busca guías de remitente (09), de transportista (31) y por eventos (G9).
 *   - SUNAT entrega como máximo 100 guías por consulta (error 2021): divide los
 *     periodos por días y, si un día pasa de 100, por bloques de 4 horas y por tipo.
 *   - Consulta el detalle de cada guía nueva; las que el tablero ya tiene no se
 *     vuelven a descargar (solo se anota su estado actual).
 *   - Las guías citadas en las facturas se consultan directamente por su número.
 *   - Si la conexión vence, espera a que se abra una guía con «Ver» y continúa.
 *
 * Seguridad:
 *   - El token solo vive en memoria y se descarta al terminar: nunca se muestra,
 *     se guarda ni se exporta.
 *   - No usa localStorage, sessionStorage, cookies ni servidores externos.
 *   - credentials: "omit" y mode: "cors" (nunca "no-cors").
 *   - La escucha de la pantalla de SUNAT es temporal y deja la página como estaba.
 *
 * Única variable global: window.GREExtractor
 * ===================================================================== */
(() => {
  'use strict';

  const VERSION = '3.1.0';
  const API_LISTADO = 'https://api-intranet.sunat.peru/v1/contribuyente/gre/comprobantes';
  const PANEL_ID = 'gre-extractor-host';
  const ORIGEN_CORRECTO = 'https://intranet.sunat.peru';

  /* ---------------------------------------------------------------
   * 0. Contexto de la consola, ejecución única y versión anterior
   * ------------------------------------------------------------- */
  // La pantalla de guías está en «iframeApplication» (intranet.sunat.peru). El menú
  // («top», e-menu.sunat.peru) es otro sitio: desde ahí no se ve lo que hace la pantalla.
  const origenActual = (() => { try { return String(self.origin || location.origin || ''); } catch (_) { return ''; } })();
  if (/sunat\.peru(:\d+)?$/i.test(origenActual) && origenActual !== ORIGEN_CORRECTO) {
    avisarContextoEquivocado(origenActual);
    return;
  }

  function avisarContextoEquivocado(origen) {
    const pasos = [
      'El extractor debe ejecutarse en la pantalla de guías, no en el menú de SUNAT.',
      '1. En la consola (F12 > Console), arriba a la izquierda, haga clic en el selector que dice «top».',
      '2. Elija «iframeApplication (…)» de intranet.sunat.peru.',
      '3. Vuelva a pegar el script (o ejecute el Snippet) y pulse Enter.'
    ];
    console.error('[GRE] La consola está en el contexto equivocado (' + origen + ').\n' + pasos.join('\n'));
    try {
      const anterior = document.getElementById('gre-aviso-contexto');
      if (anterior) anterior.remove();
      const caja = document.createElement('div');
      caja.id = 'gre-aviso-contexto';
      caja.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;max-width:430px;background:#fff;color:#1d2433;' +
        'border:2px solid #a12b2b;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.3);padding:14px 16px;font:14px/1.45 "Segoe UI",system-ui,sans-serif';
      const titulo = document.createElement('div');
      titulo.textContent = '⚠ Extractor de GRE: contexto equivocado';
      titulo.style.cssText = 'font-weight:700;color:#a12b2b;margin-bottom:6px';
      caja.append(titulo);
      for (const p of pasos) {
        const linea = document.createElement('div');
        linea.textContent = p;
        linea.style.cssText = 'margin:3px 0';
        caja.append(linea);
      }
      const boton = document.createElement('button');
      boton.textContent = 'Entendido';
      boton.style.cssText = 'margin-top:8px;padding:5px 12px;border:1px solid #a12b2b;background:#a12b2b;color:#fff;border-radius:5px;cursor:pointer';
      boton.addEventListener('click', () => caja.remove());
      caja.append(boton);
      (document.body || document.documentElement).appendChild(caja);
    } catch (_) { /* sin página visible */ }
  }

  const instanciaPrevia = window.GREExtractor;
  if (instanciaPrevia && instanciaPrevia.ejecutando) {
    console.warn('[GRE] Ya hay una búsqueda en curso. Deténgala con GREExtractor.cancelar() y espere a que termine antes de volver a pegar el script.');
    try { instanciaPrevia.mostrarPanel(); } catch (_) { /* sin panel */ }
    return;
  }
  if (instanciaPrevia) {
    try {
      if (typeof instanciaPrevia.destruir === 'function') instanciaPrevia.destruir();
      else if (typeof instanciaPrevia.cerrarPanel === 'function') instanciaPrevia.cerrarPanel();
    } catch (_) { /* ignorar */ }
  }
  // Referencia propia a fetch, tomada antes de cualquier escucha: así las consultas del
  // extractor nunca se confunden con las de la pantalla de SUNAT.
  const fetchPropio = window.fetch;

  /* ---------------------------------------------------------------
   * 1. Configuración predeterminada
   * ------------------------------------------------------------- */
  const TIPOS_GRE = { '09': 'Remitente', '31': 'Transportista', 'G9': 'Por eventos' };
  // Orden fijo (Object.keys pondría «31» primero por parecer un número)
  const ORDEN_TIPOS = Object.freeze(['09', '31', 'G9']);
  const CONFIG_PREDETERMINADA = Object.freeze({
    rucs: [],
    rol: 'ambos',               // búsqueda manual: 'receptor' | 'emisor' | 'ambos'
    tipos: ['09', '31', 'G9'],
    periodos: [],               // [{ desde: 'AAAA-MM-DD' | 'hoy' | 'hoy-N', hasta: … }]
    numSerie: '',
    numCpe: '',
    codEstado: '',
    codSubEstado: '',
    tipBusqueda: '2',           // 2 = búsqueda masiva (por fechas)
    perPage: 100,
    maxDiasBloque: 31,          // días máximos por consulta (se reduce solo si SUNAT lo rechaza)
    objetivoPorBusqueda: 80,    // guías esperadas por consulta, para no pasar el límite de 100
    pausaMinMs: 600,
    pausaMaxMs: 900,
    maxReintentos: 2,
    timeoutMs: 45000,
    maxErroresConsecutivos: 8,
    maxNoExistenSerie: 10,      // consulta por número: tantos seguidos que no existen tras la última guía conocida = fin de la serie
    esperaConexionMin: 30,      // minutos que espera una conexión nueva antes de detenerse
    descargarJSON: true,        // al terminar: JSON para el tablero
    descargarExcel: true        // al terminar: Excel para revisar
  });

  const ESTADOS_REINTENTABLES = new Set([429, 500, 502, 503, 504]);
  const COD_EXCESO = '2021';    // SUNAT: «se cuenta con más de (100) registros en el periodo consultado»
  // Respuesta de SUNAT a una guía consultada por número que no existe (el código HTTP varía: 404, 400, 422 o 500)
  const NO_EXISTE = /no\s+exist|inexistent|no\s+(se\s+)?(ha\s+)?encontr|no\s+encontrad|not\s+found|no\s+registrad/i;
  /** ¿Es el detalle de una guía (y no un mensaje de error con código 200)? */
  const pareceDetalle = (d) => esObjetoPlano(d) && ['traslado', 'emision', 'numSerie', 'numCpe'].some((k) => k in d);
  const BLOQUES_HORA = [1, 2, 3, 4, 5, 6];
  const TEXTO_BLOQUE = { 1: '00:00–03:59', 2: '04:00–07:59', 3: '08:00–11:59', 4: '12:00–15:59', 5: '16:00–19:59', 6: '20:00–23:59' };
  const TEXTO_ROL = { receptor: 'receptor', emisor: 'emisor', ambos: 'emisor y receptor' };
  const MARGEN_VENCIMIENTO_MS = 20000;

  const AYUDA_FALLO_CONEXION = [
    'El navegador no pudo leer la respuesta de SUNAT. Causas más comunes:',
    '1) La conexión venció o no es válida.',
    '2) La consola no está en el contexto «iframeApplication» (intranet.sunat.peru).',
    'Solución: pulse «Conectar», abra cualquier guía con «Ver» en la pantalla de SUNAT y vuelva a pulsar «Buscar y descargar».'
  ];

  /* ---------------------------------------------------------------
   * 2. Estado interno (nunca contiene el token)
   * ------------------------------------------------------------- */
  const estado = {
    ejecutando: false,
    pausado: false,
    esperandoConexion: false,
    controller: null,
    config: null,
    motivoFin: '',
    fase: '',                  // 'conexion' | 'busqueda' | 'detalle'
    tiempos: { inicio: 0, inicioDetalle: 0, fin: 0 },
    tokenExp: null,            // solo la hora de vencimiento, para mostrarla
    pedido: null,              // lista cargada desde el tablero (tal como llegó)
    tareas: [],                // una por búsqueda de la lista
    busquedas: [],             // cada consulta hecha en SUNAT (para el control)
    unicos: [],
    duplicados: [],
    origenes: new Map(),       // clave -> [{ etiqueta, caso, grupo }]
    resultados: new Map(),     // clave -> registro
    previos: new Map(),        // clave -> { detalle, consultadoEn } (archivo anterior)
    memoria: new Map(),        // clave -> { detalle, consultadoEn } (ejecución anterior de esta sesión)
    errores: [],
    controlDetalle: [],
    control: [],
    progreso: null,
    resumen: null,
    fallosRedSeguidos: 0,
    huboBusquedaCorrecta: false,
    mensajesExceso: new Set()  // mensajes de SUNAT que resultaron significar «demasiadas guías»
  };

  function progresoVacio() {
    return {
      total: 0, actual: '', procesadas: 0, ok: 0, error: 0, omitidas: 0, consultadas: 0, pendientesReales: 0,
      diasTotales: 0, diasHechos: 0, encontradas: 0, tareaActual: 0, tareasTotal: 0, busquedaActual: ''
    };
  }
  estado.progreso = progresoVacio();

  let ui = null;                   // referencias del panel (si existe)
  let periodosEditados = false;    // si el usuario cambió los periodos de la búsqueda manual

  // Conexión tomada de la pantalla de SUNAT. Solo en memoria (nunca global ni persistente).
  let tokenCapturado = null;       // se consume al iniciar y se descarta al terminar
  let cabecerasCapturadas = null;  // otras cabeceras que envía la aplicación (se descartan con el token)
  let filtrosCapturados = null;    // datos de la última búsqueda hecha en SUNAT (sin token)
  const urlsCapturadas = { listado: '', detalle: '' }; // direcciones sin token (plantilla y diagnóstico)
  const captura = { activa: false, modo: '', temporizador: null, restaurar: null };
  const diagnostico = { activo: false, temporizador: null, vistas: 0, api: 0, conToken: 0 };

  /* ---------------------------------------------------------------
   * 3. Utilidades generales
   * ------------------------------------------------------------- */
  class ErrorValidacion extends Error { constructor(m) { super(m); this.name = 'ErrorValidacion'; } }
  class ErrorAutenticacion extends Error {
    constructor(status, url, mensaje, codigo) {
      super(mensaje || `HTTP ${status}: SUNAT no aceptó la conexión.`);
      this.name = 'ErrorAutenticacion'; this.status = status; this.url = url;
      this.codigo = codigo || `DETENIDO_HTTP_${status}`;
    }
  }
  class ErrorDetencion extends Error {
    constructor(m, ayuda = []) { super(m); this.name = 'ErrorDetencion'; this.ayuda = ayuda; }
  }

  const esVacio = (v) => v === null || v === undefined || (typeof v === 'string' && v.trim() === '');
  const esObjetoPlano = (v) => v !== null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Date);
  const esPrimitivo = (v) => v === null || v === undefined || v instanceof Date ||
    ['string', 'number', 'boolean', 'bigint'].includes(typeof v);
  const limpio = (v) => (esVacio(v) ? '' : String(v).trim());

  // Caracteres especiales generados en código (evita escapes en el texto del script)
  const BOM = String.fromCharCode(0xFEFF);
  const RE_SEPARADORES = new RegExp('[' + String.fromCharCode(0x2028, 0x2029) + ']', 'g');
  const RE_NO_XML = new RegExp('[' + String.fromCharCode(0xFFFE, 0xFFFF) + ']', 'g');
  const sinSaltos = (s) => String(s).replace(/\r\n|\r|\n|\t/g, ' ').replace(RE_SEPARADORES, ' ');

  /** Convierte cualquier valor a texto sin producir "null"/"undefined". */
  function texto(v) {
    if (v === null || v === undefined) return '';
    if (v instanceof Date) return isNaN(v.getTime()) ? '' : v.toISOString();
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
    if (typeof v === 'object') { try { return JSON.stringify(v); } catch (_) { return ''; } }
    return String(v);
  }

  /** Lee una ruta "a.b.c" de forma segura. */
  function obtener(obj, ruta) {
    let actual = obj;
    for (const parte of ruta.split('.')) {
      if (actual === null || actual === undefined || typeof actual !== 'object') return undefined;
      actual = actual[parte];
    }
    return actual;
  }

  /** Devuelve el primer valor primitivo no vacío. */
  function primero(...valores) {
    for (const v of valores) if (!esVacio(v) && esPrimitivo(v)) return v;
    return '';
  }

  /**
   * Busca, dentro de uno o varios objetos (solo primer nivel), la primera propiedad
   * cuyo NOMBRE coincida con alguna expresión y cuyo valor sea primitivo y no vacío.
   * No inventa datos: solo lee lo que existe.
   */
  function buscarClave(nodos, expresiones) {
    const lista = (Array.isArray(nodos) ? nodos : [nodos]).filter(esObjetoPlano);
    for (const re of expresiones) {
      for (const nodo of lista) {
        for (const k of Object.keys(nodo)) {
          const v = nodo[k];
          if (re.test(k) && esPrimitivo(v) && !esVacio(v)) return v;
        }
      }
    }
    return '';
  }

  /** Busca en profundidad la primera propiedad con un nombre exacto. */
  function buscarProfundo(obj, nombre, profundidad = 0) {
    if (profundidad > 8 || obj === null || typeof obj !== 'object') return undefined;
    if (!Array.isArray(obj) && Object.prototype.hasOwnProperty.call(obj, nombre)) return obj[nombre];
    for (const v of Object.values(obj)) {
      if (v && typeof v === 'object') {
        const r = buscarProfundo(v, nombre, profundidad + 1);
        if (r !== undefined) return r;
      }
    }
    return undefined;
  }

  const dos = (n) => String(n).padStart(2, '0');
  function marcaTiempo(d = new Date()) {
    return `${d.getFullYear()}${dos(d.getMonth() + 1)}${dos(d.getDate())}_${dos(d.getHours())}${dos(d.getMinutes())}${dos(d.getSeconds())}`;
  }
  function fechaHoraLocal(d = new Date()) {
    return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())} ${dos(d.getHours())}:${dos(d.getMinutes())}:${dos(d.getSeconds())}`;
  }
  function hoyISO() {
    const d = new Date();
    return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
  }
  function duracion(ms) {
    if (!Number.isFinite(ms) || ms < 0) return '--:--:--';
    const s = Math.round(ms / 1000);
    return `${dos(Math.floor(s / 3600))}:${dos(Math.floor((s % 3600) / 60))}:${dos(s % 60)}`;
  }
  const horaDe = (ms) => fechaHoraLocal(new Date(ms)).slice(11);

  // Fechas AAAA-MM-DD (se calculan en UTC para evitar saltos por horario)
  const RE_FECHA = /^\d{4}-\d{2}-\d{2}$/;
  const DIA_MS = 86400000;
  function parsearFecha(s) {
    if (typeof s !== 'string' || !RE_FECHA.test(s)) return null;
    const [y, m, d] = s.split('-').map(Number);
    const f = new Date(Date.UTC(y, m - 1, d));
    if (f.getUTCFullYear() !== y || f.getUTCMonth() !== m - 1 || f.getUTCDate() !== d) return null;
    return f;
  }
  const isoDe = (f) => f.toISOString().slice(0, 10);
  const sumarDias = (iso, n) => isoDe(new Date(parsearFecha(iso).getTime() + n * DIA_MS));
  const diasEntre = (a, b) => Math.round((parsearFecha(b) - parsearFecha(a)) / DIA_MS) + 1; // ambos incluidos
  const dmy = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '');

  /** Fechas relativas de la lista del tablero: «hoy», «ayer» o «hoy-N». */
  function resolverFecha(valor) {
    const v = limpio(valor).toLowerCase();
    if (v === 'hoy') return hoyISO();
    if (v === 'ayer') return sumarDias(hoyISO(), -1);
    const m = /^hoy\s*-\s*(\d{1,4})$/.exec(v);
    if (m) return sumarDias(hoyISO(), -Number(m[1]));
    return limpio(valor);
  }

  /** Tipos de guía en el orden de SUNAT (09, 31, G9); sin tipos válidos, los tres. */
  function normalizarTipos(v) {
    const lista = Array.isArray(v) ? v : String(v || '').split(/[\s,;]+/);
    const t = new Set(lista.map((x) => limpio(x).toUpperCase()).filter((x) => TIPOS_GRE[x]));
    const r = ORDEN_TIPOS.filter((k) => t.has(k));
    return r.length ? r : ORDEN_TIPOS.slice();
  }

  /** Valida un RUC peruano (prefijo y dígito verificador). */
  function rucValido(ruc) {
    if (!/^(10|15|16|17|20)\d{9}$/.test(ruc)) return false;
    const pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
    const suma = pesos.reduce((s, p, i) => s + p * Number(ruc[i]), 0);
    let dv = 11 - (suma % 11);
    if (dv === 10) dv = 0;
    else if (dv === 11) dv = 1;
    return dv === Number(ruc[10]);
  }

  /** Extrae los RUC de un texto libre (líneas, comas, espacios…). */
  function extraerRucs(textoLibre) {
    const validos = [], invalidos = [], vistos = new Set();
    for (const t of String(textoLibre || '').split(/[^0-9]+/)) {
      if (!t || vistos.has(t)) continue;
      vistos.add(t);
      if (t.length === 11 && rucValido(t)) validos.push(t);
      else invalidos.push(t);
    }
    return { validos, invalidos };
  }

  /** Número de comprobante con 8 dígitos solo para mostrar. */
  function numero8(num) {
    const s = texto(num).trim();
    return /^\d+$/.test(s) ? s.padStart(8, '0') : s;
  }
  function guiaLegible(serie, num) {
    const s = texto(serie).trim();
    const n = numero8(num);
    return s || n ? `${s}-${n}` : '';
  }
  function claveGuia(ruc, cod, serie, num) {
    return [ruc, cod, serie, num].map((v) => texto(v).trim()).join('-');
  }
  function claveDesdeDetalle(det) {
    if (!esObjetoPlano(det)) return '';
    const partes = [det.numRuc, det.codCpe, det.numSerie, det.numCpe];
    if (partes.some(esVacio)) return '';
    return claveGuia(...partes);
  }

  function crearAbortError() {
    try { return new DOMException('Proceso detenido por el usuario', 'AbortError'); }
    catch (_) { const e = new Error('Proceso detenido por el usuario'); e.name = 'AbortError'; return e; }
  }
  const esAbort = (e) => !!e && e.name === 'AbortError';

  /** Espera cancelable. */
  function dormir(ms, signal) {
    return new Promise((resolve, reject) => {
      if (signal && signal.aborted) { reject(crearAbortError()); return; }
      const alAbortar = () => { clearTimeout(t); reject(crearAbortError()); };
      const t = setTimeout(() => {
        if (signal) signal.removeEventListener('abort', alAbortar);
        resolve();
      }, Math.max(0, ms));
      if (signal) signal.addEventListener('abort', alAbortar, { once: true });
    });
  }

  /** Mientras esté en pausa, espera (cancelable). */
  async function esperarSiPausado(signal) {
    let avisado = false;
    while (estado.pausado) {
      if (!avisado) { log('En pausa. Pulse «Continuar» para seguir.', 'warn'); avisado = true; actualizarUI(); }
      await dormir(300, signal);
    }
  }

  function pausaAleatoria(cfg) {
    const min = cfg.pausaMinMs, max = cfg.pausaMaxMs;
    return min + Math.floor(Math.random() * (max - min + 1));
  }

  /** Pausa entre solicitudes (la primera de la ejecución no espera). */
  async function esperarTurno(ctx) {
    if (ctx.solicitudes > 0) await dormir(pausaAleatoria(ctx.cfg), ctx.signal);
    ctx.solicitudes++;
  }

  /* ---------------------------------------------------------------
   * 4. Mensajes (consola + panel). Sin datos personales.
   *    Nivel «debug»: solo en la consola (detalles técnicos).
   * ------------------------------------------------------------- */
  function log(mensaje, nivel = 'info') {
    const fn = { info: console.log, ok: console.log, warn: console.warn, error: console.error, debug: console.log }[nivel] || console.log;
    fn.call(console, '%c[GRE]', 'color:#0a7d55;font-weight:bold', mensaje);
    if (nivel === 'debug' || !ui || !ui.log) return;
    const linea = h('div', { class: 'l-' + nivel, text: `[${fechaHoraLocal().slice(11)}] ${mensaje}` });
    ui.log.append(linea);
    while (ui.log.childElementCount > 300) ui.log.firstChild.remove();
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  function registrarError({ guia = '', clave = '', url = '', estadoHttp = '', mensaje = '', intento = '', accion = '' }) {
    estado.errores.push({
      guia, clave, url, estadoHttp: texto(estadoHttp), mensaje: texto(mensaje),
      intento: texto(intento), fechaHora: fechaHoraLocal(), accion
    });
  }

  /* ---------------------------------------------------------------
   * 5. Configuración: lista del tablero o búsqueda manual
   * ------------------------------------------------------------- */
  function entero(valor, nombre, min, max, predeterminado) {
    if (esVacio(valor)) return predeterminado;
    const n = Number(valor);
    if (!Number.isInteger(n) || n < min || n > max) {
      throw new ErrorValidacion(`«${nombre}» debe ser un número entero entre ${min} y ${max}.`);
    }
    return n;
  }
  const siNo = (v, def) => (v === undefined ? def : v === true || v === 'true');

  /** Revisa, ordena y une los periodos de la búsqueda manual. */
  function normalizarPeriodos(lista) {
    const hoy = hoyISO();
    const ok = [];
    lista.forEach((p, i) => {
      const desde = resolverFecha(p && (p.desde ?? p.fechaInicio));
      let hasta = resolverFecha(p && (p.hasta ?? p.fechaFin));
      if (!desde && !hasta) return; // fila vacía
      const n = lista.length > 1 ? ` ${i + 1}` : '';
      if (!parsearFecha(desde) || !parsearFecha(hasta)) throw new ErrorValidacion(`Periodo${n}: indique las dos fechas (desde y hasta).`);
      if (desde > hasta) throw new ErrorValidacion(`Periodo${n}: la fecha «desde» es posterior a «hasta».`);
      if (desde > hoy) throw new ErrorValidacion(`Periodo${n}: la fecha «desde» todavía no llega.`);
      if (hasta > hoy) hasta = hoy;
      ok.push({ desde, hasta });
    });
    if (!ok.length) throw new ErrorValidacion('Indique al menos un periodo (desde y hasta).');
    ok.sort((a, b) => a.desde.localeCompare(b.desde));
    const unidos = [ok[0]];
    for (const p of ok.slice(1)) {
      const u = unidos[unidos.length - 1];
      if (p.desde <= sumarDias(u.hasta, 1)) { if (p.hasta > u.hasta) u.hasta = p.hasta; }
      else unidos.push({ ...p });
    }
    return unidos;
  }

  /**
   * Revisa la lista que llega del tablero (formato GRE_PEDIDO). Cada búsqueda es:
   *   - de listado: { etiqueta, caso, grupo, rucEmisor?, rucReceptor?, tipos, desde, hasta }
   *   - directa (por número): { etiqueta, caso, directa: { rucEmisor, codCpe, serie, numero, posterior? } }
   *     «posterior»: el número es mayor que la última guía conocida de la serie (puede no existir todavía).
   * Las fechas pueden ser relativas: «hoy», «ayer» u «hoy-N».
   */
  function validarPedido(entrada) {
    let p = entrada;
    if (typeof p === 'string') {
      const t = p.trim();
      const i = t.indexOf('{');
      try { p = JSON.parse(i >= 0 ? t.slice(i) : t); } catch (_) { throw new ErrorValidacion('No reconozco esa lista: cópiela de nuevo desde el tablero.'); }
    }
    if (esObjetoPlano(p) && p.formato === 'GRE_EXTRACTOR_JSON') {
      throw new ErrorValidacion('Ese archivo es un resultado del extractor, no una lista del tablero. Para continuar una búsqueda anterior, cárguelo en «Más opciones».');
    }
    if (!esObjetoPlano(p) || p.tipo !== 'GRE_PEDIDO' || !Array.isArray(p.busquedas)) {
      throw new ErrorValidacion('No reconozco esa lista: debe copiarse desde el tablero («Lista del día» o «Buscar guías»).');
    }
    const hoy = hoyISO();
    const busquedas = [];
    let ignoradas = 0;
    p.busquedas.forEach((b, i) => {
      if (!esObjetoPlano(b)) { ignoradas++; return; }
      const etiqueta = limpio(b.etiqueta) || `Búsqueda ${i + 1}`;
      const caso = limpio(b.caso), grupo = limpio(b.grupo);
      if (esObjetoPlano(b.directa)) {
        const d = b.directa;
        const ruc = limpio(d.rucEmisor), cod = limpio(d.codCpe).toUpperCase() || '09';
        const serie = limpio(d.serie).toUpperCase(), numero = limpio(d.numero).replace(/^0+(?=\d)/, '');
        if (!rucValido(ruc) || !TIPOS_GRE[cod] || !/^[A-Z0-9]{4}$/.test(serie) || !/^\d{1,8}$/.test(numero)) { ignoradas++; return; }
        busquedas.push({ tipo: 'directa', etiqueta, caso, grupo, rucEmisor: ruc, codCpe: cod, serie, numero, posterior: d.posterior === true });
        return;
      }
      const rucE = limpio(b.rucEmisor), rucR = limpio(b.rucReceptor);
      if ((!rucE && !rucR) || (rucE && !rucValido(rucE)) || (rucR && !rucValido(rucR))) { ignoradas++; return; }
      const desde = resolverFecha(b.desde);
      let hasta = resolverFecha(b.hasta || b.desde);
      if (!parsearFecha(desde) || !parsearFecha(hasta) || desde > hasta || desde > hoy) { ignoradas++; return; }
      if (hasta > hoy) hasta = hoy;
      busquedas.push({ tipo: 'listado', etiqueta, caso, grupo, rucEmisor: rucE, rucReceptor: rucR, tipos: normalizarTipos(b.tipos), desde, hasta });
    });
    if (!busquedas.length) throw new ErrorValidacion('La lista no tiene búsquedas válidas.');
    const conocidas = Array.isArray(p.conocidas) ? p.conocidas.filter((x) => typeof x === 'string' && x) : [];
    return {
      id: limpio(p.id) || 'lista', titulo: limpio(p.titulo) || 'Lista del tablero', generado: limpio(p.generado),
      busquedas, conocidas, ignoradas
    };
  }

  /** Resumen en una línea de una lista del tablero ya revisada. */
  function textoResumenLista(p) {
    const listados = p.busquedas.filter((b) => b.tipo === 'listado');
    const directas = p.busquedas.filter((b) => b.tipo === 'directa');
    const rucs = new Set(listados.flatMap((b) => [b.rucEmisor, b.rucReceptor].filter(Boolean)));
    const desde = listados.map((b) => b.desde).sort()[0], hasta = listados.map((b) => b.hasta).sort().slice(-1)[0];
    let t = `«${p.titulo}»: ${listados.length} búsqueda(s) de ${rucs.size} RUC`;
    if (desde) t += desde === hasta ? `, del ${dmy(desde)}` : `, del ${dmy(desde)} al ${dmy(hasta)}`;
    if (directas.length) t += `; ${directas.length} guía(s) por consultar directo por su número`;
    t += '.';
    if (p.conocidas.length) t += ` ${p.conocidas.length} guía(s) ya están en el tablero: no se volverán a descargar.`;
    if (p.ignoradas) t += ` Se ignoran ${p.ignoradas} búsqueda(s) con datos no válidos.`;
    return t;
  }

  function normalizarConfig(op = {}) {
    if (!esObjetoPlano(op)) throw new ErrorValidacion('Las opciones deben ser un objeto.');
    const D = CONFIG_PREDETERMINADA;
    const cfg = {
      numSerie: limpio(op.numSerie ?? op.serie).toUpperCase(),
      numCpe: limpio(op.numCpe ?? op.numero),
      codEstado: limpio(op.codEstado),
      codSubEstado: limpio(op.codSubEstado),
      tipBusqueda: limpio(op.tipBusqueda) || D.tipBusqueda,
      perPage: entero(op.perPage ?? op.per_page, 'Registros por página', 1, 100, D.perPage),
      maxDiasBloque: entero(op.maxDiasBloque, 'Días máximos por consulta', 1, 366, D.maxDiasBloque),
      objetivoPorBusqueda: entero(op.objetivoPorBusqueda, 'Guías esperadas por consulta', 1, 100, D.objetivoPorBusqueda),
      pausaMinMs: D.pausaMinMs,
      pausaMaxMs: D.pausaMaxMs,
      maxReintentos: entero(op.maxReintentos, 'Reintentos', 0, 10, D.maxReintentos),
      timeoutMs: entero(op.timeoutMs, 'Tiempo máximo por solicitud', 5000, 300000, D.timeoutMs),
      maxErroresConsecutivos: entero(op.maxErroresConsecutivos, 'Errores seguidos permitidos', 1, 1000, D.maxErroresConsecutivos),
      maxNoExistenSerie: entero(op.maxNoExistenSerie, 'Números seguidos que no existen', 1, 1000, D.maxNoExistenSerie),
      esperaConexionMin: entero(op.esperaConexionMin, 'Minutos de espera de conexión', 1, 240, D.esperaConexionMin),
      descargarJSON: siNo(op.descargarJSON, D.descargarJSON),
      descargarExcel: siNo(op.descargarExcel, D.descargarExcel),
      // Búsqueda copiada de SUNAT: plantilla para que la consulta sea igual a la de la aplicación
      plantillaListado: urlsCapturadas.listado || ''
    };
    if (!esVacio(op.pausaMs)) {
      const p = entero(op.pausaMs, 'Pausa', 0, 60000, D.pausaMinMs);
      cfg.pausaMinMs = p; cfg.pausaMaxMs = p;
    } else {
      cfg.pausaMinMs = entero(op.pausaMinMs, 'Pausa mínima', 0, 60000, D.pausaMinMs);
      cfg.pausaMaxMs = entero(op.pausaMaxMs, 'Pausa máxima', 0, 60000, D.pausaMaxMs);
      if (cfg.pausaMinMs > cfg.pausaMaxMs) [cfg.pausaMinMs, cfg.pausaMaxMs] = [cfg.pausaMaxMs, cfg.pausaMinMs];
    }
    if (cfg.numCpe && !/^\d+$/.test(cfg.numCpe)) throw new ErrorValidacion('El número de guía debe tener solo dígitos.');

    if (op.pedido) {
      // Lista copiada del tablero
      const p = validarPedido(op.pedido);
      if (p.ignoradas) log(`Se ignoran ${p.ignoradas} búsqueda(s) de la lista con datos no válidos.`, 'warn');
      cfg.origen = 'tablero';
      cfg.busquedas = p.busquedas;
      cfg.conocidas = p.conocidas;
      cfg.pedidoInfo = { id: p.id, titulo: p.titulo, generado: p.generado, busquedas: p.busquedas.length, conocidas: p.conocidas.length };
    } else {
      // Búsqueda manual: RUC (lista o forma anterior), rol, tipos y periodos
      let rol = limpio(op.rol).toLowerCase();
      let fuente = op.rucs;
      if (esVacio(fuente) || (Array.isArray(fuente) && !fuente.length)) {
        const rr = limpio(op.rucReceptor ?? op.numRucReceptor), re = limpio(op.rucEmisor ?? op.numRucEmisor);
        if (rr) { fuente = rr; if (!rol) rol = 'receptor'; }
        else if (re) { fuente = re; if (!rol) rol = 'emisor'; }
      }
      const { validos, invalidos } = extraerRucs(Array.isArray(fuente) ? fuente.join('\n') : fuente);
      if (!validos.length) {
        throw new ErrorValidacion(invalidos.length
          ? `Ningún RUC es válido (${invalidos.join(', ')}). Revise los dígitos.`
          : 'Escriba al menos un RUC (11 dígitos), o pegue la lista del tablero.');
      }
      if (invalidos.length) log(`Se omiten ${invalidos.length} RUC no válido(s): ${invalidos.join(', ')}.`, 'warn');
      if (!['receptor', 'emisor', 'ambos'].includes(rol)) rol = D.rol;
      let periodos = Array.isArray(op.periodos) ? op.periodos : [];
      if (!periodos.length && (op.fechaInicio || op.fechaFin || op.fecEmisionIni || op.fecEmisionFin)) {
        periodos = [{ desde: op.fechaInicio ?? op.fecEmisionIni, hasta: op.fechaFin ?? op.fecEmisionFin }];
      }
      periodos = normalizarPeriodos(periodos);
      const tipos = normalizarTipos(op.tipos ?? op.codCpe);
      const roles = rol === 'ambos' ? ['emisor', 'receptor'] : [rol];
      const busquedas = [];
      for (const ruc of validos) {
        for (const r of roles) {
          for (const p of periodos) {
            busquedas.push({
              tipo: 'listado', etiqueta: `RUC ${ruc} como ${r}`, caso: '', grupo: 'manual',
              rucEmisor: r === 'emisor' ? ruc : '', rucReceptor: r === 'receptor' ? ruc : '', tipos, desde: p.desde, hasta: p.hasta
            });
          }
        }
      }
      Object.assign(cfg, { origen: 'manual', rucs: validos, rol, periodos, tipos, busquedas, conocidas: [] });
      cfg.pedidoInfo = { id: 'manual', titulo: 'Búsqueda manual', generado: fechaHoraLocal(), busquedas: busquedas.length, conocidas: 0 };
    }
    cfg.diasTotales = cfg.busquedas.filter((b) => b.tipo === 'listado').reduce((s, b) => s + diasEntre(b.desde, b.hasta), 0);
    return Object.freeze(cfg);
  }

  /** Quita lo que suele colarse al copiar: comillas, comas, punto y coma y la palabra «Bearer». */
  function limpiarToken(valor) {
    const bordes = /^["'`]+|["'`,;]+$/g;
    return String(valor || '').trim().replace(bordes, '').trim()
      .replace(/^bearer\s+/i, '').trim().replace(bordes, '').trim();
  }

  /**
   * Token para empezar: el escrito a mano en «Más opciones» o el tomado con «Conectar».
   * Si no hay ninguno, se esperará a que abra una guía con «Ver» en SUNAT.
   */
  function tokenInicial(op) {
    const manual = op && typeof op.token === 'string' ? limpiarToken(op.token) : '';
    if (manual) {
      if (/…|\.\.\./.test(manual)) {
        throw new ErrorValidacion('El token está cortado (contiene «…»). Mejor use «Conectar» y abra una guía con «Ver».');
      }
      if (/\s/.test(manual)) throw new ErrorValidacion('El token contiene espacios o saltos de línea. Cópielo nuevamente.');
      return { token: manual, origen: 'escrito a mano', cabeceras: {} };
    }
    if (tokenCapturado) {
      const r = { token: tokenCapturado, origen: 'de la pantalla de SUNAT', cabeceras: cabecerasCapturadas ? { ...cabecerasCapturadas } : {} };
      tokenCapturado = null;
      cabecerasCapturadas = null;
      return r;
    }
    return null;
  }

  /**
   * Lee, solo localmente, la hora de vencimiento (y de emisión) de un token JWT.
   * No registra ni exporta ningún otro dato del token.
   */
  function analizarToken(token) {
    const partes = String(token || '').split('.');
    if (partes.length !== 3) return { tipo: 'opaco', exp: null, iat: null };
    try {
      if (!partes.every((p) => /^[A-Za-z0-9_-]*$/.test(p))) throw new Error('caracteres no válidos');
      let b64 = partes[1].replace(/-/g, '+').replace(/_/g, '/');
      b64 += '='.repeat((4 - (b64.length % 4)) % 4);
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const carga = JSON.parse(new TextDecoder().decode(bytes));
      const exp = Number(carga && carga.exp);
      const iat = Number(carga && carga.iat);
      return {
        tipo: 'jwt',
        exp: Number.isFinite(exp) && exp > 0 ? exp * 1000 : null,
        iat: Number.isFinite(iat) && iat > 0 ? iat * 1000 : null,
        sinFirma: !partes[2]
      };
    } catch (_) {
      return { tipo: 'ilegible', exp: null, iat: null };
    }
  }

  /** Informa la vigencia de la conexión. Devuelve el vencimiento (ms) o null si no se conoce. */
  function describirToken(token, origen) {
    const info = analizarToken(token);
    if (info.tipo === 'ilegible' || info.sinFirma) {
      log('Aviso: la conexión no se pudo leer completa; si falla, pulse «Conectar» y abra una guía con «Ver».', 'warn');
      return null;
    }
    if (!info.exp) { log(`Conexión ${origen} (sin hora de vencimiento).`, 'debug'); return null; }
    if (info.exp <= Date.now()) { log(`La conexión ${origen} ya venció (a las ${horaDe(info.exp)}).`, 'warn'); return info.exp; }
    log(`Conectado con SUNAT (${origen}); la conexión vence a las ${horaDe(info.exp)}.`, 'ok');
    return info.exp;
  }

  const textoVence = (token) => {
    const info = analizarToken(token);
    return info.exp ? ` (vence a las ${horaDe(info.exp)})` : '';
  };

  /** Parámetros que sí pueden exportarse (nunca el token). */
  function parametrosExportables(cfg) {
    if (!cfg) return {};
    const claves = ['origen', 'rucs', 'rol', 'tipos', 'periodos', 'numSerie', 'numCpe', 'codEstado', 'codSubEstado',
      'tipBusqueda', 'perPage', 'maxDiasBloque', 'pausaMinMs', 'pausaMaxMs', 'maxReintentos'];
    const r = {};
    for (const k of claves) if (cfg[k] !== undefined) r[k] = Array.isArray(cfg[k]) ? JSON.parse(JSON.stringify(cfg[k])) : cfg[k];
    return r;
  }

  /* ---------------------------------------------------------------
   * 6. Solicitudes a SUNAT: reintentos, mensajes y conexión
   * ------------------------------------------------------------- */
  function calcularEspera(intento, retryAfter) {
    if (retryAfter) {
      const seg = Number(retryAfter);
      if (Number.isFinite(seg) && seg >= 0) return Math.min(seg * 1000, 120000);
      const fecha = Date.parse(retryAfter);
      if (Number.isFinite(fecha)) return Math.min(Math.max(fecha - Date.now(), 1000), 120000);
    }
    return 1000 * Math.pow(2, intento - 1) + Math.floor(Math.random() * 250); // 1 s, 2 s, 4 s...
  }

  /**
   * Lee el mensaje de error de SUNAT. Su formato es { cod, msg, errors: [{ cod, msg }] }:
   * el detalle útil y su código (por ejemplo 2021: más de 100 registros) están en «errors».
   */
  function erroresDeCuerpo(cuerpo) {
    const vacio = { principal: '', detalles: [], codigos: [], texto: '' };
    if (!cuerpo) return vacio;
    try {
      const j = JSON.parse(cuerpo);
      if (!esObjetoPlano(j)) return vacio;
      const principal = texto(primero(j.msg, j.message, j.mensaje, j.error_description, j.error)).slice(0, 200);
      const lista = [j.errors, j.errores, j.details, j.detalles].find(Array.isArray) || [];
      const codigos = [], detalles = [];
      for (const e of lista.slice(0, 5)) {
        if (esPrimitivo(e)) { if (!esVacio(e)) detalles.push(texto(e).slice(0, 200)); continue; }
        if (!esObjetoPlano(e)) continue;
        const m = texto(primero(e.msg, e.message, e.mensaje, e.desc, e.descripcion, e.detail));
        const c = texto(primero(e.cod, e.code, e.codigo));
        if (c) codigos.push(c);
        if (m) detalles.push((c ? `${m} (código ${c})` : m).slice(0, 200));
      }
      return { principal, detalles, codigos, texto: detalles.length ? detalles.join('; ') : principal };
    } catch (_) { return vacio; }
  }

  const tokenPorVencer = (ctx) => !!ctx.tokenExp && Date.now() >= ctx.tokenExp - MARGEN_VENCIMIENTO_MS;

  /** Si la pantalla de SUNAT generó una conexión más nueva durante la búsqueda, se usa sin detenerse. */
  function usarTokenMasNuevo(ctx) {
    if (!tokenCapturado || tokenCapturado === ctx.token) return;
    const nuevo = analizarToken(tokenCapturado);
    const vigente = !nuevo.exp || nuevo.exp > Date.now() + MARGEN_VENCIMIENTO_MS;
    const masNuevo = !ctx.tokenExp || !nuevo.exp || nuevo.exp > ctx.tokenExp;
    if (vigente && masNuevo) {
      ctx.token = tokenCapturado;
      ctx.tokenExp = nuevo.exp || null;
      if (cabecerasCapturadas) ctx.cabecerasExtra = { ...cabecerasCapturadas };
      estado.tokenExp = ctx.tokenExp;
      log(`Conexión con SUNAT renovada${nuevo.exp ? ` (vence a las ${horaDe(nuevo.exp)})` : ''}.`, 'ok');
    }
    tokenCapturado = null;
    cabecerasCapturadas = null;
  }

  /**
   * Detiene las consultas hasta tener una conexión nueva: se toma sola cuando el usuario
   * abre cualquier guía con «Ver» (o pulsa «Buscar») en la pantalla de SUNAT.
   */
  async function renovarConexion(ctx, motivo) {
    const textos = {
      inicial: 'Falta conectar con SUNAT.',
      vencida: 'La conexión con SUNAT venció.',
      rechazada: 'SUNAT no aceptó la conexión (HTTP 401).'
    };
    const previa = ctx.token;
    estado.esperandoConexion = true;
    iniciarCaptura('fondo');
    log(`${textos[motivo] || textos.vencida} ➜ En la pantalla de SUNAT abra cualquier guía con «Ver» (o pulse «Buscar»). Luego todo continúa solo.`, 'warn');
    if (ui && ui.compactar) ui.compactar(true);
    actualizarUI();
    const limite = Date.now() + ctx.cfg.esperaConexionMin * 60000;
    try {
      while (true) {
        if (ctx.signal.aborted) throw crearAbortError();
        if (tokenCapturado && tokenCapturado !== previa) {
          const info = analizarToken(tokenCapturado);
          if (!info.exp || info.exp > Date.now() + MARGEN_VENCIMIENTO_MS) {
            ctx.token = tokenCapturado;
            ctx.tokenExp = info.exp || null;
            ctx.cabecerasExtra = cabecerasCapturadas ? { ...cabecerasCapturadas } : (ctx.cabecerasExtra || {});
            tokenCapturado = null;
            cabecerasCapturadas = null;
            estado.tokenExp = ctx.tokenExp;
            log(`Conectado con SUNAT${info.exp ? ` (la conexión vence a las ${horaDe(info.exp)})` : ''}. Continuando…`, 'ok');
            if (ui && ui.compactar) ui.compactar(false);
            return;
          }
          tokenCapturado = null; // vencido: se descarta
        }
        if (Date.now() > limite) {
          throw new ErrorAutenticacion(0, '', `No se renovó la conexión en ${ctx.cfg.esperaConexionMin} minutos.`, 'DETENIDO_SIN_CONEXION');
        }
        await dormir(400, ctx.signal);
      }
    } finally {
      estado.esperandoConexion = false;
      actualizarUI();
    }
  }

  /**
   * GET a SUNAT con: credentials "omit", mode "cors", tiempo máximo, cancelación,
   * reintentos para 429/5xx/red, renovación de la conexión (401 o vencida),
   * parada ante 403 y registro de errores.
   * Devuelve { ok, status, data, mensaje, detalles, codigos, intentos }.
   */
  async function pedirJSON(url, ctx, etiqueta, clave = '', opciones = {}) {
    const { signal, cfg } = ctx;
    const anotarRechazos = opciones.anotarRechazos !== false;
    const totalIntentos = cfg.maxReintentos + 1;
    let ultimo = { ok: false, status: 0, mensaje: 'Sin respuesta', detalles: [], codigos: [], intentos: 0 };
    let renovaciones = 0;

    const fallar = (status, mensaje, intento, puedeReintentar, retryAfter, det = null) => {
      ultimo = { ok: false, status, mensaje, detalles: det ? det.detalles : [], codigos: det ? det.codigos : [], intentos: intento };
      if (puedeReintentar && intento < totalIntentos) {
        const espera = calcularEspera(intento, retryAfter);
        registrarError({ guia: etiqueta, clave, url, estadoHttp: status, mensaje, intento, accion: `REINTENTO en ${(espera / 1000).toFixed(1)} s` });
        log(`${etiqueta}: ${mensaje}. Reintento ${intento}/${totalIntentos - 1} en ${(espera / 1000).toFixed(1)} s.`, 'debug');
        return espera;
      }
      const rechazo = status === 400 || status === 422;
      if (!rechazo || anotarRechazos) {
        registrarError({
          guia: etiqueta, clave, url, estadoHttp: status, mensaje, intento,
          accion: status === 404 ? 'OMITIDA (no encontrada)' : rechazo ? 'RECHAZADA POR SUNAT' : 'OMITIDA (sin más reintentos)'
        });
      }
      return null;
    };

    for (let intento = 1; intento <= totalIntentos; intento++) {
      await esperarSiPausado(signal);
      if (signal.aborted) throw crearAbortError();
      usarTokenMasNuevo(ctx);
      if (tokenPorVencer(ctx)) await renovarConexion(ctx, 'vencida');

      // Controlador por solicitud: se aborta por cancelación general o por tiempo máximo.
      const ctrl = new AbortController();
      let porTimeout = false;
      const alCancelar = () => ctrl.abort();
      signal.addEventListener('abort', alCancelar, { once: true });
      const temporizador = setTimeout(() => { porTimeout = true; ctrl.abort(); }, cfg.timeoutMs);

      let resp = null, cuerpo = '';
      try {
        // Misma forma que la solicitud de la aplicación (y sus mismas cabeceras, si se tomaron).
        resp = await fetchPropio.call(window, url, {
          method: 'GET',
          mode: 'cors',
          credentials: 'omit',
          headers: {
            accept: 'application/json, text/plain, */*',
            ...(ctx.cabecerasExtra || {}),
            authorization: 'Bearer ' + ctx.token
          },
          signal: ctrl.signal
        });
        cuerpo = await resp.text();
      } catch (e) {
        clearTimeout(temporizador);
        signal.removeEventListener('abort', alCancelar);
        if (signal.aborted) throw crearAbortError();
        // Una conexión vencida suele verse como «Failed to fetch»: se pide una nueva y se repite.
        if (tokenPorVencer(ctx)) { intento--; continue; }
        const msg = porTimeout
          ? `Tiempo de espera agotado (${cfg.timeoutMs} ms)`
          : `SUNAT no respondió o el navegador bloqueó la respuesta (${(e && e.message) || e})`;
        const espera = fallar(0, msg, intento, true);
        if (espera !== null) { await dormir(espera, signal); continue; }
        return ultimo;
      }
      clearTimeout(temporizador);
      signal.removeEventListener('abort', alCancelar);
      const status = resp.status;

      // 401: la conexión no sirve → se espera una nueva y se repite (máximo 2 veces)
      if (status === 401) {
        if (renovaciones < 2) {
          renovaciones++;
          registrarError({ guia: etiqueta, clave, url, estadoHttp: 401, mensaje: 'SUNAT no aceptó la conexión', intento, accion: 'ESPERA DE CONEXIÓN NUEVA' });
          await renovarConexion(ctx, 'rechazada');
          intento--;
          continue;
        }
        registrarError({ guia: etiqueta, clave, url, estadoHttp: 401, mensaje: 'SUNAT no aceptó la conexión', intento, accion: 'PROCESO DETENIDO' });
        throw new ErrorAutenticacion(401, url);
      }
      // 403: sin permiso → se detiene todo
      if (status === 403) {
        registrarError({ guia: etiqueta, clave, url, estadoHttp: 403, mensaje: 'Sin permiso', intento, accion: 'PROCESO DETENIDO' });
        throw new ErrorAutenticacion(403, url, 'SUNAT indica que la cuenta no tiene permiso para esta consulta (HTTP 403).');
      }
      // Consulta por número: si SUNAT responde que la guía no existe, es una respuesta final, no una falla
      if (opciones.directa && !resp.ok) {
        const det = erroresDeCuerpo(cuerpo);
        const textoNE = det.texto || det.principal || (/^\s*</.test(cuerpo) ? '' : cuerpo.slice(0, 300));
        if (status === 404 || NO_EXISTE.test(`${det.texto} ${det.principal} ${textoNE}`)) {
          ultimo = { ok: false, status, mensaje: textoNE || `HTTP ${status}`, detalles: det.detalles, codigos: det.codigos, intentos: intento, noExiste: true };
          return ultimo;
        }
      }
      // 404: no encontrada → se anota y se sigue
      if (status === 404) {
        fallar(404, 'Guía no encontrada (HTTP 404)', intento, false);
        return ultimo;
      }
      // 429 y 5xx temporales → se reintenta
      if (ESTADOS_REINTENTABLES.has(status)) {
        const det = erroresDeCuerpo(cuerpo);
        const espera = fallar(status, `SUNAT respondió HTTP ${status} (temporal)${det.texto ? ' – ' + det.texto : ''}`, intento, true, resp.headers.get('retry-after'), det);
        if (espera !== null) { await dormir(espera, signal); continue; }
        return ultimo;
      }
      // Otros códigos (400, 422…): SUNAT rechazó la solicitud → no se reintenta
      if (!resp.ok) {
        const det = erroresDeCuerpo(cuerpo);
        fallar(status, det.texto ? `HTTP ${status}: ${det.texto}` : `HTTP ${status} ${resp.statusText || ''}`.trim(), intento, false, null, det);
        return ultimo;
      }
      // 2xx: validar contenido
      if (!cuerpo || !cuerpo.trim()) {
        const espera = fallar(status, 'Respuesta vacía', intento, true);
        if (espera !== null) { await dormir(espera, signal); continue; }
        return ultimo;
      }
      let data;
      try {
        data = JSON.parse(cuerpo);
      } catch (e) {
        const tipo = resp.headers.get('content-type') || '';
        const msg = (/html/i.test(tipo) || /^\s*</.test(cuerpo))
          ? 'Se recibió una página en lugar de datos (posible sesión vencida)'
          : `Respuesta no válida (${e.message})`;
        fallar(status, msg, intento, false);
        return ultimo;
      }
      return { ok: true, status, data, mensaje: '', detalles: [], codigos: [], intentos: intento };
    }
    return ultimo;
  }

  /* ---------------------------------------------------------------
   * 7. Búsqueda de guías (listado) con división automática
   *    Una «consulta» es { rucEmisor, rucReceptor, tipos, desde, hasta, bloques }.
   * ------------------------------------------------------------- */
  function construirUrlListado(cfg, c, page) {
    // Si hay una búsqueda copiada de SUNAT, se usa como plantilla: conserva el orden, el formato
    // de las fechas y cualquier parámetro adicional que envíe la aplicación. Solo cambian los valores.
    let p = new URLSearchParams();
    if (cfg.plantillaListado) {
      try { p = new URL(cfg.plantillaListado).searchParams; } catch (_) { p = new URLSearchParams(); }
    }
    const fechaDMY = /^\d{2}\/\d{2}\/\d{4}$/.test(p.get('fecEmisionIni') || '');
    const fecha = (iso) => (fechaDMY ? dmy(iso) : iso);
    p.set('numRucEmisor', c.rucEmisor || '');
    p.set('numRucReceptor', c.rucReceptor || '');
    p.set('codCpe', c.tipos.join(','));
    p.set('numSerie', cfg.numSerie);
    p.set('numCpe', cfg.numCpe);
    p.set('fecEmisionIni', fecha(c.desde));
    p.set('fecEmisionFin', fecha(c.hasta));
    p.set('codEstado', cfg.codEstado);
    p.set('codSubEstado', cfg.codSubEstado);
    p.set('rangoHoras', c.bloques && c.bloques.length ? c.bloques.join(',') : '');
    p.set('page', String(page));
    p.set('per_page', String(cfg.perPage));
    p.set('tipBusqueda', cfg.tipBusqueda);
    return `${API_LISTADO}?${p.toString()}`;
  }

  /** Quién se busca, en palabras: «RUC X (emisor)», «RUC Y (receptor)» o ambos. */
  function quien(c) {
    if (c.rucEmisor && c.rucReceptor) return `emisor ${c.rucEmisor} → receptor ${c.rucReceptor}`;
    return c.rucEmisor ? `RUC ${c.rucEmisor} (emisor)` : `RUC ${c.rucReceptor} (receptor)`;
  }
  function etiquetaConsulta(c) {
    let t = `${quien(c)} · ${dmy(c.desde)}${c.hasta !== c.desde ? ' al ' + dmy(c.hasta) : ''}`;
    if (c.bloques && c.bloques.length) t += ` · ${c.bloques.map((b) => TEXTO_BLOQUE[b]).join(', ')}`;
    if (c.tipos.length < 3) t += ` · ${c.tipos.map((x) => TIPOS_GRE[x]).join(', ')}`;
    return t;
  }
  const consultaDe = (tarea, desde, hasta) => ({ rucEmisor: tarea.rucEmisor, rucReceptor: tarea.rucReceptor, tipos: tarea.tipos, desde, hasta, bloques: null });

  /** ¿El rechazo de SUNAT parece deberse a que la búsqueda trae demasiadas guías? */
  function pareceExceso(mensaje) {
    const m = String(mensaje || '').replace(/\(c[oó]digo [^)]*\)/gi, '').replace(/HTTP \d{3}:?/gi, '');
    if (/\b100\b|exced|supera|m[aá]xim|acot|l[ií]mite|demasiad|refin|reduzc|filtr|mayor (a|que)|cantidad de (registros|resultados|comprobantes|gu[ií]as)/i.test(m)) return true;
    return (m.match(/\b\d{3,6}\b/g) || []).some((n) => Number(n) > 100);
  }
  const esExceso = (r) => (r.codigos || []).includes(COD_EXCESO) || pareceExceso(r.mensaje) || estado.mensajesExceso.has(r.mensaje);
  const esRechazo = (r) => r.status === 400 || r.status === 422;

  /** Una consulta, con todas sus páginas. */
  async function consultarBloque(ctx, c) {
    const { cfg } = ctx;
    const etiqueta = etiquetaConsulta(c);
    const items = [];
    let page = 1, total = null, perPageApi = cfg.perPage, totalPaginas = 1, incompleta = false, urlPrimera = '';
    while (true) {
      const url = construirUrlListado(cfg, c, page);
      if (page === 1) urlPrimera = url;
      await esperarTurno(ctx);
      const r = await pedirJSON(url, ctx, page > 1 ? `${etiqueta} (página ${page})` : etiqueta, '', { anotarRechazos: false });
      let recibidos = 0;
      if (!r.ok || !esObjetoPlano(r.data)) {
        if (page === 1) {
          return {
            ok: false, status: r.status, mensaje: r.ok ? 'La respuesta de SUNAT no tiene el formato esperado' : r.mensaje,
            detalles: r.detalles || [], codigos: r.codigos || [], url
          };
        }
        incompleta = true;
      } else {
        const pag = esObjetoPlano(r.data.paginacion) ? r.data.paginacion : {};
        const lote = Array.isArray(r.data.items) ? r.data.items : [];
        recibidos = lote.length;
        if (page === 1) {
          const t = Number(pag.totalRegistros);
          total = Number.isFinite(t) && !esVacio(pag.totalRegistros) ? t : null;
          const pp = Number(pag.per_page);
          perPageApi = Number.isInteger(pp) && pp > 0 ? pp : cfg.perPage;
          totalPaginas = total !== null ? Math.min(50, Math.max(1, Math.ceil(total / perPageApi))) : 1;
        }
        items.push(...lote);
      }
      const seguir = total !== null ? page < totalPaginas : (recibidos >= perPageApi && page < 50);
      if (!seguir) break;
      page++;
    }
    return { ok: true, status: 200, items, total, incompleta: incompleta || (total !== null && items.length < total), url: urlPrimera };
  }

  const TEXTO_TIPO_BUSQUEDA = {
    ok: 'Correcta',
    dividida: 'Más de 100 guías: se dividió',
    bloque_exceso: 'Tramo de 4 horas con más de 100 guías',
    dia_rechazado: 'Rechazada por SUNAT',
    ruc_rechazado: 'RUC rechazado por SUNAT',
    fallida: 'Sin respuesta de SUNAT'
  };

  function registrarBusqueda(tarea, c, r, tipo) {
    estado.busquedas.push({
      etiqueta: tarea.etiqueta, caso: tarea.caso || '', grupo: tarea.grupo || '',
      rucEmisor: c.rucEmisor || '', rucReceptor: c.rucReceptor || '', tipos: c.tipos.join(','),
      desde: c.desde, hasta: c.hasta, bloques: c.bloques ? c.bloques.join(',') : '', tipo,
      total: r.ok && r.total !== null && r.total !== undefined ? r.total : '',
      recibidos: r.ok ? r.items.length : '',
      estadoHttp: r.ok ? 200 : r.status, mensaje: r.ok ? '' : r.mensaje, incompleta: !!r.incompleta
    });
  }

  function agregarEncontradas(tarea, items, encontradas) {
    for (const it of items) {
      if (!esObjetoPlano(it)) continue;
      const clave = claveGuia(it.rucEmisor, it.codCpe, it.numSerie, it.numCpe);
      if (tarea.vistas.has(clave)) { estado.duplicados.push(clave); continue; }
      tarea.vistas.add(clave);
      tarea.encontradas++;
      if (!encontradas.has(clave)) encontradas.set(clave, it);
      if (!estado.origenes.has(clave)) estado.origenes.set(clave, []);
      const lista = estado.origenes.get(clave);
      if (!lista.some((o) => o.etiqueta === tarea.etiqueta)) {
        lista.push({ etiqueta: tarea.etiqueta, caso: tarea.caso || '', grupo: tarea.grupo || '', ...(tarea.tipo === 'directa' ? { citada: true } : {}) });
      }
    }
    estado.progreso.encontradas = encontradas.size;
  }

  /**
   * Un día con más de 100 guías: se consulta por bloques de 4 horas (rangoHoras 1 a 6),
   * dividiendo los bloques a la mitad y, si un solo bloque pasa de 100, por tipo de guía.
   */
  async function buscarPorHoras(ctx, tarea, dia, encontradas, bloques, tipos) {
    if (ctx.signal.aborted) throw crearAbortError();
    const c = { ...consultaDe(tarea, dia, dia), tipos, bloques };
    estado.progreso.busquedaActual = etiquetaConsulta(c);
    actualizarUI();
    const r = await consultarBloque(ctx, c);
    if (r.ok) {
      registrarBusqueda(tarea, c, r, 'ok');
      agregarEncontradas(tarea, r.items, encontradas);
      estado.huboBusquedaCorrecta = true;
      estado.fallosRedSeguidos = 0;
      return;
    }
    if (esRechazo(r) && esExceso(r)) {
      if (bloques.length > 1) {
        registrarBusqueda(tarea, c, r, 'dividida');
        const mitad = Math.ceil(bloques.length / 2);
        await buscarPorHoras(ctx, tarea, dia, encontradas, bloques.slice(0, mitad), tipos);
        await buscarPorHoras(ctx, tarea, dia, encontradas, bloques.slice(mitad), tipos);
      } else if (tipos.length > 1) {
        registrarBusqueda(tarea, c, r, 'dividida');
        for (const t of tipos) await buscarPorHoras(ctx, tarea, dia, encontradas, bloques, [t]);
      } else {
        registrarBusqueda(tarea, c, r, 'bloque_exceso');
        tarea.tramosExcedidos.push({ dia, bloque: bloques[0], tipo: tipos[0] });
        log(`El ${dmy(dia)} entre las ${TEXTO_BLOQUE[bloques[0]]}, ${quien(c)} tiene más de 100 guías de ${TIPOS_GRE[tipos[0]].toLowerCase()}: SUNAT no permite traer ese tramo completo.`, 'warn');
      }
      return;
    }
    registrarBusqueda(tarea, c, r, esRechazo(r) ? 'dia_rechazado' : 'fallida');
    if (esRechazo(r)) tarea.diasRechazados.push({ dia, mensaje: r.mensaje });
    else tarea.fallidas++;
    log(`No se pudo consultar ${etiquetaConsulta(c)}: ${r.mensaje}`, 'warn');
  }

  /**
   * Recorre el rango de una búsqueda en tramos de varios días. Si SUNAT rechaza un tramo por
   * pasar de 100 guías, lo divide a la mitad; si un solo día pasa de 100, lo consulta por bloques
   * de 4 horas. Si un tramo sale bien, calcula cuántos días caben en la siguiente consulta.
   */
  async function buscarRango(ctx, tarea, encontradas) {
    const { cfg } = ctx;
    const ap = tarea.aprendizaje;
    const P = estado.progreso;
    let cursor = tarea.desde;
    let ultimoRechazo = '';
    let ultimoRechazoDias = 0;
    while (cursor <= tarea.hasta) {
      if (ctx.signal.aborted) throw crearAbortError();
      const restantes = diasEntre(cursor, tarea.hasta);
      const dias = Math.max(1, Math.min(ap.tam, ap.tamMax, restantes));
      const c = consultaDe(tarea, cursor, sumarDias(cursor, dias - 1));
      P.busquedaActual = etiquetaConsulta(c);
      actualizarUI();
      const r = await consultarBloque(ctx, c);

      if (r.ok) {
        registrarBusqueda(tarea, c, r, 'ok');
        agregarEncontradas(tarea, r.items, encontradas);
        estado.huboBusquedaCorrecta = true;
        estado.fallosRedSeguidos = 0;
        const cantidad = r.total !== null && r.total !== undefined ? r.total : r.items.length;
        ap.tam = Math.max(1, Math.min(ap.tamMax, Math.floor(cfg.objetivoPorBusqueda / Math.max(cantidad / dias, 1))));
        cursor = sumarDias(c.hasta, 1);
        P.diasHechos += dias;
        // Dividir solucionó el rechazo anterior: ese mensaje de SUNAT significa «demasiadas guías».
        if (ultimoRechazo) estado.mensajesExceso.add(ultimoRechazo);
        ultimoRechazo = '';
        ultimoRechazoDias = 0;
        tarea.rechazosDia = 0;
        continue;
      }

      if (esRechazo(r)) {
        const msg = r.mensaje;
        const exceso = esExceso(r);
        const especifico = !!(r.detalles && r.detalles.length);
        const repetido = especifico && !exceso && msg === ultimoRechazo;
        if (dias > 1) {
          registrarBusqueda(tarea, c, r, 'dividida');
          ap.tamMax = Math.max(1, dias - 1);
          // Si el mismo rechazo se repite al achicar, se prueba con un solo día para saber si es por cantidad.
          ap.tam = repetido ? 1 : Math.max(1, Math.floor(dias / 2));
          ultimoRechazo = msg;
          ultimoRechazoDias = dias;
          log(`${tarea.etiqueta}: SUNAT no permitió consultar ${dias} días juntos; se divide en tramos más cortos.`, 'debug');
          continue;
        }
        if (repetido && ultimoRechazoDias > 1) {
          // Ni con un solo día cambia el rechazo: no es por la cantidad de guías.
          registrarBusqueda(tarea, c, r, 'ruc_rechazado');
          tarea.rechazo = msg;
          P.diasHechos += restantes;
          return 'rechazado';
        }
        ultimoRechazo = msg;
        ultimoRechazoDias = 1;
        if (exceso) {
          // Un solo día con más de 100 guías: por bloques de 4 horas (y por tipo, si hace falta)
          registrarBusqueda(tarea, c, r, 'dividida');
          log(`El ${dmy(cursor)} ${quien(c)} tiene más de 100 guías: se consulta por bloques de 4 horas.`);
          await buscarPorHoras(ctx, tarea, cursor, encontradas, BLOQUES_HORA.slice(0, 3), tarea.tipos);
          await buscarPorHoras(ctx, tarea, cursor, encontradas, BLOQUES_HORA.slice(3), tarea.tipos);
          P.diasHechos += 1;
          cursor = sumarDias(cursor, 1);
          tarea.rechazosDia = 0;
          continue;
        }
        registrarBusqueda(tarea, c, r, 'dia_rechazado');
        tarea.diasRechazados.push({ dia: cursor, mensaje: msg });
        log(`SUNAT rechazó «${tarea.etiqueta}» del ${dmy(cursor)}: ${msg}`, 'warn');
        tarea.rechazosDia = msg === tarea.ultimoRechazoDia ? tarea.rechazosDia + 1 : 1;
        tarea.ultimoRechazoDia = msg;
        P.diasHechos += 1;
        cursor = sumarDias(cursor, 1);
        if (tarea.rechazosDia >= 3) {
          tarea.rechazo = msg;
          if (cursor <= tarea.hasta) P.diasHechos += diasEntre(cursor, tarea.hasta);
          return 'rechazado';
        }
        continue;
      }

      // Otro problema (red, servidor, 404…): se anota y se sigue con el siguiente tramo.
      registrarBusqueda(tarea, c, r, 'fallida');
      tarea.fallidas++;
      P.diasHechos += dias;
      cursor = sumarDias(c.hasta, 1);
      log(`No se pudo consultar ${etiquetaConsulta(c)}: ${r.mensaje}`, 'warn');
      if (r.status === 0) {
        estado.fallosRedSeguidos++;
        if (!estado.huboBusquedaCorrecta || estado.fallosRedSeguidos >= 3) {
          const ayuda = await diagnosticarFalloListado(ctx, r.url);
          throw new ErrorDetencion(`No se pudo consultar a SUNAT: ${r.mensaje}.`, ayuda);
        }
      }
    }
    return 'ok';
  }

  /** Ejecuta todas las búsquedas de la lista. Devuelve un Map clave -> item del listado. */
  async function buscarTodo(ctx) {
    const { cfg } = ctx;
    const P = estado.progreso;
    const encontradas = new Map();
    const aprendizaje = new Map(); // por combinación de RUC y tipos: tamaño de tramo que funciona
    const listados = cfg.busquedas.filter((b) => b.tipo === 'listado');
    const directas = cfg.busquedas.filter((b) => b.tipo === 'directa');
    P.tareasTotal = listados.length;
    P.diasTotales = cfg.diasTotales;
    for (let i = 0; i < listados.length; i++) {
      const b = listados[i];
      const k = `${b.rucEmisor}|${b.rucReceptor}|${b.tipos.join(',')}`;
      if (!aprendizaje.has(k)) aprendizaje.set(k, { tam: cfg.maxDiasBloque, tamMax: cfg.maxDiasBloque });
      const tarea = {
        ...b, aprendizaje: aprendizaje.get(k), encontradas: 0, fallidas: 0, diasRechazados: [], tramosExcedidos: [],
        rechazo: '', ultimoRechazoDia: '', rechazosDia: 0, vistas: new Set()
      };
      estado.tareas.push(tarea);
      P.tareaActual = i + 1;
      log(`Buscando (${i + 1} de ${listados.length}): ${b.etiqueta}…`, 'debug');
      const res = await buscarRango(ctx, tarea, encontradas);
      tarea.vistas = null; // ya no se necesita
      const problemas = tarea.diasRechazados.length + tarea.tramosExcedidos.length + tarea.fallidas;
      if (res === 'rechazado') log(`SUNAT rechaza «${b.etiqueta}»: ${tarea.rechazo}. Se continúa con la siguiente.`, 'error');
      else if (problemas) log(`${b.etiqueta}: ${tarea.encontradas} guía(s); ${problemas} tramo(s) no se pudieron consultar.`, 'warn');
      else log(`${b.etiqueta}: ${tarea.encontradas} guía(s).`, tarea.encontradas ? 'ok' : 'debug');
    }
    // Consultas directas por número (guías citadas o números de una serie): se hacen en la fase de detalle.
    for (const d of directas) {
      const tarea = {
        ...d, tipos: [d.codCpe], encontradas: 0, fallidas: 0, diasRechazados: [], tramosExcedidos: [],
        rechazo: '', vistas: new Set()
      };
      estado.tareas.push(tarea);
      agregarEncontradas(tarea, [{ rucEmisor: d.rucEmisor, codCpe: d.codCpe, numSerie: d.serie, numCpe: d.numero, __directa: true, __posterior: !!d.posterior }], encontradas);
      tarea.vistas = null;
    }
    if (directas.length) log(`${directas.length} guía(s) se consultarán directo por su número.`);
    return encontradas;
  }

  const NOMBRES_PARAMETROS = {
    numRucEmisor: 'RUC emisor', numRucReceptor: 'RUC receptor', codCpe: 'Tipos de guía', numSerie: 'Serie',
    numCpe: 'Número', fecEmisionIni: 'Fecha inicial', fecEmisionFin: 'Fecha final', codEstado: 'Código estado',
    codSubEstado: 'Código subestado', rangoHoras: 'Rango de horas', per_page: 'Registros por página', tipBusqueda: 'Tipo de búsqueda'
  };

  /** Lista, en lenguaje simple, qué cambió entre la búsqueda de SUNAT y la del extractor. */
  function diferenciasConBusqueda(urlSunat, urlExtractor) {
    let a, b;
    try { a = new URL(urlSunat).searchParams; b = new URL(urlExtractor).searchParams; } catch (_) { return []; }
    const nombres = new Set([...a.keys(), ...b.keys()]);
    nombres.delete('page');
    const difs = [];
    for (const n of nombres) {
      const va = a.has(n) ? a.get(n) : null, vb = b.has(n) ? b.get(n) : null;
      if (va === vb) continue;
      const mostrar = (v) => (v === null ? '(no lo envía)' : v === '' ? '(vacío)' : `«${v}»`);
      difs.push(`${NOMBRES_PARAMETROS[n] || n}: SUNAT usó ${mostrar(va)}, el extractor ${mostrar(vb)}`);
    }
    return difs;
  }

  /**
   * Cuando SUNAT no responde de forma legible («Failed to fetch»), repite una sola vez una
   * consulta que la propia pantalla de SUNAT acaba de hacer, para separar las causas.
   */
  async function diagnosticarFalloListado(ctx, urlFallida) {
    const urlPrueba = urlsCapturadas.listado || urlsCapturadas.detalle;
    if (!urlPrueba) return AYUDA_FALLO_CONEXION.slice();
    const esBusqueda = urlPrueba === urlsCapturadas.listado;
    const queEs = esBusqueda ? 'la búsqueda que hizo la pantalla de SUNAT' : 'la guía que abrió en SUNAT';
    log(`Diagnóstico: se repetirá una sola vez ${queEs}…`, 'warn');
    let r;
    try {
      await esperarTurno(ctx);
      r = await pedirJSON(urlPrueba, { ...ctx, cfg: { ...ctx.cfg, maxReintentos: 0 } }, 'DIAGNÓSTICO');
    } catch (e) {
      if (e instanceof ErrorAutenticacion || esAbort(e)) throw e;
      r = { ok: false, mensaje: (e && e.message) || String(e) };
    }
    const lineas = ['Diagnóstico automático:'];
    if (r.ok) {
      lineas.push(`• ${queEs[0].toUpperCase()}${queEs.slice(1)} SÍ responde desde el extractor: la conexión está bien.`);
      const difs = esBusqueda ? diferenciasConBusqueda(urlPrueba, urlFallida) : [];
      if (difs.length) {
        lineas.push('• SUNAT bloquea la búsqueda por lo que cambió respecto de la suya:');
        for (const d of difs) lineas.push(`   – ${d}`);
      }
      lineas.push('• Solución: pulse «Conectar», haga en la pantalla de SUNAT una búsqueda de uno de los RUC y vuelva a intentar (se copiará su forma exacta).');
    } else {
      lineas.push(`• Incluso ${queEs} falla desde el extractor.`);
      lineas.push('• SUNAT no acepta esa conexión fuera de su pantalla, o ya no es válida.');
      lineas.push('• Para confirmarlo: pestaña Network > clic en la solicitud «comprobantes?...» en rojo > Headers > «Status Code». Envíe esa captura sin mostrar el token.');
    }
    return lineas;
  }

  /* ---------------------------------------------------------------
   * 8. Detalle de cada guía
   * ------------------------------------------------------------- */
  function construirUrlDetalle(item) {
    const segmentos = [item.rucEmisor, item.codCpe, item.numSerie, item.numCpe]
      .map((v) => encodeURIComponent(texto(v).trim())); // número sin ceros a la izquierda
    return `${API_LISTADO}/${segmentos.join('-')}`;
  }

  function crearRegistro(clave, item, extra = {}) {
    return {
      clave, listado: item || null, detalle: null, ok: false, procesada: false, directa: !!(item && item.__directa),
      http: '', intentos: 0, error: '', consultadoEn: '', origen: 'actual', ...extra
    };
  }

  function agregarControl(lista, tipo, guia, campo, valorListado, valorDetalle, detalle) {
    lista.push({ tipo, guia, campo, valorListado: texto(valorListado), valorDetalle: texto(valorDetalle), detalle });
  }

  /** Compara campos clave del listado con el detalle. */
  function compararListadoDetalle(clave, item, det) {
    if (!esObjetoPlano(item) || !esObjetoPlano(det) || item.__directa) return;
    const norm = (v) => { const s = texto(v).trim().toUpperCase(); return /^\d+$/.test(s) ? String(Number(s)) : s; };
    const pares = [['rucEmisor', 'numRuc'], ['codCpe', 'codCpe'], ['numSerie', 'numSerie'], ['numCpe', 'numCpe']];
    for (const [a, b] of pares) {
      const vl = item[a], vd = det[b];
      if (esVacio(vd)) {
        agregarControl(estado.controlDetalle, 'CAMPO_AUSENTE_EN_DETALLE', clave, `listado.${a} / detalle.${b}`, vl, '', 'El detalle no trae este campo');
      } else if (norm(vl) !== norm(vd)) {
        agregarControl(estado.controlDetalle, 'DIFERENCIA_LISTADO_DETALLE', clave, `listado.${a} / detalle.${b}`, vl, vd, 'Valores distintos');
      }
    }
  }

  async function obtenerDetalles(ctx) {
    const { cfg, signal } = ctx;
    const P = estado.progreso;
    P.total = estado.unicos.length;
    const conocidas = new Set(cfg.conocidas || []);
    const yaObtenida = (clave) => estado.previos.get(clave) || estado.memoria.get(clave);
    P.pendientesReales = estado.unicos.filter((u) => !yaObtenida(u.clave) && !conocidas.has(u.clave)).length;
    estado.tiempos.inicioDetalle = Date.now();
    const yaTablero = estado.unicos.filter((u) => conocidas.has(u.clave) && !yaObtenida(u.clave)).length;
    const reutilizadas = P.total - P.pendientesReales - yaTablero;
    if (yaTablero) log(`${yaTablero} guía(s) ya están en el tablero: solo se anota su estado actual.`, 'ok');
    if (reutilizadas) log(`${reutilizadas} guía(s) ya se habían obtenido antes y no se volverán a consultar.`, 'ok');
    if (P.pendientesReales) log(`Descargando el detalle de ${P.pendientesReales} guía(s)…`);

    let consecutivos = 0;
    // Consultas por número: por serie, cuántos números posteriores a la última guía conocida no existen seguidos
    const series = new Map();
    const serieDe = (it) => `${it.rucEmisor}|${it.codCpe}|${it.numSerie}`;
    for (const { clave, item } of estado.unicos) {
      if (signal.aborted) throw crearAbortError();
      const reg = estado.resultados.get(clave);
      const etiqueta = guiaLegible(item.numSerie, item.numCpe) || clave;
      P.actual = etiqueta;

      // Ya obtenida antes (archivo anterior o ejecución anterior de esta sesión)
      const pv = yaObtenida(clave);
      if (pv) {
        Object.assign(reg, {
          detalle: pv.detalle, ok: true, procesada: true, http: 'REUTILIZADA',
          consultadoEn: pv.consultadoEn, origen: estado.previos.has(clave) ? 'previo' : 'memoria'
        });
        compararListadoDetalle(clave, item, pv.detalle);
        P.omitidas++; P.ok++; P.procesadas++;
        actualizarUI();
        continue;
      }
      // Ya está en el tablero: no se descarga de nuevo (el listado trae su estado actual)
      if (conocidas.has(clave)) {
        Object.assign(reg, { procesada: true, origen: 'conocida', http: 'YA_EN_TABLERO' });
        P.omitidas++; P.procesadas++;
        actualizarUI();
        continue;
      }

      // Datos mínimos para armar la dirección
      const faltan = ['rucEmisor', 'codCpe', 'numSerie', 'numCpe'].filter((k) => esVacio(item[k]));
      if (faltan.length) {
        const msg = `Datos incompletos en el listado: falta ${faltan.join(', ')}`;
        registrarError({ guia: etiqueta, clave, url: '', estadoHttp: '', mensaje: msg, intento: 0, accion: 'OMITIDA' });
        Object.assign(reg, { procesada: true, error: msg });
        P.error++; P.procesadas++;
        log(`${etiqueta}: ${msg}`, 'warn');
        actualizarUI();
        continue;
      }

      // Serie que ya llegó a su último número emitido: los siguientes aún no existen
      const sv = item.__directa ? series.get(serieDe(item)) : null;
      if (item.__posterior && sv && sv.cerrada && Number(item.numCpe) > sv.ultimo) {
        Object.assign(reg, {
          procesada: true, origen: 'fin_de_serie', http: 'NO_CONSULTADA', noConsultada: true,
          error: `No se consultó: los ${cfg.maxNoExistenSerie} números anteriores de la serie ${item.numSerie} no existen todavía`
        });
        P.omitidas++; P.procesadas++;
        actualizarUI();
        continue;
      }

      await esperarTurno(ctx);
      const url = construirUrlDetalle(item);
      const r = await pedirJSON(url, ctx, etiqueta, clave, { directa: !!item.__directa });
      P.consultadas++;
      reg.procesada = true;
      reg.intentos = r.intentos;
      reg.http = r.status;
      reg.consultadoEn = fechaHoraLocal();

      const dijoNoExiste = r.ok && esObjetoPlano(r.data) && !pareceDetalle(r.data) && NO_EXISTE.test(JSON.stringify(r.data).slice(0, 2000));
      if (r.ok && esObjetoPlano(r.data) && (!item.__directa || pareceDetalle(r.data))) {
        reg.ok = true;
        reg.detalle = r.data;
        P.ok++;
        consecutivos = 0;
        if (item.__directa) series.set(serieDe(item), { racha: 0, ultimo: 0, cerrada: false });
        compararListadoDetalle(clave, item, r.data);
        log(`${P.procesadas + 1}/${P.total} ${etiqueta} OK (${obtenerBienes(r.data).length} bien(es))`, 'debug');
      } else if (item.__directa && (r.noExiste || r.status === 404 || dijoNoExiste)) {
        // La guía no existe: es una respuesta válida de SUNAT (número aún no emitido, guía física o de otro tipo)
        reg.noExiste = true;
        reg.error = 'La guía no existe en SUNAT (número aún no emitido, guía física o de otro tipo)';
        P.noExisten = (P.noExisten || 0) + 1;
        consecutivos = 0;
        const s0 = series.get(serieDe(item)) || { racha: 0, ultimo: 0, cerrada: false };
        if (item.__posterior) {
          s0.racha++;
          s0.ultimo = Math.max(s0.ultimo, Number(item.numCpe));
          if (!s0.cerrada && s0.racha >= cfg.maxNoExistenSerie) {
            s0.cerrada = true;
            log(`Serie ${item.numSerie}: ${s0.racha} números seguidos no existen; se omiten los siguientes de esa serie.`, 'ok');
          }
        }
        series.set(serieDe(item), s0);
        log(`Guía ${etiqueta}: no existe.`, 'debug');
      } else {
        reg.error = r.ok ? 'La respuesta no contiene el detalle de la guía' : r.mensaje;
        if (r.ok) registrarError({ guia: etiqueta, clave, url, estadoHttp: r.status, mensaje: reg.error, intento: r.intentos, accion: 'OMITIDA' });
        P.error++;
        if (r.status !== 404) consecutivos++;
        log(`Guía ${etiqueta}: ${reg.error}`, 'warn');
      }
      P.procesadas++;
      actualizarUI();

      if (consecutivos >= cfg.maxErroresConsecutivos) {
        throw new ErrorDetencion(`Se detuvo tras ${consecutivos} errores seguidos (posible problema de red o de SUNAT). Lo obtenido se conserva.`);
      }
    }
  }

  /* ---------------------------------------------------------------
   * 9. Proceso principal
   * ------------------------------------------------------------- */
  function reiniciarEstado(cfg) {
    estado.config = cfg;
    estado.motivoFin = 'EN_CURSO';
    estado.fase = '';
    estado.tiempos = { inicio: Date.now(), inicioDetalle: 0, fin: 0 };
    estado.tareas = [];
    estado.busquedas = [];
    estado.unicos = [];
    estado.duplicados = [];
    estado.origenes = new Map();
    estado.resultados = new Map();
    estado.errores = [];
    estado.controlDetalle = [];
    estado.control = [];
    estado.progreso = progresoVacio();
    estado.resumen = null;
    estado.pausado = false;
    estado.esperandoConexion = false;
    estado.fallosRedSeguidos = 0;
    estado.huboBusquedaCorrecta = false;
    estado.mensajesExceso = new Set();
    estado.tokenExp = null;
    estado.controller = new AbortController();
  }

  /**
   * Función principal. Ejemplos desde la consola:
   *   await GREExtractor.iniciar({ pedido: textoCopiadoDelTablero });
   *   await GREExtractor.iniciar({ rucs: ['20XXXXXXXXX'], rol: 'ambos', periodos: [{ desde: 'hoy-1', hasta: 'hoy' }] });
   * Si no hay conexión, pedirá abrir una guía con «Ver» en la pantalla de SUNAT.
   */
  async function iniciarExtraccionGRE(opciones = {}) {
    if (estado.ejecutando) {
      log('Ya hay una búsqueda en curso. Deténgala o espere a que termine.', 'warn');
      return null;
    }
    estado.ejecutando = true;
    let iniciado = false;
    const ctx = { token: null, tokenExp: null, cabecerasExtra: {}, signal: null, cfg: null, solicitudes: 0 };

    try {
      const cfg = normalizarConfig(opciones);
      const inicial = tokenInicial(opciones);
      // Borrar el token del objeto recibido para que no quede referenciado.
      if (opciones && typeof opciones === 'object' && 'token' in opciones) { try { opciones.token = ''; } catch (_) { /* objeto congelado */ } }
      detenerCaptura('inicio');

      // Guías ya obtenidas en una ejecución anterior de esta sesión: permiten continuar donde quedó.
      const memoria = new Map();
      for (const r of estado.resultados.values()) {
        if (r.ok && esObjetoPlano(r.detalle)) memoria.set(r.clave, { detalle: r.detalle, consultadoEn: r.consultadoEn });
      }

      reiniciarEstado(cfg);
      estado.memoria = memoria;
      iniciado = true;
      ctx.cfg = cfg;
      ctx.signal = estado.controller.signal;
      iniciarCaptura('fondo'); // escucha la pantalla de SUNAT para renovar la conexión sola
      actualizarUI();

      if (cfg.origen === 'tablero') {
        const n = cfg.busquedas.filter((b) => b.tipo === 'listado').length, d = cfg.busquedas.length - n;
        log(`Lista «${cfg.pedidoInfo.titulo}»: ${n} búsqueda(s)${d ? ` y ${d} guía(s) por consultar directo por su número` : ''}.`);
      } else {
        const listaPeriodos = cfg.periodos.map((p) => `${dmy(p.desde)} al ${dmy(p.hasta)}`).join('; ');
        log(`Búsqueda manual: ${cfg.rucs.length} RUC como ${TEXTO_ROL[cfg.rol]}, guías de ${cfg.tipos.map((t) => TIPOS_GRE[t].toLowerCase()).join(', ')}; periodo(s): ${listaPeriodos}.`);
      }

      if (inicial) {
        ctx.token = inicial.token;
        ctx.cabecerasExtra = inicial.cabeceras || {};
        inicial.token = null;
        ctx.tokenExp = describirToken(ctx.token, inicial.origen);
        estado.tokenExp = ctx.tokenExp;
      }
      if (!ctx.token || tokenPorVencer(ctx)) {
        estado.fase = 'conexion';
        await renovarConexion(ctx, ctx.token ? 'vencida' : 'inicial');
      }
      if (cfg.plantillaListado) log('Se usa como base la búsqueda copiada de SUNAT.', 'debug');
      const nombresExtra = Object.keys(ctx.cabecerasExtra || {});
      if (nombresExtra.length) log(`Cabeceras de la aplicación que se envían: ${nombresExtra.join(', ')}.`, 'debug');

      // Fase 1: buscar las guías
      estado.fase = 'busqueda';
      actualizarUI();
      const encontradas = await buscarTodo(ctx);
      estado.unicos = [...encontradas.entries()].map(([clave, item]) => ({ clave, item }));
      for (const { clave, item } of estado.unicos) estado.resultados.set(clave, crearRegistro(clave, item));
      log(`Búsqueda terminada: ${estado.unicos.length} guía(s) encontradas.`, 'ok');

      // Fase 2: detalle de cada guía
      estado.fase = 'detalle';
      actualizarUI();
      await obtenerDetalles(ctx);
      estado.motivoFin = 'COMPLETADO';
      log('Extracción completada.', 'ok');
    } catch (e) {
      if (esAbort(e)) {
        estado.motivoFin = 'CANCELADO';
        log('Proceso detenido. Lo obtenido se conserva y puede descargarlo.', 'warn');
      } else if (e instanceof ErrorAutenticacion) {
        estado.motivoFin = e.codigo;
        log(`${e.message} Proceso detenido; lo ya obtenido se conserva.`, 'error');
        if (e.status !== 403) log('Para continuar: pulse «Buscar y descargar» otra vez y abra una guía con «Ver» cuando se le pida. Solo se consultará lo que falta.', 'warn');
      } else if (e instanceof ErrorValidacion) {
        log(e.message, 'error');
      } else if (e instanceof ErrorDetencion) {
        estado.motivoFin = 'DETENIDO';
        log(e.message, 'error');
        for (const linea of e.ayuda) log(linea, 'warn');
      } else {
        estado.motivoFin = 'ERROR';
        log(`Error inesperado: ${(e && e.message) || e}`, 'error');
        console.error(e);
      }
    } finally {
      // Descartar la conexión (token y cabeceras) y dejar la página como estaba
      ctx.token = null;
      ctx.tokenExp = null;
      ctx.cabecerasExtra = null;
      detenerCaptura('fin');
      if (iniciado) { tokenCapturado = null; cabecerasCapturadas = null; }
      estado.tokenExp = null;
      estado.ejecutando = false;
      estado.pausado = false;
      estado.esperandoConexion = false;
      estado.controller = null;
      estado.fase = '';
      if (iniciado) {
        estado.tiempos.fin = Date.now();
        try { finalizar(); } catch (e) { log(`Error al preparar el resumen: ${e.message}`, 'error'); }
        const hayDatos = estado.resultados.size > 0;
        if (estado.motivoFin !== 'CANCELADO' && hayDatos) {
          if (estado.config.descargarJSON) { try { await descargar('json'); } catch (e) { log(`No se pudo descargar el JSON: ${e.message}`, 'error'); } }
          if (estado.config.descargarExcel) {
            if (estado.config.descargarJSON) await dormir(500);
            try { await descargar('excel'); } catch (e) { log(`No se pudo descargar el Excel: ${e.message}`, 'error'); }
          }
        }
      }
      if (ui && ui.compactar) ui.compactar(false);
      actualizarUI();
    }
    return iniciado ? estado.resumen : null;
  }

  function pausar() {
    if (!estado.ejecutando) { log('No hay una búsqueda en curso.', 'warn'); return; }
    estado.pausado = true;
    log('Pausa solicitada (se aplica antes de la siguiente consulta).', 'warn');
    actualizarUI();
  }
  function reanudar() {
    if (!estado.ejecutando) { log('No hay una búsqueda en curso.', 'warn'); return; }
    if (!estado.pausado) return;
    estado.pausado = false;
    log('Continuando.', 'ok');
    actualizarUI();
  }
  function cancelar() {
    if (!estado.ejecutando || !estado.controller) { log('No hay una búsqueda en curso.', 'warn'); return; }
    estado.pausado = false;
    estado.controller.abort();
    log('Deteniendo…', 'warn');
  }

  /* ---------------------------------------------------------------
   * 10. Control de calidad y resumen
   * ------------------------------------------------------------- */
  function obtenerBienes(det) {
    const b = obtener(det, 'traslado.bien');
    if (Array.isArray(b)) return b.filter(esObjetoPlano);
    return esObjetoPlano(b) ? [b] : [];
  }

  const TIPO_CONTROL_BUSQUEDA = {
    bloque_exceso: 'TRAMO_SUPERA_100', dia_rechazado: 'DIA_RECHAZADO', ruc_rechazado: 'RUC_RECHAZADO', fallida: 'BUSQUEDA_FALLIDA'
  };

  function construirControl() {
    const C = [...estado.controlDetalle];
    for (const b of estado.busquedas) {
      const tramo = `${dmy(b.desde)} al ${dmy(b.hasta)}${b.bloques ? ' · horas ' + b.bloques : ''}`;
      if (b.tipo === 'ok' && b.incompleta) agregarControl(C, 'BUSQUEDA_INCOMPLETA', b.etiqueta, tramo, b.total, b.recibidos, 'SUNAT informó más guías de las recibidas');
      if (TIPO_CONTROL_BUSQUEDA[b.tipo]) agregarControl(C, TIPO_CONTROL_BUSQUEDA[b.tipo], b.etiqueta, tramo, '', b.estadoHttp, b.mensaje);
    }
    for (const d of estado.duplicados) agregarControl(C, 'GUIA_REPETIDA_EN_BUSQUEDA', d, 'clave', d, '', 'Registro duplicado eliminado');
    for (const r of estado.resultados.values()) {
      if (r.origen === 'conocida' || r.noConsultada) continue;
      if (!r.procesada) agregarControl(C, 'GUIA_NO_PROCESADA', r.clave, '', '', '', `Proceso finalizado como ${textoMotivo(estado.motivoFin)}`);
      else if (!r.ok) agregarControl(C, r.noExiste ? 'GUIA_NO_EXISTE' : r.directa ? 'GUIA_CITADA_SIN_DETALLE' : 'GUIA_SIN_DETALLE', r.clave, 'HTTP', '', r.http, r.error);
      else if (obtenerBienes(r.detalle).length === 0) agregarControl(C, 'GUIA_SIN_BIENES', r.clave, 'traslado.bien', '', '0', 'La guía no tiene bienes');
      if (r.origen === 'previo_fuera_del_listado') agregarControl(C, 'PREVIO_FUERA_DEL_LISTADO', r.clave, '', '', '', 'Guía del archivo anterior que no aparece en las búsquedas actuales');
    }
    estado.control = C;
  }

  function textoMotivo(m) {
    return {
      EN_CURSO: 'En curso', COMPLETADO: 'Completado', CANCELADO: 'Detenido por el usuario', DETENIDO: 'Detenido por un problema',
      DETENIDO_SIN_CONEXION: 'Detenido: no se renovó la conexión', DETENIDO_HTTP_401: 'Detenido: SUNAT no aceptó la conexión',
      DETENIDO_HTTP_403: 'Detenido: sin permiso (HTTP 403)', ERROR: 'Detenido por un error'
    }[m] || m || '';
  }

  function calcularResumen() {
    const regs = [...estado.resultados.values()];
    const ok = regs.filter((r) => r.ok);
    const P = estado.progreso, T = estado.tiempos, cfg = estado.config;
    const tiempoTotal = (T.fin || Date.now()) - T.inicio;
    const tiempoDetalle = T.inicioDetalle ? (T.fin || Date.now()) - T.inicioDetalle : 0;
    const informadas = estado.busquedas.filter((b) => b.tipo === 'ok' && b.total !== '').reduce((s, b) => s + Number(b.total), 0);
    return {
      'Estado final': textoMotivo(estado.motivoFin),
      'Lista': cfg ? cfg.pedidoInfo.titulo : '',
      'Búsquedas de la lista': cfg ? cfg.busquedas.length : 0,
      'Consultas hechas en SUNAT': estado.busquedas.length,
      'Guías informadas por SUNAT (suma de consultas)': informadas,
      'Guías encontradas (sin repetir)': estado.unicos.length,
      'Duplicados eliminados': estado.duplicados.length,
      'Guías que ya estaban en el tablero': regs.filter((r) => r.origen === 'conocida').length,
      'Días o tramos que SUNAT no permitió consultar': estado.tareas.reduce((s, t) => s + t.diasRechazados.length + t.tramosExcedidos.length, 0),
      'Guías con detalle': ok.length,
      '  de ellas reutilizadas': regs.filter((r) => r.ok && r.origen !== 'actual').length,
      'Guías con error': regs.filter((r) => r.procesada && !r.ok && r.origen !== 'conocida' && !r.noExiste && !r.noConsultada).length,
      'Guías que no existen (consulta por número)': regs.filter((r) => r.noExiste).length,
      'Números no consultados (fin de la serie)': regs.filter((r) => r.noConsultada).length,
      'Guías no procesadas': regs.filter((r) => !r.procesada).length,
      'Total de bienes': ok.reduce((s, r) => s + obtenerBienes(r.detalle).length, 0),
      'Guías sin bienes': ok.filter((r) => obtenerBienes(r.detalle).length === 0).length,
      'Observaciones de control': estado.control.length,
      'Tiempo total': duracion(tiempoTotal),
      'Promedio por guía consultada': P.consultadas ? `${(tiempoDetalle / P.consultadas / 1000).toFixed(2)} s` : ''
    };
  }

  /** Una fila por búsqueda de la lista, para la hoja «Resumen». */
  function resumenPorBusqueda() {
    const conteo = new Map();
    for (const r of estado.resultados.values()) {
      for (const o of estado.origenes.get(r.clave) || []) {
        if (!conteo.has(o.etiqueta)) conteo.set(o.etiqueta, { ok: 0, error: 0, tablero: 0 });
        const c = conteo.get(o.etiqueta);
        if (r.ok) c.ok++;
        else if (r.origen === 'conocida') c.tablero++;
        else if (r.procesada && !r.noExiste && !r.noConsultada) c.error++;
      }
    }
    return estado.tareas.map((t) => {
      const c = conteo.get(t.etiqueta) || { ok: 0, error: 0, tablero: 0 };
      const observacion = [
        t.rechazo && `SUNAT rechazó la búsqueda: ${t.rechazo}`,
        t.tramosExcedidos.length && `${t.tramosExcedidos.length} tramo(s) de 4 horas con más de 100 guías`,
        t.diasRechazados.length && `${t.diasRechazados.length} día(s) rechazados`,
        t.fallidas && `${t.fallidas} consulta(s) sin respuesta`,
        c.tablero && `${c.tablero} ya en el tablero`
      ].filter(Boolean).join('; ');
      return {
        etiqueta: t.etiqueta, caso: t.caso || '', encontradas: t.encontradas, ok: c.ok, error: c.error,
        noConsultados: t.diasRechazados.length + t.tramosExcedidos.length, observacion
      };
    });
  }

  function finalizar() {
    // Incluir guías del archivo anterior que no aparecieron en las búsquedas actuales
    for (const [clave, pv] of estado.previos) {
      if (!estado.resultados.has(clave)) {
        estado.resultados.set(clave, crearRegistro(clave, null, {
          detalle: pv.detalle, ok: true, procesada: true, http: 'REUTILIZADA',
          consultadoEn: pv.consultadoEn, origen: 'previo_fuera_del_listado'
        }));
      }
    }
    estado.memoria = new Map();
    construirControl();
    estado.resumen = calcularResumen();
    const R = estado.resumen;

    console.log('%c[GRE] RESUMEN', 'color:#0a7d55;font-weight:bold;font-size:13px');
    console.table(R);
    if (estado.control.length) {
      const porTipo = {};
      for (const c of estado.control) porTipo[c.tipo] = (porTipo[c.tipo] || 0) + 1;
      console.log('%c[GRE] Control de calidad (cantidad por tipo)', 'color:#b36b00;font-weight:bold');
      console.table(porTipo);
    }
    log(`Resultado: ${R['Guías encontradas (sin repetir)']} guía(s) encontradas, ${R['Guías con detalle']} con detalle y ${R['Total de bienes']} bien(es).`, 'ok');
    if (R['Días o tramos que SUNAT no permitió consultar']) log(`${R['Días o tramos que SUNAT no permitió consultar']} día(s) o tramo(s) no se pudieron consultar: vea la hoja «Búsquedas» del Excel.`, 'warn');
    if (R['Guías con error']) log(`${R['Guías con error']} guía(s) con error: vea la hoja «Errores» del Excel.`, 'warn');
  }

  /* ---------------------------------------------------------------
   * 11. Aplanamiento genérico
   * ------------------------------------------------------------- */
  /**
   * Convierte un objeto anidado en { "ruta.a.b": valorPrimitivo }.
   * - Arreglos de primitivos: se unen con " | ".
   * - Arreglos de objetos (o vacíos): solo "<ruta>[cantidad]"; su contenido va en hojas aparte.
   */
  function flattenObject(valor, prefijo = '', salida = {}) {
    if (esPrimitivo(valor)) {
      if (prefijo) salida[prefijo] = valor instanceof Date ? texto(valor) : valor;
      return salida;
    }
    if (Array.isArray(valor)) {
      if (valor.length > 0 && valor.every(esPrimitivo)) salida[prefijo] = valor.map(texto).filter((s) => s !== '').join(' | ');
      else salida[`${prefijo}[cantidad]`] = valor.length;
      return salida;
    }
    if (esObjetoPlano(valor)) {
      const claves = Object.keys(valor);
      if (!claves.length && prefijo) salida[prefijo] = '';
      for (const k of claves) flattenObject(valor[k], prefijo ? `${prefijo}.${k}` : k, salida);
    }
    return salida;
  }

  /* ---------------------------------------------------------------
   * 12. Filas legibles (sin inventar propiedades)
   * ------------------------------------------------------------- */
  function subnodos(n) {
    return esObjetoPlano(n) ? [n, ...Object.values(n).filter(esObjetoPlano)] : [];
  }

  function datosPersona(nodo) {
    const lista = Array.isArray(nodo) ? nodo.filter(esObjetoPlano) : (esObjetoPlano(nodo) ? [nodo] : []);
    const una = (n) => {
      const nodos = subnodos(n);
      return {
        tipoDoc: texto(buscarClave(nodos, [/^codTip.*Doc/i, /tip.*doc/i])),
        numDoc: texto(buscarClave(nodos, [/^numDocIdentidad$/i, /^numDoc/i, /^numRuc$/i, /doc.*ident/i, /ruc/i])),
        nombre: texto(buscarClave(nodos, [/raz[oó]n/i, /^desNombre/i, /^nomb/i, /^nom[A-Z_]/, /nombre/i, /apellido/i]))
      };
    };
    const datos = lista.map(una);
    const unir = (campo) => datos.map((d) => d[campo]).filter(Boolean).join(' | ');
    return { tipoDoc: unir('tipoDoc'), numDoc: unir('numDoc'), nombre: unir('nombre') };
  }

  function datosDireccion(nodo) {
    if (!esObjetoPlano(nodo)) return { direccion: '', ubigeo: '', departamento: '', provincia: '', distrito: '', ruc: '', establecimiento: '' };
    const nodos = [nodo.direccion, ...subnodos(nodo)].filter(esObjetoPlano);
    return {
      direccion: texto(buscarClave(nodos, [/^desDireccion/i, /direcci[oó]n/i, /^desDir/i])),
      ubigeo: texto(buscarClave(nodos, [/ubigeo/i])),
      departamento: texto(buscarClave(nodos, [/^desDepartamento/i, /departamento|dpto/i])),
      provincia: texto(buscarClave(nodos, [/^desProvincia/i, /provincia/i])),
      distrito: texto(buscarClave(nodos, [/^desDistrito/i, /distrito/i])),
      ruc: texto(buscarClave(nodos, [/^numRuc$/i, /ruc/i])),
      establecimiento: texto(buscarClave(nodos, [/^(des|nom).*establec/i, /establec/i, /local/i]))
    };
  }

  function textoDeArreglo(valor) {
    if (valor === undefined || valor === null) return '';
    const lista = Array.isArray(valor) ? valor : [valor];
    return lista.map((v) => {
      if (esPrimitivo(v)) return texto(v);
      if (esObjetoPlano(v)) return Object.values(flattenObject(v)).map(texto).filter(Boolean).join(' ');
      return '';
    }).filter(Boolean).join(' | ');
  }

  /** Búsquedas (y casos) con que se encontró la guía. */
  function origenDe(clave) {
    const lista = estado.origenes.get(clave) || [];
    return {
      etiquetas: lista.map((o) => o.etiqueta).join(' | '),
      casos: [...new Set(lista.map((o) => o.caso).filter(Boolean))].join(' | ')
    };
  }

  const COLUMNAS_GUIAS = [
    'Clave', 'Encontrada por', 'Caso', 'ID interno', 'RUC emisor', 'Nombre emisor', 'Código CPE', 'Tipo CPE', 'Serie', 'Número', 'Guía completa',
    'Código estado', 'Estado', 'Subestado', 'Fecha emisión', 'Fecha generación CDR', 'Observaciones guía', 'Observaciones receptor',
    'Código motivo traslado', 'Motivo traslado', 'Fecha inicio traslado', 'Fecha entrega', 'Modalidad traslado',
    'Bultos/Pallets', 'Unidad peso', 'Peso bruto', 'Placa',
    'Partida dirección', 'Partida ubigeo', 'Partida departamento', 'Partida provincia', 'Partida distrito', 'Partida RUC establecimiento', 'Partida establecimiento',
    'Llegada dirección', 'Llegada ubigeo', 'Llegada departamento', 'Llegada provincia', 'Llegada distrito', 'Llegada RUC establecimiento', 'Llegada establecimiento',
    'Receptor tipo doc.', 'Receptor documento', 'Receptor nombre',
    'Proveedor documento', 'Proveedor nombre', 'Comprador documento', 'Comprador nombre',
    'Transportista documento', 'Transportista nombre', 'Registro MTC',
    'Cantidad bienes', 'Usuario registro', 'Fecha registro', 'Usuario modificación', 'Fecha modificación',
    'Origen', 'Consulta correcta', 'HTTP', 'Intentos', 'Consultado en', 'Mensaje error'
  ];

  /** Datos de identificación comunes (del detalle o, si falta, del listado). */
  function datosBase(reg) {
    const d = reg.detalle || {}, it = reg.listado || {};
    const ruc = primero(d.numRuc, obtener(d, 'emisor.numRuc'), it.rucEmisor);
    const serie = primero(d.numSerie, it.numSerie);
    const num = primero(d.numCpe, it.numCpe);
    const traslado = esObjetoPlano(d.traslado) ? d.traslado : {};
    const partida = datosDireccion(traslado.partida);
    const llegada = datosDireccion(traslado.llegada);
    const transp = datosPersona(traslado.transportista);
    const origen = origenDe(reg.clave);
    return {
      d, it, traslado, partida, llegada, transp, origen,
      ruc: texto(ruc),
      nombreEmisor: texto(buscarClave(subnodos(d.emisor), [/raz[oó]n/i, /^desNombre/i, /^nomb/i, /^nom[A-Z_]/, /nombre/i])),
      serie: texto(serie),
      num: texto(num),
      guia: guiaLegible(serie, num),
      fecEmision: texto(primero(obtener(d, 'emision.fecEmision'), d.fecEmision, it.fecEmision)),
      estado: texto(primero(d.desEstado, it.desEstado)),
      motivo: [texto(traslado.codMotivoTraslado), texto(traslado.desMotivoTraslado)].filter(Boolean).join(' - ')
    };
  }

  function textoConsulta(reg) {
    if (reg.ok) return 'SI';
    if (reg.origen === 'conocida') return 'YA_EN_TABLERO';
    if (reg.noExiste) return 'NO_EXISTE';
    if (reg.noConsultada) return 'NO_CONSULTADA_FIN_DE_SERIE';
    return reg.procesada ? 'NO' : 'NO_PROCESADA';
  }

  function filaGuia(reg) {
    const b = datosBase(reg);
    const { d, it, traslado } = b;
    const receptor = datosPersona(d.receptor);
    const proveedor = datosPersona(traslado.proveedor);
    const comprador = datosPersona(traslado.comprador);
    const aud = subnodos(d.auditoria);
    const fila = {
      'Clave': reg.clave,
      'Encontrada por': b.origen.etiquetas,
      'Caso': b.origen.casos,
      'ID interno': texto(d.id),
      'RUC emisor': b.ruc,
      'Nombre emisor': b.nombreEmisor,
      'Código CPE': texto(primero(d.codCpe, it.codCpe)),
      'Tipo CPE': texto(primero(d.desTipoCpe, it.desCpe, TIPOS_GRE[texto(primero(d.codCpe, it.codCpe))])),
      'Serie': b.serie,
      'Número': b.num,
      'Guía completa': b.guia,
      'Código estado': texto(primero(d.codEstado, it.codEstado)),
      'Estado': b.estado,
      'Subestado': texto(primero(d.desSubEstado, it.desSubEstado)),
      'Fecha emisión': b.fecEmision,
      'Fecha generación CDR': texto(primero(it.fecGenCdr, d.fecGenCdr, obtener(d, 'emision.fecGenCdr'))),
      'Observaciones guía': texto(primero(obtener(d, 'emision.desObservacion'), buscarClave(subnodos(d.emision), [/observ/i, /^desObs/i]))),
      'Observaciones receptor': textoDeArreglo(buscarProfundo(d, 'receptorObs')),
      'Código motivo traslado': texto(traslado.codMotivoTraslado),
      'Motivo traslado': texto(traslado.desMotivoTraslado),
      'Fecha inicio traslado': texto(traslado.fecInicioTraslado),
      'Fecha entrega': texto(traslado.fecEntrega),
      'Modalidad traslado': texto(primero(traslado.desModalidadTraslado, traslado.codModalidadTraslado)),
      'Bultos/Pallets': texto(traslado.numBultosPallets),
      'Unidad peso': texto(traslado.codUnidadMedidaPb),
      'Peso bruto': texto(traslado.numPesoBruto),
      'Placa': texto(primero(traslado.numPlacaVehiculo, buscarClave(subnodos(Array.isArray(traslado.vehiculo) ? traslado.vehiculo[0] : traslado.vehiculo), [/placa/i]))),
      'Partida dirección': b.partida.direccion,
      'Partida ubigeo': b.partida.ubigeo,
      'Partida departamento': b.partida.departamento,
      'Partida provincia': b.partida.provincia,
      'Partida distrito': b.partida.distrito,
      'Partida RUC establecimiento': b.partida.ruc,
      'Partida establecimiento': b.partida.establecimiento,
      'Llegada dirección': b.llegada.direccion,
      'Llegada ubigeo': b.llegada.ubigeo,
      'Llegada departamento': b.llegada.departamento,
      'Llegada provincia': b.llegada.provincia,
      'Llegada distrito': b.llegada.distrito,
      'Llegada RUC establecimiento': b.llegada.ruc,
      'Llegada establecimiento': b.llegada.establecimiento,
      'Receptor tipo doc.': receptor.tipoDoc,
      'Receptor documento': primero(receptor.numDoc, it.rucReceptor),
      'Receptor nombre': receptor.nombre,
      'Proveedor documento': proveedor.numDoc,
      'Proveedor nombre': proveedor.nombre,
      'Comprador documento': comprador.numDoc,
      'Comprador nombre': comprador.nombre,
      'Transportista documento': b.transp.numDoc,
      'Transportista nombre': b.transp.nombre,
      'Registro MTC': texto(buscarClave(subnodos(Array.isArray(traslado.transportista) ? traslado.transportista[0] : traslado.transportista), [/mtc/i])),
      'Cantidad bienes': reg.ok ? obtenerBienes(d).length : '',
      'Usuario registro': texto(buscarClave(aud, [/usu.*reg/i])),
      'Fecha registro': texto(buscarClave(aud, [/fec.*reg/i])),
      'Usuario modificación': texto(buscarClave(aud, [/usu.*mod/i])),
      'Fecha modificación': texto(buscarClave(aud, [/fec.*mod/i])),
      'Origen': reg.directa ? 'consulta por número' : reg.origen,
      'Consulta correcta': textoConsulta(reg),
      'HTTP': texto(reg.http),
      'Intentos': texto(reg.intentos),
      'Consultado en': reg.consultadoEn,
      'Mensaje error': reg.error
    };
    // Columnas dinámicas: todas las propiedades del detalle (los campos nuevos aparecen solos).
    if (reg.detalle) Object.assign(fila, flattenObject(reg.detalle));
    return fila;
  }

  const CAMPOS_BIEN_MAPEADOS = new Set(['numOrden', 'codBien', 'codProductoSunat', 'codSubPartida', 'codGtin', 'desBien',
    'codUniMedida', 'desUniMedida', 'numCantidad', 'indBienRegulado', 'numContenedor', 'numPrecinto']);

  function filasBienes(reg) {
    const b = datosBase(reg);
    const base = {
      'Clave': reg.clave, 'Encontrada por': b.origen.etiquetas, 'Caso': b.origen.casos,
      'RUC emisor': b.ruc, 'Nombre emisor': b.nombreEmisor, 'Serie': b.serie, 'Número': b.num,
      'Guía completa': b.guia, 'Fecha emisión': b.fecEmision, 'Estado': b.estado, 'Motivo traslado': b.motivo,
      'Partida': [b.partida.direccion, b.partida.ubigeo].filter(Boolean).join(' - '),
      'Llegada': [b.llegada.direccion, b.llegada.ubigeo].filter(Boolean).join(' - '),
      'Transportista': [b.transp.numDoc, b.transp.nombre].filter(Boolean).join(' - ')
    };
    if (!reg.ok) return [{ ...base, 'Indicador bienes': reg.origen === 'conocida' ? 'YA_EN_TABLERO' : (reg.procesada ? 'SIN_DETALLE' : 'NO_PROCESADA') }];
    const bienes = obtenerBienes(reg.detalle);
    if (!bienes.length) return [{ ...base, 'Indicador bienes': 'SIN_BIENES' }];

    return bienes.map((bien) => {
      const extra = {};
      for (const [k, v] of Object.entries(flattenObject(bien))) {
        const raiz = k.split(/[.[]/)[0];
        if (!CAMPOS_BIEN_MAPEADOS.has(raiz)) extra['bien.' + k] = v;
      }
      return {
        ...base,
        'Indicador bienes': 'CON_BIENES',
        'N° orden': texto(bien.numOrden),
        'Código bien': texto(bien.codBien),
        'Código producto SUNAT': texto(bien.codProductoSunat),
        'Subpartida': texto(bien.codSubPartida),
        'GTIN': texto(bien.codGtin),
        'Descripción bien': texto(bien.desBien),
        'Unidad medida': texto(bien.codUniMedida),
        'Descripción unidad': texto(bien.desUniMedida),
        'Cantidad': texto(bien.numCantidad),
        'Bien regulado': texto(bien.indBienRegulado),
        'Documento relacionado': textoDeArreglo(bien.docRelacionado),
        'Contenedor': texto(bien.numContenedor),
        'Precinto': texto(bien.numPrecinto),
        'Contenedor vacío': texto(primero(
          buscarClave([bien], [/contenedor.*vac|vac.*contenedor|^indVacio$/i]),
          buscarClave([b.traslado], [/contenedor.*vac|vac.*contenedor/i])
        )),
        ...extra
      };
    });
  }

  const COLUMNAS_BIENES = ['Clave', 'Encontrada por', 'Caso', 'RUC emisor', 'Nombre emisor', 'Serie', 'Número', 'Guía completa',
    'Fecha emisión', 'Estado', 'Motivo traslado', 'Partida', 'Llegada', 'Transportista', 'Indicador bienes', 'N° orden', 'Código bien',
    'Código producto SUNAT', 'Subpartida', 'GTIN', 'Descripción bien', 'Unidad medida', 'Descripción unidad', 'Cantidad', 'Bien regulado',
    'Documento relacionado', 'Contenedor', 'Precinto', 'Contenedor vacío'];

  /* ---------------------------------------------------------------
   * 13. Colecciones (arreglos) en hojas o archivos aparte
   * ------------------------------------------------------------- */
  const ARCHIVO_POR_COLECCION = {
    proveedor: 'GRE_PROVEEDORES', conductor: 'GRE_CONDUCTORES', vehiculo: 'GRE_VEHICULOS',
    contenedores: 'GRE_CONTENEDORES', contenedor: 'GRE_CONTENEDORES', receptorObs: 'GRE_OBSERVACIONES',
    docRelacionado: 'GRE_DOCUMENTOS_RELACIONADOS', docGrePorEvento: 'GRE_DOC_GRE_POR_EVENTO'
  };
  const HOJA_POR_ARCHIVO = {
    GRE_PROVEEDORES: 'Proveedores', GRE_CONDUCTORES: 'Conductores', GRE_VEHICULOS: 'Vehículos',
    GRE_CONTENEDORES: 'Contenedores', GRE_OBSERVACIONES: 'Observaciones', GRE_DOCUMENTOS_RELACIONADOS: 'Documentos relacionados',
    GRE_DOC_GRE_POR_EVENTO: 'GRE por evento'
  };
  // Si estas propiedades vienen como objeto (no arreglo), también se exportan como una fila.
  const OBJETOS_COMO_COLECCION = new Set(['proveedor', 'conductor', 'vehiculo', 'contenedores']);
  const COLUMNAS_COLECCION = ['Clave', 'RUC emisor', 'Serie', 'Número', 'Guía completa', 'Fecha emisión', 'Colección', 'Índice', 'Índice padre'];

  function nombreArchivoColeccion(clave, ruta) {
    return ARCHIVO_POR_COLECCION[clave] || ('GRE_ARR_' + ruta.replace(/\[\]/g, '').replace(/[^A-Za-z0-9]+/g, '_').toUpperCase());
  }

  function recolectarColecciones(reg, salida) {
    const b = datosBase(reg);
    const base = { 'Clave': reg.clave, 'RUC emisor': b.ruc, 'Serie': b.serie, 'Número': b.num, 'Guía completa': b.guia, 'Fecha emisión': b.fecEmision };
    const agregar = (archivo, fila) => {
      if (!salida.has(archivo)) salida.set(archivo, []);
      salida.get(archivo).push(fila);
    };
    const recorrer = (nodo, ruta, indicePadre) => {
      if (!esObjetoPlano(nodo)) return;
      for (const [k, v] of Object.entries(nodo)) {
        const r = ruta ? `${ruta}.${k}` : k;
        if (Array.isArray(v)) {
          const esBien = r === 'traslado.bien';
          v.forEach((elem, i) => {
            const indice = indicePadre ? `${indicePadre}/${i + 1}` : String(i + 1);
            if (!esBien) {
              const fila = { ...base, 'Colección': r, 'Índice': i + 1, 'Índice padre': indicePadre };
              if (esObjetoPlano(elem)) Object.assign(fila, flattenObject(elem));
              else if (esPrimitivo(elem)) fila['valor'] = elem;
              agregar(nombreArchivoColeccion(k, r), fila);
            }
            if (esObjetoPlano(elem)) recorrer(elem, `${r}[]`, indice); // arreglos anidados
          });
        } else if (esObjetoPlano(v)) {
          if (OBJETOS_COMO_COLECCION.has(k)) {
            agregar(nombreArchivoColeccion(k, r), { ...base, 'Colección': r, 'Índice': 1, 'Índice padre': indicePadre, ...flattenObject(v) });
          }
          recorrer(v, r, indicePadre);
        }
      }
    };
    recorrer(reg.detalle, '', '');
  }

  /* ---------------------------------------------------------------
   * 14. Salida: JSON para el tablero, Excel y CSV
   * ------------------------------------------------------------- */
  function unirColumnas(base, filas) {
    const cols = [...base];
    const vistas = new Set(cols);
    for (const f of filas) for (const k of Object.keys(f)) if (!vistas.has(k)) { vistas.add(k); cols.push(k); }
    return cols;
  }

  /** Reúne todos los datos en tablas (filas como objetos), para Excel y CSV. */
  function prepararTablas() {
    const regs = [...estado.resultados.values()];
    const fGuias = regs.map(filaGuia);
    const fBienes = regs.flatMap(filasBienes);
    const colsErr = ['Guía', 'Clave', 'URL', 'Estado HTTP', 'Mensaje', 'Número de intento', 'Fecha y hora', 'Acción tomada'];
    const fErr = estado.errores.map((e) => ({
      'Guía': e.guia, 'Clave': e.clave, 'URL': e.url, 'Estado HTTP': e.estadoHttp, 'Mensaje': e.mensaje,
      'Número de intento': e.intento, 'Fecha y hora': e.fechaHora, 'Acción tomada': e.accion
    }));
    const colsBusq = ['Búsqueda', 'Caso', 'RUC emisor', 'RUC receptor', 'Tipos', 'Desde', 'Hasta', 'Horas', 'Resultado',
      'Guías recibidas', 'Total SUNAT', 'HTTP', 'Mensaje de SUNAT'];
    const fBusq = estado.busquedas.map((b) => ({
      'Búsqueda': b.etiqueta, 'Caso': b.caso, 'RUC emisor': b.rucEmisor, 'RUC receptor': b.rucReceptor,
      'Tipos': b.tipos.split(',').map((t) => TIPOS_GRE[t] || t).join(', '), 'Desde': dmy(b.desde), 'Hasta': dmy(b.hasta),
      'Horas': b.bloques ? b.bloques.split(',').map((x) => TEXTO_BLOQUE[x] || x).join(', ') : '',
      'Resultado': TEXTO_TIPO_BUSQUEDA[b.tipo] || b.tipo, 'Guías recibidas': b.recibidos, 'Total SUNAT': b.total,
      'HTTP': b.estadoHttp, 'Mensaje de SUNAT': b.mensaje
    }));
    const colsCtl = ['Tipo', 'Guía', 'Campo', 'Valor listado', 'Valor detalle', 'Detalle'];
    const fCtl = estado.control.map((c) => ({
      'Tipo': c.tipo, 'Guía': c.guia, 'Campo': c.campo, 'Valor listado': c.valorListado, 'Valor detalle': c.valorDetalle, 'Detalle': c.detalle
    }));
    const colecciones = new Map();
    for (const r of regs) if (r.ok && r.detalle) recolectarColecciones(r, colecciones);
    return {
      guias: { columnas: unirColumnas(COLUMNAS_GUIAS, fGuias), filas: fGuias },
      bienes: { columnas: unirColumnas(COLUMNAS_BIENES, fBienes), filas: fBienes },
      errores: { columnas: colsErr, filas: fErr },
      busquedas: { columnas: colsBusq, filas: fBusq },
      control: { columnas: colsCtl, filas: fCtl },
      colecciones: [...colecciones].map(([nombre, filas]) => ({ nombre, columnas: unirColumnas(COLUMNAS_COLECCION, filas), filas })),
      resumen: estado.resumen || calcularResumen(),
      porBusqueda: resumenPorBusqueda()
    };
  }

  function sufijoArchivos() {
    const cfg = estado.config;
    const marca = marcaTiempo();
    if (!cfg) return `sin_datos_${marca}`;
    const id = String(cfg.pedidoInfo.id || cfg.origen).replace(/[^A-Za-z0-9_-]+/g, '-').slice(0, 40);
    const listados = cfg.busquedas.filter((b) => b.tipo === 'listado');
    if (!listados.length) return `${id}_${marca}`;
    const desde = listados.map((b) => b.desde).sort()[0], hasta = listados.map((b) => b.hasta).sort().slice(-1)[0];
    return `${id}_${desde}_a_${hasta}_${marca}`;
  }

  /**
   * JSON para el tablero: una entrada por guía con su fila del listado (estado actual), su detalle
   * completo (si se descargó) y las búsquedas o casos que la encontraron. Nunca incluye el token.
   */
  function construirJSON() {
    const cfg = estado.config;
    const guias = [...estado.resultados.values()].map((r) => ({
      clave: r.clave,
      estado: r.ok ? 'con_detalle' : r.origen === 'conocida' ? 'ya_en_tablero' : r.noExiste ? 'no_existe' : r.noConsultada ? 'no_consultada'
        : r.procesada ? 'sin_detalle' : 'no_procesada',
      citadaEnFactura: !!r.directa || (estado.origenes.get(r.clave) || []).some((o) => o.citada), // también si la halló una búsqueda
      listado: r.directa || !r.listado ? null : r.listado,
      detalle: r.ok ? r.detalle : null,
      busquedas: estado.origenes.get(r.clave) || [],
      consultadoEn: r.consultadoEn,
      origen: r.origen,
      http: texto(r.http),
      error: r.error
    }));
    return {
      formato: 'GRE_EXTRACTOR_JSON',
      version: VERSION,
      generadoEn: fechaHoraLocal(),
      estadoFinal: estado.motivoFin,
      pedido: cfg ? cfg.pedidoInfo : null,
      parametros: parametrosExportables(cfg),
      busquedas: estado.busquedas,
      guias,
      errores: estado.errores,
      control: estado.control,
      resumen: estado.resumen || calcularResumen()
    };
  }

  // ---------- Excel (.xlsx) sin librerías: ZIP sin compresión + hojas XML ----------
  const TABLA_CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = TABLA_CRC[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  /** Arma un archivo ZIP (método «store», sin compresión). */
  function crearZip(archivos, tipoMime) {
    const enc = new TextEncoder();
    const ahora = new Date();
    const horaDos = (ahora.getHours() << 11) | (ahora.getMinutes() << 5) | Math.floor(ahora.getSeconds() / 2);
    const fechaDos = ((ahora.getFullYear() - 1980) << 9) | ((ahora.getMonth() + 1) << 5) | ahora.getDate();
    const partes = [], central = [];
    let desplazamiento = 0;
    for (const a of archivos) {
      const nombre = enc.encode(a.nombre);
      const datos = a.datos;
      const crc = crc32(datos);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);
      local.setUint16(8, 0, true);
      local.setUint16(10, horaDos, true);
      local.setUint16(12, fechaDos, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, datos.length, true);
      local.setUint32(22, datos.length, true);
      local.setUint16(26, nombre.length, true);
      local.setUint16(28, 0, true);
      partes.push(new Uint8Array(local.buffer), nombre, datos);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true);
      cen.setUint16(4, 20, true);
      cen.setUint16(6, 20, true);
      cen.setUint16(8, 0x0800, true);
      cen.setUint16(10, 0, true);
      cen.setUint16(12, horaDos, true);
      cen.setUint16(14, fechaDos, true);
      cen.setUint32(16, crc, true);
      cen.setUint32(20, datos.length, true);
      cen.setUint32(24, datos.length, true);
      cen.setUint16(28, nombre.length, true);
      cen.setUint16(30, 0, true);
      cen.setUint16(32, 0, true);
      cen.setUint16(34, 0, true);
      cen.setUint16(36, 0, true);
      cen.setUint32(38, 0, true);
      cen.setUint32(42, desplazamiento, true);
      central.push(new Uint8Array(cen.buffer), nombre);
      desplazamiento += 30 + nombre.length + datos.length;
    }
    const tamCentral = central.reduce((s, p) => s + p.length, 0);
    const fin = new DataView(new ArrayBuffer(22));
    fin.setUint32(0, 0x06054b50, true);
    fin.setUint16(4, 0, true);
    fin.setUint16(6, 0, true);
    fin.setUint16(8, archivos.length, true);
    fin.setUint16(10, archivos.length, true);
    fin.setUint32(12, tamCentral, true);
    fin.setUint32(16, desplazamiento, true);
    fin.setUint16(20, 0, true);
    return new Blob([...partes, ...central, new Uint8Array(fin.buffer)], { type: tipoMime });
  }

  const XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
  const NS_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
  const NS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
  const NS_PKG = 'http://schemas.openxmlformats.org/package/2006/relationships';
  const MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

  function escaparXml(s) {
    return String(s).replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '').replace(RE_NO_XML, '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function letraColumna(i) {
    let n = i + 1, s = '';
    while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
    return s;
  }

  /** Celda: los números quedan como números; todo lo demás como texto (conserva ceros a la izquierda). */
  function celdaXml(v, ref, estilo) {
    const s = estilo ? ` s="${estilo}"` : '';
    if (v === null || v === undefined || v === '') return estilo ? `<c r="${ref}"${s}/>` : '';
    if (typeof v === 'number') return Number.isFinite(v) ? `<c r="${ref}"${s}><v>${v}</v></c>` : '';
    if (typeof v === 'boolean') return `<c r="${ref}"${s} t="b"><v>${v ? 1 : 0}</v></c>`;
    let t = sinSaltos(typeof v === 'object' ? texto(v) : String(v));
    if (t.length > 32767) t = t.slice(0, 32767);
    return `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${escaparXml(t)}</t></is></c>`;
  }

  function numColumnas(hoja) {
    let n = hoja.columnas.length;
    for (const f of hoja.filas) if (f.length > n) n = f.length;
    return Math.max(1, n);
  }

  function hojaXml(hoja) {
    const todas = [hoja.columnas, ...hoja.filas];
    const nCols = numColumnas(hoja);
    const letras = [];
    for (let c = 0; c < nCols; c++) letras.push(letraColumna(c));
    const anchos = [];
    for (let c = 0; c < nCols; c++) {
      let max = 0;
      for (let r = 0; r < Math.min(todas.length, 400); r++) {
        const v = todas[r][c];
        const l = v === null || v === undefined ? 0 : String(v).length;
        if (l > max) max = l;
      }
      anchos.push(Math.max(8, Math.min(60, max + 2)));
    }
    const partes = [XML_DECL, `<worksheet xmlns="${NS_MAIN}">`];
    partes.push(hoja.congelar === false
      ? '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
      : '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>');
    partes.push('<cols>' + anchos.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('') + '</cols>');
    partes.push('<sheetData>');
    for (let r = 0; r < todas.length; r++) {
      const fila = todas[r];
      const estilo = r === 0 || (hoja.negritas && hoja.negritas.has(r)) ? 1 : 0;
      let celdas = '';
      for (let c = 0; c < fila.length; c++) celdas += celdaXml(fila[c], letras[c] + (r + 1), estilo);
      partes.push(`<row r="${r + 1}">${celdas}</row>`);
    }
    partes.push('</sheetData>');
    if (hoja.filtro !== false && hoja.filas.length) partes.push(`<autoFilter ref="A1:${letras[nCols - 1]}${todas.length}"/>`);
    partes.push('</worksheet>');
    return partes.join('');
  }

  function nombreHojaUnico(nombre, usados) {
    const base = String(nombre).replace(/[[\]:*?/\\]/g, ' ').trim().slice(0, 31) || 'Hoja';
    let n = base, i = 2;
    while (usados.has(n.toLowerCase())) { const suf = ` ${i++}`; n = base.slice(0, 31 - suf.length) + suf; }
    usados.add(n.toLowerCase());
    return n;
  }

  /** Arma el libro .xlsx con varias hojas. */
  function construirXlsx(hojas) {
    const enc = new TextEncoder();
    const usados = new Set();
    for (const h of hojas) h.nombreFinal = nombreHojaUnico(h.nombre, usados);
    const tipos = XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
      hojas.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('') +
      '</Types>';
    const rels = `${XML_DECL}<Relationships xmlns="${NS_PKG}"><Relationship Id="rId1" Type="${NS_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>`;
    const definidos = hojas.map((h, i) => {
      if (h.filtro === false || !h.filas.length) return '';
      const nombre = h.nombreFinal.replace(/'/g, "''");
      return `<definedName name="_xlnm._FilterDatabase" localSheetId="${i}" hidden="1">${escaparXml(`'${nombre}'!$A$1:$${letraColumna(numColumnas(h) - 1)}$${h.filas.length + 1}`)}</definedName>`;
    }).join('');
    const libro = `${XML_DECL}<workbook xmlns="${NS_MAIN}" xmlns:r="${NS_REL}"><sheets>` +
      hojas.map((h, i) => `<sheet name="${escaparXml(h.nombreFinal)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('') +
      `</sheets>${definidos ? `<definedNames>${definidos}</definedNames>` : ''}</workbook>`;
    const relsLibro = `${XML_DECL}<Relationships xmlns="${NS_PKG}">` +
      hojas.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${NS_REL}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('') +
      `<Relationship Id="rId${hojas.length + 1}" Type="${NS_REL}/styles" Target="styles.xml"/></Relationships>`;
    const estilos = `${XML_DECL}<styleSheet xmlns="${NS_MAIN}">` +
      '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font><font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>' +
      '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FFDCE6F1"/><bgColor indexed="64"/></patternFill></fill></fills>' +
      '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>' +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
      '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>' +
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
    const archivos = [
      { nombre: '[Content_Types].xml', datos: enc.encode(tipos) },
      { nombre: '_rels/.rels', datos: enc.encode(rels) },
      { nombre: 'xl/workbook.xml', datos: enc.encode(libro) },
      { nombre: 'xl/_rels/workbook.xml.rels', datos: enc.encode(relsLibro) },
      { nombre: 'xl/styles.xml', datos: enc.encode(estilos) },
      ...hojas.map((h, i) => ({ nombre: `xl/worksheets/sheet${i + 1}.xml`, datos: enc.encode(hojaXml(h)) }))
    ];
    return crearZip(archivos, MIME_XLSX);
  }

  // Columnas que en Excel conviene tener como número (para sumar u ordenar)
  const COLUMNAS_NUMERICAS = new Set(['Número', 'N° orden', 'Cantidad', 'Peso bruto', 'Bultos/Pallets', 'Cantidad bienes', 'Intentos']);
  const RE_NUMERO_SIMPLE = /^-?(0|[1-9]\d{0,14})(\.\d+)?$/;

  function tablaAHoja(nombre, tabla, opciones = {}) {
    const filas = tabla.filas.map((f) => tabla.columnas.map((c) => {
      const v = f[c];
      if (COLUMNAS_NUMERICAS.has(c) && typeof v === 'string' && RE_NUMERO_SIMPLE.test(v)) return Number(v);
      return v;
    }));
    return { nombre, columnas: tabla.columnas, filas, ...opciones };
  }

  function hojaResumen(tablas) {
    const filas = [
      ['Generado', fechaHoraLocal()],
      ['Versión del extractor', VERSION]
    ];
    for (const [k, v] of Object.entries(tablas.resumen)) filas.push([k.trim(), v]);
    filas.push([]);
    const negritas = new Set([filas.length + 1]); // índice dentro de [encabezado, ...filas]
    filas.push(['Búsqueda', 'Caso', 'Guías encontradas', 'Con detalle', 'Con error', 'No consultados', 'Observación']);
    for (const r of tablas.porBusqueda) filas.push([r.etiqueta, r.caso, r.encontradas, r.ok, r.error, r.noConsultados, r.observacion]);
    return { nombre: 'Resumen', columnas: ['Concepto', 'Valor'], filas, negritas, congelar: false, filtro: false };
  }

  function construirExcel(tablas) {
    const hojas = [hojaResumen(tablas), tablaAHoja('Guías', tablas.guias), tablaAHoja('Bienes', tablas.bienes)];
    for (const col of tablas.colecciones) {
      const ruta = (col.filas[0] && col.filas[0]['Colección']) || col.nombre;
      const nombre = HOJA_POR_ARCHIVO[col.nombre] || String(ruta).replace(/\[\]/g, '').split('.').slice(-2).join(' ');
      hojas.push(tablaAHoja(nombre, col));
    }
    hojas.push(tablaAHoja('Búsquedas', tablas.busquedas));
    if (tablas.errores.filas.length) hojas.push(tablaAHoja('Errores', tablas.errores));
    hojas.push(tablaAHoja('Control', tablas.control));
    return construirXlsx(hojas);
  }

  // ---------- CSV ----------
  /** Celda CSV: sin null/undefined, sin saltos de línea, comillas escapadas y protección anti-fórmulas. */
  function celdaCSV(v) {
    let s;
    if (v === null || v === undefined) s = '';
    else if (typeof v === 'number') s = Number.isFinite(v) ? String(v) : '';
    else if (typeof v === 'boolean') s = v ? 'true' : 'false';
    else if (v instanceof Date) s = isNaN(v.getTime()) ? '' : v.toISOString();
    else if (typeof v === 'object') { try { s = JSON.stringify(v); } catch (_) { s = ''; } }
    else {
      s = sinSaltos(v);
      if (/^[=+\-@]/.test(s)) s = "'" + s; // evita fórmulas inyectadas en Excel
    }
    s = sinSaltos(s);
    return '"' + s.replace(/"/g, '""') + '"';
  }

  function generarCSV(columnas, filas) {
    const lineas = [columnas.map(celdaCSV).join(';')];
    for (const f of filas) lineas.push(columnas.map((c) => celdaCSV(f[c])).join(';'));
    return BOM + lineas.join('\r\n') + '\r\n';
  }

  /** Archivos CSV (opción «Más opciones > CSV»). */
  function construirArchivosCsv(tablas, sufijo) {
    const csv = 'text/csv;charset=utf-8';
    const archivos = [];
    const agregar = (tipo, base, tabla) => archivos.push({
      tipo, nombre: `${base}_${sufijo}.csv`, tipoMime: csv, filas: tabla.filas.length, contenido: generarCSV(tabla.columnas, tabla.filas)
    });
    agregar('guias', 'GRE_GUIAS', tablas.guias);
    agregar('bienes', 'GRE_BIENES', tablas.bienes);
    agregar('errores', 'GRE_ERRORES', tablas.errores);
    agregar('busquedas', 'GRE_BUSQUEDAS', tablas.busquedas);
    const filasControl = Object.entries(tablas.resumen).map(([k, v]) => ({ 'Tipo': 'RESUMEN', 'Guía': '', 'Campo': k.trim(), 'Valor listado': texto(v), 'Valor detalle': '', 'Detalle': '' }));
    agregar('control', 'GRE_CONTROL', { columnas: tablas.control.columnas, filas: [...filasControl, ...tablas.control.filas] });
    for (const col of tablas.colecciones) agregar('adicionales', col.nombre, col);
    return archivos;
  }

  function descargarBlob(nombre, contenido, tipoMime) {
    const blob = contenido instanceof Blob ? contenido : new Blob([contenido], { type: tipoMime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = nombre; a.style.display = 'none';
    (document.body || document.documentElement).appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  /** tipos: 'excel' | 'json' | 'csv' (todos los CSV) | 'guias' | 'bienes' | 'errores' | 'busquedas' | 'control' | 'adicionales' */
  async function descargar(tipo = 'excel') {
    if (!estado.resultados.size && !estado.errores.length && !estado.busquedas.length) { log('Todavía no hay datos para descargar.', 'warn'); return []; }
    const sufijo = sufijoArchivos();
    if (tipo === 'json') {
      try {
        const nombre = `GRE_${sufijo}.json`;
        descargarBlob(nombre, JSON.stringify(construirJSON()), 'application/json;charset=utf-8');
        log(`JSON descargado (para el tablero): ${nombre}`, 'ok');
        return [nombre];
      } catch (e) { log(`No se pudo generar el JSON: ${e.message}`, 'error'); console.error(e); return []; }
    }
    let tablas;
    try { tablas = prepararTablas(); } catch (e) { log(`No se pudieron preparar los datos: ${e.message}`, 'error'); console.error(e); return []; }
    if (tipo === 'excel') {
      try {
        const nombre = `GRE_${sufijo}.xlsx`;
        descargarBlob(nombre, construirExcel(tablas));
        log(`Excel descargado: ${nombre}`, 'ok');
        return [nombre];
      } catch (e) {
        log(`No se pudo generar el Excel: ${e.message}`, 'error');
        console.error(e);
        return [];
      }
    }
    const archivos = construirArchivosCsv(tablas, sufijo);
    const elegidos = tipo === 'csv' || tipo === 'todo' ? archivos : archivos.filter((a) => a.tipo === tipo);
    if (!elegidos.length) { log(`No hay archivos del tipo «${tipo}».`, 'warn'); return []; }
    for (const a of elegidos) {
      try { descargarBlob(a.nombre, a.contenido, a.tipoMime); log(`Descargado: ${a.nombre} (${a.filas} fila(s))`, 'ok'); }
      catch (e) { log(`Descarga bloqueada de ${a.nombre}: ${e.message}`, 'error'); }
      await dormir(450); // pausa para que el navegador no bloquee descargas múltiples
    }
    return elegidos.map((a) => a.nombre);
  }

  /** Contenido de los archivos (alternativa si las descargas están bloqueadas). */
  function exportar() {
    const r = {};
    const sufijo = sufijoArchivos();
    for (const a of construirArchivosCsv(prepararTablas(), sufijo)) r[a.nombre] = a.contenido;
    r[`GRE_${sufijo}.json`] = JSON.stringify(construirJSON());
    return r;
  }

  /* ---------------------------------------------------------------
   * 15. Continuar con un archivo de resultados anterior
   * ------------------------------------------------------------- */
  async function cargarJSONPrevio(fuente) {
    if (estado.ejecutando) { log('No se puede cargar un archivo mientras hay una búsqueda en curso.', 'warn'); return null; }
    try {
      let obj;
      if (typeof Blob !== 'undefined' && fuente instanceof Blob) obj = JSON.parse(await fuente.text());
      else if (typeof fuente === 'string') obj = JSON.parse(fuente);
      else if (fuente && typeof fuente === 'object') obj = fuente;
      else throw new Error('Indique un archivo, texto JSON u objeto.');
      if (esObjetoPlano(obj) && obj.tipo === 'GRE_PEDIDO') throw new Error('ese archivo es una lista del tablero: ábralo con «Abrir archivo de lista».');

      let lista = null;
      if (Array.isArray(obj)) lista = obj;
      else if (obj && Array.isArray(obj.guias)) lista = obj.guias.filter((g) => esObjetoPlano(g) && esObjetoPlano(g.detalle)); // versión 3
      else if (obj && Array.isArray(obj.detalles)) lista = obj.detalles; // versión 2
      if (!lista) throw new Error('formato no reconocido: se esperaba un resultado del extractor.');

      let cargadas = 0, invalidas = 0;
      for (const e of lista) {
        const det = esObjetoPlano(e) && esObjetoPlano(e.detalle) ? e.detalle : (esObjetoPlano(e) ? e : null);
        const clave = esObjetoPlano(e) && typeof e.clave === 'string' && e.clave.trim() ? e.clave.trim() : claveDesdeDetalle(det);
        if (!det || !clave) { invalidas++; continue; }
        estado.previos.set(clave, { detalle: det, consultadoEn: esObjetoPlano(e) ? texto(e.consultadoEn) : '' });
        cargadas++;
      }
      log(`Archivo anterior cargado: ${cargadas} guía(s)${invalidas ? `, ${invalidas} entrada(s) ignorada(s)` : ''}. No se volverán a consultar.`, 'ok');
      actualizarUI();
      return { cargadas, invalidas, total: estado.previos.size };
    } catch (e) {
      log(`No se pudo leer el archivo anterior: ${e.message}`, 'error');
      return null;
    }
  }

  /** Abre el selector de archivos (útil sin panel). */
  function seleccionarJSONPrevio() {
    return new Promise((resolve) => {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = '.json,application/json';
      input.addEventListener('change', async () => {
        const f = input.files && input.files[0];
        resolve(f ? await cargarJSONPrevio(f) : null);
      }, { once: true });
      input.click();
    });
  }

  function limpiarPrevios() {
    if (estado.ejecutando) { log('No se puede limpiar durante una búsqueda.', 'warn'); return; }
    estado.previos.clear();
    log('Se quitó el archivo anterior cargado.', 'ok');
    actualizarUI();
  }

  /** Olvida todo lo obtenido para que la próxima búsqueda consulte todo de nuevo. */
  function olvidarResultados() {
    if (estado.ejecutando) { log('No se puede limpiar durante una búsqueda.', 'warn'); return; }
    estado.resultados = new Map();
    estado.previos.clear();
    estado.memoria = new Map();
    estado.origenes = new Map();
    estado.tareas = []; estado.busquedas = [];
    estado.errores = []; estado.control = []; estado.controlDetalle = [];
    estado.unicos = []; estado.duplicados = [];
    estado.progreso = progresoVacio();
    estado.resumen = null; estado.motivoFin = '';
    estado.tiempos = { inicio: 0, inicioDetalle: 0, fin: 0 };
    log('Se olvidaron los resultados anteriores. La próxima búsqueda consultará todo de nuevo.', 'ok');
    actualizarUI();
  }

  /** Carga una lista del tablero (texto, objeto o archivo). Devuelve true si se cargó. */
  async function cargarLista(fuente) {
    if (estado.ejecutando) { log('No se puede cambiar la lista durante una búsqueda.', 'warn'); return false; }
    try {
      let entrada = fuente;
      if (typeof Blob !== 'undefined' && fuente instanceof Blob) entrada = await fuente.text();
      const p = validarPedido(entrada);
      estado.pedido = typeof entrada === 'string' ? JSON.parse(entrada.slice(entrada.indexOf('{'))) : entrada;
      const resumen = textoResumenLista(p);
      log(`Lista cargada ${resumen}`, 'ok');
      if (ui) { ui.resumenLista.textContent = resumen; ui.resumenLista.className = 'bien'; ui.usarModo('lista'); }
      actualizarUI();
      return true;
    } catch (e) {
      estado.pedido = null;
      const msg = e instanceof ErrorValidacion ? e.message : `No se pudo leer la lista: ${e.message}`;
      log(msg, 'error');
      if (ui) { ui.resumenLista.textContent = msg; ui.resumenLista.className = 'aviso'; }
      actualizarUI();
      return false;
    }
  }

  function quitarLista() {
    estado.pedido = null;
    if (ui) {
      ui.txtLista.value = '';
      ui.resumenLista.textContent = 'Sin lista cargada.';
      ui.resumenLista.className = 'nota';
    }
    actualizarUI();
  }

  /* ---------------------------------------------------------------
   * 16. Conexión con SUNAT: escucha temporal de la pantalla de SUNAT
   *     Toma el token (y las demás cabeceras) de las consultas que la propia
   *     pantalla hace a la API de GRE en esta pestaña. No envía nada a ningún
   *     lado y al terminar deja la página como estaba.
   *     - «manual»: botón «Conectar» (máx. 5 min); si es una búsqueda, copia sus datos.
   *     - «fondo»: durante una búsqueda del extractor, para renovar la conexión sola.
   *     - «diagnostico»: muestra qué consultas hace la pantalla (sin el token).
   * ------------------------------------------------------------- */
  const HOST_API = 'api-intranet.sunat.peru';
  const RUTA_API_GRE = '/v1/contribuyente/gre/';
  const RUTA_LISTADO = '/v1/contribuyente/gre/comprobantes';
  const RE_RUTA_DETALLE = /^\/v1\/contribuyente\/gre\/comprobantes\/[^/]+$/;
  const CAPTURA_MAX_MS = 5 * 60 * 1000;
  const DIAGNOSTICO_MS = 2 * 60 * 1000;
  // Cabeceras que no se copian: el token va aparte y las demás las pone el propio navegador.
  const CABECERAS_NO_COPIABLES = /^(authorization|cookie2?|content-length|host|origin|referer|connection|keep-alive|te|trailer|transfer-encoding|upgrade|via|expect|date|dnt|accept-charset|accept-encoding|set-cookie|proxy-.*|sec-.*|access-control-request-.*)$/i;

  /** Convierte dd/mm/aaaa a aaaa-mm-dd si la aplicación usara ese formato. */
  function normalizarFechaCapturada(valor) {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(valor || '');
    return m ? `${m[3]}-${m[2]}-${m[1]}` : valor;
  }

  /** Convierte cualquier forma de cabeceras (objeto, arreglo o Headers) en { nombre en minúsculas: valor }. */
  function cabecerasComoObjeto(fuente) {
    const r = {};
    try { new Headers(fuente).forEach((v, k) => { r[k.toLowerCase()] = v; }); } catch (_) { /* formato no estándar */ }
    return r;
  }
  function cabecerasDeFetch(input, init) {
    const r = {};
    if (typeof Request !== 'undefined' && input instanceof Request) Object.assign(r, cabecerasComoObjeto(input.headers));
    if (init && init.headers) Object.assign(r, cabecerasComoObjeto(init.headers));
    return r;
  }

  /** Modo diagnóstico: anota cada consulta que hace la pantalla de SUNAT (sin el token ni los parámetros). */
  function anotarDiagnostico(via, metodo, url, conToken) {
    if (!diagnostico.activo) return;
    let u;
    try { u = new URL(String(url), location.href); } catch (_) { return; }
    diagnostico.vistas++;
    const api = u.hostname === HOST_API && u.pathname.startsWith(RUTA_API_GRE);
    if (api) diagnostico.api++;
    if (api && conToken) diagnostico.conToken++;
    log(`Diagnóstico · ${via} ${String(metodo || 'GET').toUpperCase()} ${u.hostname}${u.pathname}${api ? (conToken ? ' · API de guías, con conexión ✓' : ' · API de guías, sin conexión') : ''}`);
  }

  /** Copia al panel los datos de una búsqueda hecha en SUNAT (RUC, rol, tipos, fechas y opciones). */
  function aplicarBusquedaCapturada(u) {
    urlsCapturadas.listado = u.href; // solo la dirección con los filtros (sin token)
    const g = (n) => (u.searchParams.has(n) ? u.searchParams.get(n).trim() : '');
    const re = g('numRucEmisor'), rr = g('numRucReceptor');
    const opciones = {
      tipBusqueda: g('tipBusqueda'), numSerie: g('numSerie'), numCpe: g('numCpe'), codEstado: g('codEstado'), codSubEstado: g('codSubEstado')
    };
    const desde = normalizarFechaCapturada(g('fecEmisionIni')), hasta = normalizarFechaCapturada(g('fecEmisionFin'));
    const ruc = rr || re;
    const rol = rr && !re ? 'receptor' : (re && !rr ? 'emisor' : '');
    const tipos = g('codCpe') ? normalizarTipos(g('codCpe')) : null;
    filtrosCapturados = { ...opciones, ruc, rol, tipos, desde, hasta };
    if (ui) {
      if (ruc && !ui.txtRucs.value.trim()) { ui.txtRucs.value = ruc; ui.txtRucs.dispatchEvent(new Event('input')); }
      if (rol && ui.radios[rol]) ui.radios[rol].checked = true;
      if (tipos) for (const [k, chk] of Object.entries(ui.chkTipos)) chk.checked = tipos.includes(k);
      if (!periodosEditados && parsearFecha(desde) && parsearFecha(hasta)) {
        ui.periodos.splice(0, ui.periodos.length, { desde, hasta });
        ui.pintarPeriodos();
      }
      for (const [k, v] of Object.entries(opciones)) if (v && ui.inputs[k]) ui.inputs[k].value = v;
    }
    const partes = [
      ruc && `RUC ${ruc}${rol ? ` (${TEXTO_ROL[rol]})` : ''}`,
      parsearFecha(desde) && parsearFecha(hasta) && `del ${dmy(desde)} al ${dmy(hasta)}`
    ].filter(Boolean);
    if (partes.length) log(`Se copiaron los datos de su búsqueda en SUNAT a la búsqueda manual: ${partes.join(', ')}.`, 'ok');
  }

  /** Revisa una consulta de la pantalla de SUNAT: si va a la API de GRE con conexión, la toma. */
  function procesarSolicitudApp(metodo, url, cabeceras) {
    if (!captura.activa || !url) return;
    let u;
    try { u = new URL(String(url), location.href); } catch (_) { return; }
    if (u.hostname !== HOST_API || !u.pathname.startsWith(RUTA_API_GRE)) return;
    const m = /^bearer\s+(\S+)$/i.exec(String((cabeceras && cabeceras.authorization) || '').trim());
    if (!m || /^(null|undefined)$/i.test(m[1])) return;

    const extra = {};
    for (const [k, v] of Object.entries(cabeceras || {})) if (!CABECERAS_NO_COPIABLES.test(k)) extra[k] = v;
    const nuevo = m[1] !== tokenCapturado;
    tokenCapturado = m[1];
    cabecerasCapturadas = extra;
    const ruta = u.pathname.replace(/\/+$/, '');
    const esGet = String(metodo || 'GET').toUpperCase() === 'GET';
    if (esGet && RE_RUTA_DETALLE.test(ruta)) urlsCapturadas.detalle = u.href;
    if (esGet && ruta === RUTA_LISTADO) urlsCapturadas.listado = u.href; // forma exacta de la búsqueda de SUNAT (sin token)

    if (captura.modo === 'fondo') { actualizarUI(); return; } // durante una búsqueda: solo la conexión
    if (captura.modo === 'diagnostico') {
      if (nuevo) log(`Conectado con SUNAT ✓${textoVence(tokenCapturado)}.`, 'ok');
      actualizarUI();
      return;
    }
    log(`Conectado con SUNAT ✓${textoVence(tokenCapturado)}.`, 'ok');
    if (esGet && ruta === RUTA_LISTADO) aplicarBusquedaCapturada(u);
    detenerCaptura('listo');
  }

  /** Empieza a escuchar (temporalmente) las consultas de la pantalla de SUNAT. */
  function iniciarCaptura(modo = 'manual') {
    if (captura.activa) {
      if (modo === 'fondo' && captura.modo !== 'fondo') {
        captura.modo = 'fondo';
        clearTimeout(captura.temporizador);
        captura.temporizador = null;
      }
      return;
    }
    if (modo === 'manual' && estado.ejecutando) { log('Durante la búsqueda la conexión se renueva sola.', 'warn'); return; }
    const restauradores = [];

    // XMLHttpRequest (lo que usa la aplicación de SUNAT). Se anotan método, dirección y cabeceras;
    // la conexión se toma en cuanto se fija la cabecera Authorization y, de nuevo, al enviar.
    const protoXHR = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
    if (protoXHR) {
      const datos = new WeakMap(); // xhr -> { metodo, url, cabeceras }
      const openOriginal = protoXHR.open;
      const cabeceraOriginal = protoXHR.setRequestHeader;
      const sendOriginal = protoXHR.send;
      const openEnvuelto = function (metodo, url) {
        try { datos.set(this, { metodo: String(metodo), url: String(url), cabeceras: {} }); } catch (_) { /* ignorar */ }
        return openOriginal.apply(this, arguments);
      };
      const cabeceraEnvuelta = function (nombre, valor) {
        try {
          const d = datos.get(this);
          if (d) {
            const k = String(nombre).toLowerCase();
            d.cabeceras[k] = d.cabeceras[k] ? `${d.cabeceras[k]}, ${valor}` : String(valor);
            if (k === 'authorization') procesarSolicitudApp(d.metodo, d.url, { ...d.cabeceras });
          }
        } catch (_) { /* nunca romper la aplicación */ }
        return cabeceraOriginal.apply(this, arguments);
      };
      const sendEnvuelto = function () {
        try {
          const d = datos.get(this);
          if (d) {
            anotarDiagnostico('XHR', d.metodo, d.url, !!d.cabeceras.authorization);
            procesarSolicitudApp(d.metodo, d.url, d.cabeceras);
          }
        } catch (_) { /* nunca romper la aplicación */ }
        return sendOriginal.apply(this, arguments);
      };
      protoXHR.open = openEnvuelto;
      protoXHR.setRequestHeader = cabeceraEnvuelta;
      protoXHR.send = sendEnvuelto;
      restauradores.push(() => {
        if (protoXHR.open === openEnvuelto) protoXHR.open = openOriginal;
        if (protoXHR.setRequestHeader === cabeceraEnvuelta) protoXHR.setRequestHeader = cabeceraOriginal;
        if (protoXHR.send === sendEnvuelto) protoXHR.send = sendOriginal;
      });
    }

    // fetch (por si la aplicación lo usa)
    const fetchOriginal = window.fetch;
    if (typeof fetchOriginal === 'function') {
      const fetchEnvuelto = function (input, init) {
        try {
          const esRequest = typeof Request !== 'undefined' && input instanceof Request;
          const url = esRequest ? input.url : String(input);
          const metodo = (init && init.method) || (esRequest ? input.method : 'GET');
          const cab = cabecerasDeFetch(input, init);
          anotarDiagnostico('fetch', metodo, url, !!cab.authorization);
          procesarSolicitudApp(metodo, url, cab);
        } catch (_) { /* nunca romper la aplicación */ }
        return fetchOriginal.apply(window, arguments);
      };
      window.fetch = fetchEnvuelto;
      restauradores.push(() => { if (window.fetch === fetchEnvuelto) window.fetch = fetchOriginal; });
    }

    captura.activa = true;
    captura.modo = modo;
    captura.restaurar = () => restauradores.forEach((f) => { try { f(); } catch (_) { /* ignorar */ } });
    if (modo === 'manual') {
      captura.temporizador = setTimeout(() => detenerCaptura('tiempo'), CAPTURA_MAX_MS);
      log('Conectando: en la pantalla de SUNAT abra cualquier guía con «Ver» (o pulse «Buscar»).', 'ok');
    }
    actualizarUI();
  }

  /** Deja de escuchar y restaura la página. */
  function detenerCaptura(motivo) {
    if (!captura.activa) return;
    if (motivo === 'fin' && diagnostico.activo) {
      // La búsqueda terminó pero el diagnóstico sigue: se mantiene la escucha en ese modo.
      captura.modo = 'diagnostico';
      actualizarUI();
      return;
    }
    const eraManual = captura.modo === 'manual';
    captura.activa = false;
    captura.modo = '';
    clearTimeout(captura.temporizador);
    captura.temporizador = null;
    if (captura.restaurar) captura.restaurar();
    captura.restaurar = null;
    if (motivo === 'usuario') log('Conexión cancelada.');
    if (motivo === 'tiempo') log('No se detectó ninguna guía abierta en 5 minutos. Revise que la consola esté en «iframeApplication» y vuelva a pulsar «Conectar».', 'warn');
    if (eraManual && ui && ui.compactar) ui.compactar(false);
    actualizarUI();
  }

  /** Botón «Conectar». */
  function conectar() {
    if (estado.ejecutando) { log('Durante la búsqueda la conexión se renueva sola.', 'warn'); return; }
    if (captura.activa && captura.modo === 'diagnostico') {
      log('El diagnóstico ya está escuchando: abra una guía con «Ver» y la conexión se tomará sola.');
      return;
    }
    iniciarCaptura('manual');
    if (captura.activa && ui && ui.compactar) ui.compactar(true);
  }

  /** Botón «Diagnóstico»: durante 2 minutos muestra qué consultas hace la pantalla de SUNAT. */
  function alternarDiagnostico() {
    if (diagnostico.activo) { terminarDiagnostico(); return; }
    Object.assign(diagnostico, { activo: true, vistas: 0, api: 0, conToken: 0 });
    if (!captura.activa) iniciarCaptura('diagnostico');
    else if (captura.modo === 'manual') { clearTimeout(captura.temporizador); captura.temporizador = null; captura.modo = 'diagnostico'; }
    diagnostico.temporizador = setTimeout(terminarDiagnostico, DIAGNOSTICO_MS);
    log('Diagnóstico activo (2 min): pulse «Buscar» o abra una guía con «Ver» en la pantalla de SUNAT. Aquí se verá cada consulta (sin el token).', 'ok');
    actualizarUI();
  }

  function terminarDiagnostico() {
    if (!diagnostico.activo) return;
    diagnostico.activo = false;
    clearTimeout(diagnostico.temporizador);
    diagnostico.temporizador = null;
    if (captura.activa && captura.modo === 'diagnostico') detenerCaptura('diagnostico');
    if (!diagnostico.vistas) {
      log('Diagnóstico: no se vio ninguna consulta. Revise que la consola esté en «iframeApplication» (intranet.sunat.peru) y que haya pulsado «Buscar» o «Ver».', 'warn');
    } else {
      log(`Diagnóstico terminado: ${diagnostico.vistas} consulta(s) vistas; ${diagnostico.api} a la API de guías, ${diagnostico.conToken} con conexión.${diagnostico.conToken ? ' La conexión se puede tomar ✓' : ''}`, diagnostico.conToken ? 'ok' : 'warn');
    }
    actualizarUI();
  }

  /** Texto y color del indicador de conexión. */
  function estadoConexion() {
    if (estado.ejecutando) {
      if (estado.esperandoConexion) return { clase: 'alerta', texto: 'Abra cualquier guía con «Ver» en la pantalla de SUNAT' };
      if (estado.tokenExp) {
        const resta = estado.tokenExp - Date.now();
        if (resta < 5 * 60000) return { clase: 'espera', texto: `Vence a las ${horaDe(estado.tokenExp)}: abra una guía con «Ver» para renovarla` };
        return { clase: 'ok', texto: `Conectado · vence a las ${horaDe(estado.tokenExp)}` };
      }
      return { clase: 'ok', texto: 'Conectado' };
    }
    if (captura.activa && captura.modo === 'manual') return { clase: 'espera', texto: 'Conectando… abra cualquier guía con «Ver» en SUNAT' };
    if (tokenCapturado) {
      const info = analizarToken(tokenCapturado);
      if (info.exp && info.exp <= Date.now()) return { clase: 'no', texto: 'La conexión venció: pulse «Conectar»' };
      return { clase: 'ok', texto: `Conectado${info.exp ? ` · vence a las ${horaDe(info.exp)}` : ''}` };
    }
    return { clase: 'no', texto: 'Sin conectar (se le pedirá al empezar)' };
  }

  /* ---------------------------------------------------------------
   * 17. Panel flotante (HTML/CSS nativo, Shadow DOM, removible)
   * ------------------------------------------------------------- */
  function h(tag, props = {}, ...hijos) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    }
    for (const c of hijos.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
    return el;
  }

  const CSS = `
    :host{all:initial}
    *{box-sizing:border-box}
    .p{position:fixed;top:10px;right:10px;width:450px;max-width:calc(100vw - 20px);max-height:94vh;display:flex;flex-direction:column;background:#fff;color:#1d2433;
      font:13px/1.4 "Segoe UI",system-ui,sans-serif;border:1px solid #c9d1dc;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.28);z-index:2147483647}
    .hd{display:flex;align-items:center;gap:6px;padding:8px 12px;background:#12355b;color:#fff;border-radius:10px 10px 0 0;cursor:move;user-select:none}
    .hd b{flex:1;font-size:14px}
    .hd small{opacity:.7;font-weight:normal;margin-left:6px;font-size:11px}
    .hd button{background:transparent;color:#fff;border:1px solid rgba(255,255,255,.45);border-radius:4px;width:26px;height:24px;cursor:pointer;padding:0;font-size:14px}
    .franja{display:flex;align-items:center;gap:8px;padding:9px 12px;background:#fff4d6;color:#7a4f00;font-size:13px;border-radius:0 0 10px 10px}
    .bd{overflow:auto;padding:10px 12px}
    .sec{margin-bottom:12px}
    .tit{display:flex;align-items:center;gap:8px;font-weight:600;color:#12355b;margin-bottom:6px}
    .num{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;background:#12355b;color:#fff;font-size:12px}
    .con{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .pill{padding:3px 10px;border-radius:12px;font-size:12px;background:#eef1f5;color:#4a5568}
    .pill.ok{background:#e3f5ec;color:#16653f}
    .pill.espera{background:#fff4d6;color:#8a5a00}
    .pill.alerta{background:#ffe1e1;color:#9b1c1c;font-weight:600;animation:parpadeo 1.2s infinite}
    @keyframes parpadeo{50%{opacity:.55}}
    .seg{display:flex;border:1px solid #12355b;border-radius:6px;overflow:hidden;margin-bottom:8px}
    .seg button{flex:1;border:0;background:#fff;color:#12355b;padding:6px;font:13px "Segoe UI",system-ui,sans-serif;cursor:pointer}
    .seg button.on{background:#12355b;color:#fff;font-weight:600}
    textarea,input{font:13px "Segoe UI",system-ui,sans-serif;padding:5px 7px;border:1px solid #b8c2cf;border-radius:5px;color:#1d2433;background:#fff;width:100%;min-width:0}
    textarea{resize:vertical;min-height:62px}
    .nota{font-size:11.5px;color:#6b7686;margin-top:4px}
    .aviso{font-size:12px;color:#9b1c1c;margin-top:4px}
    .bien{font-size:12px;color:#16653f;margin-top:4px}
    .roles{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:3px;font-size:12.5px}
    .roles label{display:flex;align-items:center;gap:4px;cursor:pointer}
    .roles input,.chk input{width:auto}
    .per{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 32px;gap:6px;align-items:end;margin-bottom:6px}
    .per label{display:flex;flex-direction:column;font-size:11px;color:#4a5568;min-width:0}
    button.b{font:13px "Segoe UI",system-ui,sans-serif;padding:6px 11px;border-radius:5px;border:1px solid #12355b;background:#12355b;color:#fff;cursor:pointer}
    button.s{background:#fff;color:#12355b}
    button.r{background:#a12b2b;border-color:#a12b2b}
    button.x{background:#fff;color:#a12b2b;border-color:#d7b4b4;padding:5px 0;width:32px}
    button.mini{padding:3px 8px;font-size:12px}
    button.grande{width:100%;padding:11px;font-size:15px;font-weight:600;background:#1f8a5b;border-color:#1f8a5b;margin-top:4px}
    button:disabled{opacity:.45;cursor:not-allowed}
    .row{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
    .bar{height:12px;background:#e6ebf1;border-radius:6px;overflow:hidden;margin-top:9px}
    .bar>div{height:100%;width:0;background:#1f8a5b;transition:width .25s}
    .linea{margin-top:6px;font-size:12.5px;min-height:18px}
    .cont{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:6px;font-size:11.5px;text-align:center;color:#4a5568}
    .cont div{background:#f4f6f9;border-radius:6px;padding:5px}
    .cont b{display:block;font-size:16px;color:#12355b}
    .log{margin-top:8px;height:120px;overflow:auto;background:#0f1724;color:#d6dde8;font:11.5px Consolas,monospace;padding:6px;border-radius:5px}
    .l-ok{color:#7ee2a8}.l-warn{color:#ffd479}.l-error{color:#ff8c8c}
    details{margin-top:10px;border-top:1px solid #e3e8ef;padding-top:7px}
    summary{cursor:pointer;color:#12355b;font-weight:600}
    .g{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px 8px;margin-top:7px}
    .g label{display:flex;flex-direction:column;font-size:11px;color:#4a5568;min-width:0}
    .full{grid-column:1/-1}
    .chk{display:flex;align-items:center;gap:6px;font-size:12.5px;margin-top:6px}
    h4{margin:10px 0 3px;font-size:12px;color:#12355b}
  `;

  const CAMPOS_AVANZADOS = [
    ['tipBusqueda', 'Tipo de búsqueda (2 = masiva)', 'text'], ['maxDiasBloque', 'Días máximos por consulta', 'number'],
    ['numSerie', 'Serie', 'text'], ['numCpe', 'Número', 'text'],
    ['codEstado', 'Código estado', 'text'], ['codSubEstado', 'Código subestado', 'text'],
    ['pausaMinMs', 'Pausa mínima (ms)', 'number'], ['pausaMaxMs', 'Pausa máxima (ms)', 'number'],
    ['maxReintentos', 'Reintentos', 'number'], ['timeoutMs', 'Tiempo máx. por solicitud (ms)', 'number']
  ];
  const ETIQUETAS_ROL = { ambos: 'Emisor y receptor', receptor: 'Receptor (destinatario)', emisor: 'Emisor (remitente)' };

  function crearPanel() {
    if (typeof document === 'undefined') return;
    cerrarPanel();
    const D = CONFIG_PREDETERMINADA;
    const cfgPrev = estado.config && estado.config.origen === 'manual' ? estado.config : null;
    const host = h('div', { id: PANEL_ID });
    const root = host.attachShadow({ mode: 'open' });
    try { const hoja = new CSSStyleSheet(); hoja.replaceSync(CSS); root.adoptedStyleSheets = [hoja]; }
    catch (_) { root.append(h('style', { text: CSS })); }

    // 1. Conexión
    const pill = h('span', { class: 'pill' });
    const btnConectar = h('button', {
      class: 'b s', onclick: () => (captura.activa && captura.modo === 'manual' ? detenerCaptura('usuario') : conectar())
    }, '🔗 Conectar');
    const btnDiagnostico = h('button', { class: 'b s', onclick: () => alternarDiagnostico(), title: 'Muestra qué consultas hace la pantalla de SUNAT (sin el token)' }, '🔍 Diagnóstico');

    // 2. Qué buscar: lista del tablero o búsqueda manual
    let modo = estado.config && estado.config.origen === 'manual' ? 'manual' : 'lista';
    const btnModoLista = h('button', { type: 'button', onclick: () => usarModo('lista') }, 'Lista del tablero');
    const btnModoManual = h('button', { type: 'button', onclick: () => usarModo('manual') }, 'Búsqueda manual');

    //   2a. Lista del tablero
    const txtLista = h('textarea', { rows: '3', placeholder: 'Pegue aquí (Ctrl+V) la lista copiada del tablero', spellcheck: 'false' });
    const resumenLista = h('div', { class: 'nota', text: 'Sin lista cargada.' });
    txtLista.addEventListener('input', () => {
      const t = txtLista.value.trim();
      if (!t) { quitarLista(); return; }
      if (!t.endsWith('}')) { // todavía incompleta (se está escribiendo): sin mensajes de error en el registro
        estado.pedido = null;
        resumenLista.textContent = 'Pegue la lista completa, tal como se copió del tablero.';
        resumenLista.className = 'nota';
        actualizarUI();
        return;
      }
      cargarLista(t);
    });
    const fileLista = h('input', { type: 'file', accept: '.json,application/json,.txt', style: 'display:none' });
    fileLista.addEventListener('change', async () => {
      const f = fileLista.files && fileLista.files[0];
      if (f) await cargarLista(f);
      fileLista.value = '';
    });
    const btnAbrirLista = h('button', { class: 'b s mini', onclick: () => fileLista.click() }, '📂 Abrir archivo de lista');
    const btnQuitarLista = h('button', { class: 'b s mini', onclick: () => quitarLista() }, '✕ Quitar lista');
    const cajaLista = h('div', {},
      h('div', { class: 'nota', text: 'En el tablero pulse «Lista del día» o «Buscar guías» en un caso; luego pegue aquí lo copiado.' }),
      txtLista, h('div', { class: 'row' }, btnAbrirLista, btnQuitarLista, fileLista), resumenLista);

    //   2b. Búsqueda manual
    const txtRucs = h('textarea', { rows: '3', placeholder: 'Escriba o pegue los RUC, uno por línea', spellcheck: 'false' });
    txtRucs.value = cfgPrev ? cfgPrev.rucs.join('\n') : '';
    const msgRucs = h('div', { class: 'nota' });
    const revisarRucs = () => {
      const { validos, invalidos } = extraerRucs(txtRucs.value);
      if (!validos.length && !invalidos.length) { msgRucs.className = 'nota'; msgRucs.textContent = 'Puede pegar varios RUC a la vez.'; return; }
      msgRucs.className = invalidos.length ? 'aviso' : 'bien';
      msgRucs.textContent = `${validos.length} RUC válido(s)` + (invalidos.length ? ` · No válidos (revise los dígitos): ${invalidos.join(', ')}` : ' ✓');
    };
    txtRucs.addEventListener('input', revisarRucs);
    const radios = {};
    const grupoRoles = h('div', { class: 'roles' }, ...Object.keys(ETIQUETAS_ROL).map((v) => {
      radios[v] = h('input', { type: 'radio', name: 'gre-rol', value: v });
      return h('label', {}, radios[v], ETIQUETAS_ROL[v]);
    }));
    radios[(cfgPrev && cfgPrev.rol) || D.rol].checked = true;
    const rolSeleccionado = () => Object.keys(radios).find((k) => radios[k].checked) || D.rol;
    const chkTipos = {};
    const grupoTipos = h('div', { class: 'roles' }, ...ORDEN_TIPOS.map((t) => {
      chkTipos[t] = h('input', { type: 'checkbox', checked: !cfgPrev || cfgPrev.tipos.includes(t) });
      return h('label', {}, chkTipos[t], `${TIPOS_GRE[t]} (${t})`);
    }));
    const tiposSeleccionados = () => Object.keys(chkTipos).filter((t) => chkTipos[t].checked);

    const periodos = cfgPrev ? cfgPrev.periodos.map((p) => ({ desde: p.desde, hasta: p.hasta })) : [{ desde: sumarDias(hoyISO(), -1), hasta: hoyISO() }];
    const contPeriodos = h('div');
    const pintarPeriodos = () => {
      contPeriodos.textContent = '';
      periodos.forEach((p, i) => {
        const desde = h('input', { type: 'date', value: p.desde });
        const hasta = h('input', { type: 'date', value: p.hasta });
        const alCambiar = () => { p.desde = desde.value; p.hasta = hasta.value; periodosEditados = true; };
        for (const ev of ['change', 'input']) { desde.addEventListener(ev, alCambiar); hasta.addEventListener(ev, alCambiar); }
        const quitar = h('button', {
          class: 'b x', title: 'Quitar periodo',
          onclick: () => { if (periodos.length > 1) { periodos.splice(i, 1); periodosEditados = true; pintarPeriodos(); } }
        }, '✕');
        contPeriodos.append(h('div', { class: 'per' }, h('label', {}, 'Desde', desde), h('label', {}, 'Hasta', hasta), quitar));
      });
      actualizarUI();
    };
    const fijarPeriodo = (desde, hasta) => { periodos.splice(0, periodos.length, { desde, hasta }); periodosEditados = true; pintarPeriodos(); };
    const btnAgregar = h('button', {
      class: 'b s mini', onclick: () => { periodos.push({ desde: '', hasta: '' }); periodosEditados = true; pintarPeriodos(); }
    }, '+ Agregar periodo');
    const btnAyerHoy = h('button', { class: 'b s mini', onclick: () => fijarPeriodo(sumarDias(hoyISO(), -1), hoyISO()) }, 'Ayer y hoy');
    const btn15 = h('button', { class: 'b s mini', onclick: () => fijarPeriodo(sumarDias(hoyISO(), -14), hoyISO()) }, 'Últimos 15 días');
    const cajaManual = h('div', {},
      txtRucs, msgRucs,
      h('div', { class: 'nota', text: 'En la guía, el RUC es:' }), grupoRoles,
      h('div', { class: 'nota', text: 'Tipos de guía:' }), grupoTipos,
      h('div', { class: 'nota', text: 'Periodos:' }), contPeriodos,
      h('div', { class: 'row' }, btnAgregar, btnAyerHoy, btn15),
      h('div', { class: 'nota', text: 'SUNAT entrega como máximo 100 guías por consulta: el extractor divide los periodos solo.' }));

    function usarModo(m) {
      modo = m;
      btnModoLista.className = m === 'lista' ? 'on' : '';
      btnModoManual.className = m === 'manual' ? 'on' : '';
      cajaLista.style.display = m === 'lista' ? '' : 'none';
      cajaManual.style.display = m === 'manual' ? '' : 'none';
      actualizarUI();
    }

    // Acción y avance
    const btnIniciar = h('button', { class: 'b grande', onclick: () => alIniciar() }, '▶ Buscar y descargar');
    const btnPausa = h('button', { class: 'b s', onclick: () => (estado.pausado ? reanudar() : pausar()) }, '⏸ Pausar');
    const btnDetener = h('button', { class: 'b r', onclick: () => cancelar() }, '■ Detener');
    const btnExcel = h('button', { class: 'b', onclick: () => descargar('excel') }, '⬇ Excel');
    const btnJSON = h('button', { class: 'b s', onclick: () => descargar('json'), title: 'Archivo para el tablero' }, '⬇ JSON');
    const barra = h('div');
    const linea = h('div', { class: 'linea' });
    const cont = {};
    const contador = (k, etiqueta) => { cont[k] = h('b', { text: '0' }); return h('div', {}, cont[k], etiqueta); };

    // Más opciones
    const inputs = {};
    const valores = { ...D, ...(estado.config || {}) };
    const campos = CAMPOS_AVANZADOS.map(([nombre, etiqueta, tipo]) => {
      inputs[nombre] = h('input', { type: tipo, value: texto(valores[nombre]), autocomplete: 'off', spellcheck: 'false' });
      return h('label', {}, etiqueta, inputs[nombre]);
    });
    inputs.token = h('input', { type: 'password', autocomplete: 'off', placeholder: 'Solo si no usa «Conectar»' });
    const chkJSON = h('input', { type: 'checkbox', checked: valores.descargarJSON !== false });
    const chkExcel = h('input', { type: 'checkbox', checked: valores.descargarExcel !== false });
    const fileInput = h('input', { type: 'file', accept: '.json,application/json', style: 'display:none' });
    fileInput.addEventListener('change', async () => {
      const f = fileInput.files && fileInput.files[0];
      if (f) await cargarJSONPrevio(f);
      fileInput.value = '';
    });
    const btn = {
      cargar: h('button', { class: 'b s', onclick: () => fileInput.click() }, '📂 Cargar resultado anterior'),
      limpiar: h('button', { class: 'b s', onclick: () => limpiarPrevios() }, 'Quitar resultado anterior'),
      olvidar: h('button', {
        class: 'b s', onclick: () => {
          const n = [...estado.resultados.values()].filter((r) => r.ok).length;
          if (!n || window.confirm(`Se olvidarán ${n} guía(s) ya obtenidas (descárguelas antes si las necesita). ¿Continuar?`)) olvidarResultados();
        }
      }, 'Empezar de cero'),
      csv: h('button', { class: 'b s', onclick: () => descargar('csv') }, '⬇ CSV')
    };
    const masOpciones = h('details', {},
      h('summary', { text: 'Más opciones' }),
      h('label', { class: 'chk' }, chkJSON, 'Al terminar, descargar el JSON (para el tablero)'),
      h('label', { class: 'chk' }, chkExcel, 'Al terminar, descargar el Excel (para revisar)'),
      h('div', { class: 'g' }, ...campos, h('label', { class: 'full' }, 'Token manual (opcional; solo memoria)', inputs.token)),
      h('h4', { text: 'Continuar con un resultado anterior' }),
      h('div', { class: 'row' }, btn.cargar, btn.limpiar, fileInput),
      h('h4', { text: 'Otras descargas y limpieza' }),
      h('div', { class: 'row' }, btn.csv, btn.olvidar)
    );

    const cuerpo = h('div', { class: 'bd' },
      h('div', { class: 'sec' },
        h('div', { class: 'tit' }, h('span', { class: 'num', text: '1' }), 'Conexión con SUNAT'),
        h('div', { class: 'con' }, pill, btnConectar, btnDiagnostico),
        h('div', { class: 'nota', text: 'Para conectar, abra cualquier guía con «Ver» en la pantalla de SUNAT. Si no lo hace ahora, se le pedirá al empezar.' })),
      h('div', { class: 'sec' },
        h('div', { class: 'tit' }, h('span', { class: 'num', text: '2' }), '¿Qué buscar?'),
        h('div', { class: 'seg' }, btnModoLista, btnModoManual),
        cajaLista, cajaManual),
      btnIniciar,
      h('div', { class: 'row' }, btnPausa, btnDetener, btnExcel, btnJSON),
      h('div', { class: 'bar' }, barra),
      linea,
      h('div', { class: 'cont' }, contador('encontradas', 'guías encontradas'), contador('ok', 'con detalle'), contador('error', 'con error')),
      h('div', { class: 'log' }),
      masOpciones
    );

    // Franja compacta: deja ver la pantalla de SUNAT mientras se espera la conexión
    const franjaTexto = h('span', { style: 'flex:1' });
    const franja = h('div', { class: 'franja', style: 'display:none' }, franjaTexto, h('button', { class: 'b s', onclick: () => compactar(false) }, 'Ver panel'));
    const compactar = (si) => {
      cuerpo.style.display = si ? 'none' : '';
      franja.style.display = si ? '' : 'none';
      actualizarUI();
    };
    const btnMin = h('button', { title: 'Minimizar', onclick: () => compactar(cuerpo.style.display !== 'none') }, '–');
    const btnCerrar = h('button', {
      title: 'Cerrar panel', onclick: () => {
        if (estado.ejecutando) log('El panel se cerró; la búsqueda sigue. Reábralo con GREExtractor.mostrarPanel().', 'warn');
        cerrarPanel();
      }
    }, '×');
    const cabecera = h('div', { class: 'hd' }, h('b', {}, 'Extractor de GRE', h('small', { text: `v${VERSION}` })), btnMin, btnCerrar);
    const panel = h('div', { class: 'p' }, cabecera, franja, cuerpo);
    root.append(panel);
    (document.body || document.documentElement).appendChild(host);

    habilitarArrastre(cabecera, panel);
    ui = {
      host, pill, btnConectar, btnDiagnostico, txtLista, resumenLista, btnAbrirLista, btnQuitarLista, txtRucs, msgRucs, radios, chkTipos,
      periodos, pintarPeriodos, btnAgregar, inputs, btn, btnIniciar, btnPausa, btnDetener, btnExcel, btnJSON, barra, linea, cont,
      franja, franjaTexto, cuerpo, compactar, usarModo, log: cuerpo.querySelector('.log')
    };
    if (estado.pedido) {
      try { resumenLista.textContent = textoResumenLista(validarPedido(estado.pedido)); resumenLista.className = 'bien'; } catch (_) { /* lista anterior no válida */ }
    }
    pintarPeriodos();
    revisarRucs();
    usarModo(modo);

    function alIniciar() {
      const op = { descargarJSON: chkJSON.checked, descargarExcel: chkExcel.checked };
      for (const [nombre] of CAMPOS_AVANZADOS) op[nombre] = inputs[nombre].value;
      if (modo === 'lista') {
        if (!estado.pedido) {
          log('Primero pegue la lista copiada del tablero (o use la búsqueda manual).', 'error');
          txtLista.focus();
          return;
        }
        op.pedido = estado.pedido;
      } else {
        const { validos, invalidos } = extraerRucs(txtRucs.value);
        if (!validos.length) {
          log(invalidos.length ? `Ningún RUC es válido: ${invalidos.join(', ')}. Revise los dígitos.` : 'Escriba al menos un RUC.', 'error');
          txtRucs.focus();
          return;
        }
        if (!tiposSeleccionados().length) { log('Marque al menos un tipo de guía.', 'error'); return; }
        if (invalidos.length && !window.confirm(`Estos RUC no son válidos y se omitirán:\n${invalidos.join(', ')}\n\n¿Continuar con los ${validos.length} RUC válidos?`)) return;
        Object.assign(op, { rucs: validos, rol: rolSeleccionado(), tipos: tiposSeleccionados(), periodos: periodos.map((p) => ({ ...p })) });
      }
      op.token = inputs.token.value;
      inputs.token.value = ''; // borrar el token del campo de inmediato
      iniciarExtraccionGRE(op).catch((e) => log(`Error: ${e.message}`, 'error'));
    }
  }

  function habilitarArrastre(asa, panel) {
    let x0 = 0, y0 = 0, arrastrando = false;
    asa.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      arrastrando = true;
      const r = panel.getBoundingClientRect();
      x0 = e.clientX - r.left; y0 = e.clientY - r.top;
      e.preventDefault();
    });
    const mover = (e) => {
      if (!arrastrando) return;
      panel.style.left = Math.max(0, e.clientX - x0) + 'px';
      panel.style.top = Math.max(0, e.clientY - y0) + 'px';
      panel.style.right = 'auto';
    };
    const soltar = () => { arrastrando = false; };
    document.addEventListener('mousemove', mover);
    document.addEventListener('mouseup', soltar);
    asa._limpiarArrastre = () => { document.removeEventListener('mousemove', mover); document.removeEventListener('mouseup', soltar); };
  }

  function cerrarPanel() {
    if (typeof document === 'undefined') return;
    if (ui && ui.host) {
      const asa = ui.host.shadowRoot && ui.host.shadowRoot.querySelector('.hd');
      if (asa && asa._limpiarArrastre) asa._limpiarArrastre();
    }
    const existente = document.getElementById(PANEL_ID);
    if (existente) existente.remove();
    ui = null;
  }

  function actualizarUI() {
    if (!ui) return;
    const E = estado, P = E.progreso;

    // Conexión
    const c = estadoConexion();
    ui.pill.className = 'pill ' + c.clase;
    ui.pill.textContent = c.texto;
    ui.btnConectar.disabled = E.ejecutando;
    ui.btnConectar.textContent = captura.activa && captura.modo === 'manual' ? '✕ Cancelar' : (tokenCapturado ? '🔗 Volver a conectar' : '🔗 Conectar');
    ui.btnDiagnostico.textContent = diagnostico.activo ? '⏹ Terminar diagnóstico' : '🔍 Diagnóstico';
    ui.franjaTexto.textContent = (E.esperandoConexion || (captura.activa && captura.modo === 'manual'))
      ? '⚠ Abra cualquier guía con «Ver» en la pantalla de SUNAT. Luego todo continúa solo.'
      : c.texto;

    // Botones y campos
    const hay = E.resultados.size > 0 || E.busquedas.length > 0 || E.errores.length > 0;
    ui.btnIniciar.disabled = E.ejecutando;
    ui.btnPausa.disabled = !E.ejecutando;
    ui.btnPausa.textContent = E.pausado ? '▶ Continuar' : '⏸ Pausar';
    ui.btnDetener.disabled = !E.ejecutando;
    ui.btnExcel.disabled = !hay;
    ui.btnJSON.disabled = !hay;
    ui.btn.csv.disabled = !hay;
    ui.btn.cargar.disabled = E.ejecutando;
    ui.btn.limpiar.disabled = E.ejecutando || E.previos.size === 0;
    ui.btn.olvidar.disabled = E.ejecutando || (E.resultados.size === 0 && E.previos.size === 0);
    ui.btnAgregar.disabled = E.ejecutando;
    ui.btnAbrirLista.disabled = E.ejecutando;
    ui.btnQuitarLista.disabled = E.ejecutando || !E.pedido;
    for (const el of ui.cuerpo.querySelectorAll('textarea, .roles input, details input, .per input, .seg button')) el.disabled = E.ejecutando;
    for (const el of ui.cuerpo.querySelectorAll('.per button')) el.disabled = E.ejecutando || ui.periodos.length === 1;

    // Avance
    let pct = 0, textoLinea = '';
    if (E.ejecutando) {
      if (E.esperandoConexion) textoLinea = '⚠ Esperando conexión: abra cualquier guía con «Ver» en la pantalla de SUNAT.';
      else if (E.pausado) textoLinea = '⏸ En pausa.';
      else if (E.fase === 'busqueda') {
        pct = P.diasTotales ? (P.diasHechos / P.diasTotales) * 100 : 0;
        textoLinea = `Buscando guías (${P.tareaActual} de ${P.tareasTotal}) · ${P.busquedaActual}`;
      } else if (E.fase === 'detalle') {
        pct = P.total ? (P.procesadas / P.total) * 100 : 100;
        let eta = '';
        if (P.consultadas > 0 && E.tiempos.inicioDetalle) {
          const porGuia = (Date.now() - E.tiempos.inicioDetalle) / P.consultadas;
          eta = duracion(porGuia * Math.max(0, P.pendientesReales - P.consultadas));
        }
        textoLinea = `Descargando detalle: ${Math.min(P.procesadas + 1, P.total)} de ${P.total}${eta ? ` · faltan ${eta}` : ''}`;
      } else textoLinea = 'Preparando…';
    } else if (E.motivoFin && E.motivoFin !== 'EN_CURSO') {
      pct = E.motivoFin === 'COMPLETADO' ? 100 : (P.total ? (P.procesadas / P.total) * 100 : 0);
      textoLinea = textoMotivo(E.motivoFin) + (E.resumen ? `: ${E.resumen['Guías con detalle']} guía(s) con detalle y ${E.resumen['Total de bienes']} bien(es).` : '.');
    } else textoLinea = 'Pegue la lista del tablero (o use la búsqueda manual) y pulse «Buscar y descargar».';
    ui.barra.style.width = pct.toFixed(1) + '%';
    ui.linea.textContent = textoLinea;
    ui.cont.encontradas.textContent = String(P.encontradas || E.unicos.length || 0);
    ui.cont.ok.textContent = String(P.ok);
    ui.cont.error.textContent = String(P.error);
  }

  // Refresco periódico (hora de vencimiento, tiempo restante) mientras hay actividad
  const refresco = setInterval(() => { if (estado.ejecutando || captura.activa) actualizarUI(); }, 1000);

  /** Elimina el panel, la escucha, los datos en memoria y el objeto global. */
  function destruir() {
    if (estado.ejecutando && estado.controller) estado.controller.abort();
    diagnostico.activo = false;
    clearTimeout(diagnostico.temporizador);
    detenerCaptura('destruir');
    tokenCapturado = null;
    cabecerasCapturadas = null;
    filtrosCapturados = null;
    urlsCapturadas.listado = ''; urlsCapturadas.detalle = '';
    estado.pedido = null;
    clearInterval(refresco);
    cerrarPanel();
    estado.resultados.clear(); estado.previos.clear(); estado.memoria.clear(); estado.origenes.clear();
    estado.errores = []; estado.control = []; estado.controlDetalle = []; estado.busquedas = []; estado.tareas = [];
    try { delete window.GREExtractor; } catch (_) { window.GREExtractor = undefined; }
    console.log('[GRE] Extractor eliminado de la página.');
  }

  /* ---------------------------------------------------------------
   * 18. Objeto de control global (único)
   * ------------------------------------------------------------- */
  window.GREExtractor = {
    version: VERSION,
    iniciar: iniciarExtraccionGRE,
    iniciarExtraccionGRE,
    pausar, reanudar, cancelar,
    conectar,
    capturarDesdeSUNAT: conectar,
    detenerCaptura: () => detenerCaptura('usuario'),
    diagnostico: alternarDiagnostico,
    cargarLista, quitarLista,
    cargarJSONPrevio, seleccionarJSONPrevio, limpiarPrevios, olvidarResultados,
    descargar,
    descargarExcel: () => descargar('excel'),
    descargarJSON: () => descargar('json'),
    exportar,
    construirJSON,
    flattenObject,
    validarRuc: rucValido,
    mostrarPanel: crearPanel, cerrarPanel, destruir,
    get ejecutando() { return estado.ejecutando; },
    get resumen() { return estado.resumen; },
    get errores() { return estado.errores.slice(); },
    get control() { return estado.control.slice(); },
    get busquedas() { return estado.busquedas.map((b) => ({ ...b })); },
    get progreso() {
      return { ...estado.progreso, fase: estado.fase, pausado: estado.pausado, esperandoConexion: estado.esperandoConexion, estado: estado.motivoFin };
    },
    get hayTokenCapturado() { return !!tokenCapturado; },
    get hayLista() { return !!estado.pedido; },
    get filtrosCapturados() { return filtrosCapturados ? { ...filtrosCapturados } : null; },
    get busquedaCapturada() { return urlsCapturadas.listado || null; }, // solo la dirección, sin token
    detallesCorrectos() { return [...estado.resultados.values()].filter((r) => r.ok).map((r) => r.detalle); }
  };

  crearPanel();
  log(`Extractor de GRE v${VERSION} listo.`, 'ok');
  if (origenActual !== ORIGEN_CORRECTO) {
    log('Aviso: este no parece el contexto «iframeApplication» (intranet.sunat.peru). Cámbielo en el selector de contexto de la consola.', 'warn');
  }
})();
