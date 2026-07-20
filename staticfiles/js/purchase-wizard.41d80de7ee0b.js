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

    // PRODUCTS_ALL: mapa plano {id: {name, barcode, image_url, stock,
    // stock_minimo}} agregado de todos los proveedores — usado para armar
    // <option>s nuevas (agregar fila / búsqueda rápida) sin importar qué
    // proveedor está elegido. El costo/último precio SÍ depende del
    // proveedor, ver productoParaProveedor().
    var PRODUCTS_ALL = {};
    Object.keys(SUPPLIERS_PRODUCTS).forEach(function (sid) {
      SUPPLIERS_PRODUCTS[sid].forEach(function (p) {
        PRODUCTS_ALL[p.id] = {
          name: p.name, barcode: p.barcode, image_url: p.image_url,
          stock: p.stock, stock_minimo: p.stock_minimo,
        };
      });
    });

    // Mismo criterio que notificaciones/services.py -> notificar_stock_bajo:
    // stock <= stock_minimo cuenta como bajo.
    function esStockBajo(p) {
      return p.stock <= p.stock_minimo;
    }

    function etiquetaProducto(p) {
      return p.name + ' — Stock: ' + p.stock;
    }

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

    /* Filas CON producto elegido pero cantidad/costo en blanco o en 0 — el
       servidor las rechaza igual (purchasing/views.py -> purchase_create),
       pero avisarlo acá evita un viaje de ida y vuelta al servidor solo para
       enterarse. No bloquea nada que el servidor no bloquee ya; solo
       adelanta el aviso. */
    function filasConDatosIncompletos() {
      return Array.prototype.filter.call(document.querySelectorAll('.detail-row'), function (row) {
        var sel = row.querySelector('.product-select');
        if (!sel || !sel.value) return false;
        var qty = parseFloat(row.querySelector('.quantity-input').value) || 0;
        var cost = parseFloat(row.querySelector('.cost-input').value) || 0;
        return qty <= 0 || cost <= 0;
      }).map(function (row) {
        return row.querySelector('.product-select option:checked').textContent;
      });
    }

    var supplierSelect = document.getElementById('id_supplier');

    // Proveedor actualmente elegido en el paso 1 — leído en vivo por
    // matcherPorProveedor() (más abajo) cada vez que se abre el selector de
    // producto. Se actualiza en el listener 'change' de supplierSelect, más
    // abajo (junto al resto de lo que ya reacciona a ese cambio).
    var proveedorActualId = supplierSelect.value;

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
          var incompletas = filasConDatosIncompletos();
          if (incompletas.length) {
            alert('Falta cantidad o costo unitario en: ' + incompletas.join(', '));
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
      var step3Fields = [
        'id_tipo_pago', 'id_meses_credito', 'id_retencion_porcentaje',
        'id_forma_pago', 'id_tarjeta_titular', 'id_tarjeta_cvv', 'id_tarjeta_expiracion',
      ];
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
      var mentionsStep3 = /cr[ée]dito|retenci[óo]n|meses|caja|tarjeta|paypal|forma de pago/.test(alertText);
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

    /* forma_pago solo aplica a compras al CONTADO (ver Purchase.clean()) —
       en CREDITO se oculta y se limpia, igual que meses_credito hace al
       revés. Estas variables tienen que existir ANTES de toggleMesesCredito
       (que las usa) — mismo cuidado de orden que invoice-wizard.js con
       guardarFacturaBtn. */
    var formaPagoWrapper = document.getElementById('forma-pago-wrapper');
    var formaPagoSelect = document.getElementById('id_forma_pago');
    var tarjetaWrapper = document.getElementById('tarjeta-wrapper');
    var guardarCompraBtn = document.getElementById('guardar-compra-btn');
    var tarjetaPagoEstado = document.getElementById('tarjeta-pago-estado');
    var tarjetaConfirmada = false;

    function actualizarEstadoPagoTarjeta() {
      if (formaPagoSelect.value !== 'tarjeta') {
        guardarCompraBtn.disabled = false;
        return;
      }
      guardarCompraBtn.disabled = !tarjetaConfirmada;
      if (tarjetaConfirmada) {
        tarjetaPagoEstado.textContent = 'Pago verificado';
        tarjetaPagoEstado.className = 'badge badge-success';
      } else {
        tarjetaPagoEstado.textContent = 'Pago pendiente';
        tarjetaPagoEstado.className = 'badge badge-warning';
      }
    }

    function toggleTarjetaCampos() {
      tarjetaWrapper.classList.toggle('d-none-force', formaPagoSelect.value !== 'tarjeta');
      tarjetaConfirmada = false;
      actualizarEstadoPagoTarjeta();
    }
    formaPagoSelect.addEventListener('change', toggleTarjetaCampos);

    function toggleMesesCredito() {
      if (tipoPagoSelect.value === 'credito') {
        mesesCreditoWrapper.classList.remove('d-none-force');
        formaPagoWrapper.classList.add('d-none-force');
        formaPagoSelect.value = '';
      } else {
        mesesCreditoWrapper.classList.add('d-none-force');
        mesesCreditoInput.value = '';
        formaPagoWrapper.classList.remove('d-none-force');
      }
      toggleTarjetaCampos();
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
      currentNeto = neto;
    }

    // Leído por la pasarela de pago simulada (tarjeta) para mostrar "Total
    // a pagar" — se actualiza en cada llamada a calcTotals().
    var currentNeto = 0;
    function getNetoActual() {
      return currentNeto;
    }

    /* ---------- Tarjeta animada (preview visual + detección de marca) ----------
       Copiado/adaptado de static/js/invoice-wizard.js — mismo patrón que ya
       usan facturas, pagos a proveedores y cobros a clientes. */
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

      if (tarjetaCvvInput && ccDisplayCvv) {
        tarjetaCvvInput.addEventListener('input', function () {
          var digits = tarjetaCvvInput.value.replace(/\D/g, '').slice(0, 4);
          ccDisplayCvv.textContent = digits || '•••';
        });
      }
    }

    /* ---------- Pasarela de pago simulada (pago con tarjeta) ----------
       PayPal acá NO usa esta pasarela ni ningún modal de "conectando" — el
       payout (Payouts API) no tiene redirect, se resuelve en el mismo
       submit del formulario (ver purchasing/views.py -> purchase_create). */
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
    var tarjetaPagarBtn = document.getElementById('tarjeta-pagar-btn');

    function mostrarPasoPasarela(paso) {
      pasarelaResumen.classList.toggle('d-none-force', paso !== 'resumen');
      pasarelaProcesando.classList.toggle('d-none-force', paso !== 'procesando');
      pasarelaAprobado.classList.toggle('d-none-force', paso !== 'aprobado');
      var enResumen = paso === 'resumen';
      pasarelaPagarBtn.classList.toggle('d-none-force', !enResumen);
      pasarelaCancelarBtn.classList.toggle('d-none-force', !enResumen);
    }

    function abrirPasarelaModal() {
      pasarelaTotal.textContent = '$' + getNetoActual().toFixed(2);
      pasarelaNumero.textContent = ccDisplayNumber ? ccDisplayNumber.textContent : '•••• •••• •••• ••••';
      pasarelaTitularSpan.textContent = tarjetaTitularInput.value.trim() || '-';
      pasarelaError.classList.add('d-none-force');
      mostrarPasoPasarela('resumen');
      pasarelaModal.show();
    }

    tarjetaPagarBtn.addEventListener('click', abrirPasarelaModal);

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
          actualizarEstadoPagoTarjeta();
          pasarelaModal.hide();
        }, 900);
      }, 1500);
    });

    pasarelaCancelarBtn.addEventListener('click', function () {
      pasarelaModal.hide();
    });

    /* Un campo required (ej. document_number, en el paso 1) que queda en un
       <div data-step> oculto (display:none, por estar en otro paso del
       wizard) al momento del submit final hace que la validación nativa del
       navegador bloquee el envío SIN mostrar ningún mensaje — un campo
       invisible no se puede enfocar, y sin foco no hay aviso ("An invalid
       form control with name='...' is not focusable"). Por eso, antes de
       dejar pasar el submit nativo, revisamos nosotros mismos cada paso en
       orden y saltamos al primero que tenga un campo :invalid — eso NO
       requiere que el campo sea visible (es una validación de estado, no de
       foco) — y ahí sí, ya con el paso visible, disparamos manualmente
       focus()+reportValidity() para que el navegador pueda mostrar su
       mensaje nativo normalmente. */
    function primerPasoConCampoInvalido() {
      for (var i = 0; i < stepEls.length; i++) {
        var invalido = stepEls[i].querySelector(':invalid');
        if (invalido) {
          return { campo: invalido, paso: parseInt(stepEls[i].dataset.step, 10) };
        }
      }
      return null;
    }

    purchaseForm.addEventListener('submit', function (e) {
      var problema = primerPasoConCampoInvalido();
      if (problema) {
        e.preventDefault();
        goToStep(problema.paso);
        window.setTimeout(function () {
          problema.campo.focus();
          problema.campo.reportValidity();
        }, 300);
        return;
      }

      if (formaPagoSelect.value === 'tarjeta' && !tarjetaConfirmada) {
        // Salvaguarda: si el submit llega por otra vía que no sea el click
        // en "Guardar Compra" (ej. Enter dentro de un campo de texto), igual
        // se corta acá y se obliga a pasar por la pasarela.
        e.preventDefault();
        abrirPasarelaModal();
      }
    });

    actualizarEstadoPagoTarjeta();

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

    // Pinta en rojo las opciones con stock bajo dentro de la lista
    // desplegable de Select2 — el <option> nativo trae data-low-stock="true"
    // (server-side en purchase_form.html, o armado en addProductRow acá
    // abajo), Select2 no respeta estilos por option nativos así que hay que
    // pasarle el texto ya envuelto vía templateResult.
    function formatearOpcionProducto(opcion) {
      if (!opcion.id) return opcion.text;
      var esBajo = $(opcion.element).data('lowStock');
      var $span = $('<span></span>').text(opcion.text);
      if (esBajo) $span.addClass('text-danger fw-bold');
      return $span;
    }

    // Filtro REAL (no solo visual) por proveedor: el <select> sigue teniendo
    // en el DOM las <option> de TODOS los productos (hace falta así para que
    // sigan disponibles si más tarde se cambia de proveedor), pero
    // Select2 arma su lista desplegable en cada apertura llamando a este
    // matcher por cada <option> — devolver null la excluye por completo,
    // ni con el buscador de texto aparece. proveedorActualId se lee en vivo
    // (closure sobre la variable de arriba), así que no hace falta
    // reinicializar Select2 cuando cambia el proveedor.
    var matcherPorDefecto = $.fn.select2.defaults.defaults.matcher;
    function matcherPorProveedor(params, opcion) {
      if (!opcion.id) return opcion; // opción placeholder "Escribe para buscar..."
      if (proveedorActualId && !productoParaProveedor(proveedorActualId, opcion.id)) return null;
      return matcherPorDefecto(params, opcion);
    }

    function initSelect2(sel) {
      $(sel).select2({
        placeholder: 'Escribe para buscar producto...',
        allowClear: true,
        width: '100%',
        templateResult: formatearOpcionProducto,
        matcher: matcherPorProveedor,
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
       fila, mismo patrón que invoice-wizard.js.

       Cuando SÍ viene productId (código de barras/búsqueda rápida), valida
       contra SUPPLIERS_PRODUCTS[proveedorActualId] antes de agregar nada —
       mismo criterio que matcherPorProveedor ya aplica al selector manual.
       Sin este chequeo, escanear el código de un producto de OTRO
       proveedor lo agregaba igual, sin aviso, ignorando por completo el
       filtro que sí respeta el <select>. El botón "+ Agregar Producto"
       (productId null/undefined) no pasa por acá — esa fila arranca vacía,
       el propio <select> ya filtrado es quien decide qué se puede elegir. */
    function addProductRow(productId) {
      if (productId && proveedorActualId && !productoParaProveedor(proveedorActualId, productId)) {
        var producto = PRODUCTS_ALL[productId];
        var nombreProducto = producto ? producto.name : 'Este producto';
        var opcionProveedor = supplierSelect.options[supplierSelect.selectedIndex];
        var nombreProveedor = opcionProveedor ? opcionProveedor.text : 'el proveedor seleccionado';
        alert('"' + nombreProducto + '" no pertenece a ' + nombreProveedor + ' — no se agregó a la compra.');
        return null;
      }
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
                  var p = PRODUCTS_ALL[id];
                  var lowStockAttr = esStockBajo(p) ? ' data-low-stock="true"' : '';
                  return '<option value="' + id + '"' + lowStockAttr + '>' + etiquetaProducto(p) + '</option>';
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

    /* Cuando cambia el proveedor: actualiza proveedorActualId (así el
       matcher del paso 2 filtra por el proveedor nuevo la próxima vez que
       se abra un selector de producto), recalcula costo/último precio
       sugerido de cada fila ya elegida (dependen del proveedor) y refresca
       qué productos quedan disponibles. Select2 propio (no initSelect2(),
       que es específico de las filas de producto y espera un <tr>
       ancestro — el select de proveedor no vive dentro de una tabla). */
    $(supplierSelect).select2({ placeholder: 'Escribe para buscar proveedor...', allowClear: true, width: '100%' });
    /* jQuery, no addEventListener: cuando el usuario elige un proveedor
       haciendo clic en el propio dropdown de Select2 (no tecleando en el
       <select> nativo), Select2 dispara el cambio internamente vía
       $(...).trigger('change') — y en jQuery 3.x eso NO despacha un evento
       DOM nativo, solo invoca handlers registrados con jQuery. Con
       addEventListener acá, un clic real de usuario nunca actualizaba
       proveedorActualId (se quedaba vacío) y todo el filtrado de
       matcherPorProveedor quedaba inerte — confirmado con Playwright
       instrumentando ambos tipos de listener en un clic real. */
    $(supplierSelect).on('change', function () {
      proveedorActualId = supplierSelect.value;
      document.querySelectorAll('.detail-row').forEach(function (row) {
        if (row.querySelector('.product-select').value) actualizarFilaConProducto(row);
      });
    });

    /* Botones de proveedor en "Reposición Urgente" (paso 1): preseleccionan
       ese proveedor en el <select> de arriba para agilizar el flujo. Si el
       proveedor ya no está en SUPPLIERS_PRODUCTS (se desactivó entre que se
       cargó la página y el clic) no hace nada — sigue siendo una opción
       válida del <select>, solo que sin productos precargados. */
    document.querySelectorAll('.reposicion-supplier-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        $(supplierSelect).val(btn.dataset.supplierId).trigger('change');
        supplierSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
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

    /* ---------- Alta rápida de bodega (modal AJAX, paso 1) ---------- */

    var bodegaSelect = document.getElementById('id_bodega');
    var quickBodegaModalEl = document.getElementById('quickBodegaModal');
    var quickBodegaModal = new bootstrap.Modal(quickBodegaModalEl);
    var quickBodegaFeedback = document.getElementById('quick-bodega-feedback');

    document.getElementById('quick-bodega-btn').addEventListener('click', function () {
      quickBodegaFeedback.classList.add('d-none-force');
      quickBodegaFeedback.textContent = '';
      document.getElementById('qb-nombre').value = '';
      quickBodegaModal.show();
    });

    document.getElementById('quick-bodega-save').addEventListener('click', function () {
      var payload = new URLSearchParams({ nombre: document.getElementById('qb-nombre').value });

      fetch(data.bodegaQuickCreateUrl, {
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
            quickBodegaFeedback.textContent = mensajes.join(' ') || 'No se pudo crear la bodega.';
            quickBodegaFeedback.classList.remove('d-none-force');
            return;
          }
          var b = result.json.bodega;
          var opt = document.createElement('option');
          opt.value = b.id;
          opt.textContent = b.label;
          bodegaSelect.appendChild(opt);
          bodegaSelect.value = String(b.id);
          quickBodegaModal.hide();
        })
        .catch(function () {
          quickBodegaFeedback.textContent = 'Error de conexión al crear la bodega.';
          quickBodegaFeedback.classList.remove('d-none-force');
        });
    });
  });
})();
