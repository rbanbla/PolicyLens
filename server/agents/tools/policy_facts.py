"""Reviewed policy facts; conditions are data, never executable expressions."""
import math
from datetime import date

FIELD_TYPES = {'age': 'number', 'income_ratio': 'number', 'household_size': 'number',
               'residence_code': 'string', 'enrollment': 'boolean', 'employment': 'string'}
UNITS = {'age': 'years', 'income_ratio': 'percent_median', 'household_size': 'persons',
         'residence_code': 'region_code', 'enrollment': 'boolean', 'employment': 'status'}


def valid_value(field, value):
    kind = FIELD_TYPES[field]
    if kind == 'number':
        return type(value) in (int, float) and 0 <= value <= 1_000_000_000 and math.isfinite(value)
    if kind == 'boolean':
        return type(value) is bool
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def validate_condition(condition, depth=0):
    if depth > 10 or not isinstance(condition, dict) or len(condition) != 1:
        raise ValueError('조건 구조 또는 중첩 깊이가 잘못되었습니다.')
    key, value = next(iter(condition.items()))
    if key in ('all', 'any'):
        if not isinstance(value, list) or not 1 <= len(value) <= 20:
            raise ValueError('조건 목록은 1~20개여야 합니다.')
        for child in value:
            validate_condition(child, depth + 1)
    elif key == 'not':
        validate_condition(value, depth + 1)
    elif key == 'compare':
        if not isinstance(value, dict) or set(value) != {'field', 'operator', 'value', 'unit', 'basis'}:
            raise ValueError('비교 조건에는 필드·연산자·값·단위·기준이 필요합니다.')
        field, op = value['field'], value['operator']
        if not isinstance(field, str) or field not in FIELD_TYPES or op not in ('eq', 'lt', 'lte', 'gt', 'gte', 'in'):
            raise ValueError('허용되지 않은 필드 또는 연산자입니다.')
        if op in ('lt', 'lte', 'gt', 'gte') and FIELD_TYPES[field] != 'number':
            raise ValueError('순서 비교는 수치 조건에만 허용됩니다.')
        values = value['value'] if op == 'in' else [value['value']]
        if not isinstance(values, list) or not 1 <= len(values) <= 100 or not all(valid_value(field, v) for v in values):
            raise ValueError('조건 값의 자료형이 잘못되었습니다.')
        if value['unit'] != UNITS[field]:
            raise ValueError('조건의 단위가 잘못되었습니다.')
        basis = value['basis']
        if field == 'income_ratio':
            if (not isinstance(basis, dict) or set(basis) != {'date', 'subject', 'household_scope'}
                    or basis['subject'] not in ('individual', 'youth_household', 'original_household')
                    or not isinstance(basis['household_scope'], str) or not 1 <= len(basis['household_scope'].strip()) <= 200):
                raise ValueError('소득 조건에는 기준일·소득 주체·가구 범위가 필요합니다.')
            basis = basis['date']
        if not isinstance(basis, str):
            raise ValueError('조건 기준일은 ISO 날짜여야 합니다.')
        try:
            parsed = date.fromisoformat(basis)
            if parsed.isoformat() != basis:
                raise ValueError('ISO 날짜 형식이 아닙니다.')
        except ValueError as exc:
            raise ValueError('조건 기준일은 YYYY-MM-DD여야 합니다.') from exc
    else:
        raise ValueError('허용되지 않은 조건입니다.')


def evaluate_condition(condition, context):
    """Evaluate one condition, not whole-program eligibility or benefit approval."""
    validate_condition(condition)
    if not isinstance(context, dict):
        raise ValueError('조건 입력은 객체여야 합니다.')

    def evaluate(node):
        key, rule = next(iter(node.items()))
        if key == 'compare':
            field = rule['field']
            given = context.get(field)
            if not isinstance(given, dict) or not valid_value(field, given.get('value')):
                return 'unknown', {field}, {'missing_or_invalid_value'}
            if any(given.get(k) != rule[k] for k in ('unit', 'basis')):
                return 'unknown', {field}, {'basis_or_unit_mismatch'}
            actual, expected, op = given['value'], rule['value'], rule['operator']
            if op == 'in': passed = actual in expected
            elif op == 'eq': passed = actual == expected
            elif op == 'lt': passed = actual < expected
            elif op == 'lte': passed = actual <= expected
            elif op == 'gt': passed = actual > expected
            else: passed = actual >= expected
            return 'met' if passed else 'not_met', set(), set()
        children = [evaluate(rule)] if key == 'not' else [evaluate(c) for c in rule]
        states = [c[0] for c in children]
        if key == 'not':
            status = {'met': 'not_met', 'not_met': 'met', 'unknown': 'unknown'}[states[0]]
        elif key == 'all':
            status = 'not_met' if 'not_met' in states else 'met' if all(s == 'met' for s in states) else 'unknown'
        else:
            status = 'met' if 'met' in states else 'not_met' if all(s == 'not_met' for s in states) else 'unknown'
        return status, set().union(*(c[1] for c in children)), set().union(*(c[2] for c in children))

    status, missing, reasons = evaluate(condition)
    return {'status': status, 'missing_fields': sorted(missing), 'reason_codes': sorted(reasons)}


def digest(value):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False).encode()).hexdigest()


def source_digest(source):
    # Includes metadata: changing an issuer/date must invalidate an old verification too.
    return digest({key: getattr(source, key) for key in ('doc_id', 'kind', 'title', 'issuer', 'version', 'source_url', 'published_on', 'pages')})


def validate_fact_value(predicate, value):
    if predicate in ('eligibility', 'exclusion'):
        validate_condition(value)
    elif predicate in ('benefit', 'application'):
        if not isinstance(value, dict) or set(value) != {'text'} or not isinstance(value['text'], str) or not 1 <= len(value['text'].strip()) <= 2000:
            raise ValueError('혜택·신청 사실에는 2000자 이내의 text가 필요합니다.')
    elif predicate == 'interaction':
        if not isinstance(value, dict) or set(value) != {'target_version_id', 'relation', 'condition'}:
            raise ValueError('사업 관계에는 대상 버전·관계·조건이 필요합니다.')
        if not isinstance(value['target_version_id'], str) or not value['target_version_id'] or value['relation'] not in ('excludes', 'requires'):
            raise ValueError('지원하지 않는 사업 관계입니다.')
        validate_condition(value['condition'])
    else:
        raise ValueError('지원하지 않는 사실 유형입니다.')


def lookup_facts(query, *, knowledge_as_of=None, effective_on=None):
    import json
    from datetime import date
    from django.db.models import Q
    from ...models import PolicyFact, PolicyVersion
    from .documents import check_quote, clean

    knowledge = date.fromisoformat(str(knowledge_as_of or date.today()))
    effective = date.fromisoformat(str(effective_on or knowledge))
    terms = [clean(t).casefold() for t in query.split() if len(clean(t)) > 1]
    if not terms:
        return []
    facts = (PolicyFact.objects.filter(status='verified', version__effective_from__lte=effective)
             .filter(Q(version__effective_until__isnull=True) | Q(version__effective_until__gte=effective))
             .select_related('version__policy').prefetch_related('evidence__source').order_by('fact_id'))
    results, valid_versions = [], set()
    for fact in facts:
        if not fact.reviewed_by or fact.reviewed_at is None:
            continue
        try:
            validate_fact_value(fact.predicate, fact.value)
        except (ValueError, TypeError):
            continue
        evidence = list(fact.evidence.all())
        if not evidence:
            continue
        valid = True
        for ev in evidence:
            source = ev.source
            if source is None or source.kind != 'policy' or source.published_on is None or source.published_on > knowledge or source_digest(source) != ev.source_hash:
                valid = False
                break
            try:
                check_quote(source.pages, {'page': ev.page, 'quote': ev.quote})
            except ValueError:
                valid = False
                break
        if not valid:
            continue
        policy, version = fact.version.policy, fact.version
        valid_versions.add(version.pk)
        searchable = clean(' '.join([policy.title, policy.issuer, policy.region_code, version.label,
                                     json.dumps(fact.value, ensure_ascii=False)] + [e.quote for e in evidence])).casefold()
        # Require every query term: an explicit different region must not silently match by "청년" alone.
        if not all(term in searchable for term in terms):
            continue
        snapshot = {'fact_id': fact.pk, 'policy_id': policy.pk, 'policy_title': policy.title, 'region_code': policy.region_code,
                    'version_id': version.pk, 'version': version.label, 'supersedes': version.supersedes_id,
                    'effective_from': str(version.effective_from), 'effective_until': str(version.effective_until) if version.effective_until else None,
                    'application_from': str(version.application_from) if version.application_from else None,
                    'application_until': str(version.application_until) if version.application_until else None,
                    'predicate': fact.predicate, 'value': fact.value, 'verification': 'verified',
                    'reviewed_by': fact.reviewed_by, 'reviewed_at': fact.reviewed_at.isoformat(),
                    'evidence': [{'source_id': e.source.doc_id, 'source_hash': e.source_hash, 'page': e.page, 'quote': e.quote,
                                  'title': e.source.title, 'source_url': e.source.source_url} for e in evidence]}
        snapshot['revision'] = digest(snapshot)
        results.append(snapshot)
    predecessors = dict(PolicyVersion.objects.values_list('pk', 'supersedes_id'))
    superseded = set()
    for version_id in valid_versions:
        visited = set()
        previous = predecessors.get(version_id)
        while previous and previous not in visited:
            superseded.add(previous)
            visited.add(previous)
            previous = predecessors.get(previous)
    return [fact for fact in results if fact['version_id'] not in superseded]
