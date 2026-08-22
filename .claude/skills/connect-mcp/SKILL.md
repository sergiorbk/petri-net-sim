---
name: connect-mcp
description: Register a running Petri Net Sim instance as an MCP server in Claude Code, Claude Desktop, Cursor, or any other MCP client. Use when someone wants an agent to build, edit or simulate Petri nets in their account over MCP, or when an MCP connection to this app returns 401 or 403.
---

# Connect a client to the Petri Net Sim MCP server

The server is bundled into the backend and speaks streamable HTTP. It
authenticates with the same `sk-` API keys the app's Settings page issues, and
each account can switch MCP access off without revoking its keys.

## 1. Find the endpoint

Ask the deployment rather than guessing: `MCP_PATH` is configurable.

```bash
curl -s http://localhost:6204/api/v1/config
```

`mcp_enabled` says whether this server serves MCP at all, `mcp_path` says
where. The endpoint is the app's own origin plus that path, for example
`http://localhost:6204/mcp`.

## 2. Get an API key

In the app: **Settings, API Keys, Create key**. The raw key is shown once.

In single-user deployments (`auth_mode: single_user` in the config above) there
is no login, so the endpoint is reachable without a token:

```bash
curl -s -X POST http://localhost:6204/api/v1/auth/api-keys \
  -H "Content-Type: application/json" -d '{"name": "my-client"}'
```

Never write a key into a file that is committed. Ask the user for theirs, or
have them paste it into the client's own config.

## 3. Register it

Claude Code, from the shell:

```bash
claude mcp add --transport http petri-net-sim http://localhost:6204/mcp \
  --header "Authorization: Bearer sk-..."
```

Claude Desktop, Cursor and other config-file clients:

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

Restart the client. The Petri net tools appear in its tool list.

## 4. Check it by hand

```bash
curl -s -X POST http://localhost:6204/mcp \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"probe","version":"1"}}}'
```

## When it refuses

| Response | Meaning |
|----------|---------|
| 401 | No `Authorization` header, a token that is not `sk-`, or a revoked key. Issue a new key. |
| 403 | The key is valid and the account has MCP switched off. Turn it back on in Settings, MCP. Another key will not help. |
| 404 | Wrong path. Re-read `mcp_path` from `/api/v1/config`. |
