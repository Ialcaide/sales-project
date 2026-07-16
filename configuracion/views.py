from django.contrib import messages
from django.shortcuts import redirect, render

from shared.decorators import permission_required_redirect

from .forms import ConfiguracionSistemaForm
from .models import ConfiguracionSistema


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

    return render(request, 'configuracion/configuracion_form.html', {'form': form})
