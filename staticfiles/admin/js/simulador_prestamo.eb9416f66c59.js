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
            <div style="font-size: 16px; margin-top: 10px; border-top: 1px dashed #cbd5e1; padding-top: 8px; margin-bottom: 10px;">
                <strong>Cuota Mensual Estimada:</strong> <span id="sim-cuota" style="font-weight: bold; color: #2563eb;">$0.00</span>
            </div>
            
            <!-- Tabla de Amortización Proyectada -->
            <div style="margin-top: 15px; margin-bottom: 15px;">
                <strong>Detalle de Cuotas Proyectadas:</strong>
                <div id="sim-cuotas-tabla" style="max-height: 200px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8px; background: #fff; margin-top: 5px;">
                    <span style="color: #64748b; font-style: italic; font-size: 13px;">Ingrese monto, cuotas y fecha para ver el cronograma.</span>
                </div>
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
    const fechaInput = document.getElementById('id_fecha_prestamo');
    
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
    
    function addMonths(date, months) {
        let d = new Date(date);
        let expectedMonth = d.getMonth() + months;
        d.setMonth(expectedMonth);
        // Ajustar desbordamiento de fin de mes
        if (d.getMonth() !== (expectedMonth % 12 + 12) % 12) {
            d.setDate(0);
        }
        return d;
    }
    
    function recalculate() {
        const monto = parseFloat(montoInput.value || 0);
        const cuotas = parseInt(cuotasInput.value || 0);
        
        // Elementos de solo lectura oficiales del Django Admin
        const interesDiv = document.querySelector('.field-interes .readonly');
        const pagarDiv = document.querySelector('.field-monto_pagar .readonly');
        const saldoDiv = document.querySelector('.field-saldo .readonly');
        const tablaContainer = document.getElementById('sim-cuotas-tabla');
        
        if (monto <= 0 || cuotas <= 0) {
            document.getElementById('sim-interes').innerText = '$0.00';
            document.getElementById('sim-total').innerText = '$0.00';
            document.getElementById('sim-cuota').innerText = '$0.00';
            document.getElementById('sim-alerta').style.display = 'none';
            tablaContainer.innerHTML = `<span style="color: #64748b; font-style: italic; font-size: 13px;">Ingrese monto, cuotas y fecha para ver el cronograma.</span>`;
            
            // Limpiar campos oficiales
            if (interesDiv) interesDiv.innerText = '$0.00';
            if (pagarDiv) pagarDiv.innerText = '$0.00';
            if (saldoDiv) saldoDiv.innerText = '$0.00';
            return;
        }
        
        const interes = monto * (tasaInteres / 100);
        const total = monto + interes;
        const cuota = total / cuotas;
        
        // Actualizar caja del simulador
        document.getElementById('sim-interes').innerText = `$${interes.toFixed(2)}`;
        document.getElementById('sim-total').innerText = `$${total.toFixed(2)}`;
        document.getElementById('sim-cuota').innerText = `$${cuota.toFixed(2)}`;
        
        // Actualizar campos oficiales de solo lectura en el formulario antes de guardar
        if (interesDiv) interesDiv.innerText = `$${interes.toFixed(2)}`;
        if (pagarDiv) pagarDiv.innerText = `$${total.toFixed(2)}`;
        if (saldoDiv) saldoDiv.innerText = `$${total.toFixed(2)}`;
        
        // Generar tabla de amortización proyectada en caliente
        let fechaBase = new Date();
        const fechaStr = fechaInput ? fechaInput.value : '';
        if (fechaStr) {
            const parts = fechaStr.split('-');
            fechaBase = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        }
        
        let offset = 1;
        let primerMes = addMonths(fechaBase, offset);
        let diffDays = Math.ceil((primerMes - fechaBase) / (1000 * 60 * 60 * 24));
        if (diffDays < 15) {
            offset = 2;
        }
        
        let cuotasListHTML = `
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="border-bottom: 2px solid #cbd5e1; text-align: left; color: #475569;">
                        <th style="padding: 4px;">N° Cuota</th>
                        <th style="padding: 4px;">Vencimiento</th>
                        <th style="padding: 4px; text-align: right;">Monto</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        const valorNormal = parseFloat((total / cuotas).toFixed(2));
        for (let i = 1; i <= cuotas; i++) {
            let cuotaValor = valorNormal;
            if (i === cuotas) {
                cuotaValor = total - (valorNormal * (cuotas - 1));
            }
            
            let fechaVenc = addMonths(fechaBase, offset + i - 1);
            const yyyy = fechaVenc.getFullYear();
            const mm = String(fechaVenc.getMonth() + 1).padStart(2, '0');
            const dd = String(fechaVenc.getDate()).padStart(2, '0');
            const fechaFormateada = `${dd}/${mm}/${yyyy}`;
            
            cuotasListHTML += `
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 4px; color: #64748b;">Cuota ${i}</td>
                    <td style="padding: 4px;">${fechaFormateada}</td>
                    <td style="padding: 4px; text-align: right; font-weight: bold; color: #1e293b;">$${cuotaValor.toFixed(2)}</td>
                </tr>
            `;
        }
        
        cuotasListHTML += `
                </tbody>
            </table>
        `;
        tablaContainer.innerHTML = cuotasListHTML;
        
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
    if (fechaInput) {
        fechaInput.addEventListener('change', recalculate);
    }
    
    // Ejecutar inicialmente si ya vienen con datos pre-seleccionados
    if (empleadoSelect && empleadoSelect.value) fetchSueldo();
    if (tipoSelect && tipoSelect.value) fetchTasa();
});
