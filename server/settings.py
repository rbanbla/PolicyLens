import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
ON_RENDER = os.environ.get("RENDER") == "true"
RENDER_ORIGIN = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
PUBLIC_ORIGIN = (os.environ.get("POLICYLENS_PUBLIC_ORIGIN") or RENDER_ORIGIN).rstrip("/")
CSRF_TRUSTED_ORIGINS = []
for origin in dict.fromkeys(filter(None, [RENDER_ORIGIN, PUBLIC_ORIGIN])):
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Public URL must be an HTTPS origin")
    ALLOWED_HOSTS.append(parsed.hostname)
    CSRF_TRUSTED_ORIGINS.append(origin)
if CSRF_TRUSTED_ORIGINS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
if ON_RENDER:
    if not PUBLIC_ORIGIN:
        raise ValueError("Render must provide RENDER_EXTERNAL_URL")
    if not os.environ.get("POLICYLENS_DEMO_PASSWORD"):
        raise ValueError("POLICYLENS_DEMO_PASSWORD is required on Render")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]
    SECURE_HSTS_SECONDS = 3600
ROOT_URLCONF = "server.urls"
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "server",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    *(["whitenoise.middleware.WhiteNoiseMiddleware", "server.middleware.DemoBasicAuthMiddleware"] if ON_RENDER else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
              "OPTIONS": {"context_processors": [
                  "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
                  "django.contrib.messages.context_processors.messages"]}}]
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.environ.get("PGDATABASE","policylens"),
                         "HOST": os.environ.get("PGHOST","localhost"), "PORT": os.environ.get("PGPORT","5432"),
                         "USER": os.environ.get("PGUSER",""), "PASSWORD": os.environ.get("PGPASSWORD","")}}
if os.environ.get("DATABASE_URL"):
    import dj_database_url
    DATABASES["default"] = dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=60, conn_health_checks=True)
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if ON_RENDER:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
