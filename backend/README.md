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
