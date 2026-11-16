# Project documentation

The outermost [AGENTS.md](../AGENTS.md) contains the project-wide lookup table. This directory explains how callers use the shared evidence/forecast backend and records the boundary between implemented behavior and design intent.

## File map

- [project-status.md](project-status.md): dated implementation review, supported capabilities, concrete gaps, and reconciliation of historical plans.
- [agent-workflow.md](agent-workflow.md): provider-free research, shared database/entity reuse, DAG updates, forecasts, reruns, reports, and CLI/HTTP handoff.
- [topic-source-graphs.md](topic-source-graphs.md): attributed claims, scoped source judgments, ownership/affiliations, event history, and cross-layer connections.
- [cycles.md](cycles.md): cycle factor records, harmonic and oscillator models, red-noise/holdout verdicts, hidden-cycle search, combination math and forecast integration. The operational procedure is the [seldon-cycles skill](../skills/seldon-cycles/SKILL.md).
- [openrouter-models.md](openrouter-models.md): dated provider catalogue check and selection rationale; current configured values live in backend config.
- [../GLOSSARY.md](../GLOSSARY.md): shared vocabulary; root design/plan files retain historical intent rather than an authoritative completion checklist.

## Maintenance

Actual implementation, schemas, CLI help, migrations, and tests are the source of truth. Check cited behavior before extending instructions; distinguish implemented features, limitations, and proposals. Do not imply that Seldon has inspected or implemented a separate Parallax frontend merely because a workflow mentions it.

Correct relevant `AGENTS.md` files when guidance is wrong, missing, or newly relevant; update this map when documents move. Keep guides concise and split detailed procedures or growing topics into focused linked documents. Keep sample dates visibly illustrative, credentials absent, and research/data writes separate from setup-only examples. Verify local links and commands without running mutations against a live database as a documentation check.
