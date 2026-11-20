// Extensión «Gestión de Riesgo · SUNAT» — página Gestión de Riesgo (mundo aislado).
// Pasa mensajes entre la página y el centro de la extensión. No guarda nada: la página guarda lo recibido, cifrado.
(() => {
  'use strict';
  const DE_PAG = 'gre-pagina', A_PAG = 'gre-extension';
  const version = chrome.runtime.getManifest().version;
  let puerto = null, apagado = false;
  const aPagina = (m) => window.postMessage({ ...m, __gre: A_PAG }, location.origin);
  function conectar() {
    if (apagado) return;
    try {
      puerto = chrome.runtime.connect({ name: 'pagina' });
    } catch (_) {
      puerto = null;
      if (!chrome.runtime || !chrome.runtime.id) { apagado = true; aPagina({ tipo: 'adios' }); return; }
      setTimeout(conectar, 2000);
      return;
    }
    puerto.onMessage.addListener((m) => { if (m && typeof m === 'object') aPagina(m); });
    puerto.onDisconnect.addListener(() => { puerto = null; setTimeout(conectar, 1000); });
    puerto.postMessage({ tipo: 'estado?' });
  }
  window.addEventListener('message', (ev) => {
    if (ev.source !== window || !ev.data || ev.data.__gre !== DE_PAG) return;
    const { __gre, ...m } = ev.data;
    // La página ya cargó: se le contesta y se le manda el estado de SUNAT (lo que llegó antes se perdió)
    if (m.tipo === 'hola') { aPagina({ tipo: 'hola', version }); if (puerto) { try { puerto.postMessage({ tipo: 'estado?' }); } catch (_) { /* se reconecta */ } } return; }
    if (!puerto) { if (m.tipo === 'iniciar') aPagina({ tipo: 'error', id: m.id, mensaje: 'La extensión se está reconectando: intente otra vez en unos segundos.' }); return; }
    try { puerto.postMessage(m); } catch (_) { puerto = null; setTimeout(conectar, 1000); }
  });
  conectar();
  aPagina({ tipo: 'hola', version });
})();
