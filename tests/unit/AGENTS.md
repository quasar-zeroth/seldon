# Backend behavior tests

See the [root AGENTS.md](../../AGENTS.md) for the project-wide lookup table and [tests guidance](../AGENTS.md) for fixtures and offline execution. Implementation, schemas, migrations, CLI help, and executable tests are authoritative; phase numbers in filenames are historical labels.

## Design and file map

These tests combine deterministic unit checks with real SQLite transactions and FastAPI/CLI workflows. They protect persistence, provenance, revision conflicts, and observable behavior across layers.

| Files or family | Responsibility |
| --- | --- |
| `test_phase_a_baseline.py` | Public imports, package metadata, and naming. |
| `test_phase_c_repositories.py`, `test_phase_c1_alignment.py` | Durable tables, CRUD/versioning, filters, audit records, rollback, snapshots, and invocation recording. |
| `test_phase_d_api.py` | HTTP contracts for scenarios, KB, graph, runs, exports, settings, analytics, pagination, and destructive-action confirmation. |
| `test_phase_e_*`, `test_phase_f_*`, `test_phase_g_*` | Context gathering, extraction, entity resolution, evidence-backed graph construction, and convergence. |
| `test_phase_h_*`, `test_phase_i_*`, `test_phase_j_*` | Forecast validation/activation, history, feedback/calibration, and advanced intelligence. |
| `test_phase_k_operations.py`, `test_followup_c11_production_ops.py`, `test_followup_c11_durable_orchestration.py` | Authentication, jobs, backups/restore, retention, health/metrics, leases/recovery, timelines, and SSE. |
| `test_agent_workspace.py` | External-agent apply/export/replay, shared entities, dependency scope, frozen forecasts and hot-take bounds, reruns, gates, stale revisions, rollback, CLI/API, and Python-agent interoperability. |
| `test_transcripts.py` | Video URL canonicalization, supplied caption formats, YouTube track selection, Supadata sync/async/errors, fallback order, transcript versions/replay/conflicts, excerpt window/quote checks with rollback, attach, source identities, pipeline stage, rerun queuing, mentions, CLI and HTTP. `httpx` and `requests` are blocked. |
| `test_cycles.py` | Cycle model recovery and red-noise rejection, oscillator overshoot, residual discovery, event persistence/replay/conflicts, derived factors, composites, topic relevance selection/ordering, cycle guidance in handoffs and reruns, frozen forecast context/staleness, reports, CLI and HTTP. |
| `test_workspace_reports.py`, `test_perspectives.py` | Saved report snapshots and tags; claims, assessments, source relationships, provenance, history, and explained connections. |
| `test_config_providers.py`, `test_openrouter_client.py`, `test_followup_c11_agent_llm.py`, `test_followup_c11_model_specialists.py` | Provider configuration, payload/retry/schema contracts, invocation metadata, repair/escalation, and specialist LLM behavior. |
| `test_followup_c11_external_retrieval.py`, `test_followup_c11_retrieval_depth.py`, `test_followup_c11_embeddings.py` | Mocked search/fetch/embedding contracts, provenance, SQLite search fallback, and pgvector SQL text. |
| `test_followup_c11_graph_algorithms.py`, `test_followup_c11_cross_scenario_intelligence.py`, `test_followup_c11_ux_exports.py` | Centrality/cascades, reusable graph lineage, cross-scenario analysis, merge review, and report formats. |
| `test_knowledge_graph.py`, `test_predictor.py`, `test_gold_scenario_e2e.py` | Compatibility JSON graph/predictor behavior and regressions against question-as-fact or stopword graph pollution. |

Workspace tests explicitly forbid provider access. Coordinator tests often use development fallbacks or fake LLMs; success does not establish live model quality. The pgvector check reads migration text and does not run a PostgreSQL database. The gold regression tests exercise the built-in pipeline, not a replay of every JSON file in `examples/gold`.

Add regression coverage where the supported behavior lives, reusing fixtures without weakening production validation. Update relevant AGENTS.md files whenever guidance is missing, stale, or newly needed. Keep these maps short; split detailed test procedures into focused linked documentation.
