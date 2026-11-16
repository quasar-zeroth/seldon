# Agent skills

[Root AGENTS.md](../AGENTS.md) contains the project-wide lookup table and the skill requirement. This directory packages Seldon capabilities as portable agent skills: one folder per skill, each with a `SKILL.md` (YAML frontmatter `name` and `description`, then instructions). `.claude/skills` links here so Claude Code discovers them; other agents find them through this map.

| Skill | Capability | Backed by |
| --- | --- | --- |
| [seldon-cycles](seldon-cycles/SKILL.md) | Cycle factors, historical series, harmonic/oscillator fits, hidden-cycle search, composites, charts, forecast priors | [workspace/cycles](../src/seldon/workspace/cycles/AGENTS.md), [docs/cycles.md](../docs/cycles.md) |
| [seldon-transcripts](seldon-transcripts/SKILL.md) | Video links to transcripts (YouTube captions, Supadata), entity mentions, quote-checked excerpts ingested as evidence with nodes/edges, pipeline stage, rerun queuing | [workspace/transcripts](../src/seldon/workspace/transcripts/AGENTS.md), [docs/transcripts.md](../docs/transcripts.md) |

Workflows that predate this directory still live in [agent-workflow.md](../docs/agent-workflow.md) (research workspace, reports, reruns) and [topic-source-graphs.md](../docs/topic-source-graphs.md) (perspectives). They meet most of the interface contract below but are not yet packaged as skills.

## Skill contract

A feature is skill-ready when an agent can discover, run, retry and interpret it without reading source code:

- **Trigger:** `description` states what the skill does and when to use it in the user's vocabulary, within about 1,000 characters. `name` matches the folder (lowercase, hyphens).
- **Interface:** a provider-free `seldon research ...` command and matching authenticated `/workspace/...` routes share one service function and Pydantic contracts. Output is JSON (Markdown/SVG where useful), with `--out FILE` support.
- **Discovery:** a `schema` command for every request body and a `catalog`/help listing for options, conventions and meanings.
- **Safety:** mutations take `request_id` and `base_revision`, replay exactly, reject stale or conflicting input, run in one transaction and keep append-only history.
- **Output:** concise by default, with full detail opt-in. Results state what they do and do not establish.
- **Instructions:** SKILL.md covers setup, numbered workflow, decision table, guardrails and troubleshooting. Keep it under about 200 lines. Link deeper theory to `docs/`, and keep contracts, numbers and model IDs in code.
- **Verification:** tests exercise the CLI and HTTP paths offline with real local databases.

A skill folder's `SKILL.md` is its directory guide; skill folders need no separate AGENTS.md. When adding or changing a capability, update its skill and this map in the same change. Keep commands in SKILL.md runnable against current CLI help.
