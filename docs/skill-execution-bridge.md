# AgentDock Skill Execution Bridge

This document describes the upgrade from instruction-only retrieval to complete,
versioned skill package delivery and isolated execution.

## 1. Architecture proposal

```text
Coding agent (Cline / Claude / Cursor)
        |
        | MCP: resolve_skill_package, list_skill_files,
        |      retrieve_skill_file, execute_skill_script,
        |      get_execution_status, retrieve_execution_result
        v
FastAPI web process  ---- never executes skill scripts ----+
        |                                                  |
        | creates ExecutionJob (DB)                        | REST /api/v1/executions
        v                                                  |
PostgreSQL execution_jobs                                 |
        ^                                                  |
        | claims queued jobs                               |
        v                                                  |
Background worker (isolated process, Docker socket)        |
        |                                                  |
        | 1. resolve immutable SkillVault snapshot         |
        | 2. verify every SHA-256                          |
        | 3. materialize temp workspace                    |
        | 4. spawn one-shot Docker container               |
        | 5. store stdout/stderr/exit code                 |
        +--------------------------------------------------+
```

The web server never runs imported code. The background worker uses a
dedicated, short-lived Docker container per execution with:

- `network_disabled=True`
- `read_only=True` and a writable `tmpfs` only for `/tmp`
- `cap_drop=["ALL"]`, `no-new-privileges`
- 1 CPU, 1 GiB RAM, 64 PIDs, 120 s timeout
- minimal environment (no secrets, no customer data)
- automatic container removal and workspace cleanup

Package reads and file retrieval are available for **every approved, security-reviewed skill**. Execution is available for every approved, security-reviewed skill whose snapshot contains Python scripts; a deployment can optionally narrow execution with `AGENTDOCK_EXEC_ALLOWED_SKILLS`. An empty allow-list means all approved, security-reviewed skills are executable.

## 2. Security design

| Requirement | Control |
|---|---|
| Pin to immutable snapshots | Jobs store `version` and `version_hash`; resolution never substitutes another version. |
| Verify hashes | Every manifest file is SHA-256 verified before materialization. |
| Path traversal | `safe_relative_path` rejects absolute paths, `..`, backslashes and drive prefixes; script paths must be inside the workspace. |
| Approved packages only | `status == approved` and `security_status == clear`; optional allow-list by slug. |
| No network | Docker `network_disabled=True` (bubblewrap `--unshare-all` when that driver is used). |
| No secrets | `env` is rebuilt from scratch; no application/customer variables are forwarded. |
| CPU/RAM/time limits | cgroup limits plus `RLIMIT_AS`/`RLIMIT_CPU`; 120 s timeout. |
| Cleanup | Containers are force-removed and workspaces deleted in `finally`. |
| Auditability | `audit_logs` entry per execution with identity, version, exit code and verified file count. |
| Cancellation | `cancel_execution` marks the job canceled; worker kills the runner and removes the container. |
| Permissions | REST and MCP execution tools require `execution:run`; package reads require `skills:read`. |

## 3. Database changes

- `execution_jobs` table: `id`, `user_id`, `team_id`, `skill_id`, `version`,
  `version_hash`, `command`, `arguments`, `status`, `stdout`, `stderr`, `error`,
  `exit_code`, `pid`, `runner_id`, `sandbox`, timestamps.
- Indexes on user, team, skill, status and runner id.
- Migrations: `20261123_0001_execution.py`, `20261123_0002_execution_runner.py`.
- Usage events: `execution.requested`, `mcp_failed` / `execution_failed` on failure.

## 4. MCP tool definitions

| Tool | Input | Output |
|---|---|---|
| `resolve_skill_package` | `id`, optional `version` | version, hash, manifest, groups, static requirements, bundle coverage |
| `list_skill_files` | `id`, optional `version` | every file with path, SHA-256 and bytes |
| `retrieve_skill_file` | `id`, `path`, optional `version` | base64 content, hash, version |
| `execute_skill_script` | `id`, `script`, optional `version`, `command`, `arguments` | queued execution job |
| `get_execution_status` | `job_id` | status, timestamps, exit code |
| `retrieve_execution_result` | `job_id` | stdout, stderr, error, exit code |
| `cancel_execution` | `job_id` | canceled job |

Cancellation is also available as `POST /api/v1/executions/{job_id}/cancel`.

## 5. Execution lifecycle

1. Agent calls `execute_skill_script`.
2. Web resolves the package, validates the script belongs to the manifest and
   creates a `queued` job pinned to the exact version hash.
3. Worker claims the job.
4. Worker verifies all file hashes and materializes a temp workspace at
   `skills/<skill-name>/...`.
5. Worker creates a network-less container, writes `runner_id`, then waits.
6. stdout/stderr/exit code are stored; audit log is written; container and
   workspace are removed.
7. Agent polls `get_execution_status` then calls `retrieve_execution_result`.

## 6. Implementation files

- `backend/agentdock/execution.py` — package resolution, hash verification,
  dependency scanning, workspace materialization, Docker/bubblewrap drivers.
- `backend/agentdock/worker.py` — execution queue processing and cancellation.
- `backend/agentdock/main.py` — REST endpoints and MCP tools.
- `backend/agentdock/models.py`, migrations — `execution_jobs`.
- `backend/agentdock/config.py` — execution settings and allow-list.
- `Dockerfile`, `docker-compose.yml` — bubblewrap install, executor workspace,
  Docker socket for worker.
- `tests/test_api.py` — automated package/execution tests.

## 7. Automated tests

`python -m pytest -q` → **47 passed**.

`test_skill_package_resolution_and_execution_job_creation` verifies:
- package resolution and complete bundle coverage;
- dataset detection from static analysis;
- REST job creation pinned to a version hash;
- all seven MCP execution tools advertised;
- MCP `execute_skill_script` returning a queued job;
- two execution jobs persisted for the user.

## 8. Live end-to-end test — UI UX Pro Max

Executed against **https://agentdock.link** through MCP with a dedicated API key.

Package resolved:

```text
version: git-6ec2bb58334c
version_hash: 1edabb86ffe4f6711c9390f0d72ff3c922ad08beaa880c1f2b4aa045b7cfd7cf
files: 81
scripts: 39
datasets: 39
bundle coverage: complete
workspace path: skills/ui-ux-pro-max
```

Command (via `execute_skill_script`):

```text
python3 skills/ui-ux-pro-max/scripts/search.py "SaaS technology landing page" --design-system
```

Result:

```text
job: 66d79e14-26f5-456a-acbe-b4819c50e571
status: succeeded
exit code: 0
stderr: empty
stdout: 6,164 characters
```

The output contains the generated design system with sections `TARGET`,
`PATTERN`, `STYLE`, `COLORS`, `TYPOGRAPHY`, concrete tokens such as primary
`#2563EB`, and an accessibility/conversion rationale.

### Comparison with direct package execution

The exact 81 files were retrieved from the same immutable snapshot and the
same command was run directly in a local temporary directory. Both runs
exited 0. The ASCII-normalized outputs are identical (2,379 characters),
confirming that the AgentDock execution delivered the same design system as
the original complete package. Minor box-drawing padding differences come from
container log capture, not from content.

## 9. Full-catalogue package verification

A controlled sequential verification was run against all live approved skills:

```text
skills: 86
packages resolved: 86
errors: 0
files retrieved and SHA-256 verified: 3,425
total bytes verified: 69,305,069 (~69 MB)
hash mismatches: 0
skills with executable Python scripts: 21
docs/asset-only skills: 65
```

This confirms that complete packages — not just `SKILL.md` — are retrievable
with exact hash verification for the entire approved catalogue. Docs-only
skills have no script to run; the other 21 are eligible for isolated execution.

## 10. Browser execution console and package download

The **Execution console** workspace page provides the same capabilities without requiring a raw MCP client:

1. Choose any approved skill.
2. Read every file in its complete package without executing anything.
3. Download the whole verified snapshot as a ZIP (`GET /api/v1/skills/{id}/package.zip`).
4. Select a Python script, supply arguments and run it in the isolated container.
5. Watch status, stdout/stderr, exit code and cancel a running job.

The ZIP endpoint verifies every SHA-256 before adding it to the archive and applies the same approval, licence, security and premium-entitlement gates as file retrieval.

## 11. Synchronization auto-approval

Set `AGENTDOCK_AUTO_APPROVE_SYNCED_SKILLS=true` to publish newly synchronized skills automatically when all of these are true:

- the repository is already `approved`;
- the skill has an allowed redistribution licence (`OWNER-AUTHORIZED` for operator-claimed owners);
- the security scan is `clear`;
- the admission result is `qualified` or `approved`.

Security findings and licence problems still force `quarantined` or `pending_review`. This removes the waiting-for-admin step for trusted repositories without disabling the safety gates.

## 12. Compatibility

Existing skill search, retrieval, version listing, resource download, REST
API, MCP search/get tools and CLI workflows remain unchanged. The new tools
and endpoints are additive.
