# Frozen gold research replay

See the [root AGENTS.md](../../AGENTS.md) for the project-wide lookup table. Implementation, schemas, migrations, CLI help, and executable tests are authoritative; these inputs preserve a dated example, not a current forecast.

| File | Responsibility |
| --- | --- |
| `README.md` | Reproduction command, dated question, graph mechanisms, and interpretation limits. |
| `01-research.json` | Initial evidence, causal assumptions, nodes/edges, and research log. |
| `02-expand.json` | Follow-up evidence and additional currency/investor dependencies. |
| `03-forecast.json` | Bounded final review, node assessments, forecast branches, benchmark, assumptions, and unresolved gaps. |
| `replay.py` | Creates a scenario, fills current scenario/revision fields, validates/applies each batch through WorkspaceService, and exports applied inputs, workspace JSON, and Markdown. |

The script uses an explicitly selected SQLite database and performs no network or model calls. Each execution creates a new scenario while preserving existing scenarios; files in the selected output directory are rewritten. Do not use the replay as a live-research refresh or as a reason to create separate databases for normal questions.

Dates, observations, and subjective uncalibrated probabilities belong in the JSON/README. Preserve the distinction between sourced evidence and causal assumptions. Replay validates saved structure; it does not independently verify source claims, estimate causal coefficients, or calibrate forecast accuracy. New research should use [the general workflow](../../docs/agent-workflow.md) and record fresh evidence.

Update relevant AGENTS.md files whenever guidance is missing, stale, incorrect, or newly needed. Keep this map concise; retain detailed reproduction and interpretation in the linked README rather than expanding AGENTS.md.
