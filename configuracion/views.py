from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from shared.decorators import permission_required_redirect

from .forms import (
    ConectarFacturacionElectronicaForm, ConfiguracionSistemaForm, EditarEmpresaActivaForm,
    VincularEmpresaExistenteForm,
)
from .models import ConfiguracionSistema, EmpresaFacturacionElectronica


@permission_required_redirect('configuracion.change_configuracionsistema', '/')
def configuracion_editar(request):
    config = ConfiguracionSistema.get_solo()

    if request.method == 'POST':
        form = ConfiguracionSistemaForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'Configuración actualizada.')
            return redirect('configuracion:configuracion_editar')
    else:
        form = ConfiguracionSistemaForm(instance=config)

    conectar_form = ConectarFacturacionElectronicaForm(initial={
        'ruc': config.empresa_ruc,
        'razon_social': config.empresa_nombre,
        'direccion_matriz': config.empresa_direccion,
        'establecimiento': config.sri_establecimiento,
        'punto_emision': config.sri_punto_emision,
        'ambiente': config.sri_ambiente,
    })
    vincular_form = VincularEmpresaExistenteForm()
    empresas = EmpresaFacturacionElectronica.objects.all()
    empresa_activa = EmpresaFacturacionElectronica.get_activa()
    editar_empresa_form = EditarEmpresaActivaForm(initial={
        'razon_social': empresa_activa.razon_social,
        'direccion_matriz': empresa_activa.direccion_matriz,
        'establecimiento': empresa_activa.codigo_establecimiento,
        'punto_emision': empresa_activa.codigo_punto_emision,
        'ambiente': empresa_activa.ambiente,
    }) if empresa_activa else None

    return render(request, 'configuracion/configuracion_form.html', {
        'form': form, 'conectar_form': conectar_form, 'vincular_form': vincular_form,
        'config': config, 'empresas': empresas, 'empresa_activa': empresa_activa,
        'editar_empresa_form': editar_empresa_form,
    })


@permission_required_redirect('configuracion.change_configuracionsistema', '/')
def conectar_facturacion_electronica(request):
    """Da de alta una empresa NUEVA en el microservicio de facturación
    electrónica y la agrega (activada) a la lista de empresas conectadas.
    Ver ConectarFacturacionElectronicaForm y las llamadas HTTP en
    facturacion_electronica.services (crear_empresa/subir_certificado)."""
    if request.method != 'POST':
        return redirect('configuracion:configuracion_editar')

    form = ConectarFacturacionElectronicaForm(request.POST, request.FILES)
    if not form.is_valid():
        detalle = '; '.join(
            f'{campo}: {", ".join(errores)}' for campo, errores in form.errors.items()
        )
        messages.error(request, f'Revisa los datos del formulario de facturación electrónica: {detalle}')
        return redirect('configuracion:configuracion_editar')

    from facturacion_electronica.services import SRIError, crear_empresa, subir_certificado

    datos = form.cleaned_data
    datos_empresa = {
        'ruc': datos['ruc'],
        'razon_social': datos['razon_social'],
        'direccion_matriz': datos['direccion_matriz'],
        'establecimiento': datos['establecimiento'],
        'punto_emision': datos['punto_emision'],
        'ambiente': datos['ambiente'],
    }

    try:
        resultado = crear_empresa(datos_empresa)
        try:
            empresa_id = resultado['id']
            api_key = resultado['api_key']
        except (KeyError, TypeError):
            raise SRIError('El microservicio no devolvió los datos esperados (id/api_key) al crear la empresa.')

        # Se guarda YA (antes de subir el certificado, y todavía inactiva):
        # si el paso del certificado falla, la empresa YA existe del lado
        # del microservicio y queda registrada acá también, para no perder
        # el id/api_key ni arriesgar un alta duplicada en un reintento.
        empresa = EmpresaFacturacionElectronica.objects.create(
            ruc=datos['ruc'], razon_social=datos['razon_social'], direccion_matriz=datos['direccion_matriz'],
            codigo_establecimiento=datos['establecimiento'], codigo_punto_emision=datos['punto_emision'],
            ambiente=datos['ambiente'], empresa_id_microservicio=str(empresa_id), api_key=api_key, activa=False,
        )
        subir_certificado(
            empresa.empresa_id_microservicio, empresa.api_key,
            datos['certificado_p12'], datos['certificado_password'],
        )
    except SRIError as e:
        messages.error(request, str(e))
        return redirect('configuracion:configuracion_editar')

    # Recién ahora, con el certificado ya subido, se activa (deja inactivas
    # a las demás automáticamente, ver EmpresaFacturacionElectronica.save()).
    empresa.activa = True
    empresa.save()
    messages.success(request, f'Empresa "{empresa.razon_social}" conectada y activada.')
    return redirect('configuracion:configuracion_editar')


@permission_required_redirect('configuracion.change_configuracionsistema', '/')
def vincular_empresa_existente(request):
    """Para una empresa que YA está dada de alta del lado del microservicio
    (ej. creada por script) — solo pide la api_key y trae el resto con GET
    /empresas/me, sin duplicar el alta. Ver VincularEmpresaExistenteForm."""
    if request.method != 'POST':
        return redirect('configuracion:configuracion_editar')

    form = VincularEmpresaExistenteForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Ingresa la api_key de la empresa a vincular.')
        return redirect('configuracion:configuracion_editar')

    from facturacion_electronica.services import SRIError, datos_empresa_desde_respuesta, obtener_empresa_actual

    api_key = form.cleaned_data['api_key']
    try:
        data = obtener_empresa_actual(api_key)
    except SRIError as e:
        messages.error(request, str(e))
        return redirect('configuracion:configuracion_editar')

    empresa_id = data.get('id')
    if empresa_id is None:
        messages.error(request, 'El microservicio no devolvió el id de la empresa.')
        return redirect('configuracion:configuracion_editar')

    campos = datos_empresa_desde_respuesta(data)
    # update_or_create por empresa_id_microservicio: si ya estaba vinculada
    # (ej. el admin repite la operación), actualiza en vez de duplicarla.
    empresa, _creada = EmpresaFacturacionElectronica.objects.update_or_create(
        empresa_id_microservicio=str(empresa_id),
        defaults={**campos, 'api_key': api_key, 'activa': True},
    )
    messages.success(request, f'Empresa "{empresa.razon_social}" vinculada y activada.')
    return redirect('configuracion:configuracion_editar')


@permission_required_redirect('configuracion.change_configuracionsistema', '/')
def activar_empresa_facturacion_electronica(request, pk):
    """Marca una empresa ya conectada como la activa (desactiva las demás,
    ver EmpresaFacturacionElectronica.save()). El cambio es manual, nunca
    automático por venta."""
    if request.method != 'POST':
        return redirect('configuracion:configuracion_editar')

    empresa = get_object_or_404(EmpresaFacturacionElectronica, pk=pk)
    empresa.activa = True
    empresa.save()
    messages.success(request, f'Empresa "{empresa.razon_social}" activada.')
    return redirect('configuracion:configuracion_editar')


@permission_required_redirect('configuracion.change_configuracionsistema', '/')
def editar_empresa_activa(request):
    """Modal 'Editar datos' de la empresa ACTIVA: PATCH /empresas/{id} con
    razón social/dirección/establecimiento/punto de emisión/ambiente
    (nunca el RUC, ver EditarEmpresaActivaForm), y si se adjuntó un
    certificado nuevo, lo sube aparte con subir_certificado() (ya
    existente, sin cambios)."""
    if request.method != 'POST':
        return redirect('configuracion:configuracion_editar')

    empresa = EmpresaFacturacionElectronica.get_activa()
    if empresa is None:
        messages.error(request, 'No hay ninguna empresa activa para editar.')
        return redirect('configuracion:configuracion_editar')

    form = EditarEmpresaActivaForm(request.POST, request.FILES)
    if not form.is_valid():
        detalle = '; '.join(
            f'{campo}: {", ".join(errores)}' for campo, errores in form.errors.items()
        )
        messages.error(request, f'Revisa los datos del formulario: {detalle}')
        return redirect('configuracion:configuracion_editar')

    from facturacion_electronica.services import SRIError, editar_empresa, subir_certificado

    datos = form.cleaned_data
    try:
        editar_empresa(empresa.empresa_id_microservicio, {
            'razon_social': datos['razon_social'], 'direccion_matriz': datos['direccion_matriz'],
            'establecimiento': datos['establecimiento'], 'punto_emision': datos['punto_emision'],
            'ambiente': datos['ambiente'],
        })
        if datos['certificado_p12']:
            subir_certificado(
                empresa.empresa_id_microservicio, empresa.api_key,
                datos['certificado_p12'], datos['certificado_password'],
            )
    except SRIError as e:
        messages.error(request, str(e))
        return redirect('configuracion:configuracion_editar')

    empresa.razon_social = datos['razon_social']
    empresa.direccion_matriz = datos['direccion_matriz']
    empresa.codigo_establecimiento = datos['establecimiento']
    empresa.codigo_punto_emision = datos['punto_emision']
    empresa.ambiente = datos['ambiente']
    empresa.save()
    messages.success(request, 'Datos de la empresa actualizados.')
    return redirect('configuracion:configuracion_editar')


@permission_required_redirect('configuracion.change_configuracionsistema', '/')
def cambiar_ambiente_empresa_activa(request):
    """Botón 'Cambiar de ambiente' de la empresa activa (con confirmación
    del lado del template) — invierte pruebas<->producción mandando SOLO
    ese campo en el PATCH."""
    if request.method != 'POST':
        return redirect('configuracion:configuracion_editar')

    empresa = EmpresaFacturacionElectronica.get_activa()
    if empresa is None:
        messages.error(request, 'No hay ninguna empresa activa.')
        return redirect('configuracion:configuracion_editar')

    from facturacion_electronica.services import SRIError, editar_empresa

    nuevo_ambiente = (
        ConfiguracionSistema.AMBIENTE_PRODUCCION if empresa.ambiente == ConfiguracionSistema.AMBIENTE_PRUEBAS
        else ConfiguracionSistema.AMBIENTE_PRUEBAS
    )
    try:
        editar_empresa(empresa.empresa_id_microservicio, {'ambiente': nuevo_ambiente})
    except SRIError as e:
        messages.error(request, str(e))
        return redirect('configuracion:configuracion_editar')

    empresa.ambiente = nuevo_ambiente
    empresa.save()
    messages.success(request, f'Ambiente cambiado a {empresa.get_ambiente_display()}.')
    return redirect('configuracion:configuracion_editar')
