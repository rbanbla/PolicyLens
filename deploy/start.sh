#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python -m gunicorn server.wsgi:application --bind "0.0.0.0:${PORT:-10000}" --workers 2 --threads 4 --timeout 120 --access-logfile -
