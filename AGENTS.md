# Seldon agent map

This outermost [AGENTS.md](AGENTS.md) contains the project-wide lookup table below. Read it first, then the nested guides for directories you change. See [GLOSSARY.md](GLOSSARY.md) for terminology and [project status](docs/project-status.md) for supported features, implementation gaps, and historical roadmap reconciliation.

## System design and current scope

Seldon owns evidence-backed knowledge graphs and probabilistic scenario forecasts. Parallax (`../../parallax`) is the primary frontend/orchestration boundary; this package stays independent of Parallax imports. `apps/web` is an existing Next.js operating console with scenario, knowledge, graph, run, calibration, and settings workflows.

Two execution paths share the relational database: built-in specialist agents use configured model/retrieval providers, while `seldon research` lets an existing coding-agent session supply research through a validated, provider-free workspace. Both preserve evidence, graph changes, forecasts, and run history. The workspace adds reusable entity identities, scoped influence DAGs, immutable forecast snapshots/reports, rerun handoffs, and topic/claim/source provenance graphs. The older `client.py`, `graph/`, and `predictions/` facade uses separate JSON files for compatibility; it is not the database scenario engine.

The project has substantial implementation and regression coverage, but empirical forecast validation, autonomous outcome monitoring, distributed execution, production database verification, and some console integration remain follow-up work. Older plans contain many already-completed items; use the status document and inspect code before treating one as a current TODO.

## Working rules

- Actual implementation, schemas, migrations, CLI help, and tests are the source of truth. These guides describe broad design and navigation; planning markdown records intent and can be obsolete.
- Correct the relevant `AGENTS.md` whenever you find incorrect, missing, or newly relevant information. Update parent lookup entries when ownership or directories change, and keep status/glossary terms aligned with implementation.
- Keep each guide concise: local responsibilities, invariants, file map, and verification links. Split growing material into a deeper directory guide or focused document and link it; do not copy contracts, model IDs, numerical settings, or long procedures into guidance.
- Maintain a guide for each maintained source, route, test, migration, documentation, and example directory. Generated dependencies, caches, build output, `.git`, and runtime data do not need guides. Use the lookup to load only relevant branches.
- Preserve user changes and existing data. Keep source provenance, transactional updates, and historical forecasts intact. Do not clean stored research as part of an unrelated code/documentation task.
- Questions share one configured database and reusable entity UUIDs. Search the knowledge library before creating duplicates; do not create a database per question. For an installed Parallax service, read its service settings to locate the live database. Standalone research CLI and API database selection differ; see the workflow.
- Forecasts distinguish evidence from assumptions and expose uncertainty, dates, sources, and unresolved questions. Research requests do not authorize trades. Pending external-agent reruns need an executing agent; creating a request does not execute research.
- Keep credentials out of guidance and logs. Exact settings and environment behavior live in [config.py](src/seldon/config.py) and [.env.example](.env.example).

## Project-wide lookup table

| Directory guide | Information owned here |
| --- | --- |
| [src](src/AGENTS.md) | Python source/package boundary |
| [src/seldon](src/seldon/AGENTS.md) | Backend architecture, configuration, CLI, compatibility facade |
| [agents](src/seldon/agents/AGENTS.md) | Provider-backed research, extraction, convergence, prediction, feedback, advanced analysis |
| [agents/providers](src/seldon/agents/providers/AGENTS.md) | External search/news adapters |
| [api](src/seldon/api/AGENTS.md) | FastAPI composition, contracts, authentication, jobs/events |
| [data](src/seldon/data/AGENTS.md) | Relational models, schemas, repositories, audits, tags, graph views |
| [graph](src/seldon/graph/AGENTS.md) | Legacy file-backed NetworkX graph and extraction |
| [kb](src/seldon/kb/AGENTS.md) | Local/remote embeddings and vector helpers |
| [llm](src/seldon/llm/AGENTS.md) | Model protocol, provider adapter, retries, invocation recording |
| [ops](src/seldon/ops/AGENTS.md) | Durable local jobs, backups/restore, seed data, logs |
| [predictions](src/seldon/predictions/AGENTS.md) | Legacy file-backed predictions and lifecycle |
| [workspace](src/seldon/workspace/AGENTS.md) | External-agent exchange, DAG gates, shared knowledge, scope, history, reports |
| [workspace/perspectives](src/seldon/workspace/perspectives/AGENTS.md) | Topics, claims, source trust/leaning, affiliations, cross-layer navigation |
| [apps](apps/AGENTS.md) | Application boundary and console entry point |
| [apps/web](apps/web/AGENTS.md) | Next.js console architecture, scripts, API settings, UI gaps |
| [web/app](apps/web/app/AGENTS.md) | App Router, root dashboard/layout, styles, route boundaries |
| [app/api](apps/web/app/api/AGENTS.md) | Same-origin server proxy boundary |
| [app/api/scenarios](apps/web/app/api/scenarios/AGENTS.md) | Scenario creation proxy |
| [app/api/scenarios/draft](apps/web/app/api/scenarios/draft/AGENTS.md) | Scenario draft proxy |
| [app/scenarios](apps/web/app/scenarios/AGENTS.md) | Scenario list and conversational creation |
| [app/scenarios/[id]](apps/web/app/scenarios/[id]/AGENTS.md) | Scenario editing, phase jobs, prediction and report controls |
| [app/kb](apps/web/app/kb/AGENTS.md) | Knowledge search, filters, entry creation |
| [app/kb/[id]](apps/web/app/kb/[id]/AGENTS.md) | Evidence detail, versions, contradictions, supersession |
| [app/graph](apps/web/app/graph/AGENTS.md) | Graph filters, editing, snapshots, merge review |
| [app/runs](apps/web/app/runs/AGENTS.md) | Run search and filtering |
| [app/runs/[id]](apps/web/app/runs/[id]/AGENTS.md) | Run provenance, messages, model calls, retry |
| [app/calibration](apps/web/app/calibration/AGENTS.md) | Outcome resolution, feedback, calibration charts |
| [app/settings](apps/web/app/settings/AGENTS.md) | Model configuration, health, destructive reset UI |
| [web/src](apps/web/src/AGENTS.md) | Reusable UI/client modules beneath routes |
| [src/components](apps/web/src/components/AGENTS.md) | Shared shell, primitives, charts, draft chat, graph canvas |
| [src/lib](apps/web/src/lib/AGENTS.md) | API compatibility barrel and client boundary |
| [src/lib/api](apps/web/src/lib/api/AGENTS.md) | Typed API contracts, transport, domain adapters |
| [web/tests](apps/web/tests/AGENTS.md) | Mock API, route smoke runner, frontend test harness |
| [web/tests/e2e](apps/web/tests/e2e/AGENTS.md) | Playwright route and mutation workflows |
| [tests](tests/AGENTS.md) | Python verification strategy, fixtures, network isolation |
| [tests/unit](tests/unit/AGENTS.md) | Repository, agent, API, workspace, graph and operations coverage |
| [tests/integration](tests/integration/AGENTS.md) | SQLite migrations, mocked providers, opt-in live provider tests |
| [alembic](alembic/AGENTS.md) | Migration environment and database targeting |
| [alembic/versions](alembic/versions/AGENTS.md) | Schema revision chain and additive upgrades |
| [.github](.github/AGENTS.md) | Repository automation boundary |
| [.github/workflows](.github/workflows/AGENTS.md) | Backend/frontend CI gates and coverage limits |
| [docs](docs/AGENTS.md) | Current status, operational workflows, provenance semantics, provider notes |
| [examples](examples/AGENTS.md) | Reproducible research examples |
| [examples/gold](examples/gold/AGENTS.md) | Dated gold evidence/forecast fixtures and offline replay |

## Root files and starting checks

[README.md](README.md) covers installation and local services; [pyproject.toml](pyproject.toml) defines packaging and Python tools; `uv.lock` and `apps/web/package-lock.json` lock dependencies. [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [launch-lan.sh](launch-lan.sh), and [alembic.ini](alembic.ini) define local deployment/migrations. The LAN override is generated by the launcher.

[docs/agent-workflow.md](docs/agent-workflow.md) is the operational research/report handoff. [docs/topic-source-graphs.md](docs/topic-source-graphs.md) explains attributed claims and source reviews. [docs/openrouter-models.md](docs/openrouter-models.md) records dated model-selection rationale, not guaranteed current availability.

[design.md](design.md) records console presentation goals. [prediction-system-plan.md](prediction-system-plan.md), [implementation-plan.md](implementation-plan.md), [llm-entity-pipeline-plan.md](llm-entity-pipeline-plan.md), and [scenario-chat-simplification-plan.md](scenario-chat-simplification-plan.md) are historical intent/backlog context; reconcile against implementation and [current status](docs/project-status.md).

Use `uv sync` and `uv run seldon research --help` for setup/discovery. Run Python checks with `uv run pytest -m "not live_openrouter"`; read [test isolation guidance](tests/AGENTS.md) first because `tests/conftest.py` loads local environment configuration and migrations honor database overrides. The console gate is `npm run test:frontend` from `apps/web`; scripts and CI are authoritative. Choose checks appropriate to the change and record what actually ran.
