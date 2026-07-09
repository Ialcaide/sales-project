from urllib.parse import urlencode


def build_extra_qs(request, exclude=('page',)):
    """
    Reconstruye el querystring actual (sin 'page') para que los links de la
    paginación conserven los filtros que el usuario ya aplicó (búsqueda,
    estado, rango de fechas, etc.) sin que cada vista tenga que enumerar a
    mano cuáles son sus propios parámetros de filtro.
    """
    params = request.GET.copy()
    for key in exclude:
        params.pop(key, None)
    return urlencode(params, doseq=True)


def get_page_range(page_obj, window=2):
    """
    Arma la lista de números de página a mostrar en la barra de paginación,
    con None donde se debe mostrar "…" (un salto). Siempre incluye la
    primera y la última página, más un rango alrededor de la página actual.

    Ej. con 20 páginas y estando en la página 10: [1, None, 8, 9, 10, 11, 12, None, 20]
    """
    total = page_obj.paginator.num_pages
    if total <= 1:
        return []

    current = page_obj.number
    pages = {1, total}
    for n in range(current - window, current + window + 1):
        if 1 <= n <= total:
            pages.add(n)

    result = []
    previous = None
    for p in sorted(pages):
        if previous is not None and p - previous > 1:
            result.append(None)
        result.append(p)
        previous = p
    return result
