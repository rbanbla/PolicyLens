"""Provider-configurable transport, normalized to the Responses output envelope."""
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from django.conf import settings
from django.utils.translation import gettext as _
from dotenv import dotenv_values


def setting(name, default=''):
    # Read only named settings; never execute .env as shell code or expose secrets.
    local = dotenv_values(settings.BASE_DIR / '.env', interpolate=False)
    return os.environ.get(name) or local.get(name) or default


def configuration():
    return setting('OPENAI_API_KEY').strip(), setting('POLICYLENS_SUMMARY_MODEL', 'gpt-4.1').strip()


def provider():
    base = setting('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    mode = setting('POLICYLENS_API_MODE', 'responses')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid provider URL')
    if mode not in ('responses', 'chat_completions'):
        raise ValueError('Invalid API mode')
    return base, mode


def identity():
    return '|'.join(provider())


def chat_messages(payload):
    messages = [{'role': 'system', 'content': payload['instructions']}]
    items = payload['input'] if isinstance(payload['input'], list) else [{'role': 'user', 'content': payload['input']}]
    for item in items:
        if item.get('type') == 'function_call':
            call = {'id': item['call_id'], 'type': 'function', 'function': {'name': item['name'], 'arguments': item['arguments']}}
            if messages[-1].get('tool_calls'):  # Parallel calls must sit in one assistant turn, before their results.
                messages[-1]['tool_calls'].append(call)
            else:
                messages.append({'role': 'assistant', 'content': None, 'tool_calls': [call]})
        elif item.get('type') == 'function_call_output':
            messages.append({'role': 'tool', 'tool_call_id': item['call_id'], 'content': item['output']})
        else:
            messages.append(item)
    return messages


def call(payload, key):
    base, mode = provider()
    if mode == 'chat_completions':
        body = {'model': payload['model'], 'messages': chat_messages(payload),
                'max_completion_tokens': payload['max_output_tokens'], 'stream': False}
        if 'tools' in payload:
            body['tools'] = [{'type': 'function', 'function': {k: v for k, v in tool.items() if k != 'type'}} for tool in payload['tools']]
        if 'tool_choice' in payload:
            body['tool_choice'] = payload['tool_choice']
        if 'text' in payload:
            fmt = payload['text']['format']
            body['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': fmt['name'], 'strict': fmt['strict'], 'schema': fmt['schema']}}
        endpoint = '/chat/completions'
    else:
        body, endpoint = payload, '/responses'
    request = Request(base + endpoint, data=json.dumps(body, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=90) as response:
        data = json.load(response)
    if mode == 'chat_completions':
        if not data.get('choices'):
            raise ValueError(_('모델 응답이 비어 있습니다.'))
        choice = data['choices'][0]
        text = choice['message'].get('content')
        if not isinstance(text, str): text = ''
        calls = [{'type': 'function_call', 'call_id': tool['id'], 'name': tool['function']['name'], 'arguments': tool['function']['arguments']}
                 for tool in choice['message'].get('tool_calls') or []]
        return {'status': 'completed' if choice.get('finish_reason') in ('stop', 'tool_calls') else 'incomplete',
                'output': calls + [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
                'usage': data.get('usage', {})}
    return data
