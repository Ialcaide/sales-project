/* Wizard de 3 pasos de billing/templates/billing/invoice_form.html (Cliente
   -> Detalles -> Facturación). Sigue siendo UN solo <form> con un solo POST
   al final, exactamente igual que antes de tener pasos — los "pasos" son
   solo una capa visual encima del mismo DOM/campos de siempre; toda la
   validación de negocio real (duplicados, stock, crédito, caja abierta)
   sigue viviendo en el servidor (billing/views.py -> invoice_create).
   Los datos vienen embebidos en window.INVOICE_WIZARD_DATA (ver el
   <script> inline justo antes de este archivo en invoice_form.html). */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var data = window.INVOICE_WIZARD_DATA;
    if (!data) return;

    var PRODUCTS = data.products;
    var CUSTOMERS = data.customers;
    var IVA_FRACCION = data.ivaFraccion;
    var formIndex = data.formIndex;
    var invoiceForm = document.getElementById('invoice-form');

    /* ---------- Navegación entre pasos ---------- */

    var stepEls = Array.prototype.slice.call(document.querySelectorAll('.wizard-step'));
    var indicatorEls = Array.prototype.slice.call(document.querySelectorAll('.wizard-step-item'));
    var connectorEls = Array.prototype.slice.call(document.querySelectorAll('.wizard-step-connector'));

    function goToStep(n) {
      stepEls.forEach(function (el) {
        el.classList.toggle('d-none-force', String(el.dataset.step) !== String(n));
      });
      indicatorEls.forEach(function (el) {
        var step = parseInt(el.dataset.stepIndicator, 10);
        el.classList.toggle('is-active', step === n);
        el.classList.toggle('is-done', step < n);
      });
      connectorEls.forEach(function (el) {
        var step = parseInt(el.dataset.connector, 10);
        el.classList.toggle('is-done', step < n);
      });
      if (window.refreshIcons) window.refreshIcons();
      window.scrollTo({ top: invoiceForm.offsetTop - 20, behavior: 'smooth' });
    }

    function tieneProductoValido() {
      return Array.prototype.some.call(document.querySelectorAll('.detail-row'), function (row) {
        var sel = row.querySelector('.product-select');
        return sel && sel.value;
      });
    }

    document.querySelectorAll('[data-wizard-next]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = parseInt(btn.dataset.wizardNext, 10);
        if (target === 2) {
          var consumidorFinal = document.getElementById(data.consumidorFinalId);
          var customerSelect = document.getElementById('id_customer');
          if (!consumidorFinal.checked && !customerSelect.value) {
            alert('Selecciona un cliente o marca la opción "Consumidor Final" antes de continuar.');
            return;
          }
        } else if (target === 3) {
          if (!tieneProductoValido()) {
            alert('Agrega al menos un producto antes de continuar.');
            return;
          }
        }
        goToStep(target);
      });
    });

    document.querySelectorAll('[data-wizard-back]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        goToStep(parseInt(btn.dataset.wizardBack, 10));
      });
    });

    /* Si la vista re-renderiza con errores (validación de negocio o de
       formulario), saltar directo al paso donde vive el campo con error en
       vez de resetear siempre al paso 1. */
    (function jumpToStepWithErrors() {
      var step3Fields = ['id_tipo_pago', 'id_forma_pago', 'id_monto_recibido',
        'id_meses_credito', 'id_tarjeta_titular', 'id_tarjeta_ultimos_digitos', 'id_tarjeta_expiracion'];
      var hasStep3Error = step3Fields.some(function (id) {
        var el = document.getElementById(id);
        if (!el) return false;
        var wrapper = el.closest('.mb-3') || el.parentElement;
        return wrapper && wrapper.querySelector('.text-danger');
      });
      if (hasStep3Error) { goToStep(3); return; }

      var detailsTable = document.getElementById('details-table');
      var hasStep2Error = detailsTable && detailsTable.querySelector('.text-danger');
      var alertBox = document.querySelector('.alert-danger, .alert-warning');
      var alertText = alertBox ? alertBox.textContent.toLowerCase() : '';
      var mentionsStep2 = /product|stock|duplicad/.test(alertText);
      var mentionsStep3 = /efectivo|tarjeta|caja|cr[ée]dito|monto/.test(alertText);
      if (mentionsStep3) { goToStep(3); return; }
      if (hasStep2Error || mentionsStep2) { goToStep(2); return; }

      var customerError = document.getElementById('customer-select-wrapper').querySelector('.text-danger');
      if (customerError) { goToStep(1); }
    })();

    /* ---------- Consumidor Final ---------- */

    var consumidorFinalCheckbox = document.getElementById(data.consumidorFinalId);
    var customerSelectWrapper = document.getElementById('customer-select-wrapper');
    var tipoPagoSelect = document.getElementById('id_tipo_pago');
    var creditoOption = tipoPagoSelect ? tipoPagoSelect.querySelector('option[value="credito"]') : null;

    function toggleConsumidorFinal() {
      var activo = consumidorFinalCheckbox.checked;
      customerSelectWrapper.classList.toggle('d-none-force', activo);
      if (activo) {
        tipoPagoSelect.value = 'contado';
        if (creditoOption) creditoOption.disabled = true;
      } else if (creditoOption) {
        creditoOption.disabled = false;
      }
      toggleFormaPago();
      toggleMesesCredito();
    }
    consumidorFinalCheckbox.addEventListener('change', toggleConsumidorFinal);

    /* ---------- Forma de pago / meses de crédito / tarjeta ---------- */

    var formaPagoWrapper = document.getElementById('forma-pago-wrapper');
    var formaPagoSelect = document.getElementById('id_forma_pago');
    var tarjetaWrapper = document.getElementById('tarjeta-wrapper');

    function toggleFormaPago() {
      if (tipoPagoSelect.value === 'contado') {
        formaPagoWrapper.classList.remove('d-none-force');
      } else {
        formaPagoWrapper.classList.add('d-none-force');
        formaPagoSelect.value = '';
      }
      montoConfirmado = false;
      toggleTarjetaCampos();
    }
    tipoPagoSelect.addEventListener('change', toggleFormaPago);

    function toggleTarjetaCampos() {
      tarjetaWrapper.classList.toggle('d-none-force', formaPagoSelect.value !== 'tarjeta');
    }
    formaPagoSelect.addEventListener('change', toggleTarjetaCampos);

    var mesesCreditoWrapper = document.getElementById('meses-credito-wrapper');
    var mesesCreditoInput = document.getElementById('id_meses_credito');
    function toggleMesesCredito() {
      if (tipoPagoSelect.value === 'credito') {
        mesesCreditoWrapper.classList.remove('d-none-force');
      } else {
        mesesCreditoWrapper.classList.add('d-none-force');
        mesesCreditoInput.value = '';
      }
    }
    tipoPagoSelect.addEventListener('change', toggleMesesCredito);

    toggleConsumidorFinal();

    /* ---------- Cartel de "monto recibido / cambio" (pago en efectivo) ---------- */

    var montoRecibidoInput = document.getElementById('id_monto_recibido');
    var montoModalEl = document.getElementById('montoRecibidoModal');
    var montoModal = new bootstrap.Modal(montoModalEl);
    var modalTotal = document.getElementById('modal-total');
    var modalMontoInput = document.getElementById('modal-monto-input');
    var modalFeedback = document.getElementById('modal-feedback');
    var montoConfirmado = false;

    formaPagoSelect.addEventListener('change', function () { montoConfirmado = false; });

    var currentTotal = 0;
    function getTotalActual() {
      return currentTotal;
    }

    function actualizarFeedbackModal() {
      var total = getTotalActual();
      var monto = parseFloat(modalMontoInput.value) || 0;
      if (monto <= 0) {
        modalFeedback.textContent = '';
        modalFeedback.className = 'mt-2 small';
      } else if (monto < total) {
        modalFeedback.textContent = 'Aún falta $' + (total - monto).toFixed(2) + ' por completar.';
        modalFeedback.className = 'mt-2 small text-danger fw-bold';
      } else {
        modalFeedback.textContent = 'Cambio a devolver: $' + (monto - total).toFixed(2);
        modalFeedback.className = 'mt-2 small text-success fw-bold';
      }
    }
    modalMontoInput.addEventListener('input', actualizarFeedbackModal);

    document.getElementById('modal-confirmar').addEventListener('click', function () {
      var total = getTotalActual();
      var monto = parseFloat(modalMontoInput.value) || 0;
      if (monto < total) {
        actualizarFeedbackModal();
        modalMontoInput.focus();
        return;
      }
      montoRecibidoInput.value = monto.toFixed(2);
      montoConfirmado = true;
      montoModal.hide();
      invoiceForm.submit();
    });

    document.getElementById('modal-cancelar').addEventListener('click', function () {
      montoModal.hide();
    });

    invoiceForm.addEventListener('submit', function (e) {
      if (formaPagoSelect.value === 'efectivo' && !montoConfirmado) {
        e.preventDefault();
        modalTotal.textContent = '$' + getTotalActual().toFixed(2);
        modalMontoInput.value = montoRecibidoInput.value || '';
        actualizarFeedbackModal();
        montoModal.show();
      }
    });

    /* ---------- Panel de información del cliente ---------- */

    document.getElementById('id_customer').addEventListener('change', function () {
      var cid = this.value;
      var info = document.getElementById('customer-info');
      if (cid && CUSTOMERS[cid]) {
        var c = CUSTOMERS[cid];
        document.getElementById('c-dni').value = c.dni;
        document.getElementById('c-first').value = c.first_name;
        document.getElementById('c-last').value = c.last_name;
        document.getElementById('c-email').value = c.email;
        document.getElementById('c-phone').value = c.phone;
        document.getElementById('c-address').value = c.address;
        document.getElementById('c-credito').value = '$' + c.credito_disponible.toFixed(2);
        info.classList.remove('d-none-force');
      } else {
        info.classList.add('d-none-force');
      }
    });

    /* ---------- Líneas de producto (paso 2) ---------- */

    function calcRow(row) {
      var qty = parseFloat(row.querySelector('.quantity-input').value) || 0;
      var price = parseFloat(row.querySelector('.price-input').value) || 0;
      var sub = qty * price;
      row.querySelector('.subtotal-cell').textContent = '$' + sub.toFixed(2);
      return sub;
    }

    function calcTotals() {
      var subtotal = 0;
      document.querySelectorAll('.detail-row').forEach(function (row) {
        subtotal += calcRow(row);
      });
      var tax = subtotal * IVA_FRACCION;
      var total = subtotal + tax;
      currentTotal = total;
      document.getElementById('summary-subtotal').textContent = '$' + subtotal.toFixed(2);
      document.getElementById('summary-tax-label').textContent = 'IVA (' + Math.round(IVA_FRACCION * 100) + '%):';
      document.getElementById('summary-tax').textContent = '$' + tax.toFixed(2);
      document.getElementById('summary-total').textContent = '$' + total.toFixed(2);
      var step3Recap = document.getElementById('step3-total-recap');
      if (step3Recap) step3Recap.textContent = '$' + total.toFixed(2);
    }

    /* Evita elegir el mismo producto en dos filas: deshabilita en cada
       <select> las opciones que ya están elegidas en OTRA fila. Es pura
       UX — el rechazo real y definitivo sigue siendo 100% del servidor
       (ver billing/views.py -> invoice_create). */
    function refreshProductAvailability() {
      var rows = Array.prototype.slice.call(document.querySelectorAll('.detail-row'));
      var selectedByRow = rows.map(function (row) {
        var sel = row.querySelector('.product-select');
        return sel ? sel.value : '';
      });
      rows.forEach(function (row, idx) {
        var sel = row.querySelector('.product-select');
        if (!sel) return;
        var takenElsewhere = {};
        selectedByRow.forEach(function (v, i) {
          if (i !== idx && v) takenElsewhere[v] = true;
        });
        Array.prototype.forEach.call(sel.options, function (opt) {
          if (!opt.value) return;
          opt.disabled = !!takenElsewhere[opt.value];
        });
      });
    }

    function initSelect2(sel) {
      $(sel).select2({
        placeholder: 'Escribe para buscar producto...',
        allowClear: true,
        width: '100%'
      }).on('change', function () {
        var pid = $(this).val();
        var row = $(this).closest('tr')[0];
        var priceInput = row.querySelector('.price-input');
        var stockInfo = row.querySelector('.stock-info');
        var productMeta = row.querySelector('.product-meta');
        var productThumb = row.querySelector('.product-thumb');
        if (pid && PRODUCTS[pid]) {
          var p = PRODUCTS[pid];
          priceInput.value = p.price.toFixed(2);
          stockInfo.textContent = 'Stock disponible: ' + p.stock;
          productMeta.textContent = (p.brand ? p.brand + ' — ' : '') + (p.barcode || 'Sin código de barras');
          if (p.image_url) {
            productThumb.src = p.image_url;
            productThumb.classList.remove('d-none-force');
          } else {
            productThumb.classList.add('d-none-force');
          }
        } else {
          priceInput.value = '';
          stockInfo.textContent = '';
          productMeta.textContent = '';
          productThumb.classList.add('d-none-force');
        }
        calcTotals();
        refreshProductAvailability();
      });
    }

    function bindProductSelect(row) {
      var sel = row.querySelector('.product-select');
      initSelect2(sel);

      row.querySelector('.quantity-input').addEventListener('input', function () {
        if (this.value < 1 || this.value === '') this.value = 1;
        calcTotals();
      });

      row.querySelector('.remove-row').addEventListener('click', function () {
        row.remove();
        calcTotals();
        refreshProductAvailability();
      });
    }

    document.querySelectorAll('.detail-row').forEach(function (row) { bindProductSelect(row); });
    calcTotals();
    refreshProductAvailability();

    /* addProductRow: la comparte el botón "+ Agregar Producto" (sin
       producto preseleccionado) y la búsqueda rápida / código de barras
       (con productId ya resuelto) — así no hay dos copias del HTML de la
       fila. */
    function addProductRow(productId) {
      var tbody = document.getElementById('formset-body');
      var row = document.createElement('tr');
      row.className = 'detail-row';
      row.innerHTML =
        '<td>' +
          '<input type="hidden" name="details-' + formIndex + '-id" value="">' +
          '<div class="d-flex align-items-center gap-2">' +
            '<img class="img-thumb-sm product-thumb d-none-force" src="" alt="">' +
            '<div class="flex-grow-1">' +
              '<select name="details-' + formIndex + '-product" class="form-select product-select">' +
                '<option value="">Escribe para buscar producto...</option>' +
                Object.keys(PRODUCTS).map(function (id) {
                  return '<option value="' + id + '">' + PRODUCTS[id].name + '</option>';
                }).join('') +
              '</select>' +
              '<small class="text-muted stock-info d-block"></small>' +
              '<small class="text-muted product-meta d-block"></small>' +
            '</div>' +
          '</div>' +
        '</td>' +
        '<td><input type="number" name="details-' + formIndex + '-quantity" class="form-control quantity-input" value="1" min="1"></td>' +
        '<td><input type="number" name="details-' + formIndex + '-unit_price" class="form-control price-input" step="0.01" readonly></td>' +
        '<td class="text-end fw-bold subtotal-cell">$0.00</td>' +
        '<td class="text-center"><button type="button" class="btn btn-danger btn-sm btn-icon-only remove-row">✕</button></td>';
      tbody.appendChild(row);
      bindProductSelect(row);
      document.getElementById('id_details-TOTAL_FORMS').value = ++formIndex;
      if (productId) {
        $(row.querySelector('.product-select')).val(String(productId)).trigger('change');
      }
      if (window.refreshIcons) window.refreshIcons();
      return row;
    }

    document.getElementById('add-row').addEventListener('click', function () {
      addProductRow(null);
    });

    /* Búsqueda rápida / escáner de código de barras: un lector USB de
       código de barras funciona como un teclado que "escribe" el código y
       presiona Enter solo — por eso basta con escuchar el evento Enter en
       un input normal, sin necesitar ninguna librería ni hardware especial
       para probarlo. */
    document.getElementById('quick-search').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      var query = this.value.trim().toLowerCase();
      if (!query) return;

      var matchId = Object.keys(PRODUCTS).find(function (id) {
        var p = PRODUCTS[id];
        return p.barcode && p.barcode.toLowerCase() === query;
      });
      if (!matchId) {
        matchId = Object.keys(PRODUCTS).find(function (id) {
          return PRODUCTS[id].name.toLowerCase().includes(query);
        });
      }

      if (matchId) {
        addProductRow(matchId);
      } else {
        alert('No se encontró ningún producto con "' + this.value + '".');
      }
      this.value = '';
      this.focus();
    });

    /* ---------- Alta rápida de cliente (modal AJAX, paso 1) ---------- */

    var quickCustomerModalEl = document.getElementById('quickCustomerModal');
    var quickCustomerModal = new bootstrap.Modal(quickCustomerModalEl);
    var quickCustomerFeedback = document.getElementById('quick-customer-feedback');

    document.getElementById('quick-customer-btn').addEventListener('click', function () {
      quickCustomerFeedback.classList.add('d-none-force');
      quickCustomerFeedback.textContent = '';
      ['dni', 'first-name', 'last-name', 'email', 'phone', 'address'].forEach(function (id) {
        document.getElementById('qc-' + id).value = '';
      });
      quickCustomerModal.show();
    });

    function getCsrfToken() {
      return invoiceForm.querySelector('[name=csrfmiddlewaretoken]').value;
    }

    document.getElementById('quick-customer-save').addEventListener('click', function () {
      var payload = new URLSearchParams({
        dni: document.getElementById('qc-dni').value,
        first_name: document.getElementById('qc-first-name').value,
        last_name: document.getElementById('qc-last-name').value,
        email: document.getElementById('qc-email').value,
        phone: document.getElementById('qc-phone').value,
        address: document.getElementById('qc-address').value,
      });

      fetch(data.quickCreateUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': getCsrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: payload.toString(),
      })
        .then(function (resp) { return resp.json().then(function (json) { return { status: resp.status, json: json }; }); })
        .then(function (result) {
          if (!result.json.ok) {
            var errors = result.json.errors || {};
            var mensajes = Object.keys(errors).map(function (field) {
              var lista = errors[field];
              var texto = Array.isArray(lista) ? lista.map(function (e) { return e.message || e; }).join(' ') : lista;
              return texto;
            });
            quickCustomerFeedback.textContent = mensajes.join(' ') || 'No se pudo crear el cliente.';
            quickCustomerFeedback.classList.remove('d-none-force');
            return;
          }
          var c = result.json.customer;
          CUSTOMERS[c.id] = c;
          var customerSelect = document.getElementById('id_customer');
          var opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = c.label;
          customerSelect.appendChild(opt);
          $(customerSelect).val(String(c.id)).trigger('change');
          quickCustomerModal.hide();
        })
        .catch(function () {
          quickCustomerFeedback.textContent = 'Error de conexión al crear el cliente.';
          quickCustomerFeedback.classList.remove('d-none-force');
        });
    });
  });
})();
