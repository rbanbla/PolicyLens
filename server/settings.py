from pathlib import Path
from dotenv import dotenv_values
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = dotenv_values(BASE_DIR / '.env').get('DJANGO_SECRET_KEY') or 'local-development-v2'
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.staticfiles', 'server']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'server.language.Language', 'django.middleware.csrf.CsrfViewMiddleware']
ROOT_URLCONF = 'server.urls'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True}]
LANGUAGE_CODE = 'ko'
LOCALE_PATHS = [BASE_DIR / 'locale']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

STATIC_URL = '/static/'
