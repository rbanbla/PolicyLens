"""Policy fact trust boundaries and deterministic condition behavior."""
from datetime import date
from importlib.util import find_spec
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from .models import ReviewRun
from .agents.runner import call_model


class TimingTests(TestCase):
    def test_retry_records_purpose_tokens_and_no_payload(self):
        run = ReviewRun(pages=['private'], calls=[], steps=[], analysis={})
        with patch('server.agents.runner.transport.call', side_effect=[TimeoutError(), {'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15}}]):
            call_model(run, 'analysis', {'input': 'private'}, 'secret')
        self.assertEqual(run.calls[0].get('attempt'), 1)
        self.assertEqual(run.calls[1].get('attempt'), 2)
        self.assertEqual(run.calls[1].get('input_tokens'), 12)
        self.assertEqual(run.calls[1].get('output_tokens'), 3)
        self.assertEqual(run.calls[1].get('purpose'), 'model')
        self.assertIsNone(run.calls[1].get('step_index'))
        self.assertNotIn('private', str(run.calls))
        self.assertNotIn('secret', str(run.calls))


class ConditionTests(SimpleTestCase):
    def setUp(self):
        self.assertIsNotNone(find_spec('server.agents.tools.policy_facts'), 'condition evaluator is missing')
        from .agents.tools.policy_facts import evaluate_condition, validate_condition
        self.evaluate = evaluate_condition
        self.validate = validate_condition
        self.condition = {'compare': {'field': 'age', 'operator': 'gte', 'value': 19,
                                      'unit': 'years', 'basis': '2026-01-01'}}
        self.context = {'age': {'value': 19, 'unit': 'years', 'basis': '2026-01-01'}}

    def test_boundary_and_missing_basis(self):
        self.assertEqual(self.evaluate(self.condition, self.context)['status'], 'met')
        self.context['age']['value'] = 18
        self.assertEqual(self.evaluate(self.condition, self.context)['status'], 'not_met')
        self.context['age']['basis'] = '2026-02-01'
        self.assertEqual(self.evaluate(self.condition, self.context)['status'], 'unknown')
        self.assertEqual(self.evaluate(self.condition, {})['missing_fields'], ['age'])

    def test_three_valued_boolean_logic(self):
        unknown = {'compare': {'field': 'enrollment', 'operator': 'eq', 'value': True, 'unit': 'boolean', 'basis': '2026-01-01'}}
        self.assertEqual(self.evaluate({'all': [self.condition, unknown]}, self.context)['status'], 'unknown')
        self.assertEqual(self.evaluate({'any': [self.condition, unknown]}, self.context)['status'], 'met')
        self.assertEqual(self.evaluate({'not': unknown}, self.context)['status'], 'unknown')
        self.context['age']['value'] = 18
        self.assertEqual(self.evaluate({'all': [self.condition, unknown]}, self.context)['status'], 'not_met')

    def test_rejects_malformed_conditions_and_values(self):
        for condition in [{'all': []}, {'evil': 'exec'}, {'compare': {**self.condition['compare'], 'operator': 'eval'}},
                          {'compare': {**self.condition['compare'], 'value': True}},
                          {'compare': {**self.condition['compare'], 'value': float('nan')}}]:
            with self.subTest(condition=condition), self.assertRaises(ValueError):
                self.validate(condition)
        self.context['age']['value'] = '19'
        self.assertEqual(self.evaluate(self.condition, self.context)['status'], 'unknown')
        self.context['age']['value'] = True
        self.assertEqual(self.evaluate(self.condition, self.context)['status'], 'unknown')

    def test_income_requires_subject_and_household_scope(self):
        condition = {'compare': {'field': 'income_ratio', 'operator': 'lte', 'value': 60,
                                  'unit': 'percent_median', 'basis': '2026-01-01'}}
        with self.assertRaises(ValueError): self.validate(condition)
        condition['compare']['basis'] = {'date': '2026-01-01', 'subject': 'youth_household', 'household_scope': '청년과 배우자'}
        context = {'income_ratio': {'value': 50, 'unit': 'percent_median', 'basis': {'date': '2026-01-01'}}}
        self.assertEqual(self.evaluate(condition, context)['status'], 'unknown')

    def test_depth_and_income_subject(self):
        deep = self.condition
        for _ in range(11): deep = {'not': deep}
        with self.assertRaises(ValueError): self.validate(deep)
        income = {'compare': {'field': 'income_ratio', 'operator': 'lte', 'value': 60,
                              'unit': 'percent_median', 'basis': {'date': '2026-01-01', 'subject': 'youth_household', 'household_scope': '청년과 배우자'}}}
        context = {'income_ratio': {'value': 50, 'unit': 'percent_median', 'basis': {'date': '2026-01-01', 'subject': 'original_household', 'household_scope': '청년과 부모'}}}
        self.assertEqual(self.evaluate(income, context)['status'], 'unknown')


class FactStoreTests(TestCase):
    def setUp(self):
        from . import models
        self.assertTrue(hasattr(models, 'PolicyFact'), 'policy models are missing')
        from .models import Policy, PolicyVersion, PolicyFact, FactEvidence, Source
        from .agents.tools.policy_facts import source_digest
        self.Policy, self.Version, self.Fact, self.Evidence = Policy, PolicyVersion, PolicyFact, FactEvidence
        self.source = Source.objects.create(doc_id='official-1', kind='policy', title='서울 청년 월세', issuer='서울시',
                                            version='2026 공고', source_url='https://example.go.kr/notice',
                                            published_on='2026-01-01', pages=['신청 대상은 만 19세 이상 청년입니다. 중복 지원은 불가합니다.'])
        self.source.refresh_from_db()
        self.digest = source_digest
        self.row = {'policy': {'policy_id': 'seoul-rent', 'title': '서울 청년 월세', 'region_code': '11', 'issuer': '서울시'},
                    'version': {'version_id': 'seoul-rent-2026', 'label': '2026', 'effective_from': '2026-01-01',
                                'effective_until': '2026-12-31', 'application_from': None, 'application_until': None},
                    'fact': {'fact_id': 'seoul-age', 'predicate': 'eligibility',
                             'value': {'compare': {'field': 'age', 'operator': 'gte', 'value': 19, 'unit': 'years', 'basis': '2026-01-01'}},
                             'status': 'verified', 'reviewed_by': 'test-reviewer', 'reviewed_at': '2026-01-02T00:00:00+00:00', 'extracted_by': 'test'},
                    'evidence': [{'source_id': self.source.doc_id, 'source_hash': source_digest(self.source), 'page': 1,
                                  'quote': '신청 대상은 만 19세 이상 청년입니다.'}]}

    def load(self, rows=None, dry_run=False, gate='pass'):
        import tempfile, json
        from pathlib import Path
        from io import StringIO
        from django.core.management import call_command
        with tempfile.TemporaryDirectory() as d, self.settings(BASE_DIR=Path(d)):
            reviewed = Path(d) / 'data' / 'reviewed'
            reviewed.mkdir(parents=True)
            from .models import Source
            (reviewed / 'documents.jsonl').write_text('\n'.join(json.dumps({'doc_id': src.doc_id,
                'gate': {'technical': gate, 'rights': 'pass'}, 'external_send_ok': True}) for src in Source.objects.all()))
            manifest = Path(d) / 'facts.jsonl'
            manifest.write_text('\n'.join(json.dumps(row) for row in (rows if rows is not None else [self.row])))
            call_command('load_policy_facts', manifest=str(manifest), dry_run=dry_run, stdout=StringIO())

    def test_import_idempotent_and_dry_run(self):
        self.load(dry_run=True)
        self.assertEqual(self.Fact.objects.count(), 0)
        self.load(); self.load()
        self.assertEqual(self.Policy.objects.count(), 1)
        self.assertEqual(self.Fact.objects.count(), 1)
        self.assertEqual(self.Evidence.objects.count(), 1)
        self.load(rows=[])
        self.assertEqual(self.Fact.objects.count(), 1)

    def test_invalid_quote_or_hash_rolls_back_batch(self):
        from copy import deepcopy
        from django.core.management.base import CommandError
        for key, value in [('quote', '원문에는 존재하지 않는 인용입니다.'), ('source_hash', '0'*64), ('page', True)]:
            bad = deepcopy(self.row)
            bad['fact']['fact_id'] = 'bad'
            bad['evidence'][0][key] = value
            with self.subTest(key=key), self.assertRaises(CommandError): self.load(rows=[self.row,bad])
            self.assertEqual(self.Fact.objects.count(), 0)

    def test_gate_and_review_metadata_are_required(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError): self.load(gate='hold')
        self.row['fact']['reviewed_by'] = ''
        with self.assertRaises(CommandError): self.load()
        self.assertEqual(self.Fact.objects.count(), 0)

    def test_lookup_excludes_unreviewed_stale_and_wrong_dates(self):
        from .agents.tools.policy_facts import lookup_facts
        self.load()
        args = dict(knowledge_as_of='2026-06-01', effective_on='2026-06-01')
        found = lookup_facts('서울 청년 월세', **args)
        self.assertEqual([f['fact_id'] for f in found], ['seoul-age'])
        self.assertEqual(lookup_facts('부산 청년 월세', **args), [])
        self.assertEqual(lookup_facts('존재하지않음', **args), [])
        self.assertEqual(lookup_facts('서울 청년 월세', knowledge_as_of='2025-12-31', effective_on='2026-06-01'), [])
        self.assertEqual(lookup_facts('서울 청년 월세', knowledge_as_of='2026-06-01', effective_on='2027-01-01'), [])
        self.Fact.objects.update(status='pending')
        self.assertEqual(lookup_facts('서울 청년 월세', **args), [])
        self.Fact.objects.update(status='verified')
        self.source.pages = ['변경된 정책 문서입니다.']
        self.source.save()
        self.assertEqual(lookup_facts('서울 청년 월세', **args), [])

    def test_explicit_correction_replaces_old_only_when_public(self):
        from copy import deepcopy
        from .models import Source
        from .agents.tools.policy_facts import lookup_facts
        self.load()
        corrected = Source.objects.create(doc_id='correction', kind='policy', title='서울 청년 월세 정정', issuer='서울시',
            version='정정', source_url='https://example.go.kr/correction', published_on='2026-07-01',
            pages=['신청 대상은 만 20세 이상 청년입니다.'])
        corrected.refresh_from_db()
        row = deepcopy(self.row)
        row['version'].update(version_id='corrected', label='정정', supersedes='seoul-rent-2026')
        row['fact']['fact_id'] = 'corrected-age'
        row['fact']['value']['compare']['value'] = 20
        row['evidence'] = [{'source_id': corrected.doc_id, 'source_hash': self.digest(corrected), 'page': 1, 'quote': corrected.pages[0]}]
        self.load(rows=[row])
        self.assertEqual([f['fact_id'] for f in lookup_facts('서울 청년 월세', knowledge_as_of='2026-06-01', effective_on='2026-06-01')], ['seoul-age'])
        self.assertEqual([f['fact_id'] for f in lookup_facts('서울 청년 월세', knowledge_as_of='2026-08-01', effective_on='2026-06-01')], ['corrected-age'])
        self.Fact.objects.filter(pk='corrected-age').update(status='pending')
        self.assertEqual([f['fact_id'] for f in lookup_facts('서울 청년 월세', knowledge_as_of='2026-08-01', effective_on='2026-06-01')], ['seoul-age'])

    def test_overlap_without_explicit_correction_is_not_resolved_by_recency(self):
        from copy import deepcopy
        from .agents.tools.policy_facts import lookup_facts
        self.load()
        row = deepcopy(self.row)
        row['version']['version_id'] = 'other-version'
        row['fact']['fact_id'] = 'other-age'
        self.load(rows=[row])
        self.assertEqual(len(lookup_facts('서울 청년 월세', effective_on='2026-06-01')), 2)

    def test_deleting_one_supporting_source_invalidates_entire_fact(self):
        from .models import Source
        from .agents.tools.policy_facts import lookup_facts
        from copy import deepcopy
        second = Source.objects.create(doc_id='second', kind='policy', title='정정 안내', issuer='서울시', version='2026',
            source_url='https://example.go.kr/second', published_on='2026-01-02', pages=self.source.pages)
        self.load()
        self.Evidence.objects.create(fact_id='seoul-age', source=second, source_hash=self.digest(second), page=1,
                                    quote=self.row['evidence'][0]['quote'])
        self.assertTrue(lookup_facts('서울 청년 월세', effective_on='2026-06-01'))
        second.delete()
        self.assertEqual(lookup_facts('서울 청년 월세', effective_on='2026-06-01'), [])

    def test_import_rejects_oversized_quote_and_non_object_records(self):
        from django.core.management.base import CommandError
        from copy import deepcopy
        with self.assertRaises(CommandError): self.load(rows=[dict(self.row, fact=[])])
        self.row['evidence'][0]['quote'] = '가' * 2001
        self.source.pages = [self.row['evidence'][0]['quote']]
        self.source.save()
        self.row['evidence'][0]['source_hash'] = self.digest(self.source)
        with self.assertRaises(CommandError): self.load()

    def test_pending_revision_revokes_old_fact(self):
        from .agents.tools.policy_facts import lookup_facts
        self.load()
        self.row['fact']['status'] = 'pending'
        self.row['fact']['reviewed_by'] = ''
        self.row['fact']['reviewed_at'] = None
        self.load()
        self.assertEqual(lookup_facts('서울 청년 월세', effective_on='2026-06-01'), [])

    def test_structured_search_obeys_upload_exclusion_and_opt_out(self):
        from .agents.tools.sources import new_research, search_sources
        self.load()
        research = new_research('2026-06-01', structured_facts=True)
        result = search_sources(['검토 중인 별도 문서'], research, '서울 청년 월세', 'all')
        self.assertEqual(result['structured_facts'][0]['fact_id'], 'seoul-age')
        self.assertTrue(result['results'])
        self.assertEqual(research['facts'][0]['fact_id'], 'seoul-age')
        self.assertEqual(new_research()['facts'], [])
        own = search_sources(self.source.pages, new_research('2026-06-01', structured_facts=True), '서울 청년 월세', 'all')
        self.assertEqual(own.get('structured_facts', []), [])
        off = search_sources(['other'], new_research('2026-06-01'), '서울 청년 월세', 'all')
        self.assertNotIn('structured_facts', off)
        opinions = search_sources(['other'], new_research('2026-06-01', structured_facts=True), '서울 청년 월세', 'opinion')
        self.assertEqual(opinions.get('structured_facts', []), [])

    def test_citation_keeps_fact_snapshot_and_renders_version(self):
        from .agents.tools.sources import new_research, search_sources, check_sources
        from django.template.loader import render_to_string
        self.load()
        research = new_research('2026-06-01', structured_facts=True)
        search_sources(['other'], research, '서울 청년 월세', 'all')
        citation = {'source_id': self.source.doc_id, 'page': 1, 'quote': self.row['evidence'][0]['quote'], 'finding': '개별 나이 조건'}
        result = {'items': [{'id': 's1-i1', 'sources': [citation]}]}
        check_sources(result, research['opened'])
        self.assertEqual(citation['policy_facts'][0]['version_id'], 'seoul-rent-2026')
        self.source.delete()
        html = render_to_string('review_steps.html', {'all_steps': True, 'display_steps': [{'stage': 'final', 'phase': 'proposal', 'result': result}]})
        self.assertIn('정책 적용 버전', html)
        self.assertIn('2026-01-01', html)
        self.assertIn('추가 확인이 필요합니다', html)

    def test_excerpt_cannot_authorize_unseen_quote(self):
        from .agents.tools.sources import new_research, search_sources, check_sources, read_source
        self.source.pages = ['청년월세 ' + '가' * 2000 + '보이지 않는 원문 인용입니다.']
        self.source.save()
        research = new_research()
        search_sources(['other'], research, '청년월세', 'all')
        result = {'items': [{'sources': [{'source_id': self.source.doc_id, 'page': 1, 'quote': '보이지 않는 원문 인용입니다.'}]}]}
        with self.assertRaises(ValueError): check_sources(result, research['opened'])
        read_source(['other'], research, self.source.doc_id, 1)
        check_sources(result, research['opened'])


class RunIntegrationTests(TestCase):
    def test_new_runs_opt_in_but_existing_runs_keep_legacy_default(self):
        from .agents.runner import create_run
        with patch('server.agents.runner.transport.configuration', return_value=('key', 'model')):
            run = create_run('owner', 'title', ['text'])
        self.assertTrue(getattr(run, 'structured_facts', False))
        self.assertFalse(getattr(ReviewRun(pages=['old']), 'structured_facts', True))

    def test_advance_snapshots_only_returned_facts(self):
        from copy import deepcopy
        from .tests import ANALYSIS, TEXT, CITATION, ITEMS, response
        from .agents.runner import create_run, advance
        from .models import Source
        Source.objects.create(doc_id='ref', kind='policy', title='ref', issuer='기관', version='2026', source_url='https://example.go.kr', pages=['공개된 별도 참고 문서입니다.'])
        with patch('server.agents.runner.transport.configuration', return_value=('key', 'model')):
            run = create_run('owner', 'title', [TEXT])
            run.analysis, run.selected_role = deepcopy(ANALYSIS), 0
            issues = {'stage': 'issues', 'role': None, 'result': {'summary': 's', 'items': [{**ITEMS['issues'], 'citation': CITATION}], 'excluded': []}}
            run.steps = [issues]
            run.save()
            returned = {'fact_id': 'f', 'revision': 'rev', 'value': {'text': '검수한 내용'}}
            def generate(run, stage, data, schema, check, research=None, search_first=False, role=None):
                self.assertTrue(research['structured_facts'])
                self.assertEqual(research['facts'], [])
                research['facts'].append(returned)
                return {'summary': 's', 'items': [{**ITEMS[stage], 'citation': CITATION, 'target_ids': ['s1-i1']}]}
            with patch('server.agents.runner.generate', side_effect=generate):
                advance(run)  # The opening debate statement.
                run.steps = run.steps + [{'stage': 'close', 'role': None, 'result': {'summary': 's', 'items': []}}]
                advance(run)  # The final step.
        self.assertEqual(run.steps[1].get('policy_facts'), [returned])
        self.assertEqual(run.steps[3].get('policy_facts'), [returned])

    def test_evaluation_rejects_conflicting_arms_before_api(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with patch('server.agents.runner.transport.call') as model:
            with self.assertRaises(CommandError):
                call_command('evaluate', 'doc', no_sources=True, structured_facts=True)
        model.assert_not_called()


class OfflineConditionTests(SimpleTestCase):
    def test_reviewable_cases_run_without_model(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        from pathlib import Path
        from django.conf import settings
        from django.core.management import get_commands
        self.assertIn('evaluate_conditions', get_commands())
        out = StringIO()
        with patch('server.integrations.transport.call') as model:
            call_command('evaluate_conditions', cases=str(settings.BASE_DIR / 'server' / 'fixtures' / 'ontology_conditions.jsonl'), stdout=out)
        self.assertIn('30/30', out.getvalue())
        self.assertIn('합성', out.getvalue())
        model.assert_not_called()

    def test_wrong_expected_result_fails(self):
        import json, tempfile
        from pathlib import Path
        from django.core.management import call_command, get_commands
        from django.core.management.base import CommandError
        from io import StringIO
        self.assertIn('evaluate_conditions', get_commands())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'cases.jsonl'
            p.write_text(json.dumps({'case_id': 'bad', 'kind': 'synthetic', 'condition': {'compare': {'field': 'age', 'operator': 'gte', 'value': 19, 'unit': 'years', 'basis': '2026-01-01'}}, 'context': {}, 'expected': 'met'}))
            with self.assertRaises(CommandError): call_command('evaluate_conditions', cases=str(p), stdout=StringIO())


class PairedEvaluationTests(TestCase):
    def test_reference_requires_same_document_before_model_call(self):
        import json, tempfile
        from pathlib import Path
        from io import StringIO
        from django.core.management import call_command, get_commands
        from django.core.management.base import CommandError
        from server.management.commands.evaluate import Command
        parser = Command().create_parser('manage.py', 'evaluate')
        self.assertTrue(any(a.dest == 'reference_run' for a in parser._actions))
        with tempfile.TemporaryDirectory() as d, self.settings(BASE_DIR=Path(d)):
            base=Path(d)/'data'
            (base/'reviewed').mkdir(parents=True)
            (base/'processed'/'doc').mkdir(parents=True)
            (base/'reviewed'/'documents.jsonl').write_text(json.dumps({'doc_id':'doc','title':'t','published_on':'2026-01-01','gate':{'technical':'pass','rights':'pass'},'external_send_ok':True}))
            (base/'processed'/'doc'/'pages.json').write_text(json.dumps([{'text':'현재 문서'}]))
            ref=Path(d)/'ref.json'
            ref.write_text(json.dumps({'doc_id':'doc','as_of':'2026-01-01','document_hash':'wrong'}))
            with patch('server.integrations.transport.call') as model, self.assertRaises(CommandError):
                call_command('evaluate','doc',reference_run=str(ref),stdout=StringIO())
            model.assert_not_called()
            self.assertEqual(ReviewRun.objects.count(),0)


class EvaluationGateTests(TestCase):
    def test_unapproved_document_is_rejected_before_api(self):
        import tempfile, json
        from pathlib import Path
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with tempfile.TemporaryDirectory() as d, self.settings(BASE_DIR=Path(d)):
            folder=Path(d)/'data'/'reviewed'
            folder.mkdir(parents=True)
            (folder/'documents.jsonl').write_text(json.dumps({'doc_id':'doc','title':'private','published_on':'2026-01-01',
                'gate':{'technical':'pass','rights':'pass'},'external_send_ok':False}))
            with patch('server.integrations.transport.call') as model, self.assertRaises(CommandError):
                call_command('evaluate','doc')
            model.assert_not_called()
            self.assertEqual(ReviewRun.objects.count(),0)
