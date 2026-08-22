# Running the app

Four ways, all of them Docker. Pick by what you are doing, not by what looks
smallest.

## 1. Use it

```bash
docker compose up -d --build
```

Production-style build: optimized UI behind nginx, backend with several
workers, PostgreSQL. App on **http://localhost:6200**.

Accounts are on by default here, so the first visit offers signup.

## 2. Develop it

```bash
make dev
# or: docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Source is bind-mounted and both halves reload on save:

| | Where |
|---|---|
| UI, Vite dev server | http://localhost:6203 |
| API and its docs | http://localhost:6201/docs |

To run one half on the host instead of in Docker, see
[`backend/README.md`](../backend/README.md) and
[`frontend/README.md`](../frontend/README.md).

> [!NOTE]
> On Windows, Vite does not always see host edits through the bind mount,
> because inotify events are not forwarded. If a change does not appear,
> restart the frontend container.

## 3. Deploy it

```bash
cp .env.example .env
# APP_ENV=prod, a strong DB_PASSWORD, explicit AUTH_JWT_SECRET_KEY and
# CREDENTIALS_MASTER_KEY, APP_PUBLIC_URL=https://your.domain
docker compose up -d --build
```

> [!IMPORTANT]
> With `APP_ENV=prod` the backend refuses to start on insecure configuration,
> so those secrets are not optional. See
> [configuration.md](configuration.md).

Terminate TLS in front of it. There is an example nginx config in
[`deploy/nginx/app.conf.example`](../deploy/nginx/app.conf.example).

On a real server, pull published images instead of building on the box, and
let a release ship itself. See [deployment.md](deployment.md).

## 4. One container

```bash
docker compose -f docker-compose.allinone.yml up -d
```

Frontend, backend and Postgres in a single container on
**http://localhost:6204**, single-user mode, zero configuration. Secrets are
generated on first start and persisted in its data volume, so restarts keep
everything. Good for trying the app or running it for yourself, not for a
shared deployment.

## Ports

| Port | What |
|------|------|
| 6200 | UI, production stack |
| 6201 | API, production stack |
| 6202 | PostgreSQL on the host, for dev tools |
| 6203 | UI, dev overlay only |
| 6204 | The all-in-one container |
| 6205 | petri-server, when the Compose profile is on |

Every one of them is an `.env` variable. See
[configuration.md](configuration.md).

## Make targets

```
make up            start the full stack, build if needed
make dev           start with hot reload
make allinone      start the single-container image
make down          stop, keeping data volumes
make clean         stop and remove everything including data
make logs          tail logs
make ps            service status
make secrets       print the auto-generated secrets, first start only
make test          run the backend tests in a one-off container
make help          list all of it
```

`make` wraps Docker Compose and nothing else. The commands above work without
it; on Windows, run them directly or use Git Bash.
