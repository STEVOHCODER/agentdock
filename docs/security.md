# Security notes

## Implemented controls

- Passwords use PBKDF2-HMAC-SHA256 with random salts and 310,000 iterations.
- Browser sessions use random opaque tokens; only token hashes are stored. Cookies are HttpOnly and SameSite=Lax. Set AGENTDOCK_SESSION_SECURE_COOKIE=true behind HTTPS.
- API keys use random values with a prefix for display and SHA-256 hashes at rest. A key is returned only once, can be revoked and carries explicit read/write scopes. Administrator endpoints require a separate admin scope that user-created keys cannot request.
- Admin endpoints enforce a server-side administrator role.
- Browser mutations check Origin against the explicit CORS origin list. CORS permits credentials only for that list.
- Sign-in, registration and token issuance use shared Redis IP limits in production. All requests have a shared baseline cap. Development mode has a local fallback. Set `AGENTDOCK_REQUEST_RATE_LIMIT_PER_MINUTE` and `AGENTDOCK_AUTH_RATE_LIMIT_PER_MINUTE` to tune the limits for the expected gateway/client traffic.
- Responses set content-type sniffing, frame and referrer protections; production also sets HSTS.
- GitHub URLs are strict HTTPS github.com owner/repository paths. API and raw content use fixed hosts, redirects are rejected, GitHub credentials are not sent to raw content, and resource paths are traversal-checked.
- Webhook endpoints verify HMAC signatures over the raw request body and bound payload size. Payment events are deduplicated by provider event id; GitHub push events only queue work for approved, tracked repositories.
- `AGENTDOCK_FIRST_PARTY_OWNERS` is an explicit operator declaration. Only owners listed there can have unlicensed imported skills marked `OWNER-AUTHORIZED`; the marker is not assignable through the API and stays off by default.
- File sizes and counts are bounded. Executable files are never run. Snapshots use per-file hashes and immutable commit-derived version folders.
- Imports with missing/unclear licences remain in review. Admin decisions cannot bypass the explicit licence or security gates.

## Important limitations

This build has not completed a production security review:

- Static suspicious-command and secret patterns are narrow. They do not detect all malware, prompt injection or harmful instructions. Treat imported skills as untrusted and require human review.
- Trusted-publisher and admission weights are stored/scored but not yet governed by a full audited policy editor.
- Redis-backed request limits are shared across web replicas, but are currently keyed by client IP. Configure trusted proxy CIDRs correctly and account for shared NAT or gateway egress when setting capacity. Add gateway/WAF protections for volumetric abuse.
- Email verification, password reset, scoped API keys and a rights/takedown workflow are implemented. SMTP and payment-provider credentials are not included in the repository and must be configured before those channels are live. OAuth and an external secret manager are not part of this build.
- RBAC covers regular users, creators and administrators, with team owner/admin/member roles. Team tenancy is enforced at the API layer on every team-scoped route.
- Paid entitlements are granted only by a verified provider webhook or by an administrator recording a manual payment. Before enabling a hosted provider, complete licence review, creator agreements, refund testing, and verify the webhook signature configuration. S3-compatible snapshot storage is supported but must be configured for multi-host deployment; PostgreSQL stores the work queue.

## Deployment checklist

- Use PostgreSQL, a unique 32+ character secret, HTTPS, secure cookies and exact browser origins.
- Store .env outside source control and restrict access to it.
- Keep the API host port private behind a TLS reverse proxy.
- Use a least-privilege GitHub token.
- Restrict and back up the shared filesystem or S3-compatible SkillVault. Ensure web and workers use the same storage configuration.
- Monitor database, Redis, worker leases, backups, disk/object storage use and failed job counts.
- Put the web API behind a TLS load balancer and centralized, redacted logs before multi-replica production.
- Review rights to redistribute each imported skill; a public GitHub URL does not itself grant those rights.
