# Deployment guide

## Docker Compose

1. Copy .env.example to .env.
2. Set AGENTDOCK_ENV=production, unique random values for AGENTDOCK_SECRET_KEY, POSTGRES_PASSWORD and REDIS_PASSWORD, a bootstrap administrator email and strong password, and the exact public HTTPS site origin in AGENTDOCK_FRONTEND_ORIGINS.
3. Set AGENTDOCK_SESSION_SECURE_COOKIE=true. Optionally set a read-only GitHub API token.
4. Create and start:

    docker compose up -d --build

Compose waits for PostgreSQL and Redis, applies Alembic migrations once, then starts the API/site and separate import/sync worker. The web port is bound to host loopback on port 8000; configure a host TLS reverse proxy to forward to it. Do not expose plain HTTP port 8000 to the public internet.

Workers each claim one job at a time. You can scale the same-host worker pool with `docker compose up -d --scale worker=4`. Claims are locked in PostgreSQL, and expired leases are returned to the queue. The Compose file publishes one API instance; for multiple API replicas, put replicas behind a load balancer and point all of them at the same PostgreSQL and Redis services.

Tune database capacity with `AGENTDOCK_DATABASE_POOL_SIZE`, `AGENTDOCK_DATABASE_MAX_OVERFLOW` and `AGENTDOCK_DATABASE_POOL_TIMEOUT_SECONDS`. Size the PostgreSQL connection limit for the sum of API and worker processes; the configured pool and overflow are per process. Tune shared per-IP request caps with `AGENTDOCK_REQUEST_RATE_LIMIT_PER_MINUTE` and `AGENTDOCK_AUTH_RATE_LIMIT_PER_MINUTE`. If many users share one proxy or NAT address, set limits for that combined traffic and trust only the actual proxy addresses.

The import API accepts at most 250 repositories and 5,000 selected folders per batch, and at most 500 selected folders for one repository. Each skill is capped at 100 files and 2 MB per file; a repository import is capped at 200 MB. For a very large GitHub repository, provide explicit skill paths: the importer falls back from GitHub's truncated repository tree to selected folder trees. An unselected full-repository import returns an actionable error when GitHub truncates the repository tree.

The frontend is built into the API image. Production traffic uses one origin for the SPA and API/MCP/docs.

## Health and logs

- Health check: /api/health
- Application logs: docker compose logs -f web
- Worker logs: docker compose logs -f worker
- Migration: docker compose run --rm migrate

Set alerts in the hosting environment for unhealthy database/web/worker containers and low disk space.

## Database migrations

For local development, run:

    alembic upgrade head

Back up the current database and SkillVault before applying a new migration. Schema revisions are in backend/migrations/versions/.

## Reverse proxy

Terminate TLS at a trusted proxy and forward to 127.0.0.1:8000. Preserve the external host and scheme. Cap request size, set request timeouts, and add proxy rate limits. Only trust forwarded headers from that proxy.

## Rollback

Stop web and worker containers, restore the PostgreSQL dump and SkillVault backup from the same recovery point, deploy the prior image, then start services. Do not roll back the schema independently of the application version unless that migration explicitly supports it.

## Environment reference

| Variable | Purpose |
|---|---|
| AGENTDOCK_ENV | development or production; production requires a strong secret |
| AGENTDOCK_SECRET_KEY | Deployment secret guard; keep unique and private |
| AGENTDOCK_ADMIN_EMAIL / AGENTDOCK_ADMIN_PASSWORD | Bootstrap the first administrator if absent |
| AGENTDOCK_DATABASE_URL | SQLite or PostgreSQL SQLAlchemy URL |
| AGENTDOCK_STORAGE_PATH | SkillVault directory shared by web and worker |
| AGENTDOCK_S3_BUCKET | Optional shared S3-compatible snapshot storage; recommended across hosts |
| AGENTDOCK_S3_REGION / AGENTDOCK_S3_ENDPOINT_URL | Object storage location and optional compatible endpoint |
| AGENTDOCK_S3_ACCESS_KEY_ID / AGENTDOCK_S3_SECRET_ACCESS_KEY | Optional object storage credentials; workload identity is preferred where available |
| AGENTDOCK_S3_PREFIX | Prefix for snapshot objects |
| AGENTDOCK_REDIS_URL | Shared production request limiter; Compose constructs it from REDIS_PASSWORD |
| AGENTDOCK_TRUSTED_PROXIES | Optional comma-separated proxy IPs/CIDRs whose forwarded client-IP headers are trusted |
| AGENTDOCK_GITHUB_TOKEN | Optional GitHub API token |
| AGENTDOCK_SESSION_SECURE_COOKIE | Must be true behind HTTPS |
| AGENTDOCK_FRONTEND_ORIGINS | Comma-separated exact trusted browser Origins |
| POSTGRES_PASSWORD | Compose PostgreSQL password; use a URL-safe random value |
| REDIS_PASSWORD | Compose Redis password; use a URL-safe random value |

## First run and seed data

On first startup the application seeds four subscription plans and sixteen original MIT-licensed starter skills (three premium listings). Seeding is idempotent and does not overwrite administrator edits. Set `AGENTDOCK_SEED_LIBRARY=false` if you want an empty catalogue. The worker also runs maintenance every ten minutes to expire subscriptions and execute scheduled GitHub discovery.

## Email, payments and webhooks

- Configure SMTP (`AGENTDOCK_SMTP_HOST`, `AGENTDOCK_SMTP_PORT`, credentials, `AGENTDOCK_SMTP_FROM`) before enabling `AGENTDOCK_REQUIRE_EMAIL_VERIFICATION`. Without SMTP, verification and reset tokens are logged and only returned in development responses.
- The default `AGENTDOCK_PAYMENT_PROVIDER=manual` is a real invoice workflow. Administrators record payments in the control center before entitlements are granted. Set `AGENTDOCK_MANUAL_BILLING_EMAIL` to the address customers should pay.
- To enable a hosted provider, set its API key and webhook secret and configure the webhook URL to `https://<origin>/api/v1/webhooks/payments/<provider>`. Paddle also needs price IDs in the `payment_prices` system setting. Webhooks are signature-verified and deduplicated.
- For GitHub push webhooks, set `AGENTDOCK_GITHUB_WEBHOOK_SECRET` and point the repository or organization webhook at `https://<origin>/api/v1/webhooks/github` with `application/json` content type.
- Set `AGENTDOCK_PUBLIC_URL` to the exact HTTPS origin so verification, invitation and checkout links are correct.

## Additional environment variables

| Variable | Purpose |
|---|---|
| AGENTDOCK_PUBLIC_URL | Public HTTPS origin used in emailed and checkout links |
| AGENTDOCK_SEED_LIBRARY | Seed the MIT starter library on first run (default true) |
| AGENTDOCK_SMTP_HOST / AGENTDOCK_SMTP_PORT / AGENTDOCK_SMTP_USER / AGENTDOCK_SMTP_PASSWORD / AGENTDOCK_SMTP_FROM | SMTP delivery |
| AGENTDOCK_REQUIRE_EMAIL_VERIFICATION | Require verified email for full access when SMTP is configured |
| AGENTDOCK_PAYMENT_PROVIDER | manual, paddle, flutterwave or urubutopay |
| AGENTDOCK_PAYMENT_CURRENCY / AGENTDOCK_MANUAL_BILLING_EMAIL / AGENTDOCK_PLATFORM_COMMISSION_BPS | Billing defaults |
| AGENTDOCK_PADDLE_API_KEY / AGENTDOCK_PADDLE_WEBHOOK_SECRET / AGENTDOCK_PADDLE_ENVIRONMENT | Paddle credentials |
| AGENTDOCK_FLUTTERWAVE_SECRET_KEY / AGENTDOCK_FLUTTERWAVE_WEBHOOK_HASH | Flutterwave credentials |
| AGENTDOCK_URUBUTOPAY_API_KEY / AGENTDOCK_URUBUTOPAY_WEBHOOK_SECRET / AGENTDOCK_URUBUTOPAY_CHECKOUT_URL | UrubutoPay credentials |
| AGENTDOCK_GITHUB_WEBHOOK_SECRET | HMAC secret for GitHub push webhooks |
| AGENTDOCK_FIRST_PARTY_OWNERS | Comma-separated GitHub owners whose unlicensed repositories may be marked OWNER-AUTHORIZED by the importer |
| AGENTDOCK_DISCOVERY_ENABLED / AGENTDOCK_DISCOVERY_INTERVAL_HOURS / AGENTDOCK_DISCOVERY_TOPICS / AGENTDOCK_DISCOVERY_KEYWORDS / AGENTDOCK_DISCOVERY_MIN_STARS / AGENTDOCK_DISCOVERY_PER_PAGE | Automated GitHub discovery defaults |
