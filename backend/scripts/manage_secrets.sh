#!/bin/sh
# Shared secret generation/loading logic for entrypoint scripts.
#
# Used by both backend/entrypoint.sh (the normal multi-container stack) and
# deploy/allinone/entrypoint.sh (the single-container image), so the
# auto-generation behavior stays identical between the two instead of
# drifting apart as two copies of the same shell snippet.
#
# Usage (POSIX sh, source this file then call the functions):
#   . /path/to/manage_secrets.sh
#   ensure_secrets_file "$SECRETS_FILE"
#   load_secrets_file "$SECRETS_FILE"
#
# ensure_secrets_file requires `uv` (and the `cryptography` package, already
# a backend dependency) on PATH to run the Python generator.

# True when APP_ENV names a deployed environment. Kept in step with
# Settings.is_production in src/core/config.py, which recognises the same
# four spellings.
is_deployed_env() {
    case "$(printf '%s' "${APP_ENV:-local}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')" in
        stage|staging|prod|production) return 0 ;;
        *) return 1 ;;
    esac
}

# Generate AUTH_JWT_SECRET_KEY and CREDENTIALS_MASTER_KEY into $1 if that
# file does not already exist. No-op if $1 is empty or already present.
#
# Refuses to generate anything in a deployed environment. Generated secrets
# are per-container by construction: a second replica, or a first one whose
# volume was not preserved, invents different ones. That logs every user out
# on a JWT secret it does not share, and makes every stored BYOK key
# unreadable on a master key it does not share. Both failures look like data
# loss and arrive long after the deploy that caused them, so this is a
# refusal to start rather than a warning nobody reads.
ensure_secrets_file() {
    secrets_file="$1"

    # Supplied explicitly: nothing to generate, anywhere. This is the path a
    # Kubernetes Secret or a real .env takes, and it needs no volume at all.
    if [ -n "${AUTH_JWT_SECRET_KEY:-}" ] && [ -n "${CREDENTIALS_MASTER_KEY:-}" ]; then
        return 0
    fi

    if is_deployed_env; then
        cat >&2 <<'ERREOF'
================================================================
  REFUSING TO START: secrets must be set explicitly
================================================================
  APP_ENV names a deployed environment, and AUTH_JWT_SECRET_KEY
  and CREDENTIALS_MASTER_KEY are not both set.

  Auto-generation exists for a laptop. Here it would mint a
  different pair per container, which logs every user out and
  makes every stored BYOK key unreadable the moment a second
  replica starts or a volume is replaced.

  Generate them once and pass them in (a Kubernetes Secret, or
  .env on the server):

    AUTH_JWT_SECRET_KEY:
      openssl rand -hex 32

    CREDENTIALS_MASTER_KEY:
      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

  See docs/deployment.md.
================================================================
ERREOF
        exit 1
    fi

    if [ -n "$secrets_file" ] && [ ! -f "$secrets_file" ]; then
        uv run python - "$secrets_file" <<'PYEOF'
import sys, secrets
from cryptography.fernet import Fernet
from pathlib import Path

secrets_file = Path(sys.argv[1])
secrets_file.parent.mkdir(parents=True, exist_ok=True)

jwt_secret = secrets.token_hex(32)
master_key = Fernet.generate_key().decode()

secrets_file.write_text(
    f"AUTH_JWT_SECRET_KEY={jwt_secret}\n"
    f"CREDENTIALS_MASTER_KEY={master_key}\n"
)

border = "=" * 64
print(border)
print("  AUTO-GENERATED SECRETS, saved to volume, shown once")
print(border)
print(f"  AUTH_JWT_SECRET_KEY     = {jwt_secret}")
print(f"  CREDENTIALS_MASTER_KEY  = {master_key}")
print(border)
sys.stdout.flush()
PYEOF
    fi
}

# Export every KEY=value line from $1 into the environment, but only where
# that variable isn't already set (env vars passed in explicitly always win
# over the persisted file).
load_secrets_file() {
    secrets_file="$1"
    if [ -n "$secrets_file" ] && [ -f "$secrets_file" ]; then
        while IFS= read -r line; do
            case "$line" in
                ''|\#*) continue ;;
            esac
            key="${line%%=*}"
            value="${line#*=}"
            eval "current=\${${key}:-}"
            if [ -z "$current" ]; then
                export "${key}=${value}"
            fi
        done < "$secrets_file"
    fi
}
