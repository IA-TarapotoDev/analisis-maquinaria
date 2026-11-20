// Extensión «Gestión de Riesgo · SUNAT» — pantalla de SUNAT (mundo aislado).
// Pasa mensajes entre el extractor (mundo de la página) y el centro de la extensión. No guarda nada.
(() => {
  'use strict';
  const DE_MAIN = 'gre-ext-main', A_MAIN = 'gre-ext-isolated';
  let puerto = null, apagado = false;
  const aMain = (m) => window.postMessage({ ...m, __gre: A_MAIN }, location.origin);
  function conectar() {
    if (apagado) return;
    try {
      puerto = chrome.runtime.connect({ name: 'sunat' });
    } catch (_) {
      puerto = null;
      // La extensión se actualizó o se quitó: esta pestaña ya no puede hablarle (hay que recargarla)
      if (!chrome.runtime || !chrome.runtime.id) { apagado = true; return; }
      setTimeout(conectar, 2000);
      return;
    }
    puerto.onMessage.addListener((m) => { if (m && typeof m === 'object') aMain(m); });
    puerto.onDisconnect.addListener(() => { puerto = null; setTimeout(conectar, 1000); });
    aMain({ tipo: 'estado?' });   // el extractor se anuncia (y reenvía lo que la página aún no confirmó)
  }
  window.addEventListener('message', (ev) => {
    if (ev.source !== window || !ev.data || ev.data.__gre !== DE_MAIN) return;
    const { __gre, ...m } = ev.data;
    if (!puerto) return;   // sin conexión con la extensión: el extractor vuelve a enviar lo pendiente
    try { puerto.postMessage(m); } catch (_) { puerto = null; setTimeout(conectar, 1000); }
  });
  conectar();
})();
