from django.core.management.base import BaseCommand

from billing.models import Customer, Supplier
from security.models import UserProfile
from shared.validators import normalize_phone, validate_phone
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = (
        'Normaliza los teléfonos ya guardados (Customer, Supplier, UserProfile) '
        'anteponiendo +593 a los que no tengan código de país, para que '
        'send_whatsapp_message (shared/notifications.py) los pueda usar tal cual.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué cambiaría, sin guardar nada.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total_actualizados = 0

        for label, queryset in (
            ('Customer', Customer.objects.exclude(phone__isnull=True).exclude(phone='')),
            ('Supplier', Supplier.objects.exclude(phone__isnull=True).exclude(phone='')),
            ('UserProfile', UserProfile.objects.exclude(phone='')),
        ):
            for obj in queryset:
                original = obj.phone
                normalizado = normalize_phone(original)
                if normalizado == original:
                    continue
                try:
                    validate_phone(normalizado)
                except ValidationError:
                    self.stdout.write(self.style.WARNING(
                        f'{label} #{obj.pk}: "{original}" no se pudo normalizar a un formato válido, se deja igual.'
                    ))
                    continue

                self.stdout.write(f'{label} #{obj.pk}: "{original}" -> "{normalizado}"')
                total_actualizados += 1
                if not dry_run:
                    obj.phone = normalizado
                    obj.save(update_fields=['phone'])

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'(dry-run) {total_actualizados} teléfonos se normalizarían.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'{total_actualizados} teléfonos normalizados.'))
