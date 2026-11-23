# AgentDock skill showcase — design capability run

This folder was generated from a fresh live run against **https://agentdock.link** on 2026-11-23. Everything in it comes from skills retrieved from the AgentDock marketplace; no pre-baked design system was copied from outside the platform.

## What was tested

A new scoped API key (`skills:read`, `execution:run`) was created through Integrations. The earlier keys had been revoked.

- Searches: `frontend design` (52), `ui ux` (9), `design system` (15), `react` (5), nonsense query (0), category `Frontend` (44).
- Three complete packages were resolved and hash-checked:
  - `ui-ux-pro-max` — 81 files, version `git-6ec2bb58334c`
  - `design-taste-frontend` — 1,631 files
  - `frontend-design` — 2 files
- Package ZIP: 674,287 bytes, valid `PK` signature.
- `SKILL.md` and script hashes matched the manifest for every probed file.
- Scripts were executed through **MCP**, not local substitution:
  - Python: `ui-ux-pro-max/scripts/search.py "SaaS technology landing page" --design-system` → succeeded, exit 0, 1,173 ms, 4.44 MB peak.
  - Node: `design-taste-frontend/scripts/copy-lint.mjs` run on its own `SKILL.md --json` → succeeded, exit 0, 6,249 bytes JSON.
- Lifecycle checks: invalid script path rejected, invalid argument types rejected, failed job produced stderr, queued job canceled, revoked key returned 401.

## Honest limitations

- The primary account reached its daily free quota (20/20) after the main executions. A second disposable QA account was created to finish the remaining script and lifecycle checks.
- The first Node lint attempt used `SKILL.md` and failed with `ENOENT`; the script expects paths relative to the package root (`skills/design-taste-frontend/SKILL.md`). It was rerun correctly and succeeded. The failed attempt is not presented as a pass.
- All temporary API keys created for this run were revoked afterwards.
- Dynamic sandbox exploitation-style probes were not run; only the exposed execution interface was used.

## Files

| File | Description |
|---|---|
| `index.html` | Static showcase page generated using the exact design tokens returned by the executed `ui-ux-pro-max` script. |
| `design-system/MASTER.md` | Cleaned design-system output from the MCP execution. |
| `design-system/MASTER.raw.txt` | Raw stdout including the terminal box-drawing frame. |
| `retrieved/frontend-design.SKILL.md` | Complete SKILL.md retrieved from the `frontend-design` package. |
| `copy-lint-report.json` | JSON output from the Node `copy-lint` script. |
| `evidence.json` | Structured live evidence: searches, packages, hashes, executions, lifecycle. |
| `agentdock-api.mjs`, `demo.mjs`, `retrieved-skills.json` | Earlier REST/MCP demo helpers retained from the prior showcase pass. |

## Design provenance

The generated page follows the exact pattern and tokens returned by the executed skill:

- Pattern: Hero + Testimonials + CTA
- Style: Vibrant & Block-based
- Primary `#2563EB`, Secondary `#7C3AED`, Accent `#EC4899`
- Typography: Chakra Petch / Russo One
- Accessibility items from the skill checklist (visible focus, reduced motion, responsive breakpoints, SVG icons) were applied.

Open `index.html` in a browser to view the showcase.
