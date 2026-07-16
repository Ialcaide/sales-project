/* Inicializa los íconos Lucide (data-lucide="...") en toda la página, y
   expone window.refreshIcons() para volver a llamarlo tras inyectar DOM
   dinámico (ej. filas nuevas de un formset). */
(function () {
  function render() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }
  window.refreshIcons = render;
  document.addEventListener('DOMContentLoaded', render);
})();
