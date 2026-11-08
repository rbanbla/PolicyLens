"""Import reviewed facts without altering or implicitly approving source documents."""
import json
import re
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from server.models import Policy, PolicyVersion, PolicyFact, FactEvidence, Source
from server.agents.tools.documents import check_quote
from server.agents.tools.policy_facts import source_digest, validate_fact_value


class Command(BaseCommand):
    help = '원문 게이트·해시·인용을 검증하고 정책 사실 JSONL을 원자적으로 적재한다.'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, manifest, dry_run, **options):
        try:
            records = [json.loads(line) for line in Path(manifest).read_text().splitlines() if line.strip()]
            if not records:
                self.stdout.write('0건: 기존 사실을 변경하지 않았습니다.')
                return
            registry = settings.BASE_DIR / 'data' / 'reviewed' / 'documents.jsonl'
            gates = {d['doc_id']: d for line in registry.read_text().splitlines() if line.strip() for d in [json.loads(line)]}
            with transaction.atomic():
                seen, policies, versions = set(), {}, {}
                for record in records:
                    self.import_record(record, gates, seen, policies, versions)
                for fact in PolicyFact.objects.filter(fact_id__in=seen, predicate='interaction'):
                    target = fact.value['target_version_id']
                    if target == fact.version_id or not PolicyVersion.objects.filter(pk=target).exists():
                        raise ValueError('관계 대상 버전이 없거나 자기 자신입니다.')
                if dry_run:
                    transaction.set_rollback(True)
        except (OSError, ValueError, TypeError, KeyError, ValidationError) as exc:
            raise CommandError(f'정책 사실 적재 실패: {exc}') from exc
        self.stdout.write(f'{len(records)}건 {"검증 (저장 안 함)" if dry_run else "적재"}')

    def import_record(self, record, gates, seen, policies, versions):
        if not isinstance(record, dict) or set(record) != {'policy', 'version', 'fact', 'evidence'}:
            raise ValueError('policy/version/fact/evidence 필드가 필요합니다.')
        if any(not isinstance(record[k], dict) for k in ('policy', 'version', 'fact')):
            raise ValueError('정책·버전·사실은 객체여야 합니다.')
        policy, version, fact = (record[key].copy() for key in ('policy', 'version', 'fact'))
        if set(policy) != {'policy_id', 'title', 'region_code', 'issuer'}:
            raise ValueError('정책 필드를 확인하세요.')
        version.setdefault('supersedes', None)
        if set(version) != {'version_id', 'label', 'effective_from', 'effective_until', 'application_from', 'application_until', 'supersedes'}:
            raise ValueError('버전 필드를 확인하세요.')
        if set(fact) != {'fact_id', 'predicate', 'value', 'status', 'reviewed_by', 'reviewed_at', 'extracted_by'}:
            raise ValueError('사실 필드를 확인하세요.')
        for data, key in ((policy, 'policy_id'), (version, 'version_id'), (fact, 'fact_id')):
            if not isinstance(data[key], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,96}', data[key]):
                raise ValueError('식별자는 영문·숫자·밑줄·하이픈 1~96자여야 합니다.')
        if fact['fact_id'] in seen:
            raise ValueError('한 manifest에 중복 fact_id가 있습니다.')
        seen.add(fact['fact_id'])
        for data, key, definitions in ((policy, 'policy_id', policies), (version, 'version_id', versions)):
            if data[key] in definitions and definitions[data[key]] != data:
                raise ValueError('한 manifest에서 정책/버전 정의가 충돌합니다.')
            definitions[data[key]] = data
        validate_fact_value(fact['predicate'], fact['value'])
        if fact['status'] == 'verified' and (not isinstance(fact['reviewed_by'], str) or not fact['reviewed_by'].strip() or not fact['reviewed_at']):
            raise ValueError('검수 완료 사실에는 검수자·검수 시각이 필요합니다.')
        policy_obj = Policy(**policy)
        policy_obj.full_clean(validate_unique=False)
        existing = Policy.objects.filter(pk=policy_obj.pk).first()
        if existing and any(getattr(existing, k) != policy[k] for k in policy):
            raise ValueError('기존 정책 정의 변경은 새 식별자 또는 별도 재검수가 필요합니다.')
        policy_obj.save()
        version_fields = {k: v for k, v in version.items() if k != 'supersedes'}
        predecessor = PolicyVersion.objects.filter(pk=version['supersedes']).first() if version['supersedes'] else None
        if version['supersedes'] and (predecessor is None or predecessor.policy_id != policy_obj.pk or predecessor.pk == version['version_id']):
            raise ValueError('대체할 버전은 같은 정책의 기존 버전이어야 합니다.')
        version_obj = PolicyVersion(policy=policy_obj, supersedes=predecessor, **version_fields)
        version_obj.full_clean(validate_unique=False)
        for start, end in (('effective_from', 'effective_until'), ('application_from', 'application_until')):
            a, b = getattr(version_obj, start), getattr(version_obj, end)
            if b and (not a or b < a):
                raise ValueError('기간의 시작과 끝을 확인하세요.')
        existing = PolicyVersion.objects.filter(pk=version_obj.pk).first()
        if existing and (existing.policy_id != policy_obj.pk or any(getattr(existing, k) != getattr(version_obj, k) for k in version)):
            raise ValueError('기존 버전 정의를 덮어쓸 수 없습니다. 새 버전 ID를 사용하세요.')
        version_obj.save()
        fact_obj = PolicyFact(version=version_obj, **fact)
        fact_obj.full_clean(validate_unique=False)
        if fact_obj.reviewed_at and fact_obj.reviewed_at.utcoffset() is None:
            raise ValueError('검수 시각에는 시간대가 필요합니다.')
        existing = PolicyFact.objects.filter(pk=fact_obj.pk).first()
        if existing and existing.version_id != version_obj.pk:
            raise ValueError('사실의 소속 버전을 변경할 수 없습니다.')
        fact_obj.save()
        evidence = record['evidence']
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 5:
            raise ValueError('사실마다 1~5개 원문 근거가 필요합니다.')
        fact_obj.evidence.all().delete()
        for ev in evidence:
            if not isinstance(ev, dict) or set(ev) != {'source_id', 'source_hash', 'page', 'quote'}:
                raise ValueError('근거 필드를 확인하세요.')
            source = Source.objects.filter(doc_id=ev['source_id'], kind='policy').first()
            gate = gates.get(ev['source_id'], {})
            if source is None or any(gate.get('gate', {}).get(k) != 'pass' for k in ('technical', 'rights')) or gate.get('external_send_ok') is not True:
                raise ValueError('자료가 없거나 공개 자료 게이트를 통과하지 않았습니다.')
            if ev['source_hash'] != source_digest(source):
                raise ValueError('원문 스냅샷 해시가 일치하지 않습니다.')
            if type(ev['page']) is not int or not isinstance(ev['quote'], str) or len(ev['quote']) > 2000:
                raise ValueError('페이지·인용 자료형이 잘못되었습니다.')
            check_quote(source.pages, ev)
            FactEvidence.objects.create(fact=fact_obj, source=source, source_hash=ev['source_hash'], page=ev['page'], quote=ev['quote'])
