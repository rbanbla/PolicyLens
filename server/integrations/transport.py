"""Provider-configurable transport, normalized to the Responses output envelope."""
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from django.conf import settings
from dotenv import dotenv_values


class ModelError(Exception):
    """A model call or its output could not be used. The message is shown to users."""


def setting(name, default=''):
    # Read only named settings; never execute .env as shell code or expose secrets.
    local = dotenv_values(settings.BASE_DIR / '.env', interpolate=False)
    return os.environ.get(name) or local.get(name) or default


def configuration():
    return setting('OPENAI_API_KEY').strip(), setting('POLICYLENS_SUMMARY_MODEL', 'gpt-4.1').strip()


def debate_model(default):
    return setting('POLICYLENS_DEBATE_MODEL', default)


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


def call(payload, key):
    base, mode = provider()
    if mode == 'chat_completions':
        fmt = payload['text']['format']
        body = {'model': payload['model'], 'messages': [
            {'role': 'system', 'content': payload['instructions']},
            {'role': 'user', 'content': payload['input']}],
            'max_completion_tokens': payload['max_output_tokens'], 'stream': False,
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': fmt['name'], 'strict': fmt['strict'], 'schema': fmt['schema']}}}
        endpoint = '/chat/completions'
    else:
        body, endpoint = payload, '/responses'
    request = Request(base + endpoint, data=json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=60) as response:
        data = json.load(response)
    if mode == 'chat_completions':
        choice = data['choices'][0]
        text = choice['message'].get('content')
        if not isinstance(text, str): text = ''
        return {'status': 'completed' if choice.get('finish_reason') == 'stop' else 'incomplete',
                'id': data.get('id', ''), 'usage': data.get('usage', {}),
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
    return data
