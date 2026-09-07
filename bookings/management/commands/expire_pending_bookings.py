from django.core.management.base import BaseCommand
from bookings.services import expire_pending


class Command(BaseCommand):
    help = "Expire stale pending booking holds."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f"Expired {expire_pending()} booking(s)."))
