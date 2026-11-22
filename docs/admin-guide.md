# Administrator guide

## Bootstrap the first administrator

Set AGENTDOCK_ADMIN_EMAIL and AGENTDOCK_ADMIN_PASSWORD in the server's `.env` before startup. Use a unique password of at least 12 characters. If no user exists for that address, startup creates the administrator. If that address belongs to an existing non-admin account and no administrator exists yet, startup promotes it only when the configured password matches the account's current password. A mismatch stops startup with an actionable error; it never silently grants access. Once an administrator exists, restarting the app does not reset passwords or roles.

There is no separate admin login URL. Sign in through the regular account screen with the configured administrator account. The protected **Administration** item appears in the workspace sidebar only for administrator roles. From there choose **Import repository** to queue sources.

Account creation never grants admin status based only on an email value.

## Import and review

1. Open **Administration → Import repository**.
2. Enter an exact HTTPS github.com/owner/repository URL, optionally select a skill folder, and choose a community label in a batch import.
3. Start the synchronization worker. Imports return to the durable job queue and do not run until a worker claims them.
4. AgentDock checks repository metadata, branch, licence, commit, tree, each skill's SKILL.md, supporting file sizes, metadata, maintenance date, popularity and static security patterns.
5. Review the per-skill score, source and licence in the admission queue. An unknown or non-allowlisted licence cannot be approved. A flagged security scan is quarantined.
6. Enter a meaningful decision reason and approve or reject. Approved skills become visible in Explore skills. A trusted publisher raises credibility; it never auto-approves content.

The importer does not run code from GitHub. A batch supports up to 250 repositories and 5,000 selected skill folders; each repository can select up to 500 folders. Packages are capped at 100 files and 2 MB per file, and each repository import is capped at 200 MB. For a large repository whose GitHub tree is truncated, select skill folder paths explicitly. Use multiple batches to process larger collections.

## Trusted publishers

Add a GitHub user or organization only after checking ownership and authenticity. Keep a short verification note. Removing a trusted publisher affects future scoring; already-approved skills retain their recorded status until an administrator re-reviews them.

## Repository controls

- Pause sync: stop scheduled polling while keeping approved skill distribution active.
- Resume: re-enable polling only when every skill from the repository is approved.
- Exclude: withdraw approved skills from the catalogue and stop scheduled sync. Reapproval is a per-skill review action.
- Sync now: add a job to the database queue. The worker must be running.

If a sync receives GitHub 404, the source is marked unavailable, snapshots are retained and an audit event is recorded. GitHub's public API cannot reliably distinguish deleted, private and some other unavailable states.

## Review queue and audit

The queue separates review and quarantine. Approval is rejected unless the source licence is on the redistribution allowlist and the current security scan is clear. Every approve/reject/quarantine/withdraw decision requires an administrator and a reason. The administrator API exposes recent audit events.

## Operational monitoring

- GET /api/health checks the API database connection.
- Administration → Sync jobs shows status and retry count.
- Failed syncs use exponential backoff. Source-unavailable jobs are terminal until an administrator restores or re-reviews the source.
- Configure platform monitoring for the web service, PostgreSQL, storage volume and worker process.

## First-run starter library

The first startup seeds four subscription plans and sixteen original MIT-licensed AgentDock starter skills, including three premium listings. Seeding is idempotent; existing edits to plans and skills are preserved. Set AGENTDOCK_SEED_LIBRARY=false to skip seeding.

## Marketplace and creator review

1. **Creators** reviews creator applications. Approving gives the account the `creator` role and allows it to submit listings.
2. **Marketplace** reviews submitted listings. Approval requires the underlying skill to be approved and cleared for commercial distribution. Pausing a listing keeps purchase history but stops new sales.
3. Every status change records a reason, notification and audit event. Featured listings appear first in the marketplace and on the landing page.

## Billing operations

- **Payments** lists every checkout. With the default manual provider, `Record payment` fulfils a pending invoice and grants the subscription or skill entitlement. `Refund` reverses the purchase, earning and subscription.
- **Subscriptions** shows active plans and cancellation state. `Activate` records a manual paid payment and fulfils it, leaving a complete audit trail.
- **Plans** can be created and updated from the control center. Provider price IDs (for Paddle) are stored in `payment_prices` system settings.
- Hosted providers only fulfil entitlements through signed webhooks; a browser redirect is never trusted.

## Users, teams and rights

- **Users** supports search, role changes (`free`, `developer`, `creator`, `admin`, `super_admin`) and activation. Deactivating a user revokes active API keys.
- **Rights** handles copyright, licence, privacy and takedown requests. Resolving a request can suspend the affected skill and pause its listing while the claim is reviewed.
- Rights requests can also be submitted from the public Rights page without an account.

## Discovery and GitHub webhooks

Discovery records repository candidates from GitHub search; it never imports or approves a skill automatically. Configure topics, keywords, minimum stars and result counts in **Discovery**, then run it once or wait for the worker's scheduled run.

Set `AGENTDOCK_GITHUB_WEBHOOK_SECRET` and add a push webhook pointing at `POST /api/v1/webhooks/github`. AgentDock verifies the `X-Hub-Signature-256` header over the raw body, updates the commit SHA and queues a sync for approved, tracked repositories.

## Analytics

**Overview** reports users, revenue, MRR/ARR, marketplace GMV, commission, active subscriptions, catalogue health, open rights requests, security findings and a 14-day activity series. Use it with **Audit** to trace privileged actions.
