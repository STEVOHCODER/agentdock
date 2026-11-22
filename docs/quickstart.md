# Connect an agent to AgentDock

## 1. Create an account

Open the AgentDock site, choose Start free, and register with an email and a password of at least 12 characters. When SMTP is configured, verify your email from the link we send. With no mail provider configured, development responses include a one-time verification link; ask an administrator if production access needs verification.

## 2. Create an API key

Open Integrations and choose MCP, REST API or CLI. Create a key and copy the secret while the one-time key panel is open. AgentDock stores a hash and cannot show it again. The page can test AgentDock's MCP endpoint, copy an example configuration, show last key use and revoke a key. Generate a replacement before disconnecting an old key so you can update the agent without a gap.

## 3. Configure an MCP client

Set the remote MCP URL to the site origin plus /mcp. Add this header in the client's secret/configuration UI:

    Authorization: Bearer <your AgentDock API key>

AgentDock accepts JSON request/response messages. It does not currently stream server-sent events or keep stateful MCP sessions.

## 4. Try a search

Ask the agent: “Search AgentDock for a skill to build a React analytics dashboard.”

The search_skills tool returns approved skills. The agent can call get_skill and fetch individual resources with get_skill_resource.

## No skills appear?

A new deployment is preloaded with sixteen original MIT-licensed AgentDock starter skills, so Explore should never be empty on first run. Additional community skills appear only after an administrator imports repositories, starts the worker, reviews candidates and approves eligible skills. Only approved skills appear in Explore and search. A regular user cannot import or approve sources.

To access administration, sign in with the administrator account configured by `AGENTDOCK_ADMIN_EMAIL` and `AGENTDOCK_ADMIN_PASSWORD`. The **Control center** entry appears in the workspace sidebar for that account. If no administrator exists yet and an existing account is configured for bootstrap, the password must match its current password before AgentDock promotes its role.

## Teams, billing and purchases

Create a workspace from **Teams** to invite teammates and share collections. Free team workspaces have two seats; upgrade the workspace from **Billing** for more. Premium skills are purchased from the Marketplace. With the default manual payment provider, send the invoice reference to the configured billing email and an administrator records the payment before retrieval is unlocked.

For local setup, follow the project README to create `.env`, run migrations, start the API and frontend, and start the background worker in a separate terminal. The app's Documentation link and the signed-in sidebar's **Need a hand?** card open the in-app help center.

## CLI

    python -m pip install -e .
    agentdock login --url https://your-agentdock-domain.example
    agentdock search "React analytics dashboard"
    agentdock get skill-slug

To print an MCP config snippet, run agentdock connect mcp. Replace the key placeholder with your API key and store it in your coding agent's secret manager.

## Troubleshooting

- 401: sign in again or create a new API key. Revoked keys stop working immediately.
- 403 on /mcp: check AGENTDOCK_FRONTEND_ORIGINS; a browser-based MCP client must have an allowed Origin. Native clients may omit Origin.
- 406 on /mcp: the client must send Accept: application/json, text/event-stream.
- No skills appear: an administrator must import a public GitHub repository and approve each eligible skill first.
- GitHub 429: set a GitHub token to improve public API rate limits.
- A resource is unavailable: check the skill's licence and whether its repository/version remains approved.
