# AgentDock architecture

## Runtime

AgentDock currently uses a modular monolith:

- Web: React 19 and Vite. The built SPA is served by FastAPI; the development server proxies /api and /mcp.
- Application/API: FastAPI, Pydantic and SQLAlchemy 2. REST and MCP use the same user and role checks.
- Database: SQLite for local development, PostgreSQL for Docker deployments. Alembic records schema versions.
- SkillVault: filesystem or S3-compatible storage writes immutable version folders. Database rows hold manifests, checksums, source commits, licences and version references. Multi-host deployments should use shared object storage.
- Ingestion: PostgreSQL-backed import batches and repository jobs are processed by separate worker processes. `FOR UPDATE SKIP LOCKED` lets workers claim different jobs safely; lease expiry recovers work after a crash, and transient errors use exponential backoff. A batch may include 250 repositories and 5,000 selected folders.
- Request protection: Redis applies shared rate limits across API replicas in production. Local development uses a bounded in-process fallback.
- Sync: approved repositories are polled every six hours (2,000+ stars), daily (100+ stars) or weekly (below 100 stars).
- CLI: Python client that uses the REST API and downloads versioned resources without cloning a repository.

There is no AI inference dependency. PostgreSQL uses an indexed full-text document over skill metadata; local SQLite development uses bounded keyword matching. Results can be filtered by category or source community.

## Request flow

    Browser / coding agent / CLI
                 |
                 | cookie session or hashed bearer API key
                 v
               FastAPI
                 | shared authorization and retrieval rules
          +------+------+
          |             |
      PostgreSQL    Redis      SkillVault files/object storage
          |
   Import/sync queue ------> worker pool ------> GitHub API and raw file reads

REST, MCP and the CLI route retrieval through the same skill/version/licence checks. Imported scripts are untrusted content and are never executed by AgentDock.

## Data model

The initial migration creates:

- users, sessions, api_keys
- repositories, skills, skill_versions
- collections, collection_items, usage_events
- admission_decisions, trusted_publishers, audit_logs
- import_batches, synchronization_jobs

Foreign keys enforce ownership and delete behavior. Unique constraints prevent duplicate repository URLs, skill slugs, API key hashes, trusted publishers, collection items or skill versions.

Skill version rows are append-only at the application layer and contain source commit, content hash, file manifest and snapshot location. Each file is separately hashed. Snapshot directories are not overwritten by sync.

## Admission lifecycle

GitHub imports are read-only and host-validated. Repository metadata and a bounded Git tree identify skill folders. Each skill is fetched and evaluated on its own:

1. Popularity (15), source credibility (20), maintenance (20), quality (20), static security checks (15), licence (10).
2. The sum is compared with the starting threshold of 75. A non-trusted source below 100 stars stays in manual review even if its score is high.
3. A recognized licence on the strict redistribution allowlist and a clear static scan are mandatory before approval.
4. A high score means qualified, never automatically approved. An administrator decision and recorded reason are required.
5. A scan finding quarantines the skill. An administrator cannot bypass the licence or security gates.

Trusted publishers add credibility points but do not approve skills. This build does not yet expose all score weights as administrator-editable settings or monitor organizations automatically.

## MCP

POST /mcp accepts JSON-RPC initialize, tool-list, tool-call, ping and notification messages. It returns JSON responses; GET returns 405 because it does not offer an SSE stream. Origin is checked against configured frontend origins, and MCP clients must accept both JSON and event-stream responses. The server negotiates protocol versions 2025-03-26, 2025-06-18 and 2025-11-25.

Implemented tools: search_skills, get_skill, get_skill_resource, list_categories, list_skill_versions, get_skill_metadata, save_skill_to_collection, list_user_collections, check_subscription.
