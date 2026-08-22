---
name: petri-api
description: Call the Petri Net Sim HTTP API from code or a shell. Generate a net from a natural-language prompt through the OpenAI-compatible endpoint, then read, store, export or simulate it. Use when someone wants to script this app rather than click it, or when an API call returns 401, 403 or an empty reply.
---

# Driving the Petri Net Sim HTTP API

Two shapes share one origin: an OpenAI-compatible chat endpoint that generates
nets, and a REST API that stores, exports and simulates them.

## Before anything

```bash
curl -s http://localhost:6204/api/v1/config
```

`http_api_enabled` says whether this deployment serves the API at all,
`http_api_path` gives the base path (`/api/v1`), and `docs_url` /
`openapi_url` are non-null wherever docs are on. `auth_mode: single_user`
means there is no login and requests need no token.

Authenticate with an `sk-` key from **Settings, API Keys**, sent as
`Authorization: Bearer sk-...`. The full schema is always the source of truth:
`GET /openapi.json`, or the interactive docs at `/docs`.

## Generate a net from a prompt

Any OpenAI client library works. The model id is `petri-net-sim`.

```bash
curl -s http://localhost:6204/api/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "petri-net-sim",
    "messages": [{"role": "user", "content": "A workshop with two machines and one queue"}]
  }'
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:6204/api/v1", api_key="sk-...")
reply = client.chat.completions.create(
    model="petri-net-sim",
    messages=[{"role": "user", "content": "A workshop with two machines and one queue"}],
)
```

Pass `"stream": true` for token streaming. The reply carries the generated net
and download links for its PNML.

This is BYOK: the agent runs on the caller's own LLM credentials. Add them in
Settings, LLM Profiles, or bind one to a key when creating it, otherwise the
call fails with a credentials error rather than a network error.

## The REST surface

| Area | Endpoints |
|------|-----------|
| Chat sessions | `GET /sessions`, `GET /sessions/{id}/net`, `GET /sessions/{id}/pnml`, `PATCH /sessions/{id}/share` |
| Saved nets | `GET` and `POST /nets`, `GET`, `PUT`, `DELETE /nets/{id}`, `GET /nets/{id}/pnml` |
| Petri-objects | `GET` and `POST /petri-objects`, `GET`, `PUT`, `DELETE /petri-objects/{id}` |
| PNML | `POST /pnml/parse` to read a document back into the app's model |
| Simulation | `POST /simulate`, `POST /simulate/precompute`, `POST /simulate/composed` |
| Account | `GET` and `PATCH /auth/me`, `GET` and `POST /auth/api-keys` |

Responses are wrapped: `{"success": true, "data": ..., "meta": ..., "error": null}`.
Read `data`. Simulation endpoints stream Server-Sent Events instead.

`PATCH /auth/me` also carries the two integration switches, `mcp_enabled` and
`http_api_enabled`. Both default to true and are stored per account.

## When it refuses

| Response | Meaning |
|----------|---------|
| 401 | Missing or invalid key. In `multi` mode everything needs one except `/config`, `/health` and the public share links. |
| 403 | The key is valid and the account has API access switched off. Turn it on in Settings, OpenAPI. |
| 422 | Schema mismatch. Check the request against `/openapi.json`, which is generated from the code. |
| Empty reply | Usually no usable LLM credential behind the key. Check Settings, LLM Profiles. |
