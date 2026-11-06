from django.core.management import call_command
from django.test import TestCase

from ..models import BSourceCandidate, Evidence


class BSourceWorkbookTests(TestCase):
    def test_workbook_is_review_only_and_reimport_preserves_decisions(self):
        call_command('import_b_sources', verbosity=0)
        self.assertEqual(BSourceCandidate.objects.count(), 91)
        self.assertEqual(Evidence.objects.count(), 0)
        candidate = BSourceCandidate.objects.get(sheet='Student views', row_number=6)
        self.assertEqual(candidate.matched_source_ids, ['KR_korea'])
        self.assertEqual(candidate.collection_status, 'downloaded')
        self.assertEqual(candidate.quote_match, 'yes')
        guideline = BSourceCandidate.objects.get(sheet='Student views', row_number=9)
        self.assertEqual(guideline.quote_match, 'yes')
        self.assertTrue(guideline.matching_attachment_paths)
        candidate.decision = 'exclude'
        candidate.review_note = 'Manual review'
        candidate.save(update_fields=['decision', 'review_note'])

        call_command('import_b_sources', verbosity=0)
        candidate.refresh_from_db()
        self.assertEqual(BSourceCandidate.objects.count(), 91)
        self.assertEqual(candidate.decision, 'exclude')
        self.assertEqual(candidate.review_note, 'Manual review')
        self.assertEqual(Evidence.objects.count(), 0)
