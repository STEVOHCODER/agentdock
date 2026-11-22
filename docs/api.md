# REST API reference

The generated interactive reference is at `/api/docs`; the OpenAPI document is at `/api/openapi.json`.

## Authentication

- Browser: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`.
- Verification and recovery: `POST /api/v1/auth/verify-email`, `POST /api/v1/auth/resend-verification`, `POST /api/v1/auth/forgot-password`, `POST /api/v1/auth/reset-password`.
- Profile and security: `PATCH /api/v1/account/profile`, `POST /api/v1/account/change-password`, `POST /api/v1/account/delete`.
- Notifications: `GET /api/v1/account/notifications`, `POST /api/v1/account/notifications/{id}/read`.
- Bearer keys: `POST /api/v1/auth/token`, `GET/POST /api/v1/auth/api-keys`, `DELETE /api/v1/auth/api-keys/{key_id}`.

A bearer key is sent as `Authorization: Bearer adk_...`. The complete key is returned only once; only its SHA-256 hash is stored. Supported scopes are `skills:read`, `library:read`, `library:write`, `account:read`, `teams:read`, `teams:write`, `marketplace:read`, `marketplace:write` and `billing:read`. User-created keys cannot grant administrator access.

New passwords require at least 12 characters. Verification and reset tokens are single-use and expire. Without SMTP, development responses include a one-time debug link; production never returns tokens.

## Catalogue

- `GET /api/v1/skills/search?q=...&category=...&community=...&limit=20&offset=0`
- `GET /api/v1/skills/discovery` (recommended, popular, recently updated and privacy-thresholded community trends)
- `GET /api/v1/skills/{id-or-slug}`
- `POST /api/v1/skills/{id-or-slug}/retrieve`
- `GET /api/v1/skills/{id-or-slug}/versions`
- `GET /api/v1/skills/{id-or-slug}/resources`
- `GET /api/v1/skills/{id-or-slug}/resources/{path}?version=...`
- `GET /api/v1/categories`, `GET /api/v1/communities`

Search defaults to 20 results and is capped at 50. Full resource requests return an ETag and accept a version selector. Premium skills require a paid entitlement.

## User workspace

- `GET /api/v1/user/library`, `POST /api/v1/user/library`, `DELETE /api/v1/user/library/{skill_id}`
- `GET /api/v1/user/vault` (saved snapshots, version counts, last known upstream status and verification state)
- `POST/GET/PATCH/DELETE /api/v1/user/collections[...]` (collections and shared team collections)
- `GET /api/v1/account/usage`, `GET /api/v1/account/entitlements`, `GET /api/v1/integrations`

## Teams

- `GET/POST /api/v1/teams`, `GET/PATCH/DELETE /api/v1/teams/{id}`
- `POST /api/v1/teams/{id}/invitations`, `DELETE /api/v1/teams/{id}/invitations/{invitation_id}`
- `POST /api/v1/teams/invitations/accept`
- `PATCH/DELETE /api/v1/teams/{id}/members/{user_id}`
- `GET /api/v1/teams/{id}/usage`

Seat limits are enforced when invitations are created and accepted.

## Marketplace and billing

- `GET /api/v1/plans`
- `GET /api/v1/marketplace/listings`, `GET /api/v1/marketplace/featured`, `GET /api/v1/marketplace/listings/{id}`
- `POST /api/v1/marketplace/purchases`, `GET /api/v1/marketplace/purchases`
- `GET/POST /api/v1/marketplace/listings` and `PATCH /api/v1/marketplace/listings/{id}` (creators)
- `GET/POST /api/v1/creator/profile`, `GET /api/v1/creator/earnings`
- `GET /api/v1/account/subscription`, `POST /api/v1/account/subscription/checkout`, `POST /api/v1/account/subscription/cancel`
- `GET /api/v1/account/billing`
- `POST /api/v1/webhooks/payments/{paddle|flutterwave|urubutopay}`
- `POST /api/v1/rights-requests`

A checkout creates a `pending` payment. Entitlement is granted only by a verified provider webhook or by an administrator recording a manual payment. Browser redirects never grant access.

## Administrator

Every endpoint checks for an administrator role:

- `GET /api/v1/admin/overview`, `GET /api/v1/admin/analytics`
- `GET /api/v1/admin/skills?status=...`, `POST /api/v1/admin/skills/{id}/decision`
- `POST /api/v1/admin/repositories/import`, `POST /api/v1/admin/import-batches`, `GET /api/v1/admin/import-batches[/{id}]`
- `GET /api/v1/admin/repositories`, `POST /api/v1/admin/repositories/{id}/status`, `POST /api/v1/admin/repositories/{id}/sync`
- `GET/POST /api/v1/admin/trusted-publishers`, `DELETE /api/v1/admin/trusted-publishers/{id}`
- `GET /api/v1/admin/synchronization`, `GET /api/v1/admin/audit-logs`
- `GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}/role`, `POST /api/v1/admin/users/{id}/status`
- `GET /api/v1/admin/subscriptions`, `POST /api/v1/admin/subscriptions/activate`
- `GET /api/v1/admin/payments`, `POST /api/v1/admin/payments/{id}/fulfill`, `POST /api/v1/admin/payments/{id}/refund`
- `GET/POST/PATCH /api/v1/admin/plans[...]`
- `GET /api/v1/admin/marketplace/listings`, `POST /api/v1/admin/marketplace/listings/{id}/status`
- `GET /api/v1/admin/creators`, `POST /api/v1/admin/creators/{user_id}/status`
- `GET /api/v1/admin/rights-requests`, `POST /api/v1/admin/rights-requests/{id}/resolve`
- `GET/PATCH /api/v1/admin/settings`, `GET/POST /api/v1/admin/discovery`, `POST /api/v1/admin/discovery/run`
- `GET /api/v1/admin/security`, `GET /api/v1/admin/system`
- `POST /api/v1/webhooks/github` (signature verified, not admin-authenticated)

## Errors

Errors use JSON `detail` responses. Common codes: 401 (not signed in), 402 (entitlement required), 403 (not admin, disallowed origin or forbidden scope), 404 (not found/not approved), 409 (duplicate or incompatible state), 413 (bounded payload size), 422 (invalid input or rights/security gate), 429 (rate limit), 503 (provider or configuration unavailable).

Import batches accept at most 250 repositories and 5,000 explicitly selected skill folders; each repository may select up to 500 folders. Imports return `202 Accepted`; poll the batch endpoint for progress. Skills still require review and approval before appearing in public search. Package limits are 100 files and 2 MB per file, with a 200 MB cumulative cap per repository import.
