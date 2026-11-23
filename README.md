# AgentDock

**Stop Installing Skills. Start Using Them.**

AgentDock is the infrastructure behind your AI coding agent: a curated skill catalogue with on-demand retrieval, immutable versioned snapshots, teams, billing and governance. The web app, REST API, MCP server and CLI all use the same reviewed catalogue.

## What works

- **Marketing site and workspace** with a dark, responsive design: hero, product preview, feature and pricing sections, marketplace, documentation and a full signed-in dashboard.
- **Skill catalogue**: searchable, licence-checked, statically scanned and served from immutable snapshots. Sixteen original MIT-licensed AgentDock starter skills are preloaded on first run so the catalogue is useful immediately.
- **Accounts**: registration, email verification, password reset, profile updates, password changes, account deactivation, scoped API keys and server-side sessions.
- **Marketplace**: free and premium listings, purchases, team or personal entitlements, reviews, creator applications and earnings tracking. Premium retrieval is blocked until payment is fulfilled or an entitlement exists.
- **Billing**: subscription plans, checkout adapters for manual invoices, Paddle, Flutterwave and UrubutoPay, signed provider webhooks, refunds, receipts and admin activation. No entitlement is granted from a browser redirect.
- **Teams**: workspaces with invitations, seat limits, roles, shared collections and team usage analytics.
- **Administration**: analytics and revenue reporting, admission moderation, listing and creator review, payments and subscriptions, user management, rights/takedown workflow, imports, repositories, GitHub discovery, security scans, settings and audit logs.
- **Automation**: GitHub candidate discovery, scheduled synchronization, push webhooks, subscription expiry and a background worker with recoverable leases.
- **Integrations**: Streamable HTTP MCP at `/mcp`, OpenAPI REST at `/api/docs`, and a CLI for search, retrieval, teams, billing and the marketplace.
- **Operations**: PostgreSQL job claims, Redis-backed shared rate limits, optional S3-compatible SkillVault, Alembic migrations and a production Docker Compose stack.

## External services that need credentials

These features are implemented but stay inactive until the relevant credentials are configured:

- Email verification and password reset delivery need SMTP. Without SMTP, development responses include a one-time debug link and production returns a safe message.
- Paddle, Flutterwave and UrubutoPay need API and webhook credentials plus configured price IDs. The default `manual` provider is a real invoice workflow where an administrator records payment before access is granted.
- Automated GitHub discovery needs a read-only GitHub token. Push webhooks need a shared secret.
- Native editor plugins and semantic/vector search are not part of this build.

The static security scanner is pattern-based and is not a malware detector. Imported skills still require human review. Production rollout needs security, legal and capacity reviews.

## Local development

Requirements: Python 3.11+, Node.js 20.19+ (or 22.12+) and npm.

1. Copy `.env.example` to `.env`:

    ```powershell
    Copy-Item .env.example .env
    ```

   Replace `AGENTDOCK_SECRET_KEY` with a random value of at least 32 characters and set `AGENTDOCK_ADMIN_EMAIL` plus a password of at least 12 characters. First startup creates that administrator if needed. Existing non-admin accounts are promoted only when the configured password matches the account's current password.

2. Install dependencies and apply migrations:

    ```powershell
    python -m pip install -e .
    npm install
    alembic upgrade head
    ```

3. Start the API and frontend in separate terminals:

    ```powershell
    uvicorn backend.agentdock.main:app --reload --port 8000
    npm run dev
    ```

4. Open http://localhost:5173. The first startup seeds four subscription plans and the original MIT-licensed starter library; no network access is required.

5. Start the worker when you want queued imports, discovery and subscription expiry processed:

    ```powershell
    python -m backend.agentdock.worker
    ```

## Subscription plans

| Plan | Monthly | Annual | Seats |
|---|---:|---:|---:|
| Free | $0 | — | 1 |
| Developer | $3 | $30 | 1 |
| Duo | $5 | $50 | 2 |
| Small Team | $8 | $80 | 4 |
| Growth Team | $10 | $100 | 7 |

The default payment provider is manual invoicing: a customer receives an invoice reference and an administrator records the payment in the control center before entitlements are granted. Paddle, Flutterwave and UrubutoPay adapters are present but inactive until their credentials and webhooks are configured.

## API and MCP

- Health: `GET /api/health`
- OpenAPI: `/api/openapi.json`, interactive docs: `/api/docs`
- Search: `GET /api/v1/skills/search?q=dashboard`
- Retrieve: `POST /api/v1/skills/{slug}/retrieve`
- Catalogue: `GET /api/v1/skills/discovery`, `GET /api/v1/categories`, `GET /api/v1/communities`
- Marketplace: `GET /api/v1/marketplace/listings`, `POST /api/v1/marketplace/purchases`
- Account: `GET /api/v1/account/entitlements`, `GET /api/v1/account/billing`, `GET /api/v1/account/usage`
- Teams: `GET/POST /api/v1/teams`, `POST /api/v1/teams/{id}/invitations`
- Webhooks: `POST /api/v1/webhooks/payments/{paddle|flutterwave|urubutopay}`, `POST /api/v1/webhooks/github`
- MCP: `POST /mcp` with `Authorization: Bearer <API key>`

Create an API key in Integrations or use `POST /api/v1/auth/token`. The key is returned once. MCP tools include `search_skills`, `get_skill`, `get_skill_resource`, `list_skill_versions`, `browse_marketplace`, `list_my_purchases`, `check_subscription`, `get_usage`, `list_teams`, and collection helpers.

## CLI

```powershell
python -m pip install -e .
agentdock login --url http://localhost:8000
agentdock search "react dashboard"
agentdock get react-analytics-dashboard
agentdock plans
agentdock marketplace
agentdock teams
agentdock doctor
agentdock connect mcp
```

The CLI stores its token in `APPDATA/AgentDock/config.json` on Windows or `~/.config/AgentDock/config.json` elsewhere.

## Configuration

See `.env.example`. All settings use the `AGENTDOCK_` prefix.

Production essentials: `AGENTDOCK_ENV=production`, a unique 32+ character `AGENTDOCK_SECRET_KEY`, `AGENTDOCK_SESSION_SECURE_COOKIE=true` when the public URL is HTTPS (`false` for direct HTTP, otherwise browsers discard the session cookie), PostgreSQL `AGENTDOCK_DATABASE_URL`, exact `AGENTDOCK_FRONTEND_ORIGINS`, `AGENTDOCK_PUBLIC_URL`, `AGENTDOCK_REDIS_URL`, bootstrap admin credentials, and SMTP/payment/discovery credentials as needed.

## Tests and build

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
npm run build
```

Tests cover admission gates, path traversal, GitHub host validation, authentication and API keys, authorization, MCP, bulk imports, email flows, teams, marketplace entitlements, billing fulfilment, admin operations and first-run seeding.

## Deployment

See `docs/deployment.md`, `docs/oracle-deployment.md`, `docs/api.md`, `docs/admin-guide.md`, `docs/security.md` and `docs/backup-recovery.md`. Docker Compose runs PostgreSQL, Redis, a migration step, the web service and a separate worker. Place the web container behind a TLS reverse proxy and back up PostgreSQL plus the SkillVault volume.

## Oracle Cloud

The OCI CLI is installed locally and a `DEFAULT` profile is configured. `deploy/oracle/preflight.ps1` validates access; `deploy/oracle/deploy.ps1` prepares a compute instance with cloud-init. See `docs/oracle-deployment.md`. No instance has been launched.

## Project layout

- `backend/agentdock`: FastAPI application, domain modules, worker and vault
- `backend/migrations`: idempotent Alembic history
- `frontend`: React + Vite site and workspace
- `cli`: AgentDock command-line client
- `tests`: API and integration tests
- `docs`: API, integration, operations and security guides
