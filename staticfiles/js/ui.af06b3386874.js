/* Glue de UX menor que no amerita su propio archivo. La mayoría del
   filtrado/búsqueda/paginación ya viaja por querystring de Django (ver
   customer_list.html y similares) — acá solo van mejoras puramente
   visuales que no dependen de esa lógica. */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    // Atajo de teclado "/" para enfocar el buscador del header.
    var searchInput = document.querySelector('.header-search input');
    if (searchInput) {
      document.addEventListener('keydown', function (e) {
        if (e.key === '/' && document.activeElement !== searchInput &&
            !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
          e.preventDefault();
          searchInput.focus();
        }
      });
    }

    // Cierra alertas dismissable al hacer click en su botón .btn-close.
    document.querySelectorAll('.alert .btn-close').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var alert = btn.closest('.alert');
        if (alert) alert.remove();
      });
    });

    // Ripple: círculo que se expande desde el punto de click, en cualquier
    // .btn o .row-action-btn — ver .ripple-effect en animations.css.
    document.addEventListener('click', function (e) {
      var target = e.target.closest('.btn, .row-action-btn');
      if (!target || target.disabled) return;

      target.classList.add('ripple-surface');
      var rect = target.getBoundingClientRect();
      var size = Math.max(rect.width, rect.height);
      var ripple = document.createElement('span');
      ripple.className = 'ripple-effect';
      ripple.style.width = ripple.style.height = size + 'px';
      ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
      ripple.style.top = (e.clientY - rect.top - size / 2) + 'px';
      target.appendChild(ripple);
      ripple.addEventListener('animationend', function () { ripple.remove(); });
    });
  });
})();
