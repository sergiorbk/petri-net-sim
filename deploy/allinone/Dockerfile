# All-in-one image: frontend + backend + Postgres in ONE container on ONE
# port. Build from the repo root (the frontend stage needs frontend/, the
# final stage needs backend/):
#
#   docker build -f deploy/allinone/Dockerfile -t petri-net-sim-allinone .
#
# This is an ADDITIONAL artifact alongside the normal multi-container
# docker-compose.yml (nginx + backend + postgres, three containers) -- that
# setup is unchanged and still the one to use for a real deployment. This
# image trades that isolation for a single `docker run`/`docker compose up`,
# defaulting to AUTH_MODE=single_user (no signup step) for someone who just
# wants to try the app.
#
# ---- Stage 1: build the frontend (same as frontend/Dockerfile's "build" stage) ----
FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---- Stage 2: backend + Postgres + the built frontend, one process tree ----
FROM python:3.13-slim

WORKDIR /app

# --- Python deps (uv-managed, mirrors backend/Dockerfile) ---
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev
COPY backend/ .

# --- PostgreSQL 16 (matches the major version of postgres:16-alpine used by
# the multi-container docker-compose.yml) plus tini.
#
# Debian trixie's own apt repo only carries postgresql-17 (the version that
# shipped with this Debian release), so postgresql-16 comes from the PGDG
# apt repo (apt.postgresql.org), which maintains every supported Postgres
# major version for every supported Debian/Ubuntu release. tini becomes PID
# 1 (see ENTRYPOINT below) purely for correct signal forwarding and zombie
# reaping around the two long-running processes entrypoint.sh supervises
# (Postgres, uvicorn) -- simpler than adding a config-file-driven process
# manager like supervisord for exactly two processes.
#
# curl/gnupg are only needed to fetch and verify the PGDG signing key, so
# they're removed again in the same layer; ca-certificates stays (the app
# talks HTTPS to whichever LLM provider the user configures).
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc]" \
        "https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16 tini fonts-dejavu-core \
    && apt-get purge -y --auto-remove curl gnupg \
    # libllvm19 (JIT), libz3-4 (only used by libllvm19) and libperl5.40 plus
    # perl-modules-5.40 (PL/Perl) are hard Depends of postgresql-16 /
    # postgresql-common, not Recommends, so --no-install-recommends above
    # does not touch them, and apt refuses a normal removal since it would
    # also want to remove postgresql-16 itself. Neither JIT nor PL/Perl is
    # used anywhere in this application (the entrypoint below starts
    # Postgres directly with pg_ctl, never through postgresql-common's own
    # Perl-based cluster wrapper scripts), so dpkg purges them by name with
    # their dependency check overridden. Verified empirically, not just by
    # reading the dependency graph: a container built without these three
    # packages runs initdb, starts, restarts, and serves real queries
    # normally; only explicitly forcing `jit = on` (something nothing in
    # this codebase ever does) fails that one query with a plain, catchable
    # "could not load library" error, not a server crash. perl-base stays --
    # it is Essential and dpkg refuses to remove it regardless, and at under
    # 8MB it was never the size problem. Together this trims roughly 200MB
    # off what would otherwise be a ~1.1GB image. \
    && dpkg --purge --force-depends libllvm19 libz3-4 libperl5.40 perl-modules-5.40 \
    && rm -rf /var/lib/postgresql/16/main /etc/postgresql /var/lib/apt/lists/*

ENV PATH="/usr/lib/postgresql/16/bin:${PATH}"

# --- Built frontend, served by the backend itself (see
# backend/src/api/static_frontend.py) instead of a separate nginx --
# there's only one container, so one process can own both the API and the
# static assets on the same port. ---
COPY --from=frontend-build /app/dist /app/static

# --- Entrypoint. manage_secrets.sh is shared with backend/entrypoint.sh
# (see backend/scripts/manage_secrets.sh) rather than duplicated here. ---
# The licence travels with the software, because PolyForm requires it to:
# publishing this image is distribution, and a recipient who only ever runs
# `docker pull` must still receive the terms and the Required Notice. Without
# this line the image is the one copy of the project that ships without them.
COPY LICENSE /LICENSE

COPY backend/scripts/manage_secrets.sh /manage_secrets.sh
COPY deploy/allinone/entrypoint.sh /entrypoint-allinone.sh
RUN chmod +x /entrypoint-allinone.sh /manage_secrets.sh

# --- Defaults: single-user, no-login mode; zero configuration required.
# Postgres data and the auto-generated JWT/Fernet secrets both live under
# one mounted volume (DATA_DIR) so a single named volume covers both -- see
# docker-compose.allinone.yml. Postgres itself is never exposed outside the
# container (DB_HOST is the loopback address, and Postgres is only told to
# listen on 127.0.0.1 -- see entrypoint.sh), so its credentials are fixed
# defaults rather than generated, matching docker-compose.yml's own
# defaults for consistency; the secrets that actually matter (JWT signing,
# BYOK credential encryption) are the ones auto-generated. ---
ENV AUTH_MODE=single_user \
    APP_ENV=local \
    FRONTEND_STATIC_DIR=/app/static \
    DATA_DIR=/data \
    PGDATA=/data/postgres \
    SECRETS_FILE=/data/secrets/app.env \
    DB_HOST=127.0.0.1 \
    DB_PORT=5432 \
    DB_NAME=petri_net_sim \
    DB_USER=petri_net_sim \
    DB_PASSWORD=petri_net_sim \
    UVICORN_WORKERS=1

EXPOSE 8000
VOLUME ["/data"]

ENTRYPOINT ["tini", "--", "/entrypoint-allinone.sh"]
