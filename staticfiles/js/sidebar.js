/* Colapsar/expandir el sidebar (persistido) y drawer deslizable en móvil. */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var shell = document.querySelector('.app-shell');
    if (!shell) return;

    var backdrop = document.getElementById('drawerBackdrop');

    // --- Colapsar/expandir en escritorio (persistido) ---
    var collapseToggle = document.getElementById('sidebarCollapseToggle');
    if (localStorage.getItem('sidebarCollapsed') === '1') {
      shell.classList.add('sidebar-collapsed');
    }
    if (collapseToggle) {
      collapseToggle.addEventListener('click', function () {
        var collapsed = shell.classList.toggle('sidebar-collapsed');
        localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
      });
    }

    // --- Drawer móvil ---
    function openDrawer() {
      shell.classList.add('sidebar-mobile-open');
      if (backdrop) backdrop.classList.add('show');
    }
    function closeDrawer() {
      shell.classList.remove('sidebar-mobile-open');
      if (backdrop) backdrop.classList.remove('show');
    }
    var mobileToggle = document.getElementById('sidebarMobileToggle');
    if (mobileToggle) mobileToggle.addEventListener('click', openDrawer);
    if (backdrop) backdrop.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDrawer();
    });
  });
})();
