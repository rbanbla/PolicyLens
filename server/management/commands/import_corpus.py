from django.core.management.base import BaseCommand
from django.db import transaction
from server.data import corpus
from server.models import Evidence, ResearchAsset


class Command(BaseCommand):
    help = "Index all collected assets and import traceable provisional B evidence."

    @transaction.atomic
    def handle(self, *args, **options):
        count = corpus.index_assets()
        self.stdout.write(f"Assets indexed: {count}")
        Evidence.objects.filter(managed=True).update(present=False)
        corpus.import_student_transcripts()
        corpus.import_faculty_aggregates()
        corpus.import_policies()
        corpus.import_asu_policies()
        corpus.index_tabular()
        profiles = corpus.import_profiles()
        self.stdout.write(f"Evidence: {Evidence.objects.filter(active=True, present=True).count()}, profile sample: {profiles}")
        self.stdout.write(f"Missing source paths: {ResearchAsset.objects.filter(available=False).count()}")
