/* Toggle de modo oscuro/claro. La decisión inicial (antes del primer
   pintado) la toma un pequeño script inline en <head> de base.html — acá
   solo se maneja el click del botón y su persistencia. */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('themeToggle');
    if (!toggle) return;

    toggle.addEventListener('click', function () {
      var root = document.documentElement;
      var isDark = root.getAttribute('data-theme') === 'dark';
      var next = isDark ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      if (window.refreshIcons) window.refreshIcons();
    });
  });
})();
