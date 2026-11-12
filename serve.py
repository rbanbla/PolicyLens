"""Serve PolicyLens to visitors through ngrok on macOS or Windows. Ctrl+C stops it."""
import os

os.environ['DJANGO_DEBUG'] = '0'  # .env may turn debug on for development, but its error page shows the model API key.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')

import django
from django.core.management import call_command
from waitress import serve

django.setup()
# A copied folder or a pulled update may bring new migrations, CSS or JS.
call_command('migrate', interactive=False, verbosity=0)
call_command('collectstatic', interactive=False, verbosity=0)
from server.wsgi import application

print('PolicyLens: http://127.0.0.1:8001  (Ctrl+C로 종료)', flush=True)
# ngrok connects from this machine and says the visitor came over HTTPS; only this machine is trusted to say so.
serve(application, host='127.0.0.1', port=8001, trusted_proxy='127.0.0.1', trusted_proxy_headers='x-forwarded-proto')
