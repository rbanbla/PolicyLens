#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec python3 scripts/local_server.py "${1:-status}"
