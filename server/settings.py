import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit
from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values
BASE_DIR = Path(__file__).resolve().parent.parent
env = {**dotenv_values(BASE_DIR / '.env', interpolate=False), **os.environ}  # The platform's variables win over .env.
DEBUG = env.get('DJANGO_DEBUG') == '1'  # Off unless asked: the debug page shows local variables, the model API key among them.
SECRET_KEY = env.get('DJANGO_SECRET_KEY') or ('local-development-v2' if DEBUG else '')
if not SECRET_KEY:
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY, or DJANGO_DEBUG=1 for local development.')
ALLOWED_HOSTS = (env.get('DJANGO_ALLOWED_HOSTS') or 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.staticfiles', 'server']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'server.language.Language', 'django.middleware.csrf.CsrfViewMiddleware']
ROOT_URLCONF = 'server.urls'
if env.get('DB_DATABASE_URL'):  # VibeHub's PostgreSQL, connected with the env prefix DB. SQLite would lock every write while a step waits on the model.
    url = urlsplit(env['DB_DATABASE_URL'])
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': url.path.lstrip('/'), 'HOST': url.hostname, 'PORT': url.port or '',
                             'USER': unquote(url.username or ''), 'PASSWORD': unquote(url.password or ''), 'OPTIONS': dict(parse_qsl(url.query))}}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True}]
LANGUAGE_CODE = 'ko'
LOCALE_PATHS = [BASE_DIR / 'locale']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# The platform's proxy ends HTTPS; without this header Django sees http and every POST fails the CSRF origin check.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = [f'https://{host}' for host in ALLOWED_HOSTS]  # Still passes if the proxy leaves that header out.
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
