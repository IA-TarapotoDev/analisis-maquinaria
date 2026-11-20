// Extensión «Gestión de Riesgo · SUNAT» — pantalla de SUNAT (mundo de la página, junto al extractor).
// Recibe la lista que manda la página, corre el extractor y devuelve lo obtenido por partes. Cada parte queda en memoria
// hasta que la página confirma que la guardó; si no lo confirma, se vuelve a enviar. Si al final queda algo sin confirmar
// (por ejemplo, se cerró la página), se descarga el JSON completo para cargarlo a mano.
(() => {
  'use strict';
  const X = window.GREExtractor;
  if (!X || !window.__GRE_EXTENSION__ || window.__GRE_PUENTE__) return;
  window.__GRE_PUENTE__ = true;
  const DE = 'gre-ext-isolated', A = 'gre-ext-main';
  const REENVIO_MS = 60000, ESPERA_FINAL_MS = 120000;
  const enviar = (m) => { try { window.postMessage({ ...m, __gre: A }, location.origin); } catch (_) { /* sin destino */ } };
  let corrida = null;   // { id, modulo, n, partes: Map n → { texto, enviada, final }, fin }

  const resumenCorrida = () => (corrida ? { id: corrida.id, modulo: corrida.modulo, partes: corrida.n, pendientes: corrida.partes.size, fin: corrida.fin } : null);
  function informar() {
    let p = null;
    try { p = X.progreso; } catch (_) { /* sin progreso */ }
    const ejecutando = !!X.ejecutando;
    enviar({ tipo: 'estado', version: X.version, ejecutando, conexion: ejecutando ? !(p && p.esperandoConexion) : !!X.hayTokenCapturado,
      progreso: ejecutando || corrida ? p : null, corrida: resumenCorrida() });
  }
  function mandarParte(n, x) {
    x.enviada = Date.now();
    enviar({ tipo: 'parte', id: corrida.id, modulo: corrida.modulo, n, final: x.final, json: x.texto });
  }
  function entregar(json) {
    if (!corrida) return;
    const n = ++corrida.n;
    const x = { texto: JSON.stringify(json), final: !!json.final, enviada: 0 };
    corrida.partes.set(n, x);
    mandarParte(n, x);
  }
  async function iniciar(m) {
    if (X.ejecutando) { enviar({ tipo: 'error', id: m.id, mensaje: 'Ya hay una búsqueda en curso en la pestaña de SUNAT: espere a que termine o deténgala.' }); return; }
    if (corrida && corrida.partes.size) {
      enviar({ tipo: 'error', id: m.id, mensaje: 'La búsqueda anterior tiene partes que la página aún no guardó: espere un momento y vuelva a intentarlo.' });
      return;
    }
    corrida = { id: String(m.id), modulo: String(m.modulo || ''), n: 0, partes: new Map(), fin: null };
    try { X.mostrarPanel(); } catch (_) { /* sin panel */ }
    enviar({ tipo: 'iniciada', id: corrida.id });
    const c = corrida;
    let error = '';
    try {
      const op = m.opciones && typeof m.opciones === 'object' ? m.opciones : {};
      await X.iniciar({ pedido: m.pedido, descargarJSON: false, descargarExcel: false, alEntregar: entregar,
        entregaCadaMs: op.entregaCadaMs, entregaCadaGuias: op.entregaCadaGuias });
    } catch (e) { error = (e && e.message) || String(e); }
    const p = X.progreso || {};
    c.fin = { estado: p.estado || '', error: error || (c.n ? '' : X.ultimoError || '') };
    enviar({ tipo: 'terminada', id: c.id, estado: c.fin.estado, error: c.fin.error, partes: c.n });
    informar();
    // Lo que la página no confirme en 2 minutos se descarga completo (para cargarlo a mano)
    setTimeout(() => {
      if (corrida !== c || !c.partes.size) return;
      try { X.descargarJSON(); } catch (_) { /* sin descarga */ }
      c.partes.clear();
      c.fin.descargado = true;
      informar();
    }, ESPERA_FINAL_MS);
  }

  window.addEventListener('message', (ev) => {
    if (ev.source !== window || !ev.data || ev.data.__gre !== DE) return;
    const m = ev.data;
    if (m.tipo === 'iniciar') iniciar(m);
    else if (m.tipo === 'detener') { if (X.ejecutando && (!corrida || !m.id || String(m.id) === corrida.id)) X.cancelar(); }
    else if (m.tipo === 'recibida') { if (corrida && String(m.id) === corrida.id) corrida.partes.delete(Number(m.n)); }
    else if (m.tipo === 'estado?') {
      informar();
      if (corrida) for (const [n, x] of corrida.partes) mandarParte(n, x);   // la extensión se reconectó: lo pendiente otra vez
    }
  });
  // Cada 3 segundos: el estado (también mantiene despierta a la extensión) y lo que la página no confirmó en un minuto
  setInterval(() => {
    informar();
    if (corrida) for (const [n, x] of corrida.partes) if (Date.now() - x.enviada > REENVIO_MS) mandarParte(n, x);
  }, 3000);
  informar();
})();
