import json
import re
import time
from datetime import date
from django.utils.translation import gettext as _
from ...models import Source
from .documents import check_quote, clean
from .policy_facts import lookup_facts, digest, source_digest

MAX_RESULTS = 5
MAX_PAGES_PER_SOURCE = 2
BEFORE, AFTER = 300, 900


def tool(name, description, properties):
    return {'type': 'function', 'name': name, 'description': description, 'strict': True,
            'parameters': {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}}


TOOLS = [
    tool('search_sources', '서버에 저장된 정책 문서와 공개 의견을 키워드로 찾는다. 사업명과 확인할 조건을 짧게 넣는다.',
         {'query': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['all', 'policy', 'opinion']}}),
    tool('read_source', '검색으로 찾은 서버 자료의 한 쪽 전체를 읽는다.',
         {'source_id': {'type': 'string'}, 'page': {'type': 'integer'}}),
]


def new_research(as_of=None, *, structured_facts=False):
    return {'opened': {}, 'log': [], 'as_of': as_of, 'structured_facts': structured_facts, 'facts': []}


def available(upload, as_of):
    # shortcut: scans every source in memory, fine for hundreds of pages; move to full-text search when the corpus outgrows that.
    # The reviewed document must not come back as its own outside evidence.
    own = clean(''.join(upload))
    sources = Source.objects.all()
    if as_of:  # Evaluation must not read what happened later, or the opinions it is scored against.
        sources = sources.filter(published_on__lte=as_of, kind='policy')
    return [source for source in sources if clean(''.join(source.pages)) != own]


def record(research, source, page, text=None):
    visible = source.pages[page - 1] if text is None else text
    key = (source.doc_id, page)
    previous = research['opened'].get(key, {})
    segments = previous.get('segments', [])
    if visible not in segments:
        segments = segments + [visible]
    research['opened'][key] = {
        **previous, 'source_id': source.doc_id, 'page': page, 'kind': source.get_kind_display(), 'title': source.title,
        'issuer': source.issuer, 'version': source.version, 'source_url': source.source_url,
        'segments': segments, 'text': '\n…\n'.join(segments)}

def entry(source, page, **content):
    return {'source_id': source.doc_id, 'kind': source.kind, 'title': source.title, 'issuer': source.issuer,
            'version': source.version, 'page': page, **content}


def pattern(token):
    # PDF text often splits Korean words with spaces, so a token matches across whitespace.
    return re.compile(r'\s*'.join(map(re.escape, token)), re.IGNORECASE)


def weigh(terms, text):
    weight, start = 0, None
    for whole, part in terms:
        match = whole.search(text)
        if match:
            weight += 1
        elif part and (match := part.search(text)):  # 국토교통부 and 국토부, 중복수혜 and 중복 선정: the same word in other clothes.
            weight += .5
        if match and start is None:
            start = match.start()
    return weight, start


def search_sources(upload, research, query, kind):
    terms = [(pattern(token), pattern(token[:len(token) // 2]) if len(token) >= 4 else None)
             for token in query.split() if len(token) > 1]
    today = date.fromisoformat(str(research['as_of'] or date.today()))
    hits = []
    sources = available(upload, research['as_of'])
    for source in sources:
        if kind != 'all' and source.kind != kind:
            continue
        heading = 2 * weigh(terms, f'{source.title} {source.issuer}')[0]
        recent = 1 if source.published_on and 0 <= (today - source.published_on).days <= 365 else 0  # An old round must not bury the latest notice.
        for page, text in enumerate(source.pages, 1):
            weight, start = weigh(terms, text)
            if start is not None:
                hits.append((weight + heading + recent, source, page, text, start))
    hits.sort(key=lambda hit: -hit[0])
    results, used, returned_facts = [], {}, []
    by_id = {source.doc_id: source for source in sources}
    if research.get('structured_facts') and kind != 'opinion':
        for fact in lookup_facts(query, knowledge_as_of=research['as_of'], effective_on=today):
            evidence = fact['evidence']
            if any(e['source_id'] not in by_id or source_digest(by_id[e['source_id']]) != e['source_hash'] for e in evidence):
                continue
            pages = {(r['source_id'], r['page']) for r in results}
            new_pages = {(e['source_id'], e['page']) for e in evidence} - pages
            if len(pages | new_pages) > MAX_RESULTS or any(
                    used.get(source_id, 0) + sum(s == source_id for s, _ in new_pages) > MAX_PAGES_PER_SOURCE
                    for source_id, _ in new_pages):
                continue
            for ev in evidence:
                source, page = by_id[ev['source_id']], ev['page']
                record(research, source, page, ev['quote'])
                existing = next((r for r in results if r['source_id'] == source.doc_id and r['page'] == page), None)
                if existing is None:
                    results.append(entry(source, page, excerpt=ev['quote']))
                    used[source.doc_id] = used.get(source.doc_id, 0) + 1
                elif ev['quote'] not in existing['excerpt']:
                    existing['excerpt'] += '\n…\n' + ev['quote']
                opened = research['opened'][(source.doc_id, page)]
                opened.setdefault('facts', []).append(fact)
            returned_facts.append(fact)
            if len(returned_facts) == MAX_RESULTS:
                break
    pages = {(r['source_id'], r['page']) for r in results}
    for _, source, page, text, start in hits:
        if (source.doc_id, page) in pages:
            continue
        if len(results) < MAX_RESULTS and used.get(source.doc_id, 0) < MAX_PAGES_PER_SOURCE:
            used[source.doc_id] = used.get(source.doc_id, 0) + 1
            excerpt = text[max(0, start - BEFORE):start + AFTER]
            record(research, source, page, excerpt)
            results.append(entry(source, page, excerpt=excerpt))
            pages.add((source.doc_id, page))
    result = {'results': results} if results else {'results': [], 'note': '찾지 못했습니다.'}
    if research.get('structured_facts'):
        result['structured_facts'] = returned_facts
        for fact in returned_facts:
            if not any(f['revision'] == fact['revision'] for f in research['facts']):
                research['facts'].append(fact)
        # No shared cache: revision identifies exactly the reviewed facts returned in this tool call.
        result['evidence_revision'] = digest(returned_facts)
    return result


def read_source(upload, research, source_id, page):
    source = next((source for source in available(upload, research['as_of']) if source.doc_id == source_id), None)
    if source is None or not 1 <= page <= len(source.pages):
        return {'error': '해당 자료나 쪽이 없습니다.'}
    record(research, source, page)
    return entry(source, page, text=source.pages[page - 1])


def run_tool(upload, research, call):
    # Arguments come from the model, so bad ones go back to it as a result instead of failing the step.
    started = time.monotonic()
    try:
        arguments = json.loads(call['arguments'])
        if call['name'] == 'search_sources':
            result = search_sources(upload, research, str(arguments['query']), arguments['kind'])
            found = len(result['results'])
        elif call['name'] == 'read_source':
            result = read_source(upload, research, str(arguments['source_id']), int(arguments['page']))
            found = 0 if 'error' in result else 1
        else:
            result, found = {'error': '없는 도구입니다.'}, 0
    except (KeyError, TypeError, ValueError):
        result, arguments, found = {'error': '도구 인자가 잘못되었습니다.'}, {}, 0
    research['log'].append({'tool': call['name'], 'input': arguments.get('query') or arguments.get('source_id', ''), 'found': found, 'elapsed_ms': round((time.monotonic() - started) * 1000, 2)})
    return json.dumps(result, ensure_ascii=False)


def check_sources(result, opened):
    for item in result['items']:
        for source in item.get('sources', []):
            found = opened.get((source['source_id'], source['page']))
            if found is None:
                raise ValueError(_('도구로 읽지 않은 서버 자료는 인용할 수 없습니다: %(id)s %(page)s쪽') % {'id': source['source_id'], 'page': source['page']})
            try:
                segments = found.get('segments', [found['text']])
                if not any(clean(source['quote']) in clean(segment) for segment in segments):
                    raise ValueError(_('도구에서 반환하지 않은 구간입니다.'))
                check_quote([found['text']], {'page': 1, 'quote': source['quote']})
            except ValueError as exc:
                raise ValueError(_('서버 자료 %(id)s %(page)s쪽 인용 오류. %(reason)s') % {'id': source['source_id'], 'page': source['page'], 'reason': exc}) from exc
            # A snapshot, so the run still shows its evidence after the corpus changes.
            source.update({key: found[key] for key in ('kind', 'title', 'issuer', 'version', 'source_url')})

            related = [fact for fact in found.get('facts', []) if any(
                ev['source_id'] == source['source_id'] and ev['page'] == source['page'] and
                (clean(ev['quote']) in clean(source['quote']) or clean(source['quote']) in clean(ev['quote']))
                for ev in fact['evidence'])]
            if related:
                source['policy_facts'] = list({f['revision']: f for f in related}.values())
