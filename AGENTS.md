# Working on Petri Net Sim

Notes for coding agents (and new humans). Short on purpose. The
[README](README.md) covers what the app is and how to run it; this covers how
to change it.

## Layout

```
backend/     FastAPI + LangGraph. Python 3.13, uv, pytest, alembic.
frontend/    React 18 + Vite. TypeScript, npm, vitest.
deploy/      allinone image, example nginx config.
.github/     CI, version bump, GHCR release.
```

Inside `backend/src`:

| Path | What it holds |
|------|---------------|
| `api/versions/v1/` | REST routers and schemas (`/api/v1/...`) |
| `openai_api/` | The OpenAI-compatible chat API |
| `mcp/` | MCP server: tools, resources, prompts, key auth |
| `services/agent/` | The LangGraph agent and its tools |
| `services/petri/` | Net model, patterns, PNML import and export |
| `services/simulation/` | The built-in engine, plus the remote adapter |
| `infrastructure/postgres/` | Models, repositories, migrations |

Inside `frontend/src`: `apps/` (routed apps), `shell/` (the frame around
them), `components/`, `stores/` (Zustand), `lib/` (PNML, API clients,
client-side simulation).

## Commands

```bash
# Backend, from backend/
uv sync --extra dev
uv run pytest                     # 2200+ tests, about 90 seconds
uv run pytest tests/test_foo.py -q --no-cov
uv run alembic upgrade head

# Frontend, from frontend/
npm ci
npm run typecheck
npm run test:run
npm run build

# The whole stack
make dev            # hot reload: UI :6203, API :6201
make allinone       # one container on :6204, no login
```

## House rules

**A setting either does something or it does not exist.** The repo has already
been audited once for options that read as load-bearing and were not. If you
add a toggle, wire it to the code that honours it, and add the test that
proves a request is actually refused.

**Assert on the second request.** A handler can return the value it meant to
save while the transaction rolls back underneath it. `UserRepository.update`
flushes but does not commit, and the session dependency does not commit on the
way out, so a router that writes must commit. Round-trip the read.

**JSON columns need a new dict.** `dict(user.metadata_)` is shallow: the
nested dicts inside it are the same objects SQLAlchemy holds as the committed
value. Edit one in place and the flush sees no change, so the write silently
disappears. Build a fresh nested dict before assigning.

**Every user-facing string is a key** in both `frontend/src/i18n/locales/en.json`
and `uk.json`. No literals in components.

**PNML is a contract.** Exports are validated against the real ISO/IEC 15909-2
RELAX NG grammar in `backend/tests/schema/`, and composed models are read by
PetriObjModelPaint's `petri-server`. Changing the shape of a document means
updating the golden fixtures and running the schema tests.

**Comments say why.** The surrounding code explains decisions and traps, not
mechanics. Match that. Write English, and skip the em dashes.

**Commits** are conventional-commit prefixed (`feat(scope):`), narrative in
the body, and carry no AI attribution trailers.

## The two machine-facing entry points

Both take `sk-` API keys created in Settings, and both can be switched off per
account (stored in `User.metadata_`, see `services/auth/integrations.py`):

- **MCP** at `/mcp`, streamable HTTP. Auth and the per-account switch are
  enforced in `src/mcp/auth.py`.
- **OpenAI-compatible API** at `/api/v1/chat/completions`. The switch is
  enforced in `get_http_api_context`, and only for API-key callers: the web UI
  hits the same endpoint with a browser session and must keep working.

`GET /api/v1/config` reports, without authentication, which of the two this
deployment serves and at which paths. Read connection URLs from there rather
than assuming defaults.

## Branches and releases

**Trunk-based development, in its GitHub Flow shape.** One long-lived branch,
the repository's default, and nothing else lives long:

1. Branch off the trunk for one piece of work. Keep it short: days, not weeks.
2. Open a pull request into the trunk. CI runs there, and that run is the gate.
3. Merge, delete the branch.

There is no `develop`, no `release/*`, no `hotfix/*`. A fix is a branch and a
pull request like anything else, and it ships by cutting a release from the
trunk afterwards.

**Releases are tags, and tags are the only version that means anything.**
Semantic versioning, `v1.2.3`:

| Step | What happens |
|------|--------------|
| Run `bump-version.yml` | Rewrites every version literal, regenerates the golden PNML fixtures, runs both suites as a gate, commits and tags |
| Publish a GitHub Release from the tag | A human step, and the only one |
| `release.yml` reacts | Builds and pushes the all-in-one image to GHCR, the only one published |
| `deploy.yml` reacts | Ships that release to the configured server |

So the trunk is always releasable and a release is never a branch: it is a
commit on the trunk with a tag pointing at it, and rolling back means
deploying the previous tag.

Nothing in `.github/workflows/` names the trunk. CI has no branch filter and
`bump-version.yml` falls back to `github.event.repository.default_branch`, so
renaming that branch never leaves a workflow quietly matching nothing.

## Skills

`.claude/skills/` holds task guides worth loading before you start:

| Skill | Load it when |
|-------|--------------|
| **add-a-setting** | Anything reaches the Settings screen, or a saved value does not survive a reload |
| **pnml-standard** | The shape of a PNML document changes, or a conformance test fails |
| **connect-mcp** | Registering this app's MCP server in a client |
| **petri-api** | Driving the HTTP API from code or a shell |

The last two are operational and overlap [docs/integrations.md](docs/integrations.md),
which is the same ground written for a person rather than for an agent
mid-task.
