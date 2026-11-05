#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077

python=.venv/bin/python
if [[ ! -x "$python" ]]; then
    if ! command -v python3.11 >/dev/null; then
        echo "최초 설치에 Python 3.11이 필요합니다." >&2
        exit 1
    fi
    python3.11 -m venv .venv
fi
if ! "$python" -c 'import django, psycopg, pgserver, pypdf, dotenv, openpyxl, pyarrow' 2>/dev/null; then
    "$python" -m pip install -r requirements.txt pgserver==0.1.4
fi
pgbin=$("$python" -c 'import pgserver; from pathlib import Path; print(Path(pgserver.__file__).parent / "pginstall/bin")')

export PGHOST="$PWD/.pgdata/socket" PGPORT=55432 PGDATABASE=policylens PGUSER="$(id -un)"
mkdir -p "$PGHOST"
chmod 700 "$PGHOST"
if [[ ! -s .pgdata/secret ]]; then
    "$python" -c 'import secrets; print(secrets.token_urlsafe(50))' > .pgdata/secret
fi
export DJANGO_SECRET_KEY
DJANGO_SECRET_KEY=$(cat .pgdata/secret)

if [[ ! -f .pgdata/db/PG_VERSION ]]; then
    "$pgbin/initdb" -D .pgdata/db -A trust --encoding=UTF8 --locale=C >/dev/null
fi
if ! "$pgbin/pg_ctl" -D .pgdata/db status >/dev/null; then
    "$pgbin/pg_ctl" -D .pgdata/db -l .pgdata/postgres.log -o "-k '$PGHOST' -p $PGPORT -c listen_addresses=''" -w start
    trap '"$pgbin/pg_ctl" -D .pgdata/db -m fast -w stop' EXIT
fi
exists=$("$pgbin/psql" -X -At -d postgres -c "SELECT 1 FROM pg_database WHERE datname = 'policylens'")
if [[ "$exists" != 1 ]]; then
    "$pgbin/createdb" policylens
fi
"$python" manage.py migrate --noinput
"$python" manage.py seed_demo
corpus_ready=$("$python" manage.py shell -c 'from server.models import Evidence; print(int(Evidence.objects.exists()))' | tail -n 1)
if [[ "$corpus_ready" != 1 ]]; then
    "$python" manage.py import_corpus
fi
"$python" manage.py import_b_sources
"$python" manage.py export_b_inventory
"$python" scripts/data/organize_roles.py
admin_exists=$("$python" manage.py shell -c 'from django.contrib.auth import get_user_model; print(int(get_user_model().objects.filter(is_superuser=True, is_active=True).exists()))' | tail -n 1)
if [[ "$admin_exists" != 1 ]]; then
    echo "최초 실행입니다. 로그인에 사용할 연구자 계정을 만들어 주세요."
    "$python" manage.py createsuperuser
fi
echo "PolicyLens 접속: http://127.0.0.1:8000/ (종료: Ctrl+C)"
"$python" manage.py runserver --noreload --insecure 127.0.0.1:8000
