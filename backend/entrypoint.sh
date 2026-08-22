#!/bin/sh
set -e

# Auto-generate secrets on first start (local deployment only).
# SECRETS_FILE is set by docker-compose.local.yml; unset in prod.
. "$(dirname "$0")/scripts/manage_secrets.sh"

ensure_secrets_file "$SECRETS_FILE"

# Load secrets from volume file; env vars already set take priority.
load_secrets_file "$SECRETS_FILE"

uv run alembic upgrade head
exec uv run uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers "${UVICORN_WORKERS:-1}"
