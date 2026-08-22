# Configuration

Every setting has a working default, so the stack runs with no `.env` at all.
To change something:

```bash
cp .env.example .env
```

[`.env.example`](../.env.example) is the full reference and explains each
value in place. This page covers the ones people actually reach for.

## Ports

| Variable | Default | What |
|----------|---------|------|
| `FRONTEND_PORT` | `6200` | UI, production stack |
| `BACKEND_PORT` | `6201` | API, production stack |
| `DB_PORT` | `6202` | PostgreSQL on the host, for dev tools |
| `FRONTEND_DEV_PORT` | `6203` | Vite dev server, dev overlay only |
| `PORT` | `6204` | The all-in-one container |
| `PETRI_SERVER_PORT` | `6205` | petri-server, when its Compose profile is on |

## Application

| Variable | Default | What |
|----------|---------|------|
| `APP_ENV` | `local` | `local` is relaxed and serves API docs. `prod` hardens the server and refuses to start on insecure config |
| `APP_PUBLIC_URL` | `http://localhost:6201` | Public backend URL, used to build absolute links such as PNML downloads |
| `UVICORN_WORKERS` | `2` | Backend worker processes |

## Accounts

| Variable | Default | What |
|----------|---------|------|
| `AUTH_MODE` | `multi` | `multi` requires accounts: signup, login, OAuth, JWT and API keys. `single_user` has no login at all: every request runs as one fixed local account |

`single_user` is for a personal instance on your own machine. There is no
other access control at that layer, so anyone who can reach the port is the
user. With `APP_ENV=prod` the backend says so loudly at startup.

## Secrets

| Variable | Default | What |
|----------|---------|------|
| `AUTH_JWT_SECRET_KEY` | generated locally, required when deployed | Signs access and refresh tokens |
| `CREDENTIALS_CIPHER` | `fernet` | How stored LLM keys are encrypted |
| `CREDENTIALS_MASTER_KEY` | generated locally, required when deployed | The key that cipher uses |

Left blank **outside a deployed environment**, both are generated on first
start, printed once to the backend logs and kept in the `secrets` volume.
`make secrets` prints them back.

> [!IMPORTANT]
> With `APP_ENV` set to `prod`, `production`, `stage` or `staging`, the
> entrypoint refuses to start unless both are supplied. It does not generate
> them and warn: a generated pair differs per container, so a second replica
> or a replaced volume logs every user out and makes every stored LLM
> credential unreadable. Those failures look like data loss and surface long
> after the deploy that caused them.

Generate a Fernet master key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Simulation engine

| Variable | Default | What |
|----------|---------|------|
| `SIMULATION_ENGINE` | `builtin` | `builtin` for the Python engine that ships here, `remote` for a petri-server instance |
| `SIMULATION_REMOTE_URL` | empty | Base URL of that instance. Required when the engine is `remote` |
| `SIMULATION_REMOTE_FALLBACK` | `true` | On an unreachable remote engine: `true` runs the model here and says so on the stream, `false` reports the failure |

Setting a URL is not on its own a request to compute there. The engine has to
be switched explicitly, so a leftover address cannot quietly route every run
through a service nobody deployed.

See [petriobjmodelpaint.md](petriobjmodelpaint.md) for what petri-server is
and how to bring one up.

## LLM keys

There is nothing to configure. The app is BYOK: every user adds their own key
in Settings, and it is encrypted with the cipher above before it is stored.
No shared server-side key exists.
