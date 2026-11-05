"""Load a curated, non-user-data snapshot once into a fresh hosted database."""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from server.models import Evidence, ResearchAsset, StudyCase


class Command(BaseCommand):
    help = "Load the initial public policy and B evidence snapshot once."

    @transaction.atomic
    def handle(self, *args, **options):
        if Evidence.objects.exists():
            self.stdout.write("B evidence already present; seed skipped")
            return
        if ResearchAsset.objects.exists() or StudyCase.objects.exists():
            raise CommandError("Database is partially populated; refusing to overwrite existing data")
        fixture = settings.BASE_DIR / "deploy" / "seed.json.gz"
        if not fixture.is_file():
            raise CommandError("Missing deploy/seed.json.gz")
        call_command("loaddata", str(fixture), verbosity=0)
        if not Evidence.objects.exists() or not StudyCase.objects.exists():
            raise CommandError("Seed lacks the public policy or B evidence")
        self.stdout.write(f"Seed loaded: {Evidence.objects.count()} B records")
