// Extensión «Gestión de Riesgo · SUNAT»: avisa al extractor (que se carga justo después) que corre dentro de la extensión.
// Así no muestra su panel al abrir la pantalla y toma la conexión (token) de la propia pantalla de SUNAT, solo en memoria.
window.__GRE_EXTENSION__ = true;
