# Backend ownership

[Root AGENTS.md](../../AGENTS.md) contains the project-wide lookup table; [src/AGENTS.md](../AGENTS.md) covers packaging boundaries.

Seldon persists reusable evidence and explainable forecasts. Two storage generations coexist: the SQL-backed research system and a legacy file-backed facade consumed by Parallax. Keep their state and APIs distinct, and do not import Parallax into this package.

| Location | Responsibility |
| --- | --- |
| [data/](data/AGENTS.md) | Canonical SQL scenarios, evidence KB, entity relationship graph (ERG), predictions, versions and audit records. |
| [workspace/](workspace/AGENTS.md) | Provider-free agent exchange, scenario influence DAG validation, shared knowledge scope, reruns, reports, topic/source graphs and cycle factors on the same database. |
| [agents/](agents/AGENTS.md) | Built-in research, extraction, relationship, convergence, prediction, advanced analysis and feedback coordinators. |
| [api/](api/AGENTS.md) | FastAPI routes, authentication, application factories and pipeline/operations wiring. |
| [graph/](graph/AGENTS.md), [predictions/](predictions/AGENTS.md) | Legacy JSON graph and market-prediction files, accessed through `client.py`. |
| [kb/](kb/AGENTS.md), [llm/](llm/AGENTS.md) | Embeddings and OpenAI-compatible model protocols/adapters. |
| [ops/](ops/AGENTS.md) | Durable in-process jobs, backups, seed data and logs. |
| `config.py` | Typed settings, provider presets and environment loading; keep exact models, limits and fallback settings here. |
| `cli.py`, `__init__.py` | Operations/research command dispatch and public package exports. |

User-facing capabilities follow the root [skill requirement](../../AGENTS.md#features-are-agent-skills): one service function behind both `seldon research` and `/workspace`, plus a `skills/<name>/SKILL.md`. Normal semantic execution in `agents/` needs a working provider. External agents supply their own research and reasoning through `workspace/`. Preserve provenance, caller-owned transactions, shared UUIDs and frozen forecast history in both workflows. Verify changed behavior with the relevant [tests](../../tests/AGENTS.md); the offline suite excludes `live_openrouter`.

For implemented capabilities versus remaining work, read [project status](../../docs/project-status.md); terminology is in [GLOSSARY.md](../../GLOSSARY.md).

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; split detailed material into focused linked docs or child maps before it causes context bloat.
