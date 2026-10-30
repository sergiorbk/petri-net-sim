# Backend

FastAPI + LangGraph service. Turns natural-language descriptions of production
and queueing systems into Petri nets, exports them as PNML, and simulates them.

**Stack:** Python 3.13 · FastAPI · LangGraph · LangChain · PostgreSQL · MCP

Three surfaces, one process:

| Surface | Path | Notes |
|---------|------|-------|
| REST API | `/api/v1` | sessions, nets, Petri-objects, simulation |
| OpenAI-compatible API | `/api/v1/chat/completions` | works with any OpenAI client library |
| MCP server | `/mcp` | streamable HTTP, tools and resources for building nets |

The last two authenticate with `sk-` API keys, and each account can close
either one from the app's own Settings without touching its keys.

Normally you run this through the monorepo's Compose stack: see the
[root README](../README.md). The rest of this file is for running it alone.

## Standalone development

```bash
uv sync --extra dev                    # dependencies, including test extras
docker compose up -d postgres          # a database, from the root compose file
uv run alembic upgrade head            # migrations
uv run uvicorn main:app --reload --host 0.0.0.0 --port 6201
uv run pytest
```

Configuration comes from environment variables or a local `.env`; the
[root `.env.example`](../.env.example) is the reference.

## Running the MCP server on its own

| Mode | Command | Endpoint |
|------|---------|----------|
| Bundled (default) | `uvicorn main:app` | `http://host:6201/mcp` |
| Standalone HTTP | `uv run python mcp_server.py` | `http://host:8001/mcp` |
| Standalone stdio | `uv run python mcp_server.py --stdio` | n/a |

On Windows, add `--loop src.core.event_loop:new_event_loop` to the Uvicorn
command. PostgreSQL checkpointing requires a selector event loop there; Uvicorn's
default proactor loop cannot open Psycopg asynchronous connections.


### Training data and network images

The chat header's **Training ZIP** action downloads the current session's
PNML, visible conversation, available verification evidence, a network-only
PNG and geometry from the same renderer. Editor **Export > PNG** renders the
selected model without application controls. The image uses model coordinates;
it is not an editor screenshot and its geometry is not a verified detection dataset.

MCP exposes `export_training_data(title, context, conversation, tool_calls)`
and `export_image(title)`. Both return `filename`, `media_type` and
`data_base64`; decode the base64 to save the file. Supply only actual client
messages or tool records when available. The application cannot recover an
external client's chat. Missing records are declared in `manifest.json`.

Archives follow the shared training-bundle schema, include SHA-256 hashes,
and start with `unreviewed` acceptance and `unknown` verification. A completed
simulation is evidence, not automatic acceptance. The live MCP ledger keeps
the latest 200 calls of that session and excludes export payloads. Credential
fields and common credential patterns are redacted. No settings or environment
snapshot is exported. Review a bundle before including it in a training corpus.

Run `uv run python scripts/smoke_mcp_workflow.py --output <directory>` after
building the frontend to verify real HTTP MCP modeling, simulation, PNML
reopening, ZIP schema/hashes and authenticated ZIP/PNG downloads against an
isolated temporary PostgreSQL instance. Docker is required.

Shared modeling skills are installed by uv from a versioned GitHub Release wheel.
The URL and SHA-256 are pinned in pyproject.toml and uv.lock; a plain clone and
the usual uv sync command are sufficient. No PyPI account or submodule is needed.
