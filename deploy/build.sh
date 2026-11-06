#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -r requirements-deploy.txt
python manage.py collectstatic --noinput
