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
        'id_meses_credito', 'id_tarjeta_titular', 'id_tarjeta_cvv', 'id_tarjeta_expiracion'];
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

    /* ---------- Modo de cliente (Consumidor Final / Cliente con datos) ---------- */

    var consumidorFinalCheckbox = document.getElementById(data.consumidorFinalId);
    var customerSelectWrapper = document.getElementById('customer-select-wrapper');
    var customerSelect = document.getElementById('id_customer');
    var modoClienteHint = document.getElementById('modo-cliente-hint');
    var modoClienteRadios = Array.prototype.slice.call(document.querySelectorAll('input[name="modo_cliente"]'));
    var tipoIdFiltroRadios = Array.prototype.slice.call(document.querySelectorAll('input[name="tipo_id_filtro"]'));
    var tipoPagoSelect = document.getElementById('id_tipo_pago');
    var creditoOption = tipoPagoSelect ? tipoPagoSelect.querySelector('option[value="credito"]') : null;

    var MODO_CLIENTE_HINTS = {
      consumidor_final: 'Venta de mostrador sin cliente registrado — siempre al contado, sin envío de PDF por correo.',
      con_datos: 'Filtra por tipo de identificación si quieres acotar la búsqueda, o deja "Todos" para ver cualquier cliente.',
    };

    function marcarTarjetasSeleccionadas(radios) {
      radios.forEach(function (radio) {
        radio.closest('.option-card, .choice-option').classList.toggle('is-checked', radio.checked);
      });
    }

    function modoClienteActual() {
      var marcado = modoClienteRadios.filter(function (r) { return r.checked; })[0];
      return marcado ? marcado.value : 'consumidor_final';
    }

    function tipoIdFiltroActual() {
      var marcado = tipoIdFiltroRadios.filter(function (r) { return r.checked; })[0];
      return marcado ? marcado.value : 'todos';
    }

    /* Deja ver solo los clientes cuyo tipo_identificacion corresponde al
       filtro elegido — deshabilitando las <option> que no aplican, mismo
       patrón que refreshProductAvailability() en el paso 2. "todos" no
       filtra nada. Si el cliente ya elegido deja de aplicar al cambiar de
       filtro, se limpia la selección. */
    function filtrarClientesPorTipo() {
      var filtro = tipoIdFiltroActual();
      Array.prototype.forEach.call(customerSelect.options, function (opt) {
        if (!opt.value) return;
        var c = CUSTOMERS[opt.value];
        if (!c) return;
        opt.disabled = filtro !== 'todos' && c.tipo_identificacion !== filtro;
      });
      var actual = customerSelect.value;
      if (actual && CUSTOMERS[actual]) {
        var seleccionado = CUSTOMERS[actual];
        var sigueValido = filtro === 'todos' || seleccionado.tipo_identificacion === filtro;
        if (!sigueValido) $(customerSelect).val('').trigger('change');
      }
    }
    tipoIdFiltroRadios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        marcarTarjetasSeleccionadas(tipoIdFiltroRadios);
        filtrarClientesPorTipo();
      });
    });

    function toggleConsumidorFinal() {
      var modo = modoClienteActual();
      var esConsumidorFinal = modo === 'consumidor_final';
      consumidorFinalCheckbox.checked = esConsumidorFinal;

      var yaVisible = !customerSelectWrapper.classList.contains('d-none-force');
      if (esConsumidorFinal) {
        customerSelectWrapper.classList.add('d-none-force');
      } else if (!yaVisible) {
        /* Reinicia la animación de aparición cada vez que se muestra (no
           solo la primera vez) — quitar y forzar reflow antes de
           reagregar la clase, mismo criterio que .dropdown-menu.show. */
        customerSelectWrapper.classList.remove('d-none-force', 'animate-slide-up');
        void customerSelectWrapper.offsetWidth;
        customerSelectWrapper.classList.add('animate-slide-up');
        filtrarClientesPorTipo();
      }
      modoClienteHint.textContent = MODO_CLIENTE_HINTS[modo];
      marcarTarjetasSeleccionadas(modoClienteRadios);

      if (esConsumidorFinal) {
        tipoPagoSelect.value = 'contado';
        if (creditoOption) creditoOption.disabled = true;
      } else if (creditoOption) {
        creditoOption.disabled = false;
      }
      toggleFormaPago();
      toggleMesesCredito();
    }
    modoClienteRadios.forEach(function (radio) {
      radio.addEventListener('change', toggleConsumidorFinal);
    });

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

    /* ---------- Tarjeta animada (preview visual + detección de marca) ----------
       El input de número de tarjeta NO tiene "name": nunca se envía al
       servidor, solo alimenta esta animación y detecta la marca por
       prefijo. Lo único que sí viaja al backend son el titular, el CVV/CVC
       y la expiración (campos reales del form, ver InvoiceForm). */
    var ccNumberInput = document.getElementById('cc-number-input');
    var ccFlipCard = document.getElementById('cc-flip-card');
    var ccDisplayNumber = document.getElementById('cc-display-number');
    var ccDisplayName = document.getElementById('cc-display-name');
    var ccDisplayExpiry = document.getElementById('cc-display-expiry');
    var ccDisplayCvv = document.getElementById('cc-display-cvv');
    var ccBrandHint = document.getElementById('cc-brand-hint');
    var ccHeadingBrand = document.getElementById('cc-heading-brand');
    var tarjetaTitularInput = document.getElementById('id_tarjeta_titular');
    var tarjetaCvvInput = document.getElementById('id_tarjeta_cvv');
    var tarjetaExpiracionInput = document.getElementById('id_tarjeta_expiracion');

    if (ccNumberInput && ccFlipCard) {
      var CARD_BRANDS = [
        { id: 'amex', label: 'American Express', groups: [4, 6, 5], re: /^3[47]/ },
        { id: 'diners', label: 'Diners Club', groups: [4, 6, 4], re: /^3(?:0[0-5]|[68])/ },
        { id: 'visa', label: 'Visa', groups: [4, 4, 4, 4], re: /^4/ },
        { id: 'mastercard', label: 'Mastercard', groups: [4, 4, 4, 4], re: /^(5[1-5]|2(2[2-9][1-9]|2[3-9]\d|[3-6]\d{2}|7[01]\d|720))/ },
        { id: 'discover', label: 'Discover', groups: [4, 4, 4, 4], re: /^(6011|65|64[4-9]|622)/ },
        { id: 'jcb', label: 'JCB', groups: [4, 4, 4, 4], re: /^35(?:2[89]|[3-8]\d)/ },
      ];

      function detectBrand(digits) {
        for (var i = 0; i < CARD_BRANDS.length; i++) {
          if (CARD_BRANDS[i].re.test(digits)) return CARD_BRANDS[i];
        }
        return null;
      }

      function groupDigits(digits, groups) {
        var parts = [];
        var pos = 0;
        for (var i = 0; i < groups.length && pos < digits.length; i++) {
          parts.push(digits.slice(pos, pos + groups[i]));
          pos += groups[i];
        }
        return parts;
      }

      function formatCardInput(digits, groups) {
        return groupDigits(digits, groups).join(' ');
      }

      /* Enmascara todo menos los últimos 4 dígitos ya escritos (igual que
         un datáfono/app bancaria real) — la fila de arriba de la tarjeta
         nunca muestra el número completo, ni siquiera el que el usuario
         acaba de escribir. */
      function maskedDisplay(digits, groups) {
        if (!digits) return '•••• •••• •••• ••••';
        var masked = digits.length <= 4 ? digits : '•'.repeat(digits.length - 4) + digits.slice(-4);
        return formatCardInput(masked, groups);
      }

      function updateCard() {
        var raw = ccNumberInput.value.replace(/\D/g, '').slice(0, 19);
        var brand = detectBrand(raw);
        var groups = brand ? brand.groups : [4, 4, 4, 4];

        ccNumberInput.value = formatCardInput(raw, groups);
        ccDisplayNumber.textContent = maskedDisplay(raw, groups);

        if (brand) {
          ccFlipCard.setAttribute('data-brand', brand.id);
          ccBrandHint.textContent = 'Tarjeta detectada: ' + brand.label;
          ccHeadingBrand.textContent = brand.label;
        } else if (raw.length > 0) {
          ccFlipCard.setAttribute('data-brand', 'unknown');
          ccBrandHint.textContent = '';
          ccHeadingBrand.textContent = '';
        } else {
          ccFlipCard.removeAttribute('data-brand');
          ccBrandHint.textContent = '';
          ccHeadingBrand.textContent = '';
        }

      }
      ccNumberInput.addEventListener('input', updateCard);

      if (tarjetaTitularInput) {
        tarjetaTitularInput.addEventListener('input', function () {
          ccDisplayName.textContent = tarjetaTitularInput.value.trim().toUpperCase() || 'NOMBRE DEL TITULAR';
        });
      }

      if (tarjetaExpiracionInput) {
        tarjetaExpiracionInput.addEventListener('input', function () {
          if (!tarjetaExpiracionInput.value) { ccDisplayExpiry.textContent = 'MM/AA'; return; }
          var parts = tarjetaExpiracionInput.value.split('-');
          if (parts.length === 3) { ccDisplayExpiry.textContent = parts[1] + '/' + parts[0].slice(2); }
        });
      }

      /* El CVV es independiente del número (no se puede derivar de él) —
         se escribe aparte y se refleja en el reverso de la tarjeta, que es
         justo lo que el usuario ve al pasar el mouse (mismo lugar donde
         está impreso en una tarjeta física real). */
      if (tarjetaCvvInput && ccDisplayCvv) {
        tarjetaCvvInput.addEventListener('input', function () {
          var digits = tarjetaCvvInput.value.replace(/\D/g, '').slice(0, 4);
          ccDisplayCvv.textContent = digits || '•••';
        });
      }
    }

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

    /* Si la vista re-renderiza con errores, el radio debe reflejar lo que el
       usuario ya había elegido (no resetear siempre a Consumidor Final) —
       se deduce del estado real que Django ya dejó en el checkbox oculto y
       en el <select> de cliente, no de qué radio quedó "checked" en el HTML
       estático (que solo sirve de default para una página nueva). */
    (function fijarModoClienteInicial() {
      if (consumidorFinalCheckbox.checked) return;
      if (!customerSelect.value || !CUSTOMERS[customerSelect.value]) return;
      var radioEl = document.querySelector('input[name="modo_cliente"][value="con_datos"]');
      if (radioEl) radioEl.checked = true;
      var c = CUSTOMERS[customerSelect.value];
      var filtroEl = document.querySelector('input[name="tipo_id_filtro"][value="' + c.tipo_identificacion + '"]');
      if (filtroEl) filtroEl.checked = true;
    })();
    toggleConsumidorFinal();
    marcarTarjetasSeleccionadas(tipoIdFiltroRadios);

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

    /* ---------- Pasarela de pago simulada (pago con tarjeta) ----------
       Mismo espíritu que el cartel de efectivo de arriba: al tocar
       "Guardar Factura" con tarjeta, se intercepta el submit y se muestra
       este modal en vez de guardar directo. Solo cuando el pago simulado
       queda "Aprobado" se dispara invoiceForm.submit() de verdad — 100%
       decorativo, no hay ninguna pasarela real integrada (Stripe, etc.). */
    var pasarelaModalEl = document.getElementById('pasarelaPagoModal');
    var pasarelaModal = new bootstrap.Modal(pasarelaModalEl);
    var pasarelaTotal = document.getElementById('pasarela-total');
    var pasarelaNumero = document.getElementById('pasarela-numero');
    var pasarelaTitularSpan = document.getElementById('pasarela-titular');
    var pasarelaResumen = document.getElementById('pasarela-resumen');
    var pasarelaProcesando = document.getElementById('pasarela-procesando');
    var pasarelaAprobado = document.getElementById('pasarela-aprobado');
    var pasarelaError = document.getElementById('pasarela-error');
    var pasarelaPagarBtn = document.getElementById('pasarela-pagar');
    var pasarelaCancelarBtn = document.getElementById('pasarela-cancelar');
    var tarjetaConfirmada = false;

    formaPagoSelect.addEventListener('change', function () { tarjetaConfirmada = false; });

    function mostrarPasoPasarela(paso) {
      pasarelaResumen.classList.toggle('d-none-force', paso !== 'resumen');
      pasarelaProcesando.classList.toggle('d-none-force', paso !== 'procesando');
      pasarelaAprobado.classList.toggle('d-none-force', paso !== 'aprobado');
      var enResumen = paso === 'resumen';
      pasarelaPagarBtn.classList.toggle('d-none-force', !enResumen);
      pasarelaCancelarBtn.classList.toggle('d-none-force', !enResumen);
    }

    pasarelaPagarBtn.addEventListener('click', function () {
      var cvv = tarjetaCvvInput.value.trim();
      if (!tarjetaTitularInput.value.trim()) {
        pasarelaError.textContent = 'Indica el titular de la tarjeta.';
        pasarelaError.classList.remove('d-none-force');
        return;
      }
      if (!/^\d{3,4}$/.test(cvv)) {
        pasarelaError.textContent = 'Ingresa un CVV/CVC válido (3 o 4 números).';
        pasarelaError.classList.remove('d-none-force');
        return;
      }
      if (!tarjetaExpiracionInput.value) {
        pasarelaError.textContent = 'Indica la fecha de expiración de la tarjeta.';
        pasarelaError.classList.remove('d-none-force');
        return;
      }
      pasarelaError.classList.add('d-none-force');
      mostrarPasoPasarela('procesando');
      window.setTimeout(function () {
        mostrarPasoPasarela('aprobado');
        window.setTimeout(function () {
          tarjetaConfirmada = true;
          pasarelaModal.hide();
          invoiceForm.submit();
        }, 700);
      }, 1500);
    });

    pasarelaCancelarBtn.addEventListener('click', function () {
      pasarelaModal.hide();
    });

    invoiceForm.addEventListener('submit', function (e) {
      if (formaPagoSelect.value === 'efectivo' && !montoConfirmado) {
        e.preventDefault();
        modalTotal.textContent = '$' + getTotalActual().toFixed(2);
        modalMontoInput.value = montoRecibidoInput.value || '';
        actualizarFeedbackModal();
        montoModal.show();
      } else if (formaPagoSelect.value === 'tarjeta' && !tarjetaConfirmada) {
        e.preventDefault();
        pasarelaTotal.textContent = '$' + getTotalActual().toFixed(2);
        pasarelaNumero.textContent = ccDisplayNumber ? ccDisplayNumber.textContent : '•••• •••• •••• ••••';
        pasarelaTitularSpan.textContent = tarjetaTitularInput.value.trim() || '-';
        pasarelaError.classList.add('d-none-force');
        mostrarPasoPasarela('resumen');
        pasarelaModal.show();
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
    var qcTipoIdRadios = Array.prototype.slice.call(document.querySelectorAll('input[name="qc_tipo_identificacion"]'));
    var qcDniLabel = document.getElementById('qc-dni-label');
    var qcDniInput = document.getElementById('qc-dni');

    var QC_DNI_TEXTOS = {
      cedula: { label: 'Cédula (10 dígitos)', maxLength: 10, inputMode: 'numeric' },
      ruc: { label: 'RUC (13 dígitos)', maxLength: 13, inputMode: 'numeric' },
      pasaporte: { label: 'Pasaporte', maxLength: 20, inputMode: 'text' },
    };

    function qcTipoIdActual() {
      var marcado = qcTipoIdRadios.filter(function (r) { return r.checked; })[0];
      return marcado ? marcado.value : 'cedula';
    }

    function actualizarCamposQcDni() {
      var textos = QC_DNI_TEXTOS[qcTipoIdActual()];
      qcDniLabel.textContent = textos.label;
      qcDniInput.maxLength = textos.maxLength;
      qcDniInput.inputMode = textos.inputMode;
      marcarTarjetasSeleccionadas(qcTipoIdRadios);
    }
    qcTipoIdRadios.forEach(function (radio) {
      radio.addEventListener('change', actualizarCamposQcDni);
    });

    document.getElementById('quick-customer-btn').addEventListener('click', function () {
      quickCustomerFeedback.classList.add('d-none-force');
      quickCustomerFeedback.textContent = '';
      ['dni', 'first-name', 'last-name', 'email', 'phone', 'address'].forEach(function (id) {
        document.getElementById('qc-' + id).value = '';
      });
      // Hereda el filtro activo del paso 1 como punto de partida (si hay
      // uno concreto elegido) — el usuario todavía puede cambiarlo adentro
      // del modal antes de guardar.
      var filtroActivo = tipoIdFiltroActual();
      var tipoInicial = filtroActivo === 'todos' ? 'cedula' : filtroActivo;
      var radioInicial = document.querySelector('input[name="qc_tipo_identificacion"][value="' + tipoInicial + '"]');
      if (radioInicial) radioInicial.checked = true;
      actualizarCamposQcDni();
      quickCustomerModal.show();
    });

    function getCsrfToken() {
      return invoiceForm.querySelector('[name=csrfmiddlewaretoken]').value;
    }

    document.getElementById('quick-customer-save').addEventListener('click', function () {
      var payload = new URLSearchParams({
        tipo_identificacion: qcTipoIdActual(),
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
