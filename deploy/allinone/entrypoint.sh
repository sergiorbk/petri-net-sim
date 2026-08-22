#!/bin/sh
# Entrypoint for the all-in-one image (frontend + backend + Postgres, one
# container, one port). Runs as PID 1's child under tini (see
# deploy/allinone/Dockerfile): initializes Postgres on first run, starts it,
# waits for it, generates/loads secrets, runs migrations, then runs uvicorn
# in the foreground.
#
# Two long-running processes (Postgres, uvicorn) are supervised directly
# here with pg_ctl + shell trap/wait rather than a separate process manager
# (supervisord): there are only two of them, tini already reaps zombies and
# forwards signals into this script, pg_ctl already does reliable
# start/stop/wait for Postgres on its own (no manual PID tracking needed),
# and this keeps the same "small shell entrypoint" shape as the existing
# backend/entrypoint.sh instead of introducing a second, differently-shaped
# supervision mechanism.
set -e

SCRIPT_DIR="$(dirname "$0")"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/manage_secrets.sh"

DATA_DIR="${DATA_DIR:-/data}"
PGDATA="${PGDATA:-$DATA_DIR/postgres}"
SECRETS_FILE="${SECRETS_FILE:-$DATA_DIR/secrets/app.env}"
DB_NAME="${DB_NAME:-petri_net_sim}"
DB_USER="${DB_USER:-petri_net_sim}"
DB_PASSWORD="${DB_PASSWORD:-petri_net_sim}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

mkdir -p "$PGDATA" "$(dirname "$SECRETS_FILE")"
chown -R postgres:postgres "$PGDATA"
chown postgres:postgres /var/run/postgresql

FIRST_INIT=0
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    FIRST_INIT=1
    echo "Initializing PostgreSQL data directory at $PGDATA ..."
    pwfile="$(mktemp)"
    printf '%s' "$DB_PASSWORD" > "$pwfile"
    chown postgres:postgres "$pwfile"
    su postgres -c "initdb -D '$PGDATA' -U '$DB_USER' --pwfile='$pwfile' --auth=scram-sha-256 --encoding=UTF8"
    rm -f "$pwfile"
    # Postgres never needs to be reachable from outside this container (the
    # app talks to it over 127.0.0.1 in the same network namespace), so keep
    # it off the wire entirely rather than relying only on the compose file
    # not publishing a port for it.
    echo "listen_addresses = '127.0.0.1'" >> "$PGDATA/postgresql.conf"
fi

echo "Starting PostgreSQL ..."
su postgres -c "pg_ctl start -D '$PGDATA' -l '$PGDATA/server.log' -w -t 60"

if [ "$FIRST_INIT" = "1" ]; then
    echo "Creating database '$DB_NAME' ..."
    # createdb connects over TCP to 127.0.0.1, which -- like every other
    # host connection -- requires the scram-sha-256 password set above via
    # initdb --pwfile. Without PGPASSWORD it blocks on an interactive
    # "Password:" prompt that never gets an answer in a container.
    su postgres -c "PGPASSWORD='$DB_PASSWORD' createdb -U '$DB_USER' -h '$DB_HOST' -p '$DB_PORT' '$DB_NAME'"
fi

# Auto-generate JWT/Fernet secrets on first run and persist them to the same
# volume as the Postgres data (shared with backend/entrypoint.sh so the two
# images don't carry duplicate copies of this logic).
ensure_secrets_file "$SECRETS_FILE"
load_secrets_file "$SECRETS_FILE"

export DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD

echo "Running database migrations ..."
uv run alembic upgrade head

stop_postgres() {
    su postgres -c "pg_ctl stop -D '$PGDATA' -m fast -w -t 30" 2>/dev/null || true
}

shutdown() {
    echo "Shutting down ..."
    if [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; then
        kill -TERM "$APP_PID" 2>/dev/null || true
        wait "$APP_PID" 2>/dev/null || true
    fi
    stop_postgres
    exit 0
}
trap shutdown TERM INT

echo "Starting application ..."
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-1}" &
APP_PID=$!

APP_EXIT=0
wait "$APP_PID" || APP_EXIT=$?
echo "Application exited ($APP_EXIT); stopping PostgreSQL ..."
stop_postgres
exit "$APP_EXIT"
