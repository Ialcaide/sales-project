/*
 * Tarjeta animada + pasarela simulada para el formulario de pago a
 * proveedores (pagos/pago_form.html). Copiado y adaptado de
 * static/js/invoice-wizard.js (mismo patrón que ya usa facturas) — acá no
 * hay formset de líneas ni PayPal real, así que se deja afuera todo lo que
 * no aplica (panel PayPal, modal de efectivo/cajero, wizard de pasos).
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var pagoForm = document.getElementById('pago-form');
    if (!pagoForm) return;

    var formaPagoSelect = document.getElementById('id_forma_pago');
    var tarjetaWrapper = document.getElementById('tarjeta-wrapper');
    var guardarPagoBtn = document.getElementById('guardar-pago-btn');
    var tarjetaPagoEstado = document.getElementById('tarjeta-pago-estado');
    var valorInput = document.getElementById('id_valor');
    var tarjetaConfirmada = false;

    function getTotalActual() {
      return parseFloat(valorInput.value) || 0;
    }

    function actualizarEstadoPagoTarjeta() {
      if (formaPagoSelect.value !== 'tarjeta') {
        guardarPagoBtn.disabled = false;
        return;
      }
      guardarPagoBtn.disabled = !tarjetaConfirmada;
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

    /* ---------- Tarjeta animada (preview visual + detección de marca) ---------- */
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

    /* ---------- Pasarela de pago simulada ---------- */
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
      pasarelaTotal.textContent = '$' + getTotalActual().toFixed(2);
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

    pagoForm.addEventListener('submit', function (e) {
      if (formaPagoSelect.value === 'tarjeta' && !tarjetaConfirmada) {
        // Salvaguarda: si el submit llega por otra vía que no sea el click
        // en "Guardar Pago" (ej. Enter dentro de un campo de texto, que no
        // respeta el atributo disabled del botón), igual se corta acá y se
        // obliga a pasar por la pasarela.
        e.preventDefault();
        abrirPasarelaModal();
      }
    });

    toggleTarjetaCampos();
  });
})();
