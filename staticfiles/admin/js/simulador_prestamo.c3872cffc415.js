document.addEventListener('DOMContentLoaded', function () {
    // 1. Crear e insertar el contenedor del simulador
    const fieldsets = document.querySelectorAll('fieldset.module');
    if (fieldsets.length === 0) return;
    
    const simulatorDiv = document.createElement('div');
    simulatorDiv.id = 'prestamo-simulator-box';
    simulatorDiv.className = 'module';
    simulatorDiv.style.marginTop = '20px';
    simulatorDiv.style.padding = '15px';
    simulatorDiv.style.border = '1px solid #ccc';
    simulatorDiv.style.borderRadius = '4px';
    simulatorDiv.style.backgroundColor = '#f9f9f9';
    
    simulatorDiv.innerHTML = `
        <h2 style="margin-top: 0; color: #1e293b; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 12px;">Simulador: Cuota Mensual Estimada</h2>
        <div style="font-size: 14px; line-height: 1.8; color: #334155;">
            <div><strong>Sueldo Empleado:</strong> <span id="sim-sueldo">$0.00</span></div>
            <div><strong>Tasa de Interés:</strong> <span id="sim-tasa">0%</span></div>
            <div><strong>Interés Estimado:</strong> <span id="sim-interes">$0.00</span></div>
            <div><strong>Total a Pagar (Estimado):</strong> <span id="sim-total">$0.00</span></div>
            <div style="font-size: 16px; margin-top: 10px; border-top: 1px dashed #cbd5e1; padding-top: 8px;">
                <strong>Cuota Mensual Estimada:</strong> <span id="sim-cuota" style="font-weight: bold; color: #2563eb;">$0.00</span>
            </div>
            <div id="sim-alerta" style="margin-top: 12px; padding: 10px; border-radius: 4px; display: none; font-weight: bold; font-size: 13px;"></div>
        </div>
    `;
    
    // Insertar después del primer fieldset
    fieldsets[0].parentNode.insertBefore(simulatorDiv, fieldsets[0].nextSibling);
    
    // 2. Selectores de los campos del formulario del Admin
    const empleadoSelect = document.getElementById('id_empleado');
    const tipoSelect = document.getElementById('id_tipo_prestamo');
    const montoInput = document.getElementById('id_monto');
    const cuotasInput = document.getElementById('id_numero_cuotas');
    
    let sueldoEmpleado = 0;
    let tasaInteres = 0;
    
    function fetchSueldo() {
        const id = empleadoSelect.value;
        if (!id) {
            sueldoEmpleado = 0;
            document.getElementById('sim-sueldo').innerText = '$0.00';
            recalculate();
            return;
        }
        fetch(`/rrhh/prestamos/api/empleado/${id}/`)
            .then(res => {
                if (!res.ok) throw new Error('Error al obtener sueldo');
                return res.json();
            })
            .then(data => {
                sueldoEmpleado = parseFloat(data.sueldo || 0);
                document.getElementById('sim-sueldo').innerText = `$${sueldoEmpleado.toFixed(2)}`;
                recalculate();
            })
            .catch(err => console.error(err));
    }
    
    function fetchTasa() {
        const id = tipoSelect.value;
        if (!id) {
            tasaInteres = 0;
            document.getElementById('sim-tasa').innerText = '0%';
            recalculate();
            return;
        }
        fetch(`/rrhh/prestamos/api/tipo-prestamo/${id}/`)
            .then(res => {
                if (!res.ok) throw new Error('Error al obtener tasa');
                return res.json();
            })
            .then(data => {
                tasaInteres = parseFloat(data.tasa_interes || 0);
                document.getElementById('sim-tasa').innerText = `${tasaInteres}%`;
                recalculate();
            })
            .catch(err => console.error(err));
    }
    
    function recalculate() {
        const monto = parseFloat(montoInput.value || 0);
        const cuotas = parseInt(cuotasInput.value || 0);
        
        if (monto <= 0 || cuotas <= 0) {
            document.getElementById('sim-interes').innerText = '$0.00';
            document.getElementById('sim-total').innerText = '$0.00';
            document.getElementById('sim-cuota').innerText = '$0.00';
            document.getElementById('sim-alerta').style.display = 'none';
            return;
        }
        
        const interes = monto * (tasaInteres / 100);
        const total = monto + interes;
        const cuota = total / cuotas;
        
        document.getElementById('sim-interes').innerText = `$${interes.toFixed(2)}`;
        document.getElementById('sim-total').innerText = `$${total.toFixed(2)}`;
        document.getElementById('sim-cuota').innerText = `$${cuota.toFixed(2)}`;
        
        const alerta = document.getElementById('sim-alerta');
        if (sueldoEmpleado > 0) {
            const limite40 = sueldoEmpleado * 0.40;
            if (cuota > sueldoEmpleado) {
                alerta.innerText = `¡Crítico! La cuota ($${cuota.toFixed(2)}) supera el 100% del sueldo ($${sueldoEmpleado.toFixed(2)}).`;
                alerta.style.backgroundColor = '#fee2e2';
                alerta.style.color = '#991b1b';
                alerta.style.border = '1px solid #fca5a5';
                alerta.style.display = 'block';
            } else if (cuota > limite40) {
                alerta.innerText = `¡Alerta! La cuota ($${cuota.toFixed(2)}) supera el 40% del sueldo ($${limite40.toFixed(2)}).`;
                alerta.style.backgroundColor = '#fef3c7';
                alerta.style.color = '#92400e';
                alerta.style.border = '1px solid #fcd34d';
                alerta.style.display = 'block';
            } else {
                alerta.innerText = `Apto. La cuota está dentro de la capacidad de endeudamiento del empleado.`;
                alerta.style.backgroundColor = '#dcfce7';
                alerta.style.color = '#166534';
                alerta.style.border = '1px solid #86efac';
                alerta.style.display = 'block';
            }
        } else {
            alerta.style.display = 'none';
        }
    }
    
    // Asignar listeners
    if (empleadoSelect) empleadoSelect.addEventListener('change', fetchSueldo);
    if (tipoSelect) tipoSelect.addEventListener('change', fetchTasa);
    
    if (montoInput) {
        montoInput.addEventListener('input', recalculate);
        montoInput.addEventListener('change', recalculate);
    }
    if (cuotasInput) {
        cuotasInput.addEventListener('input', recalculate);
        cuotasInput.addEventListener('change', recalculate);
    }
    
    // Ejecutar inicialmente si ya vienen con datos pre-seleccionados
    if (empleadoSelect && empleadoSelect.value) fetchSueldo();
    if (tipoSelect && tipoSelect.value) fetchTasa();
});
