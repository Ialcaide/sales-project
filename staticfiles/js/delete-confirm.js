/* Modal de confirmación de borrado compartido (templates/partials/delete_modal.html).
   Cualquier botón con data-bs-toggle="modal" data-bs-target="#deleteModal"
   data-delete-url="..." data-delete-label="..." rellena y abre el modal —
   el POST real lo sigue haciendo el mismo formulario/URL de siempre
   (mismas vistas Django, sin cambios). La mecánica de apertura/cierre
   (foco, ESC, backdrop) sigue siendo de bootstrap.bundle.min.js. */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var modalEl = document.getElementById('deleteModal');
    if (!modalEl) return;

    var form = modalEl.querySelector('#deleteModalForm');
    var labelEl = modalEl.querySelector('#deleteModalLabel');

    modalEl.addEventListener('show.bs.modal', function (event) {
      var trigger = event.relatedTarget;
      if (!trigger) return;
      var url = trigger.getAttribute('data-delete-url');
      var label = trigger.getAttribute('data-delete-label') || 'este elemento';
      if (form && url) form.setAttribute('action', url);
      if (labelEl) labelEl.textContent = label;
    });
  });
})();
