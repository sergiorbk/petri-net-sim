# Connecting other tools

Two doors lead into the app besides the browser: an **MCP server** and an
**OpenAI-compatible HTTP API**. Both take the same API keys, and each can be
closed off per account without touching those keys.

| | Endpoint | For |
|---|---|---|
| **MCP** | `/mcp`, streamable HTTP | Claude Desktop, Claude Code, Cursor and other MCP clients |
| **HTTP API** | `/api/v1`, OpenAI-compatible | Any OpenAI client library, from your own code |

## 1. Create an API key

**Settings → API Keys → Create key.** The raw key is shown once, so copy it
then.

A key can be bound to one of your LLM profiles. Requests made with it run on
that model, which is how one key can be "the cheap one" and another "the good
one".

## 2. Find your URLs

Every instance answers this without authentication:

```bash
curl -s http://localhost:6204/api/v1/config
```

```json
{
  "auth_mode": "single_user",
  "mcp_enabled": true,
  "mcp_path": "/mcp",
  "http_api_enabled": true,
  "http_api_path": "/api/v1",
  "openapi_url": "/openapi.json",
  "docs_url": "/docs"
}
```

The **Settings → MCP** and **Settings → OpenAPI** pages print the same URLs
already filled in for the instance you are looking at, which is easier than
assembling them by hand. `mcp_path` is configurable and the docs routes are
switched off in deployed environments, so read them rather than assume.

## MCP

Claude Code:

```bash
claude mcp add --transport http petri-net-sim http://localhost:6204/mcp \
  --header "Authorization: Bearer sk-..."
```

Claude Desktop, Cursor, and anything else with a config file:

```json
{
  "mcpServers": {
    "petri-net-sim": {
      "type": "http",
      "url": "http://localhost:6204/mcp",
      "headers": { "Authorization": "Bearer sk-..." }
    }
  }
}
```

Restart the client and the Petri net tools appear in its tool list: building
and editing nets, composing Petri-objects, running simulations, exporting
PNML.

The server also runs on its own, without the web app:

```bash
uv run python mcp_server.py            # HTTP on :8001
uv run python mcp_server.py --stdio    # stdio, for a local client
```

## HTTP API

The model id is `petri-net-sim`, and the base URL is the app's origin plus
`/api/v1`.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:6204/api/v1", api_key="sk-...")
reply = client.chat.completions.create(
    model="petri-net-sim",
    messages=[{"role": "user", "content": "A workshop with two machines and one queue"}],
)
```

```bash
curl http://localhost:6204/api/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "petri-net-sim",
       "messages": [{"role": "user", "content": "A workshop with two machines and one queue"}]}'
```

`"stream": true` streams tokens. The reply carries the generated net and
download links for its PNML.

Beyond chat there is a REST surface for sessions, saved nets, Petri-objects,
PNML parsing and simulation. The interactive docs at `/docs` and the schema at
`/openapi.json` are generated from the code, so they are never out of date.

## The switches

Each account owns both doors independently, on the **MCP** and **OpenAPI**
settings pages. Turning one off makes this server answer **403** to requests
made with that account's API keys, while the keys keep working everywhere
else.

The web app is unaffected either way: it reaches the same endpoints with a
browser session rather than an API key, and only key-authenticated callers are
gated.

## When it refuses

| Response | Meaning |
|----------|---------|
| **401** | No `Authorization` header, a token that is not `sk-`, or a revoked key |
| **403** | The key is valid and the account has that door switched off. Another key will not help |
| **404** on `/mcp` | Wrong path, or this deployment runs with MCP disabled. Check `/api/v1/config` |
| **422** | Request does not match the schema. Compare against `/openapi.json` |
| Empty reply | Usually no usable LLM credential behind the key. Check Settings → LLM Profiles |
