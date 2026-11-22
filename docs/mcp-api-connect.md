# Connect AgentDock with MCP or the REST API

This guide shows the exact steps to connect an agent to AgentDock on Oracle at `http://92.5.229.27:8000`, using either MCP or the REST API with an API key.

## 1. Sign in

Open http://92.5.229.27:8000 and sign in, or create an account:

```powershell
Invoke-WebRequest -Method Post -Uri http://92.5.229.27:8000/api/v1/auth/login -ContentType application/json -Body '{"email":"<your-email>","password":"<your-password>"}'
```

## 2. Get an API key (required for both MCP and REST)

Open **Integrations**, or create a token with the API:

```powershell
$token = Invoke-RestMethod -Method Post -Uri http://92.5.229.27:8000/api/v1/auth/token -ContentType application/json -Body '{"email":"<your-email>","password":"<your-password>"}'
$token.access_token
```

Store this API key. It is shown once.

## 3. Connect MCP

Copy this JSON into your MCP client configuration (Claude, Cursor, Windsurf, OpenCode, etc.):

```json
{
  "mcpServers": {
    "agentdock": {
      "url": "http://92.5.229.27:8000/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

Then verify it works:

```powershell
Invoke-WebRequest -Method Post -Uri http://92.5.229.27:8000/mcp -ContentType application/json -Body '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' -Headers @{'Authorization'='Bearer <your-api-key>';'Accept'='application/json, text/event-stream'}
```

List tools:

```powershell
Invoke-WebRequest -Method Post -Uri http://92.5.229.27:8000/mcp -ContentType application/json -Body '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' -Headers @{'Authorization'='Bearer <your-api-key>';'Accept'='application/json, text/event-stream'}
```

Call a skill:

```powershell
Invoke-WebRequest -Method Post -Uri http://92.5.229.27:8000/mcp -ContentType application/json -Body '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_skills","arguments":{"query":"test-driven-development"}}}' -Headers @{'Authorization'='Bearer <your-api-key>';'Accept'='application/json, text/event-stream'}
```

## 4. Use the REST API

Search skills:

```powershell
Invoke-WebRequest -Uri 'http://92.5.229.27:8000/api/v1/skills/search?q=test-driven-development&limit=10' -Headers @{'Authorization'='Bearer <your-api-key>'}
```

Retrieve instructions for a skill:

```powershell
Invoke-WebRequest -Method Post -Uri 'http://92.5.229.27:8000/api/v1/skills/stevohcoder-igura-marketplace-agents-skills-test-driven-development/retrieve' -ContentType application/json -Body '{}' -Headers @{'Authorization'='Bearer <your-api-key>'}
```

## Troubleshooting

- 401: sign in again or create an API key with `POST /api/v1/auth/token`.
- 403 on `/mcp`: some MCP clients send an `Origin` header. Make sure it matches `AGENTDOCK_FRONTEND_ORIGINS`.
- 406 on `/mcp`: send `Accept: application/json, text/event-stream`.
- 404 skill: check the slug in `/api/v1/skills/search`.
