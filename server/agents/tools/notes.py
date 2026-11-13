import json
from ..validation import check_text
from .documents import align_citations, check_quote, clean
from .sources import tool

TOOLS = [
    tool('note_issue', '토론 중 원래 쟁점에 없던 조항이 새로 부딪히면 쟁점 메모에 남긴다. 메모한 쟁점은 토론하지 않고 기록만 한다.',
         {'issue': {'type': 'string'}, 'reason': {'type': 'string'}, 'page': {'type': 'integer'}, 'quote': {'type': 'string'}}),
]


def note_issue(pages, notes, call):
    # Kept in memory until the step is saved, so a failed or retried turn leaves no note behind.
    try:
        arguments = json.loads(call['arguments'])
        if call['name'] != 'note_issue':
            raise KeyError
        note = {'issue': str(arguments['issue']).strip(), 'reason': str(arguments['reason']).strip(),
                'citation': {'page': int(arguments['page']), 'quote': str(arguments['quote'])}}
    except (KeyError, TypeError, ValueError):
        return json.dumps({'error': '도구 인자가 잘못되었습니다.'}, ensure_ascii=False)
    try:
        if not note['issue'] or not note['reason']:
            raise ValueError('issue와 reason을 채워 주세요.')
        check_text(pages, {'summary': '', 'items': [{'issue': note['issue'], 'reason': note['reason']}]})
        align_citations(pages, [note['citation']])
        check_quote(pages, note['citation'])
    except ValueError as exc:
        return json.dumps({'error': str(exc)}, ensure_ascii=False)
    if any(clean(saved['citation']['quote']) == clean(note['citation']['quote']) for saved in notes):
        return json.dumps({'error': '이미 메모한 조항입니다.'}, ensure_ascii=False)
    notes.append(note)
    return json.dumps({'saved': True}, ensure_ascii=False)
