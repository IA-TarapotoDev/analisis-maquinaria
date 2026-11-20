// Extensión «Gestión de Riesgo · SUNAT» — centro de mensajes.
// Une la pestaña de SUNAT (donde corre el extractor) con la página Gestión de Riesgo. No guarda nada: solo pasa mensajes
// entre las dos pestañas, en memoria, y sabe qué pantalla de SUNAT tiene conexión.
'use strict';
const sunat = new Map();      // puerto de una pantalla de SUNAT → { conexion, ejecutando, visto }
const paginas = new Set();    // puertos de la página
const corridas = new Map();   // id de la búsqueda → puerto de SUNAT que la corre

const resumenSunat = () => {
  const xs = [...sunat.values()];
  return { tipo: 'sunat', abierto: xs.length > 0, conexion: xs.some((x) => x.conexion), ejecutando: xs.some((x) => x.ejecutando) };
};
function aPaginas(m) {
  for (const p of paginas) { try { p.postMessage(m); } catch (_) { paginas.delete(p); } }
}
/** La pantalla de SUNAT con conexión y libre (si hay varias, la última que se reportó). */
function elegirSunat() {
  let mejor = null;
  for (const [p, x] of sunat) if (x.conexion && !x.ejecutando && (!mejor || x.visto > sunat.get(mejor).visto)) mejor = p;
  return mejor;
}
function aSunat(m) {
  const p = m.id ? corridas.get(String(m.id)) : null;
  for (const s of p ? [p] : sunat.keys()) { try { s.postMessage(m); } catch (_) { /* se cerró */ } }
}

chrome.runtime.onConnect.addListener((puerto) => {
  if (puerto.name === 'sunat') {
    sunat.set(puerto, { conexion: false, ejecutando: false, visto: Date.now() });
    puerto.onMessage.addListener((m) => {
      const x = sunat.get(puerto);
      if (!x || !m || typeof m !== 'object') return;
      x.visto = Date.now();
      if (m.tipo === 'estado') {
        const antes = `${x.conexion}|${x.ejecutando}`;
        x.conexion = !!m.conexion;
        x.ejecutando = !!m.ejecutando;
        if (m.corrida && m.corrida.id) corridas.set(String(m.corrida.id), puerto);
        // A la página solo le interesa la pantalla que corre una búsqueda o tiene conexión
        if (m.ejecutando || m.conexion || (m.corrida && m.corrida.id)) aPaginas(m);
        if (antes !== `${x.conexion}|${x.ejecutando}`) aPaginas(resumenSunat());
        return;
      }
      if (m.id) corridas.set(String(m.id), puerto);
      aPaginas(m);
    });
    puerto.onDisconnect.addListener(() => {
      sunat.delete(puerto);
      for (const [id, p] of corridas) if (p === puerto) corridas.delete(id);
      aPaginas(resumenSunat());
    });
    return;
  }
  if (puerto.name === 'pagina') {
    paginas.add(puerto);
    puerto.onMessage.addListener((m) => {
      if (!m || typeof m !== 'object') return;
      if (m.tipo === 'iniciar') {
        const s = elegirSunat();
        if (!s) {
          puerto.postMessage({ tipo: 'error', id: m.id, mensaje: sunat.size
            ? 'SUNAT está abierto, pero todavía no tiene conexión: en la pantalla de consulta de guías, pulse «Buscar» o abra una guía con «Ver».'
            : 'No hay una pantalla de SUNAT abierta: entre a SUNAT Operaciones en Línea y abra la consulta de guías de remisión.' });
          return;
        }
        corridas.set(String(m.id), s);
        s.postMessage(m);
        return;
      }
      if (m.tipo === 'estado?') { puerto.postMessage(resumenSunat()); return; }
      if (m.tipo === 'detener' || m.tipo === 'recibida') aSunat(m);
    });
    puerto.onDisconnect.addListener(() => paginas.delete(puerto));
    puerto.postMessage(resumenSunat());
  }
});
