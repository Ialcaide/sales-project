/* Wizard de 3 pasos de purchasing/templates/purchasing/purchase_form.html
   (Proveedor -> Detalles -> Pago), con panel lateral fijo (resumen + fase).
   Mismo espíritu que static/js/invoice-wizard.js: UN solo <form> con un
   solo POST al final — los "pasos" y el panel lateral son solo una capa
   visual sobre el mismo DOM/campos de siempre; toda la validación de
   negocio real (duplicados, proveedor activo, cantidad/costo) sigue
   viviendo en el servidor (purchasing/views.py -> purchase_create).
   Los datos vienen embebidos en window.PURCHASE_WIZARD_DATA (ver el
   <script> inline justo antes de este archivo en purchase_form.html). */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var data = window.PURCHASE_WIZARD_DATA;
    if (!data) return;

    var SUPPLIERS_PRODUCTS = data.suppliersProducts;
    var IVA_FRACCION = data.ivaFraccion;
    var formIndex = data.formIndex;
    var purchaseForm = document.getElementById('purchase-form');

    // PRODUCTS_ALL: mapa plano {id: {name, barcode, image_url}} agregado de
    // todos los proveedores — usado para armar <option>s nuevas (agregar
    // fila / búsqueda rápida) sin importar qué proveedor está elegido. El
    // costo/último precio SÍ depende del proveedor, ver productoParaProveedor().
    var PRODUCTS_ALL = {};
    Object.keys(SUPPLIERS_PRODUCTS).forEach(function (sid) {
      SUPPLIERS_PRODUCTS[sid].forEach(function (p) {
        PRODUCTS_ALL[p.id] = { name: p.name, barcode: p.barcode, image_url: p.image_url };
      });
    });

    function productoParaProveedor(supplierId, productId) {
      var lista = SUPPLIERS_PRODUCTS[supplierId] || [];
      for (var i = 0; i < lista.length; i++) {
        if (String(lista[i].id) === String(productId)) return lista[i];
      }
      return null;
    }

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
      window.scrollTo({ top: purchaseForm.offsetTop - 20, behavior: 'smooth' });
    }

    function tieneProductoValido() {
      return Array.prototype.some.call(document.querySelectorAll('.detail-row'), function (row) {
        var sel = row.querySelector('.product-select');
        return sel && sel.value;
      });
    }

    var supplierSelect = document.getElementById('id_supplier');

    document.querySelectorAll('[data-wizard-next]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = parseInt(btn.dataset.wizardNext, 10);
        if (target === 2) {
          if (!supplierSelect.value) {
            alert('Selecciona un proveedor antes de continuar.');
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

    /* Si la vista re-renderiza con errores, saltar directo al paso donde
       vive el campo con error en vez de resetear siempre al paso 1. */
    (function jumpToStepWithErrors() {
      var step3Fields = ['id_tipo_pago', 'id_meses_credito', 'id_retencion_porcentaje'];
      var hasStep3Error = step3Fields.some(function (id) {
        var el = document.getElementById(id);
        if (!el) return false;
        var wrapper = el.closest('.mb-3, .col-md-6') || el.parentElement;
        return wrapper && wrapper.querySelector('.text-danger');
      });
      if (hasStep3Error) { goToStep(3); return; }

      var detailsTable = document.getElementById('details-table');
      var hasStep2Error = detailsTable && detailsTable.querySelector('.text-danger');
      var alertBox = document.querySelector('.alert-danger, .alert-warning');
      var alertText = alertBox ? alertBox.textContent.toLowerCase() : '';
      var mentionsStep2 = /producto|cantidad|costo|duplicad/.test(alertText);
      var mentionsStep3 = /cr[ée]dito|retenci[óo]n|meses/.test(alertText);
      if (mentionsStep3) { goToStep(3); return; }
      if (hasStep2Error || mentionsStep2) { goToStep(2); return; }

      var supplierError = document.getElementById('id_supplier').closest('.card-body').querySelector('.text-danger');
      if (supplierError) { goToStep(1); }
    })();

    /* ---------- Forma de pago / meses de crédito ---------- */

    var tipoPagoSelect = document.getElementById('id_tipo_pago');
    var mesesCreditoWrapper = document.getElementById('meses-credito-wrapper');
    var mesesCreditoInput = document.getElementById('id_meses_credito');
    var retencionInput = document.getElementById('id_retencion_porcentaje');

    function toggleMesesCredito() {
      if (tipoPagoSelect.value === 'credito') {
        mesesCreditoWrapper.classList.remove('d-none-force');
      } else {
        mesesCreditoWrapper.classList.add('d-none-force');
        mesesCreditoInput.value = '';
      }
      calcTotals();
    }
    tipoPagoSelect.addEventListener('change', toggleMesesCredito);
    mesesCreditoInput.addEventListener('input', calcTotals);
    retencionInput.addEventListener('input', calcTotals);
    if (!retencionInput.value) retencionInput.value = data.retencionDefault || 0;

    /* ---------- Totales (subtotal, descuento, IVA, retención, interés) ---------- */

    // Debe reflejar exactamente Purchase.INTERES_TIERS (purchasing/models.py).
    var INTERES_TIERS = [[3, 0.05], [6, 0.10], [12, 0.15], [24, 0.20], [36, 0.25]];
    function tasaInteres(meses) {
      for (var i = 0; i < INTERES_TIERS.length; i++) {
        if (meses <= INTERES_TIERS[i][0]) return INTERES_TIERS[i][1];
      }
      return INTERES_TIERS[INTERES_TIERS.length - 1][1];
    }

    function calcRow(row) {
      var qty = parseFloat(row.querySelector('.quantity-input').value) || 0;
      var cost = parseFloat(row.querySelector('.cost-input').value) || 0;
      var descuento = parseFloat(row.querySelector('.descuento-input').value) || 0;
      var sub = qty * cost * (1 - descuento / 100);
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
      var retencionPct = parseFloat(retencionInput.value) || 0;
      var retencionValor = subtotal * (retencionPct / 100);

      document.getElementById('summary-subtotal').textContent = '$' + subtotal.toFixed(2);
      document.getElementById('summary-tax-label').textContent = 'IVA (' + Math.round(IVA_FRACCION * 100) + '%):';
      document.getElementById('summary-tax').textContent = '$' + tax.toFixed(2);
      document.getElementById('summary-total').textContent = '$' + total.toFixed(2);
      document.getElementById('summary-retencion').textContent = '-$' + retencionValor.toFixed(2);

      var meses = parseInt(mesesCreditoInput.value, 10);
      var interes = 0;
      var totalAPagar = total;
      var box = document.getElementById('summary-credito-box');
      if (tipoPagoSelect.value === 'credito' && meses > 0) {
        interes = total * tasaInteres(meses);
        totalAPagar = total + interes;
        document.getElementById('summary-interes').textContent = '$' + interes.toFixed(2);
        document.getElementById('summary-total-credito').textContent = '$' + totalAPagar.toFixed(2);
        document.getElementById('summary-cuota-minima').textContent = '$' + (totalAPagar / meses).toFixed(2);
        box.classList.remove('d-none-force');
      } else {
        box.classList.add('d-none-force');
      }

      var neto = totalAPagar - retencionValor;
      document.getElementById('summary-neto').textContent = '$' + neto.toFixed(2);
      var step3Recap = document.getElementById('step3-neto-recap');
      if (step3Recap) step3Recap.textContent = '$' + neto.toFixed(2);
    }

    /* ---------- Líneas de producto (paso 2) ---------- */

    /* Evita elegir el mismo producto en dos filas: deshabilita en cada
       <select> las opciones ya elegidas en OTRA fila — igual que
       invoice-wizard.js. El rechazo real y definitivo sigue siendo 100%
       del servidor (ver purchasing/views.py -> purchase_create). */
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

    function actualizarFilaConProducto(row) {
      var sel = row.querySelector('.product-select');
      var pid = sel.value;
      var costInput = row.querySelector('.cost-input');
      var productMeta = row.querySelector('.product-meta');
      var productThumb = row.querySelector('.product-thumb');
      var lastPriceInfo = row.querySelector('.last-price-info');
      var supplierId = supplierSelect.value;

      if (pid && PRODUCTS_ALL[pid]) {
        var base = PRODUCTS_ALL[pid];
        var enProveedor = productoParaProveedor(supplierId, pid);
        productMeta.textContent = base.barcode || 'Sin código de barras';
        if (base.image_url) {
          productThumb.src = base.image_url;
          productThumb.classList.remove('d-none-force');
        } else {
          productThumb.classList.add('d-none-force');
        }
        if (enProveedor && enProveedor.cost) {
          costInput.value = enProveedor.cost.toFixed(2);
        }
        if (enProveedor && enProveedor.last_price) {
          lastPriceInfo.textContent = 'Último precio pagado a este proveedor: $' + enProveedor.last_price.toFixed(2);
        } else {
          lastPriceInfo.textContent = '';
        }
      } else {
        productMeta.textContent = '';
        productThumb.classList.add('d-none-force');
        lastPriceInfo.textContent = '';
      }
      calcTotals();
      refreshProductAvailability();
    }

    function initSelect2(sel) {
      $(sel).select2({
        placeholder: 'Escribe para buscar producto...',
        allowClear: true,
        width: '100%'
      }).on('change', function () {
        actualizarFilaConProducto(sel.closest ? sel.closest('tr') : $(sel).closest('tr')[0]);
      });
    }

    function bindProductSelect(row) {
      var sel = row.querySelector('.product-select');
      initSelect2(sel);

      row.querySelector('.quantity-input').addEventListener('input', function () {
        if (this.value < 1 || this.value === '') this.value = 1;
        calcTotals();
      });
      row.querySelector('.cost-input').addEventListener('input', calcTotals);
      row.querySelector('.descuento-input').addEventListener('input', calcTotals);

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
       fila, mismo patrón que invoice-wizard.js. */
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
                Object.keys(PRODUCTS_ALL).map(function (id) {
                  return '<option value="' + id + '">' + PRODUCTS_ALL[id].name + '</option>';
                }).join('') +
              '</select>' +
              '<small class="text-muted product-meta d-block"></small>' +
              '<small class="text-success fw-bold last-price-info d-block"></small>' +
            '</div>' +
          '</div>' +
        '</td>' +
        '<td><input type="number" name="details-' + formIndex + '-quantity" class="form-control quantity-input" value="1" min="1"></td>' +
        '<td><input type="number" name="details-' + formIndex + '-unit_cost" class="form-control cost-input" step="0.01" min="0.01"></td>' +
        '<td><input type="number" name="details-' + formIndex + '-descuento_porcentaje" class="form-control descuento-input" value="0" step="0.01" min="0" max="100"></td>' +
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

    /* Cuando cambia el proveedor: recalcula costo/último precio sugerido de
       cada fila ya elegida (dependen del proveedor) y refresca qué
       productos quedan disponibles. */
    initSelect2(supplierSelect);
    supplierSelect.addEventListener('change', function () {
      document.querySelectorAll('.detail-row').forEach(function (row) {
        if (row.querySelector('.product-select').value) actualizarFilaConProducto(row);
      });
    });

    /* Búsqueda rápida / escáner de código de barras: un lector USB de
       código de barras funciona como un teclado que "escribe" el código y
       presiona Enter solo. */
    document.getElementById('quick-search').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      var query = this.value.trim().toLowerCase();
      if (!query) return;

      var matchId = Object.keys(PRODUCTS_ALL).find(function (id) {
        var p = PRODUCTS_ALL[id];
        return p.barcode && p.barcode.toLowerCase() === query;
      });
      if (!matchId) {
        matchId = Object.keys(PRODUCTS_ALL).find(function (id) {
          return PRODUCTS_ALL[id].name.toLowerCase().includes(query);
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

    /* ---------- Alta rápida de proveedor (modal AJAX, paso 1) ---------- */

    var quickSupplierModalEl = document.getElementById('quickSupplierModal');
    var quickSupplierModal = new bootstrap.Modal(quickSupplierModalEl);
    var quickSupplierFeedback = document.getElementById('quick-supplier-feedback');

    document.getElementById('quick-supplier-btn').addEventListener('click', function () {
      quickSupplierFeedback.classList.add('d-none-force');
      quickSupplierFeedback.textContent = '';
      ['name', 'contact-name', 'email', 'phone', 'address'].forEach(function (id) {
        document.getElementById('qs-' + id).value = '';
      });
      quickSupplierModal.show();
    });

    function getCsrfToken() {
      return purchaseForm.querySelector('[name=csrfmiddlewaretoken]').value;
    }

    document.getElementById('quick-supplier-save').addEventListener('click', function () {
      var payload = new URLSearchParams({
        name: document.getElementById('qs-name').value,
        contact_name: document.getElementById('qs-contact-name').value,
        email: document.getElementById('qs-email').value,
        phone: document.getElementById('qs-phone').value,
        address: document.getElementById('qs-address').value,
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
            quickSupplierFeedback.textContent = mensajes.join(' ') || 'No se pudo crear el proveedor.';
            quickSupplierFeedback.classList.remove('d-none-force');
            return;
          }
          var s = result.json.supplier;
          SUPPLIERS_PRODUCTS[s.id] = [];
          var opt = document.createElement('option');
          opt.value = s.id;
          opt.textContent = s.label;
          supplierSelect.appendChild(opt);
          $(supplierSelect).val(String(s.id)).trigger('change');
          quickSupplierModal.hide();
        })
        .catch(function () {
          quickSupplierFeedback.textContent = 'Error de conexión al crear el proveedor.';
          quickSupplierFeedback.classList.remove('d-none-force');
        });
    });
  });
})();
