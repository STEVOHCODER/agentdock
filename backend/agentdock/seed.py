"""Idempotent first-run data: plans, settings and the original AgentDock starter library.

Every starter skill is authored for AgentDock and licensed MIT. This gives a new
deployment a useful, legally clean catalogue and marketplace without importing
third-party repositories or relying on network access.
"""
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (MarketplaceListing, SecurityScan, Skill, SkillVersion, SubscriptionPlan, SystemSetting,
                     utcnow)
from .vault import save_snapshot

logger = logging.getLogger("agentdock.seed")


PLANS = [
    {
        "code": "free", "name": "Free", "description": "Discover and use the free community catalogue.",
        "price_cents": 0, "annual_price_cents": 0, "member_limit": 1, "sort_order": 0,
        "features": ["Public skill discovery", "Basic skill retrieval", "Basic MCP integration",
                     "Access to free community skills"],
    },
    {
        "code": "developer", "name": "Developer", "description": "A personal workspace with advanced discovery.",
        "price_cents": 300, "annual_price_cents": 3000, "member_limit": 1, "sort_order": 1,
        "features": ["Everything in Free", "Personal skill collections", "Advanced discovery and filters",
                     "Version preferences", "Personal workspace", "Priority support"],
    },
    {
        "code": "duo", "name": "Duo", "description": "Two seats with shared skills and purchases.",
        "price_cents": 500, "annual_price_cents": 5000, "member_limit": 2, "sort_order": 2,
        "features": ["Everything in Developer", "Up to 2 members", "Shared skill collections",
                     "Shared purchase history", "Team workspace", "Member management"],
    },
    {
        "code": "team", "name": "Small Team", "description": "Shared expertise for up to four people.",
        "price_cents": 800, "annual_price_cents": 8000, "member_limit": 4, "sort_order": 3,
        "features": ["Everything in Duo", "Up to 4 members", "Shared skill collections",
                     "Team workspace", "Shared purchase history", "Member management"],
    },
    {
        "code": "growth", "name": "Growth Team", "description": "A larger shared library with analytics.",
        "price_cents": 1000, "annual_price_cents": 10000, "member_limit": 7, "sort_order": 4,
        "features": ["Everything in Small Team", "Up to 7 members", "Shared team library",
                     "Team-wide skill management", "Usage analytics and priority support",
                     "Shared premium entitlements where licensed"],
    },
]

DEFAULT_DISCOVERY = {
    "enabled": True,
    "interval_hours": 24,
    "topics": ["agent-skills", "claude-skills", "ai-agent-skills", "codex-skills"],
    "keywords": ["agent skills", "SKILL.md"],
    "languages": [],
    "min_stars": 100,
    "per_page": 30,
    "last_run_at": None,
}


def _md(name: str, description: str, body: str, *, tags: str = "", version: str = "1.0.0") -> bytes:
    return f"""---
name: {name}
description: {description}
license: MIT
version: {version}
metadata:
  author: AgentDock Studio
  tags: {tags}
---

{body.strip()}
""".encode("utf-8")


STARTER_SKILLS = [
    {
        "slug": "react-analytics-dashboard", "name": "React Analytics Dashboard",
        "description": "Design and build clear, responsive React analytics dashboards with accessible charts, useful empty states and production-ready data boundaries.",
        "category": "Frontend", "technologies": ["React", "TypeScript", "Tailwind CSS", "Recharts"],
        "featured": True, "premium": False, "changelog": "Initial release with layout, chart and accessibility guidance.",
        "dependencies": ["React 18+", "A chart library such as Recharts or visx"],
        "permissions": ["Read access to the project source", "Permission to add UI components"],
        "reference": ("references/dashboard-checklist.md", b"""# Dashboard review checklist

- Every chart answers one question stated in its title or caption.
- KPI cards show a comparison, not a number in isolation.
- Loading, empty, partial and error states exist for each data source.
- Colour is never the only carrier of meaning.
- Tables remain usable at 320 px and with keyboard-only navigation.
- Date ranges and filters are reflected in the URL.
- Large series are aggregated before they reach the browser.
"""),
        "body": """
## When to use this skill

Use this when a task involves an analytics screen, admin dashboard, KPI overview or any UI whose main job is to help someone understand data. It is not a chart-library tutorial; it is a workflow for shipping a dashboard that survives real data.

## Workflow

1. **Write the questions first.** List the three to five decisions the screen should support. Each chart must map to one question. Delete decorative charts.
2. **Inspect the data contract.** Identify the shape, freshness, timezone, units and null behaviour of every series. Never infer a metric's definition from its column name.
3. **Choose the layout.** Use a 12-column grid with KPI cards on top, the primary trend next, then breakdowns. Keep the most important number visible without scrolling on a 1366 × 768 viewport.
4. **Build the data layer.** Put fetching in a typed hook or server loader. Handle loading, empty, partial and error states separately. Abort stale requests. Never render `NaN` or `undefined` as a value.
5. **Build the visual layer.** Use a restrained palette, one accent colour for the primary series and neutral tones for context. Format numbers with `Intl.NumberFormat`. Label units and time zones.
6. **Make it accessible.** Provide a text summary for every chart, use semantic headings, keep contrast at 4.5:1, and ensure filters and drill-downs work with a keyboard.
7. **Verify with realistic data.** Test zero rows, one row, a huge series, missing values, a slow response and an API failure. Check the layout at 320 px, 768 px and 1440 px.

## Quality bar

- Every card has a title, a value, a comparison and a time window.
- The page states when the data was last refreshed.
- Filters are shareable through the URL.
- Charts degrade to a table or summary when JavaScript-heavy rendering is unavailable.
- No client component fetches more rows than it can render.

## Common mistakes

- A wall of KPI cards with no hierarchy.
- Pie charts with more than five slices.
- Truncated axes that exaggerate change.
- Re-fetching the entire dashboard when one filter changes.
- Treating an empty array as an error or an error as an empty array.

## Output

Return the component structure, the data contract, the state matrix and a short list of the decisions you made. If the repository has an existing design system, reuse it instead of introducing a second one.
""",
    },
    {
        "slug": "nextjs-app-architecture", "name": "Next.js App Router Architecture",
        "description": "Structure a maintainable Next.js App Router application with clear server/client boundaries, caching, authentication and deployment-safe data access.",
        "category": "Frontend", "technologies": ["Next.js", "React", "TypeScript"],
        "featured": False, "premium": False, "changelog": "Initial release covering App Router boundaries and caching.",
        "dependencies": ["Next.js 14+", "React 18+"],
        "permissions": ["Read access to the application source", "Permission to add routes and server modules"],
        "reference": ("references/app-router-map.md", b"""# App Router decision map

| Need | Default choice |
|---|---|
| Data required before first paint | Server Component |
| Local interaction only | Client Component at the leaf |
| Mutations | Server Action or route handler with validation |
| Per-user data | Dynamic rendering and an explicit auth check |
| Public cached content | Static rendering with revalidation |
| Long-running work | Background job, not a request |
"""),
        "body": """
## When to use this skill

Use this for a new Next.js App Router application or when an existing app has unclear server/client boundaries, duplicated data fetching or fragile caching.

## Workflow

1. **Map the routes.** Write the route tree with its loading, error and not-found states before writing components.
2. **Draw the server boundary.** Fetch data in Server Components by default. Add `"use client"` only at the smallest interactive leaf. Never pass secrets or raw database clients into a Client Component.
3. **Define the data layer.** Put queries in `lib/data/*` with typed inputs and outputs. Use one authorization check per entry point, not per component.
4. **Choose caching deliberately.** For each route, state whether it is static, revalidated or dynamic. User-specific data must be dynamic and must not be cached across users.
5. **Handle mutations.** Validate input with a schema, authorize, write in a transaction, then revalidate the exact tags or paths affected.
6. **Design failure states.** Add `error.tsx`, `not-found.tsx` and loading skeletons that preserve layout. Do not show a blank screen while a slow query runs.
7. **Verify the build.** Run the production build, check for accidental client bundles, and inspect the route output for static/dynamic behaviour.

## Quality bar

- No server-only module is imported by a Client Component.
- Every mutation has server-side validation and authorization.
- Cached data has an explicit invalidation strategy.
- Images use the framework image component or documented dimensions.
- Environment variables are validated at startup.

## Common mistakes

- Marking an entire page as a Client Component to use one button.
- Fetching the same data in a layout and a page without deduplication.
- Caching personalized responses.
- Using middleware as the only authorization layer.

## Output

Provide the route tree, the server/client boundary, the cache policy and the failure states. Note any migration steps for an existing app.
""",
    },
    {
        "slug": "production-api-design", "name": "Production API Design",
        "description": "Design and review production HTTP APIs with stable contracts, validation, pagination, idempotency, authorization and observable failure modes.",
        "category": "Backend", "technologies": ["REST", "OpenAPI", "Node.js", "Python"],
        "featured": True, "premium": False, "changelog": "Initial release with contract and reliability checklists.",
        "dependencies": ["An HTTP framework", "A schema validation library", "A database"],
        "permissions": ["Read access to API source", "Permission to update API contracts and tests"],
        "reference": ("references/api-contract-checklist.md", b"""# API contract checklist

- Resource names are plural nouns; verbs live in the operation.
- Every list endpoint has a documented limit and cursor or offset.
- Every error uses the same envelope and a stable machine code.
- 401 means unauthenticated; 403 means authenticated but not allowed.
- Mutations validate input and are safe to retry when idempotency is claimed.
- Timestamps are ISO 8601 UTC.
- Money is an integer minor unit plus a currency code.
- Deprecations have a date and a migration path.
"""),
        "body": """
## When to use this skill

Use this when adding endpoints, reviewing an API contract, or preparing an API for external consumers. It applies to REST and RPC-style HTTP APIs.

## Workflow

1. **Model resources.** Name resources after domain nouns. Keep ownership and tenancy explicit. Avoid endpoints that expose database tables directly.
2. **Write the contract first.** For each endpoint document method, path, auth, request schema, success response, error codes, pagination and rate limits.
3. **Validate at the boundary.** Reject unknown or malformed input with a 422 and a field-level explanation. Never pass raw request objects into the data layer.
4. **Authorize server-side.** Check the caller's identity and resource ownership in the same transaction as the write. A hidden button is not authorization.
5. **Make writes safe.** Use transactions for multi-row changes. Support idempotency keys for retried creates and payment operations. Return the existing result for a duplicate key.
6. **Bound responses.** Paginate lists, cap page size, avoid unbounded joins, and return stable ordering. Use sparse fields or resource endpoints for large payloads.
7. **Observe the endpoint.** Log request id, route, status, latency and actor id without secrets. Emit metrics for latency and error rate. Add a health signal for critical dependencies.
8. **Test the contract.** Cover success, validation, unauthorized, forbidden, not found, conflict, rate limit and provider failure. Add a test for idempotent replay.

## Quality bar

- The OpenAPI document matches the implementation.
- Error responses never leak stack traces, SQL or provider secrets.
- List endpoints return a total or a next cursor.
- Monetary values use integer minor units.
- Breaking changes require a version or a documented migration window.

## Common mistakes

- Returning 200 with `{ "error": ... }`.
- Trusting a client-supplied user id.
- Retrying a payment create without an idempotency key.
- Unbounded `limit` parameters.
- Mixing authentication failures and authorization failures.

## Output

Return the endpoint table, schemas, status-code matrix, authorization rules and a test list. Flag any contract that cannot be implemented safely with the current data model.
""",
    },
    {
        "slug": "python-data-analysis", "name": "Python Data Analysis",
        "description": "Turn raw tabular data into a reproducible Python analysis with clean inputs, validated assumptions, useful visuals and an honest written conclusion.",
        "category": "Data Analysis", "technologies": ["Python", "pandas", "Jupyter", "Matplotlib"],
        "featured": False, "premium": False, "changelog": "Initial release with reproducibility and data-quality guidance.",
        "dependencies": ["Python 3.10+", "pandas", "matplotlib or plotly"],
        "permissions": ["Read access to the dataset", "Permission to create analysis files"],
        "reference": ("references/analysis-log.md", b"""# Analysis log template

1. Question:
2. Data source and extraction time:
3. Grain (one row = ?):
4. Known quality issues:
5. Cleaning decisions and why:
6. Metric definitions:
7. Findings with uncertainty:
8. What would change the conclusion:
"""),
        "body": """
## When to use this skill

Use this for exploratory analysis, reporting, cohort analysis, forecasting inputs or any task where a dataset must become a defensible conclusion.

## Workflow

1. **State the question and decision.** Write what action the analysis will inform. If no decision depends on it, ask why it is being done.
2. **Inspect before transforming.** Check row count, grain, dtypes, duplicate keys, null rates, date ranges, units and outliers. Save the raw file or a hash.
3. **Build a reproducible pipeline.** Use a script or notebook with deterministic ordering. Set random seeds. Avoid manual spreadsheet edits that cannot be reproduced.
4. **Clean with a log.** For each cleaning decision record the rule, the number of affected rows and the reason. Never silently drop outliers.
5. **Validate assumptions.** Check joins for fan-out, compare totals before and after aggregation, and test a small hand-computed sample.
6. **Analyze.** Prefer simple, interpretable statistics. Report denominators, confidence intervals or ranges where relevant. Separate correlation from causation.
7. **Visualize for the question.** Label axes and units, start bar charts at zero, show sample sizes, and avoid chart types that hide distribution.
8. **Write the conclusion.** Lead with the answer, then evidence, limitations and the next check. Include the code path and data snapshot.

## Quality bar

- A second person can rerun the analysis from a clean environment.
- Every metric has a written definition.
- Nulls and duplicates are handled explicitly.
- Charts have titles, units and source notes.
- The conclusion states uncertainty and does not overclaim.

## Common mistakes

- Joining on a non-unique key and inflating totals.
- Comparing averages across groups with different distributions.
- Dropping nulls without checking whether they are informative.
- Using a timezone-naive date column for daily aggregation.
- Reporting a percentage without its denominator.

## Output

Return the question, data contract, cleaning log, metric definitions, findings, limitations and the exact command to reproduce the analysis.
""",
    },
    {
        "slug": "postgres-performance", "name": "PostgreSQL Performance Tuning",
        "description": "Diagnose slow PostgreSQL queries and schema problems with evidence, then apply safe indexes, query rewrites and configuration changes.",
        "category": "Databases", "technologies": ["PostgreSQL", "SQL", "EXPLAIN ANALYZE"],
        "featured": False, "premium": False, "changelog": "Initial release with a measurement-first tuning workflow.",
        "dependencies": ["PostgreSQL 14+", "Access to query statistics"],
        "permissions": ["Read access to schema and query plans", "Change approval for indexes and migrations"],
        "reference": ("references/postgres-diagnostics.sql", b"""-- Find expensive statements (requires pg_stat_statements)
SELECT calls, round(total_exec_time::numeric, 2) AS total_ms,
       round(mean_exec_time::numeric, 2) AS mean_ms, rows, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;

-- Check table and index bloat signals
SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
"""),
        "body": """
## When to use this skill

Use this when a PostgreSQL-backed endpoint is slow, a migration needs an index, or a database is approaching a capacity limit. Do not tune from intuition; measure first.

## Workflow

1. **Define the symptom.** Record the endpoint, query, latency target, row counts and time window. Separate cold-start latency from steady-state latency.
2. **Capture the plan.** Run `EXPLAIN (ANALYZE, BUFFERS)` on the real query with realistic parameters. Note actual rows versus estimated rows and the slowest node.
3. **Check the data model.** Verify keys, constraints, cardinality and column types. A missing unique constraint or a text date column often matters more than an index.
4. **Fix the biggest cost.** Prefer query rewrites and correct indexes over global configuration changes. For composite indexes, match the equality columns first and the range column last.
5. **Validate the index.** Confirm it is used, measure write overhead, and check whether an existing index already covers the query. Create indexes concurrently in production.
6. **Review locking and migrations.** Use `lock_timeout` and `statement_timeout`. Avoid long transactions and table rewrites during peak traffic.
7. **Re-measure.** Compare p50 and p95 latency, buffers, rows and plan shape. Keep the before/after evidence.

## Quality bar

- Every recommendation cites a plan or metric.
- New indexes have a named query and a rollback path.
- Migrations are safe to run online.
- No `SELECT *` in hot paths.
- Connection pooling is sized for the database, not just the app.

## Common mistakes

- Adding an index before checking the query's row estimates.
- Using `OFFSET` for deep pagination.
- Running `VACUUM FULL` during traffic.
- Storing timestamps without a timezone.
- Changing `work_mem` globally to fix one query.

## Output

Return the diagnosis, evidence, proposed change, migration SQL, expected impact, rollback and verification query.
""",
    },
    {
        "slug": "docker-deployment-hardening", "name": "Docker Deployment Hardening",
        "description": "Harden a container deployment with minimal images, non-root users, health checks, secret handling, resource limits and safe rollout procedures.",
        "category": "DevOps", "technologies": ["Docker", "Compose", "Kubernetes", "CI/CD"],
        "featured": True, "premium": False, "changelog": "Initial release with a production readiness checklist.",
        "dependencies": ["Docker Engine", "A container registry"],
        "permissions": ["Access to container configuration", "Permission to change deployment manifests"],
        "reference": ("references/container-checklist.md", b"""# Container production checklist

- Pinned base image digest or minor version.
- Multi-stage build; no compilers in the runtime image.
- Non-root user with a fixed UID.
- Read-only root filesystem where possible.
- Health check and graceful shutdown handler.
- Secrets injected at runtime, never baked into layers.
- CPU and memory requests/limits set.
- Logs to stdout/stderr with no secrets.
- Backups and rollback tested, not just documented.
"""),
        "body": """
## When to use this skill

Use this before exposing a containerized service to production, or when reviewing a Dockerfile and Compose/Kubernetes manifest.

## Workflow

1. **Inspect the image.** Identify the base, build stages, final user, exposed ports and entrypoint. Remove build tools, package caches and source maps from the runtime layer.
2. **Reduce attack surface.** Run as a non-root user, drop Linux capabilities, use a read-only root filesystem where practical, and mount only required writable paths.
3. **Handle secrets.** Inject secrets at runtime from the platform secret store. Never copy `.env` files, keys or tokens into an image layer.
4. **Set health and lifecycle.** Add a readiness check for dependencies and a liveness check for the process. Handle `SIGTERM`, stop accepting traffic, finish in-flight work and exit within the grace period.
5. **Bound resources.** Set CPU and memory requests and limits. Size connection pools for the number of replicas. Add disk and log rotation limits.
6. **Make delivery reproducible.** Pin versions, scan the image, sign or attest it where supported, and deploy immutable tags or digests.
7. **Prepare recovery.** Document rollback, database migration order, backup restore and a tested smoke check.

## Quality bar

- The image runs as non-root.
- The app starts without a writable working directory.
- Health checks reflect real dependency state.
- Secrets are absent from image history.
- A failed migration stops the rollout.

## Common mistakes

- Using `latest` in production.
- Running migrations from every replica.
- Ignoring `SIGTERM` and waiting for a forced kill.
- Publishing the database port publicly.
- Baking environment-specific configuration into the image.

## Output

Return the Dockerfile/manifest changes, a risk table, the rollout and rollback commands, and the checks that still require human verification.
""",
    },
    {
        "slug": "ai-agent-tool-design", "name": "AI Agent Tool Design",
        "description": "Design safe, reliable tools for AI coding agents with narrow contracts, explicit permissions, bounded outputs and recoverable errors.",
        "category": "AI Engineering", "technologies": ["MCP", "LLM tool use", "TypeScript", "Python"],
        "featured": True, "premium": False, "changelog": "Initial release covering tool contracts and safety.",
        "dependencies": ["An MCP or tool-calling SDK"],
        "permissions": ["Access to tool definitions", "Permission to update agent-facing APIs"],
        "reference": ("references/tool-contract-template.md", b"""# Tool contract

- Name:
- One-sentence purpose:
- Inputs (types, bounds, defaults):
- Outputs (shape, size bound):
- Side effects:
- Authorization check:
- Retry semantics:
- Failure messages the agent can act on:
- Examples of valid and invalid calls:
"""),
        "body": """
## When to use this skill

Use this when exposing an operation to an AI agent through MCP, function calling or a plugin. The goal is a tool that is easy to call correctly and hard to misuse.

## Workflow

1. **Start from the user task.** Write one sentence describing the outcome. If the tool needs a paragraph, split it.
2. **Define a narrow contract.** Use explicit typed inputs with bounds and defaults. Avoid free-form SQL, shell strings or arbitrary URLs unless the product genuinely requires them and can sandbox them.
3. **State side effects.** Mark read-only versus mutating tools. Require confirmation for destructive or costly operations. Make mutating tools idempotent where possible.
4. **Authorize inside the tool.** Resolve the caller from the transport credential. Never accept a user id from the model. Apply the same permissions as the REST API.
5. **Bound the output.** Return a small structured payload with pagination or resource references. Truncate with a clear marker, not a silent cut.
6. **Write actionable errors.** Return a stable code and a human-readable next step. Distinguish invalid input, not found, permission denied and transient failure.
7. **Test model behaviour.** Try ambiguous prompts, missing arguments, oversized inputs and repeated calls. Confirm the agent can recover without guessing.
8. **Document examples.** Provide one valid call and one invalid call per tool.

## Quality bar

- Tool names are verbs with clear nouns.
- Every input has a type and a bound.
- Read-only tools have no side effects.
- The output fits comfortably in a model context window.
- Errors tell the agent what to do next.

## Common mistakes

- One tool that does everything.
- Trusting a model-supplied tenant id.
- Returning an unbounded file or query result.
- Hiding a permission failure behind a generic error.
- Executing imported code in the API process.

## Output

Return the tool list with contracts, permission rules, size bounds, error codes and test cases. Flag any operation that should not be exposed to an agent.
""",
    },
    {
        "slug": "technical-documentation", "name": "Technical Documentation",
        "description": "Write accurate, task-oriented technical documentation with a clear audience, runnable examples, prerequisites and maintenance hooks.",
        "category": "Documentation", "technologies": ["Markdown", "OpenAPI", "Docs-as-code"],
        "featured": False, "premium": False, "changelog": "Initial release with a reader-first documentation workflow.",
        "dependencies": ["A Markdown editor or docs site"],
        "permissions": ["Read access to the product", "Permission to update docs"],
        "reference": ("references/doc-review.md", b"""# Documentation review

- Who is the reader and what are they trying to do?
- Is the first paragraph the outcome, not the history?
- Can every command be copied and run?
- Are prerequisites and expected output shown?
- Are failure cases and next steps covered?
- Is there an owner and a review date?
- Are screenshots current and necessary?
"""),
        "body": """
## When to use this skill

Use this for READMEs, setup guides, API references, runbooks, onboarding docs and release notes.

## Workflow

1. **Name the reader.** Write one sentence: "This is for a backend developer who has Python installed and wants to add authentication in 15 minutes."
2. **Lead with the outcome.** State what the reader will accomplish and what they need before starting.
3. **Order by the reader's path.** Prerequisites → shortest working example → explanation → variations → troubleshooting → reference.
4. **Make examples runnable.** Use real commands, realistic placeholders and expected output. Test every command in a clean environment.
5. **Explain the why briefly.** A short reason helps readers adapt the example. Link to deeper material instead of expanding every branch.
6. **Document failure.** Include the most common error messages and what to do. Do not hide limitations.
7. **Add maintenance hooks.** Include an owner, last-reviewed date and links to the source of truth. Remove screenshots that will drift.

## Quality bar

- The first screen tells the reader whether the page is for them.
- Commands are copy-pasteable and safe.
- Secrets are placeholders, never real values.
- Every link resolves.
- The document does not contradict the product UI.

## Common mistakes

- Starting with architecture before showing a working example.
- Using "simply" for a multi-step process.
- Documenting an aspirational feature as if it exists.
- Screenshots with unreadable text.
- No troubleshooting section.

## Output

Return the document, the commands you tested, the unresolved questions and the review date.
""",
    },
    {
        "slug": "playwright-e2e-testing", "name": "Playwright End-to-End Testing",
        "description": "Build reliable Playwright end-to-end tests with stable selectors, isolated data, meaningful assertions and CI-friendly diagnostics.",
        "category": "Testing", "technologies": ["Playwright", "TypeScript", "CI"],
        "featured": False, "premium": False, "changelog": "Initial release with flake prevention and CI guidance.",
        "dependencies": ["Node.js 18+", "Playwright"],
        "permissions": ["Read access to the web app", "Permission to add test files"],
        "reference": ("references/e2e-test-plan.md", b"""# E2E test plan

Critical journeys:
1. Sign up, verify, sign in, sign out.
2. Search, open a skill, retrieve it.
3. Save to a collection and remove it.
4. Connect an agent with an API key.
5. Admin imports, reviews and approves a skill.
6. Purchase a premium skill and retrieve it.
7. Invite a teammate and accept the invitation.

For each journey: setup, action, assertion, cleanup, failure diagnostic.
"""),
        "body": """
## When to use this skill

Use this when adding browser tests for a critical user journey, replacing brittle tests, or setting up end-to-end coverage in CI.

## Workflow

1. **Choose journeys, not pages.** Test the outcomes users depend on: sign in, retrieve a skill, purchase, invite a teammate.
2. **Create isolated data.** Each test creates its own user or fixture with a unique suffix. Never depend on a shared production-like account.
3. **Use role and label selectors.** Prefer `getByRole`, `getByLabel` and visible text. Add `data-testid` only when no accessible selector exists.
4. **Wait on state, not time.** Use web-first assertions (`toBeVisible`, `toHaveURL`). Remove arbitrary sleeps.
5. **Assert the meaningful result.** Check the retrieved skill content, entitlement state or persisted record, not just that a toast appeared.
6. **Capture diagnostics.** On failure, keep a trace, screenshot and console log. Use `trace: 'retain-on-failure'` in CI.
7. **Run in parallel safely.** Isolate storage state, database records and email tokens. Avoid tests that mutate global settings.
8. **Stabilize CI.** Pin the browser version, start dependencies with health checks, and fail with a readable report.

## Quality bar

- A failing test points to a user-visible problem.
- No test depends on another test's order.
- No hardcoded waits.
- Secrets come from the environment.
- Destructive tests never run against production.

## Common mistakes

- Using CSS selectors tied to layout classes.
- Testing implementation details instead of outcomes.
- Sharing one account across parallel tests.
- Asserting on a toast that disappears.
- Ignoring the first flaky failure.

## Output

Return the journey list, fixtures, selectors, assertions and CI configuration. Note any gap that requires a unit or integration test instead.
""",
    },
    {
        "slug": "ui-ux-review", "name": "UI/UX Design Review",
        "description": "Review an interface for clarity, hierarchy, accessibility and conversion, then produce prioritized, implementable design fixes.",
        "category": "UI/UX Design", "technologies": ["Figma", "Accessibility", "Design systems"],
        "featured": False, "premium": False, "changelog": "Initial release with a structured review rubric.",
        "dependencies": ["Screenshots or access to the interface"],
        "permissions": ["Read access to the UI", "Permission to propose design changes"],
        "reference": ("references/ux-review-rubric.md", b"""# UX review rubric

- First impression: what is this, who is it for, what do I do next?
- Hierarchy: one primary action per screen.
- Copy: specific, human, no filler.
- States: loading, empty, error, success, disabled, permission denied.
- Accessibility: contrast, focus, labels, keyboard, motion.
- Responsiveness: 320, 768, 1024, 1440.
- Trust: pricing, privacy, security and support are findable.
"""),
        "body": """
## When to use this skill

Use this for a landing page, dashboard, onboarding flow, pricing page or any screen that must communicate and convert.

## Workflow

1. **State the job of the screen.** Write the one action the screen should drive. If there are three equal primary actions, the hierarchy is broken.
2. **Review the first five seconds.** Identify the value proposition, audience and next step. Remove anything that competes with them.
3. **Audit hierarchy.** Check type scale, spacing, contrast and grouping. The most important element should be obvious without reading every word.
4. **Review every state.** Loading, empty, error, success, disabled and permission-denied states must be designed, not left to the browser.
5. **Check accessibility.** Contrast, focus order, keyboard reachability, labels, error association and reduced motion. Do not rely on colour alone.
6. **Test responsiveness.** Look for overflow, cramped tap targets, hidden actions and unreadable tables at 320 px.
7. **Prioritize fixes.** Label each issue as blocker, high, medium or polish, with the user impact and a concrete change.

## Quality bar

- One primary action per screen.
- Copy is specific and free of generic AI language.
- Every interactive element has a visible focus state.
- Empty states explain what to do next.
- Pricing and trust information are easy to find.

## Common mistakes

- Decorative gradients competing with the headline.
- Too many accent colours.
- Placeholder-only labels.
- A modal that traps keyboard focus incorrectly.
- Mobile navigation that hides the primary action.

## Output

Return a prioritized list: issue, evidence, user impact, recommended change and acceptance check. Include a short "what is working" section so the team knows what to preserve.
""",
    },
    {
        "slug": "gis-spatial-workflows", "name": "GIS and Spatial Workflows",
        "description": "Build reliable GIS workflows with correct coordinate systems, validated geometries, spatial indexes and clear map communication.",
        "category": "GIS and Engineering", "technologies": ["PostGIS", "QGIS", "GeoJSON", "Python"],
        "featured": False, "premium": False, "changelog": "Initial release with CRS and geometry validation guidance.",
        "dependencies": ["PostGIS or a GIS library such as GeoPandas"],
        "permissions": ["Read access to spatial data", "Permission to create spatial tables or maps"],
        "reference": ("references/gis-checks.sql", b"""-- PostGIS sanity checks
SELECT ST_SRID(geom) AS srid, count(*) FROM parcels GROUP BY ST_SRID(geom);
SELECT count(*) FROM parcels WHERE NOT ST_IsValid(geom);
SELECT count(*) FROM parcels WHERE ST_IsEmpty(geom);
CREATE INDEX IF NOT EXISTS parcels_geom_gix ON parcels USING GIST (geom);
"""),
        "body": """
## When to use this skill

Use this for maps, spatial joins, routing, boundary analysis, parcel data, environmental layers or any dataset with coordinates.

## Workflow

1. **Declare the coordinate reference system.** Record the CRS of every input. Transform to a projected CRS for distance and area calculations; keep geographic coordinates for display.
2. **Validate geometry.** Check for invalid rings, self-intersections, empty geometries, duplicate vertices and mixed SRIDs. Repair with a documented method.
3. **Inspect the grain.** One row per parcel, address or sensor? Confirm the key before joining. Spatial joins can fan out.
4. **Build a spatial index.** Use GiST in PostGIS or the equivalent in the chosen engine. Filter with a bounding box before an expensive exact predicate.
5. **Compute with the right units.** Never calculate metres from degrees. Document the projection and the units of every output.
6. **Design the map.** Include a scale bar, north arrow where relevant, legend, source and timestamp. Use colour-blind-safe classes and a basemap that does not overpower the data.
7. **Validate against ground truth.** Compare a sample with known locations or an independent source. Check total area and boundary sums.

## Quality bar

- Every layer has a declared CRS.
- Invalid geometries are repaired or excluded with a count.
- Spatial predicates are backed by an index.
- Distances and areas state their units.
- The map has a source and a timestamp.

## Common mistakes

- Mixing EPSG:4326 and a projected CRS in one calculation.
- Using `ST_Intersects` without a bounding-box prefilter on large tables.
- Joining points to polygons without checking duplicates.
- Rendering every feature at every zoom level.
- Publishing precise locations without a privacy review.

## Output

Return the data contract, CRS decisions, validation report, spatial SQL, map specification and accuracy checks.
""",
    },
    {
        "slug": "automation-workflows", "name": "Automation Workflows",
        "description": "Design dependable business automations with explicit triggers, idempotent steps, retries, human approval and observable failures.",
        "category": "Automation", "technologies": ["Webhooks", "Queues", "Zapier", "Python"],
        "featured": False, "premium": False, "changelog": "Initial release with reliability and approval patterns.",
        "dependencies": ["A workflow engine or queue", "Access to the connected services"],
        "permissions": ["Access to integration credentials", "Approval to create automations"],
        "reference": ("references/automation-blueprint.md", b"""# Automation blueprint

- Trigger and source of truth:
- Steps and side effects:
- Idempotency key:
- Retry policy and dead-letter handling:
- Human approval point:
- Rollback or compensation:
- Alert destination:
- Test cases: duplicate event, out-of-order event, provider timeout, permission failure.
"""),
        "body": """
## When to use this skill

Use this when connecting services, replacing a manual recurring task, or reviewing an automation that touches money, customers or production systems.

## Workflow

1. **Write the trigger and outcome.** Name the event source and the final observable result. Identify the source of truth.
2. **Map the steps.** For each step list inputs, side effects, timeout and failure behaviour. Mark irreversible steps.
3. **Make it idempotent.** Store the provider event id or a deterministic key. On replay, return the existing result instead of repeating the side effect.
4. **Choose retry semantics.** Retry transient failures with exponential backoff and jitter. Do not retry validation or permission failures. Route exhausted jobs to a dead-letter queue with an alert.
5. **Add human approval where needed.** Payments, deletions, bulk emails and permission changes should require an explicit approval or a bounded preview.
6. **Handle order and duplicates.** Events may arrive twice or out of order. Use timestamps or version numbers and reconcile.
7. **Observe the workflow.** Log the correlation id, step, attempt and outcome. Emit an alert when a job is stuck or a dead-letter queue grows.
8. **Test the unhappy path.** Duplicate event, provider timeout, revoked credential, malformed payload and partial completion.

## Quality bar

- Every side effect is idempotent or compensated.
- Credentials are scoped and rotated.
- Failures are visible to an owner.
- A human can pause the automation.
- Test mode does not touch real customers.

## Common mistakes

- Triggering on a mutable event with no version.
- Retrying a charge without an idempotency key.
- Sending a success message before the downstream write commits.
- Storing credentials in the workflow definition.
- No dead-letter queue.

## Output

Return the trigger, step table, idempotency keys, retry policy, approval points, alerts and test cases.
""",
    },
    {
        "slug": "code-review-checklist", "name": "Code Review Checklist",
        "description": "Review a change for correctness, security, maintainability, performance and tests, and produce specific, respectful, actionable feedback.",
        "category": "Development", "technologies": ["Git", "Testing", "Security"],
        "featured": False, "premium": False, "changelog": "Initial release with a severity-based review method.",
        "dependencies": ["Access to the diff and repository context"],
        "permissions": ["Read access to the repository", "Permission to comment on the change"],
        "reference": ("references/review-severity.md", b"""# Review severity

- Blocker: data loss, security hole, broken build, incorrect money movement.
- High: likely production bug, missing authorization, unhandled failure.
- Medium: maintainability or performance issue with a clear fix.
- Low: naming, style or documentation.
- Nit: optional preference; label it clearly.
"""),
        "body": """
## When to use this skill

Use this when reviewing a pull request, preparing a change for review, or auditing a risky diff.

## Workflow

1. **Read the intent.** Read the description and linked issue before the diff. If the intent is unclear, ask for it instead of guessing.
2. **Understand the blast radius.** Identify affected users, data, money, permissions and external services. Check migrations and configuration.
3. **Review correctness first.** Trace the main path and edge cases. Look for nulls, empty collections, time zones, concurrency and partial failure.
4. **Review security.** Check authorization on every new entry point, input validation, secret handling, injection surfaces and logging of sensitive data.
5. **Review tests.** Confirm the tests fail without the change and cover the risky path. Flag assertions that only check status codes or mocks.
6. **Review maintainability.** Look for duplicated logic, unclear names, hidden coupling and unnecessary abstractions. Match the surrounding style.
7. **Label severity.** Use blocker, high, medium, low or nit. Explain the impact and suggest a concrete fix. Praise good decisions.
8. **Verify the build.** Run the relevant tests and lint where possible. Do not approve a change you could not evaluate.

## Quality bar

- Comments are specific and actionable.
- Blockers are separated from preferences.
- Security and data-loss risks are never downgraded to nits.
- The review does not demand unrelated refactors.
- Approval means you would be comfortable shipping it.

## Common mistakes

- Reviewing only the diff and missing surrounding context.
- Approving because tests pass while authorization is missing.
- Bikeshedding style while a blocker remains.
- Asking for a rewrite instead of a targeted fix.
- Not checking migration rollback.

## Output

Return a summary, blocker/high/medium/low findings with file references, test gaps and a clear approve/request-changes recommendation.
""",
    },
    {
        "slug": "premium-react-dashboard-patterns", "name": "Advanced React Dashboard Patterns",
        "description": "A premium pattern library for complex React dashboards: URL-driven filters, virtualized tables, streaming metrics, optimistic updates and resilient chart states.",
        "category": "Frontend", "technologies": ["React", "TypeScript", "TanStack Query", "TanStack Table"],
        "featured": True, "premium": True, "price_cents": 1200,
        "changelog": "Initial premium release: advanced state, performance and resilience patterns.",
        "dependencies": ["React 18+", "TanStack Query", "TanStack Table"],
        "permissions": ["Read access to the project source", "Permission to add dependencies"],
        "reference": ("references/advanced-patterns.md", b"""# Advanced dashboard patterns

- URL state: filters, sort, page, date range, comparison window.
- Query keys: include every server input; use structural sharing.
- Tables: virtualization for 500+ rows, sticky header, column visibility persisted.
- Streaming: render a stable skeleton, merge partial payloads, show staleness.
- Optimistic updates: snapshot, apply, rollback on error, reconcile on settle.
- Charts: cap points, downsample, show gaps for missing data, expose a table fallback.
"""),
        "body": """
## When to use this skill

Use this when a dashboard has outgrown a single fetch and a few cards: many filters, large tables, live data, multiple user roles or expensive charts.

## Workflow

1. **Make the URL the source of truth.** Serialize filters, sort, pagination, date range and comparison into search params. Validate and clamp them on read.
2. **Design query keys.** Include every input that changes the response. Separate summary and detail queries. Use prefetch for the next likely view.
3. **Handle partial data.** Render each panel independently. One failed panel must not blank the page. Show a timestamp and a retry action per panel.
4. **Virtualize large tables.** Keep the header sticky, preserve focus, and expose a non-virtualized print/export path. Persist column visibility per user.
5. **Use optimistic updates carefully.** Snapshot the previous state, apply the change, roll back on failure, and reconcile with the server response. Never optimistically confirm money movement.
6. **Bound chart rendering.** Downsample or aggregate large series, cap tooltip payloads, and provide a data table for accessibility.
7. **Instrument the experience.** Measure time to first meaningful panel, query error rate and interaction latency. Log slow queries without sensitive payloads.
8. **Test the hard states.** Slow network, one failing endpoint, empty comparison period, 10,000 rows, stale permissions and a cancelled request.

## Quality bar

- Every panel is independently recoverable.
- Filters survive refresh and can be shared.
- Tables remain keyboard-navigable at scale.
- No layout shift when data arrives.
- Permissions are checked server-side per panel.

## Common mistakes

- One global loading spinner for six independent queries.
- Recreating query keys on every render.
- Rendering 50,000 SVG points.
- Optimistically updating a destructive action.
- Hiding a permission error as an empty chart.

## Output

Return the state model, query-key table, component boundaries, performance budgets and the resilience test matrix.
""",
    },
    {
        "slug": "premium-api-security-audit", "name": "Enterprise API Security Audit",
        "description": "A premium, evidence-driven API security review covering authentication, authorization, tenancy, injection, SSRF, secrets, rate limits and audit trails.",
        "category": "Backend", "technologies": ["OWASP ASVS", "REST", "OAuth", "Security"],
        "featured": True, "premium": True, "price_cents": 1500,
        "changelog": "Initial premium release with a full audit worksheet.",
        "dependencies": ["Access to API source and configuration", "A test environment"],
        "permissions": ["Read access to source", "Written authorization for security testing"],
        "reference": ("references/api-security-worksheet.md", b"""# API security worksheet

## Identity
- Session cookie: HttpOnly, Secure, SameSite; rotation on login.
- API keys: hashed at rest, scoped, revocable, last-used tracking.
- Password reset: single-use, expiring, no account enumeration.

## Authorization
- Every object read/write checks ownership or team role.
- Admin routes check role server-side, not in the UI.
- Tenant id is never accepted from the client without verification.

## Input and output
- Schema validation on every mutation.
- Parameterized queries only.
- SSRF allowlist for outbound URLs.
- File type, size and content validation.
- No secrets or stack traces in responses or logs.

## Abuse
- Per-IP and per-account rate limits.
- Idempotency on payment and create operations.
- Webhook signature verification and replay protection.
- Audit log for privileged actions.
"""),
        "body": """
## When to use this skill

Use this before exposing an API to customers, after a major auth change, or when preparing for a security review. Only test systems you are authorized to test.

## Workflow

1. **Inventory the surface.** List every route, method, auth mode, data class and external dependency. Include MCP tools, webhooks and CLI endpoints.
2. **Verify identity.** Check password hashing, session rotation, cookie flags, API-key hashing, scope enforcement and reset-token single use. Test account enumeration.
3. **Test authorization.** For each object route, attempt access as another user, a team member without the role, and an unauthenticated caller. Verify tenant isolation on list and detail endpoints.
4. **Probe input handling.** Try schema bypass, mass assignment, path traversal, SQL/NoSQL injection, template injection, SSRF and oversized payloads. Confirm output encoding.
5. **Review secrets and logs.** Search for credentials in source, build artifacts, error responses and logs. Confirm redaction of tokens, cookies and personal data.
6. **Review abuse controls.** Check rate limits per IP and account, idempotency, webhook signatures, replay windows and dead-letter handling.
7. **Review privileged operations.** Confirm audit logs, reason capture, least privilege and the ability to revoke access.
8. **Write the report.** For each finding: severity, evidence, affected asset, exploitability, fix and retest step.

## Quality bar

- Every finding has reproducible evidence.
- Critical findings include a containment step.
- Fixes are specific, not "add validation".
- The report distinguishes confirmed issues from hypotheses.
- No production data is exfiltrated or modified.

## Common mistakes

- Testing authorization only through the UI.
- Treating a 404 as proof of authorization.
- Logging the full request body containing tokens.
- Trusting a webhook without verifying the raw body signature.
- Using a shared admin API key for automation.

## Output

Return an executive summary, finding table with severity and evidence, remediation plan, retest checklist and residual risk.
""",
    },
    {
        "slug": "premium-data-storytelling", "name": "Data Storytelling for Dashboards",
        "description": "A premium method for turning analysis into a clear visual narrative: choose the right chart, frame the comparison, annotate the insight and avoid misleading visuals.",
        "category": "Data Analysis", "technologies": ["Data visualization", "Storytelling", "Accessibility"],
        "featured": True, "premium": True, "price_cents": 900,
        "changelog": "Initial premium release with narrative and chart-selection frameworks.",
        "dependencies": ["A charting library", "A defined audience and decision"],
        "permissions": ["Access to the dataset", "Permission to publish the visual"],
        "reference": ("references/chart-selection.md", b"""# Chart selection

| Question | Chart |
|---|---|
| Change over time | Line |
| Compare categories | Horizontal bar |
| Distribution | Histogram or box plot |
| Relationship | Scatter |
| Part of a whole, few categories | Stacked bar |
| Exact lookup | Table |

Always: title states the insight, subtitle states the comparison, source and date are visible.
"""),
        "body": """
## When to use this skill

Use this when a chart or dashboard must persuade, explain or support a decision, not merely display data.

## Workflow

1. **Name the audience and decision.** A chart for an executive needs a different level of detail than one for an analyst.
2. **Write the takeaway as a sentence.** "Activation rose 12 points after onboarding was shortened." The chart supports the sentence; it does not replace it.
3. **Choose the comparison.** State the baseline: previous period, target, cohort or peer group. A number without a comparison is not a story.
4. **Select the chart.** Use position and length for precise comparison. Avoid pies for more than five slices, dual axes and 3D effects.
5. **Annotate the insight.** Mark the launch, the anomaly or the threshold. Remove gridlines and labels that do not help the decision.
6. **Design for accessibility.** Use a colour-blind-safe palette, direct labels, sufficient contrast and a text/table alternative.
7. **State uncertainty.** Show sample size, confidence range or missing data. Do not smooth away a meaningful gap.
8. **Test comprehension.** Ask someone outside the project what they conclude. If it differs from your takeaway, fix the chart, not the reader.

## Quality bar

- The title states the insight, not the metric name.
- The comparison and time window are explicit.
- The chart type matches the question.
- The source and freshness are visible.
- A table alternative exists for key data.

## Common mistakes

- Truncated bar axes.
- Dual axes that imply a relationship.
- Rainbow palettes with no meaning.
- Dense labels that overlap.
- A dashboard with no stated decision.

## Output

Return the takeaway, audience, comparison, chart specification, annotation plan, accessibility notes and the data source.
""",
    },
]


def _plan_seed(db: Session) -> None:
    for item in PLANS:
        plan = db.get(SubscriptionPlan, item["code"])
        if plan is None:
            db.add(SubscriptionPlan(**item))
        else:
            # Keep administrator edits; only fill missing defaults.
            if not plan.features:
                plan.features = item["features"]
            if not plan.description:
                plan.description = item["description"]
    if not db.get(SystemSetting, "discovery"):
        db.add(SystemSetting(key="discovery", value=DEFAULT_DISCOVERY))
    if not db.get(SystemSetting, "marketplace"):
        db.add(SystemSetting(key="marketplace", value={
            "commission_bps": 1500, "reviews_enabled": True,
            "payouts_enabled": False, "payout_note": "Creator payouts require a configured payment provider.",
        }))
    if not db.get(SystemSetting, "security"):
        db.add(SystemSetting(key="security", value={
            "scan_on_import": True, "require_manual_approval": True,
            "minimum_score": 75, "quarantine_on_findings": True,
        }))
    db.commit()


def seed_library(db: Session) -> dict:
    settings = get_settings()
    _plan_seed(db)
    if not settings.seed_library:
        return {"seeded": 0, "skipped": True}
    created = 0
    for item in STARTER_SKILLS:
        existing = db.scalar(select(Skill).where(Skill.slug == item["slug"]))
        if existing:
            if existing.is_premium and item.get("premium"):
                listing = db.scalar(select(MarketplaceListing).where(MarketplaceListing.skill_id == existing.id))
                if not listing:
                    db.add(MarketplaceListing(skill_id=existing.id, title=item["name"], summary=item["description"],
                                              price_cents=item["price_cents"], status="approved",
                                              commission_bps=settings.platform_commission_bps,
                                              featured=item.get("featured", False), published_at=utcnow()))
            continue
        skill = Skill(
            repository_id=None, slug=item["slug"], name=item["name"], description=item["description"],
            instructions="", path="", category=item["category"], creator="AgentDock Studio",
            community="AgentDock Starter Library", license_id="MIT", source_url="", stars=0,
            score=100, status="approved", is_premium=item.get("premium", False),
            is_featured=item.get("featured", False), commercial_ok=True, security_status="clear",
            latest_version="1.0.0", technologies=item.get("technologies", []),
            compatibility=["MCP-compatible agents", "AgentDock REST API", "AgentDock CLI"],
            dependencies=item.get("dependencies", []), permissions=item.get("permissions", []),
            changelog=item.get("changelog", ""),
        )
        db.add(skill)
        db.flush()
        files = {
            "SKILL.md": _md(item["name"], item["description"], item["body"],
                            tags=", ".join(item.get("technologies", []))),
            item["reference"][0]: item["reference"][1],
        }
        version = "1.0.0"
        snapshot, content_hash, manifest = save_snapshot(skill.id, version, files)
        skill_version = SkillVersion(skill_id=skill.id, version=version, source_commit="",
                                     content_hash=content_hash, manifest=manifest, snapshot_path=snapshot,
                                     changelog=item.get("changelog", ""))
        db.add(skill_version)
        db.flush()
        db.add(SecurityScan(skill_id=skill.id, version_id=skill_version.id, status="clear", findings=[],
                            scanner="agentdock-static-v2"))
        if item.get("premium"):
            db.add(MarketplaceListing(skill_id=skill.id, title=item["name"], summary=item["description"],
                                      price_cents=item["price_cents"], status="approved",
                                      commission_bps=settings.platform_commission_bps,
                                      featured=item.get("featured", False), published_at=utcnow()))
        created += 1
    db.commit()
    if created:
        logger.info("Seeded %s original AgentDock starter skills", created)
    return {"seeded": created, "skipped": False}
