# The Seldon Project — Detailed Implementation Plan

This document turns `prediction-system-plan.md` into an implementation roadmap for the renamed `seldon` repository and Python application.

The project name in user-facing copy should be **The Seldon Project**. The repository, Python package, service names, import paths, and local CLI/app names should use **`seldon`**.

## 0. Implementation Principles

- **Python backend first:** Build the core prediction engine as typed Python modules with a FastAPI service boundary.
- **Agent contracts over prompts:** Each agent gets explicit Pydantic input/output schemas, persistent run records, and test fixtures before complex prompt work.
- **OpenRouter-compatible by default:** All LLM calls route through an OpenRouter adapter that accepts configurable model IDs, routing preferences, timeouts, max tokens, temperature, and fallback policies.
- **Observable and replayable:** Every agent run stores input, output, model, token/cost metadata when available, source references, errors, and elapsed time.
- **Human-auditable:** Predictions, KB facts, graph edges, and scenario changes must be traceable to source evidence and agent decisions.
- **Frontend as operating console:** The frontend should let a human inspect scenarios, KB evidence, graph relationships, prediction confidence, agent runs, calibration, and diffs.

## 1. Target Repository Shape

```text
seldon/
  pyproject.toml
  prediction-system-plan.md
  implementation-plan.md
  README.md
  src/seldon/
    api/                    # FastAPI app, routers, dependencies
    agents/                 # Agent base class and specialist agents
    core/                   # Shared types, time, IDs, errors, result wrappers
    data/                   # Repositories, DB sessions, migrations
    graph/                  # ERG services and graph algorithms
    kb/                     # Knowledge-base models, vector indexing, search
    llm/                    # OpenRouter client, model registry, JSON parsing
    predictions/            # Scenario store, prediction engine, scoring
    runs/                   # Agent run orchestration, message bus, queues
    feedback/               # Outcome monitor, calibration, root cause analysis
    cli/                    # Optional Typer CLI for local/dev operations
  apps/web/                 # Next.js/React frontend
  tests/
    unit/
    integration/
    fixtures/
```

Keep the existing `src/seldon/graph` and `src/seldon/predictions` code as the seed, but migrate from file-only JSON storage toward repository interfaces backed by SQLite/PostgreSQL.

## 2. Backend Technology Plan

### Core stack

- Python 3.12+
- FastAPI for HTTP API
- Pydantic v2 for schemas/contracts
- SQLAlchemy 2.x + Alembic for relational storage
- SQLite for local development; PostgreSQL for production
- pgvector on PostgreSQL, with a SQLite-friendly fallback for local/dev vector search
- NetworkX initially for in-process graph algorithms; persist canonical graph entities/edges in DB
- httpx for OpenRouter API calls
- tenacity or custom retry policy for transient LLM/API failures
- pytest + pytest-asyncio for tests
- ruff + mypy/pyright for quality gates

### API service responsibilities

- Scenario lifecycle management
- KB ingestion/search/audit
- ERG nodes/edges and graph traversal queries
- Agent run orchestration and status
- Prediction generation, update, resolution, and calibration
- Frontend-facing summaries, timelines, graphs, and diffs

## 3. OpenRouter Model Compatibility

### Configuration model

Add a first-class model registry under `seldon.llm`:

```python
class OpenRouterConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
    app_name: str = "The Seldon Project"
    site_url: str | None = None
    timeout_seconds: float = 90
    default_model: str = "anthropic/claude-sonnet-4.5"
    fast_model: str = "anthropic/claude-haiku-4.5"
    reasoning_model: str = "openai/gpt-5.1"
    embedding_model: str = "text-embedding-3-small"
    fallback_models: list[str] = []
```

Each agent should declare a `model_profile`, not a hardcoded model:

- `fast`: extraction, summarization, dedupe candidates
- `balanced`: synthesis, scenario writing, graph consistency checks
- `reasoning`: instability analysis, root cause analysis, adversarial review
- `embedding`: KB/vector indexing

Map profiles to OpenRouter model IDs in config so models can be swapped without code changes.

### OpenRouter adapter requirements

- Implement `complete_json(messages, system=None, model=None, schema=None, **kwargs)` compatible with the existing `LLMClientProtocol`.
- Send OpenAI-compatible chat completion requests to `/chat/completions`.
- Include OpenRouter headers when configured:
  - `Authorization: Bearer $OPENROUTER_API_KEY`
  - `HTTP-Referer` if `site_url` exists
  - `X-Title: The Seldon Project`
- Support:
  - JSON mode / structured outputs where the selected model supports it
  - tool-free fallback JSON extraction when strict JSON mode fails
  - configurable temperature, max tokens, top_p, reasoning effort where supported
  - retries on 429/5xx with backoff and clear failure records
  - per-agent model override
  - run metadata capture: model, provider, latency, token usage, estimated cost when returned

### Config examples

```toml
[llm.openrouter]
default_model = "anthropic/claude-sonnet-4.5"
fast_model = "google/gemini-2.5-flash"
reasoning_model = "openai/gpt-5.1"
fallback_models = ["openrouter/auto"]

[agents.query_decomposer]
model_profile = "fast"
temperature = 0.1

[agents.scenario_synthesizer]
model_profile = "reasoning"
temperature = 0.2
```

## 4. Data Model Implementation

### Phase 1 storage entities

Create database tables and Pydantic schemas for:

- `kb_entries`
- `kb_entry_versions`
- `kb_entry_contradictions`
- `sources`
- `erg_nodes`
- `erg_edges`
- `scenario_predictions`
- `scenario_versions`
- `scenario_evidence_links`
- `agent_runs`
- `agent_messages`
- `model_invocations`
- `audit_log`

### KBEntry fields

Implement the fields from `prediction-system-plan.md`:

- content, original snippet, source type/url/name
- created/updated/valid_from/valid_until timestamps
- topics, entities, scenario_ids
- perspective tags: sentiment, political lean, geopolitical lens, confidence
- supersession/version fields
- embedding metadata and vector index pointer

### ERG fields

Implement the plan's node and edge structures:

- Node type: entity, event, topic, metric, policy, actor
- Current state and state_updated_at
- Stability and importance scores
- Edge relationship type, strength, confidence, lag, direction, evidence links

### Prediction fields

Move beyond bull/base/bear file sidecars into versioned DB-backed predictions:

- statement, scope, timeframe, resolution criteria
- scenarios with probabilities and confidence
- key drivers/nodes
- evidence links
- assumptions
- probability history
- status: draft, active, monitoring, resolved, archived
- outcome and calibration result

Markdown export can remain as an optional generated read-only view.

## 5. Backend API Plan

### Core routes

- `GET /health`
- `GET /config/models`
- `PATCH /config/models` for local/dev model overrides if safe
- `POST /scenarios`
- `GET /scenarios`
- `GET /scenarios/{id}`
- `POST /scenarios/{id}/run-context-gathering`
- `POST /scenarios/{id}/run-extraction`
- `POST /scenarios/{id}/run-graph-construction`
- `POST /scenarios/{id}/run-prediction`
- `POST /scenarios/{id}/run-feedback`
- `GET /kb/search`
- `GET /kb/entries/{id}`
- `POST /kb/entries`
- `GET /graph/nodes`
- `GET /graph/nodes/{id}`
- `GET /graph/edges`
- `GET /graph/neighborhood/{node_id}`
- `GET /runs`
- `GET /runs/{id}`
- `POST /runs/{id}/retry`
- `GET /calibration/summary`

### Streaming/frontend updates

Start simple with polling. Add Server-Sent Events later:

- `GET /events/runs` for agent run updates
- `GET /events/scenarios/{id}` for live scenario/prediction updates

## 6. Frontend Plan

### Recommended stack

- Next.js + React + TypeScript
- Tailwind CSS or shadcn/ui for fast dashboard development
- TanStack Query for API data fetching/cache
- React Flow or Sigma.js for graph visualization
- Recharts/Visx for confidence and calibration charts
- Monaco editor or simple markdown viewer for plan/prompt/evidence inspection

### Main screens

1. **Home / Mission Control**
   - Active scenarios
   - Latest prediction updates
   - Agent runs in progress
   - Alerts: contradictions, high instability, stale predictions, failed runs

2. **Scenario Detail**
   - Scenario statement, timeframe, status, confidence
   - Bull/base/bear or multi-branch probabilities
   - Evidence chain
   - Assumptions registry
   - Probability history chart
   - Scenario version diffs
   - Run buttons for each phase

3. **Knowledge Base Explorer**
   - Semantic search
   - Filters: topic, entity, source, date, perspective, confidence
   - Provenance view
   - Contradiction/supersession indicators

4. **Graph Explorer**
   - Nodes/edges visualization
   - Relationship filters
   - Confidence/strength/lag overlays
   - Neighborhood expansion
   - Importance/stability heatmap

5. **Agent Runs Console**
   - Timeline of phase and specialist runs
   - Inputs/outputs/model metadata
   - Retry failed run
   - Compare outputs across model choices

6. **Calibration & Feedback**
   - Brier score / calibration curves
   - Resolved predictions
   - Miss analysis
   - Model/profile performance by agent type

7. **Settings**
   - OpenRouter model IDs by profile
   - Agent-specific overrides
   - Source configuration
   - Persistence/vector backend status

## 7. Phased Implementation Roadmap

## Phase A — Rename, Baseline, and Compatibility

Goal: make the existing repo cleanly become `seldon` without changing behavior.

Backend tasks:

- Rename package/imports from `intelligence` to `seldon`.
- Rename project metadata in `pyproject.toml`.
- Update README to use `seldon` for package/app and **The Seldon Project** for prose.
- Keep compatibility aliases only if Parallax or other consumers still import `intelligence`.
- Run and fix existing tests.

Deliverables:

- `src/seldon` imports pass.
- Existing prediction and graph tests pass.
- Repo path is `/home/sid/xyz/seldon`.
- Existing user plan is `/home/sid/xyz/seldon/prediction-system-plan.md`.

## Phase B — OpenRouter LLM Foundation

Goal: make every agent/model call configurable through OpenRouter.

Backend tasks:

- Create `seldon.llm.openrouter.OpenRouterClient`.
- Extend `LLMClientProtocol` with async support or add separate async protocol.
- Add model profiles: fast, balanced, reasoning, embedding.
- Add per-agent model config.
- Add structured JSON response handling with validation retries.
- Store model invocation metadata in `model_invocations`.
- Replace hardcoded models in config with OpenRouter profile references.

Tests:

- Unit test request payload construction.
- Unit test fallback model selection.
- Unit test malformed JSON recovery.
- Integration test with mocked OpenRouter responses.

Frontend tasks:

- Settings page mock for model profiles.
- Display model used on agent run rows.

Phase B implementation note:

- `apps/web` is not bootstrapped yet, so the Phase B frontend work is intentionally deferred.
- The model-profile settings mock and agent-run model display should be implemented in Phase D after the FastAPI shell and web app skeleton exist.

## Phase C — Persistence Layer and Auditability

Goal: replace file-only state with a durable DB-backed core.

Backend tasks:

- Add SQLAlchemy models and Alembic migrations.
- Implement repository interfaces:
  - `KBRepository`
  - `GraphRepository`
  - `ScenarioRepository`
  - `AgentRunRepository`
  - `AuditRepository`
- Support SQLite locally.
- Add transaction-scoped writes with audit log records.
- Keep JSON/Markdown exporters for human-readable snapshots.

Tests:

- Repository CRUD tests.
- Migration smoke test.
- Audit log emitted on create/update/supersede.

Frontend tasks:

- Basic scenario list from API.
- Basic KB entry detail view.

Phase C implementation note:

- The backend persistence core is in place: SQLAlchemy models, Alembic migration, SQLite support, repository interfaces, audit records, version rows, and Markdown snapshot exporters.
- The Phase C frontend tasks depend on the Phase D FastAPI shell and `apps/web`; they are intentionally deferred into Phase D.

## Phase C.1 — Persistence Completion and Plan Alignment

Goal: close the remaining data-architecture gaps found during the Phase A–C verification pass before building substantial agent workflows on top of the DB.

Backend tasks:

- Add full Pydantic create/read/update schemas for every Phase C table, not just the primary create contracts:
  - `sources`, `kb_entry_versions`, `kb_entry_contradictions`
  - `scenario_versions`, `scenario_evidence_links`
  - `agent_runs`, `agent_messages`, `model_invocations`, `audit_log`
- Add a relational `scenarios` table for the plan-level Scenario object (`name`, `description`, `target_question`, `time_horizon`, `erg_snapshot_id`, `kb_snapshot_at`) and link `scenario_predictions` to it.
- Add `feedback_entries` for the prediction-system plan's feedback store (`actual_outcome`, comparison, missed factors, graph corrections, lessons learned).
- Add `content_embedding` or an explicit embedding/vector record contract for KB entries, while keeping `embedding_metadata` and `vector_index_pointer` as backend metadata.
- Extend `KBRepository.search` beyond substring/topic/entity filters with:
  - semantic/vector search adapter boundary
  - temporal filters (`valid_from`, `valid_until`, `created_at`, `updated_at`)
  - delta queries (`updated_since`)
  - supersession/current-only filtering
  - scenario lookup
  - perspective filtering
  - decay scoring and confidence aggregation helpers
- Add graph snapshot persistence/export so ERG snapshots can be versioned and diffed over time.
- Add graph reuse helpers for cross-scenario node/edge discovery and import suggestions.
- Bridge Phase B invocation metadata into the relational `model_invocations` repository; keep JSONL only as an optional local debug/export path.
- Add OpenRouter retry/backoff for 429/5xx responses with tests, since current fallback-model retry does not yet implement status-aware backoff.
- Add repository tests for transaction rollback behavior, read/update schemas, KB temporal/perspective filters, graph snapshots, feedback entries, and relational model invocation recording.

Frontend/API carry-forward:

- Implement the Phase C frontend tasks after Phase D exposes the API: basic scenario list and KB entry detail view.

Phase C.1 implementation note:

- Implemented in the backend with `scenarios`, `feedback_entries`, graph snapshots/diffs, content embeddings, expanded schemas, KB temporal/perspective/current filters, decay/confidence helpers, graph reuse candidates, relational model invocation recording, and OpenRouter 429/5xx retry/backoff tests.
- Remaining frontend/API carry-forward stays in Phase D because it depends on the FastAPI shell and web app skeleton.

## Phase D — FastAPI Backend Shell

Goal: expose stable service endpoints for frontend and future automations.

Backend tasks:

- Create `seldon.api.app:create_app()`.
- Add dependency injection for config, DB session, LLM client.
- Implement health/config/scenario/kb/graph/run routes.
- Add OpenAPI docs.
- Add consistent error response shape.
- Add CORS config for local web app.

Tests:

- API route smoke tests with TestClient.
- Error handling tests.
- Config loading tests.

Frontend tasks:

- Next.js app bootstrapped in `apps/web`.
- API client generated or manually typed.
- Mission Control skeleton wired to `/health`, `/scenarios`, `/runs`.
- Add Settings page mock for OpenRouter model profiles and agent-specific overrides deferred from Phase B.
- Display model/profile used on agent run rows once `/runs` exposes invocation metadata.

## Phase E — Phase 1 Agents: Context Gathering

Implements plan agents 1.0–1.5.

Agents:

1. `ContextGatheringCoordinator`
   - Input: scenario question/topic, timeframe, depth, source policy
   - Output: run plan and child run IDs

2. `QueryDecomposer`
   - Breaks a scenario into search/retrieval subquestions.
   - Uses fast/balanced model profile.

3. `InformationRetriever`
   - Retrieves from existing KB first.
   - Supports pluggable web/API retrieval later.
   - Stores raw source references.

4. `InformationSummarizer`
   - Summarizes retrieved source material into temporally tagged observations.
   - Preserves original snippets and source URLs.

5. `DeduplicationDeltaDetector`
   - Finds duplicate or superseding facts.
   - Flags new-vs-known deltas.

6. `KBWriter`
   - Validates and writes KB entries.
   - Links entries to scenarios.
   - Emits audit log.

Backend tasks:

- Agent base class with typed `run()` contract.
- Agent run persistence.
- Phase coordinator that serializes child agents at first; queues can come later.
- KB semantic search fallback initially keyword-based if embeddings are not done yet.

Frontend tasks:

- Scenario action: “Gather Context”.
- Agent run timeline.
- KB entries created from a run.

## Phase F — Phase 2 Agents: Entity, Event, and Topic Extraction

Implements plan agents 2.0–2.4.

Agents:

1. `ExtractionCoordinator`
2. `EntityExtractor`
3. `EventExtractor`
4. `TopicThemeExtractor`
5. `NodeDeduplicatorMerger`

Backend tasks:

- Convert existing `EntityExtractor` into schema-validated agent.
- Add event and topic extraction schemas.
- Write ERG nodes with evidence KB links.
- Add merge proposals before destructive merges.
- Keep all original node IDs as aliases when merging.

Tests:

- Entity extraction fixture tests.
- Merge proposal tests.
- Graph repository write tests.

Frontend tasks:

- Scenario entity/topic panel.
- Node merge review UI.
- Graph explorer v1 using persisted nodes/edges.

## Phase G — Phase 3 Agents: Relationship Graph Construction

Implements plan agents 3.0–3.3 and the convergence loop across phases 1–3.

Agents:

1. `GraphConstructionCoordinator`
2. `PairwiseRelationshipDetector`
3. `GraphConsistencyChecker`
4. `ImportanceScorer`

Backend tasks:

- Generate candidate node pairs by scenario scope and KB evidence overlap.
- Ask LLM only for bounded candidate pairs, not all graph pairs.
- Store edge strength, confidence, lag, direction, and evidence IDs.
- Add graph consistency checks:
  - circular contradictions
  - unsupported high-confidence edges
  - stale relationships
  - duplicate edges
- Compute importance using degree, centrality, scenario usage, and evidence count.
- Implement convergence loop:
  - run context gathering
  - run extraction
  - run graph construction
  - detect gaps
  - loop until max iterations or marginal new info falls below threshold

Frontend tasks:

- Relationship evidence drawer.
- Edge confidence/strength controls.
- Graph heatmap for importance.

## Phase H — Phase 4 Agents: Prediction Engine

Implements plan agents 4.0–4.4.

Agents:

1. `PredictionCoordinator`
2. `NodeStatePredictor`
3. `GraphTraversalSimulator`
4. `InstabilityAnalyzer`
5. `ScenarioSynthesizer`

Backend tasks:

- Create versioned scenario prediction model.
- Implement node state forecasts with confidence and time horizon.
- Simulate graph propagation from changed nodes.
- Detect instability hotspots and cascade risks.
- Synthesize scenarios with probabilities, rationale, drivers, assumptions, and resolution criteria.
- Validate probabilities sum correctly.
- Link each prediction to KB entries and graph nodes/edges.
- Preserve the existing prediction markdown renderer as an exporter.

Tests:

- Scenario probability validation.
- Prediction versioning.
- Instability scoring.
- Snapshot tests for markdown export.

Frontend tasks:

- Prediction detail page.
- Probability history chart.
- Driver/assumption/evidence tabs.
- Scenario diff viewer.

## Phase I — Phase 5 Agents: Feedback and Learning

Implements plan agents 5.0–5.3.

Agents:

1. `FeedbackCoordinator`
2. `OutcomeMonitor`
3. `RootCauseAnalyzer`
4. `CalibrationTracker`

Backend tasks:

- Add prediction resolution workflow.
- Implement outcome check records.
- Compute calibration metrics:
  - Brier score
  - log score where appropriate
  - bucketed calibration by confidence range
  - per-model/per-agent performance
- Root cause analyzer compares prediction assumptions vs observed outcome.
- Update KB with feedback corrections.
- Mark superseded facts and failed assumptions.

Frontend tasks:

- Resolution review screen.
- Calibration dashboard.
- Miss analysis view.

## Phase J — Advanced Intelligence Features

Implements section 7 of the plan.

Agents/features:

- `AdversarialRedTeamAgent`
- `HistoricalAnalogyMatcher`
- `BaseRateAnchorer`
- `SentimentDriftTracker`
- `AssumptionRegistry`
- `UncertaintyQuantificationLayer`
- `ExpertPerspectiveSimulator`
- `InformationValueCalculator`
- `ScenarioVersioningDiff`
- `CascadeRiskScorer`

Backend tasks:

- Add red-team pass before scenario activation.
- Store base rates and analogies as first-class evidence.
- Track sentiment drift by topic over time.
- Add assumption objects and assumption status.
- Quantify uncertainty separately from scenario probability.
- Estimate value of new information and suggest next retrieval tasks.

Frontend tasks:

- Red-team critique panel.
- Historical analogies panel.
- Assumption registry table.
- Uncertainty and cascade risk visualizations.

## Phase K — Productionization and Operations

Backend tasks:

- Add background job runner: start with in-process task queue; consider Dramatiq/Celery/RQ later.
- Add auth if exposed beyond localhost.
- Add structured logs.
- Add backups for DB and vector index.
- Add Dockerfile and compose file for API + web + Postgres.
- Add seed/demo data.
- Add CI checks:
  - ruff
  - typecheck
  - pytest
  - frontend lint/typecheck/build

Frontend tasks:

- Empty states and error states.
- Loading/progress states for agent runs.
- Responsive graph explorer.
- Export/download buttons for scenario reports.

## Follow-up A — Detailed Verification Misses

This verification pass reviewed `implementation-plan.md`, `prediction-system-plan.md`, the committed Phase A-K code, tests, API, persistence layer, agents, frontend, and production files. The current implementation is a strong end-to-end skeleton: DB-backed scenarios/KB/ERG/predictions exist, Phase E-J coordinators run, FastAPI routes expose the core workflow, the Next.js console builds, and Phase K ops basics are present. The items below are the remaining gaps or partial implementations against the plan.

### A.1 Repository shape and platform foundations

- **Missing package directories from target shape:** `src/seldon/core`, `src/seldon/kb`, `src/seldon/runs`, `src/seldon/feedback`, and `src/seldon/cli` were not created as first-class packages. Their responsibilities are currently folded into `data`, `agents`, `api`, and `ops`.
- **PostgreSQL/pgvector is not actually implemented:** the app can use SQLAlchemy URLs and ships Postgres in compose, but there is no pgvector schema, extension setup, vector repository, or production vector search backend.
- **NetworkX graph adapter is still missing:** the legacy NetworkX code remains, but there is no DB-to-NetworkX graph view/adapter for traversal algorithms.
- **Message bus remains implicit only:** agent messages are modeled, but coordinator/specialist communication is still direct function calls; there is no structured internal message flow beyond persisted `AgentRun` input/output.
- **CLI operations are not implemented:** no Typer/local CLI exists for scenarios, jobs, backups, seed data, or local operations.

### A.2 OpenRouter/model foundation gaps

- **Live agent flows do not actually call OpenRouter for Phase E-J reasoning:** most agents are deterministic heuristics and do not invoke `llm_client.complete_json`, so model profiles exist but are not exercised in the main workflow.
- **Per-agent model configuration is not wired into `AgentBase`:** `AgentsConfig` declares overrides, but `AgentBase` and specialists do not resolve agent-specific temperature/max token/model overrides when calling the LLM.
- **Relational model invocation capture is not wired to live API runs:** `DatabaseModelInvocationRecorder` exists, but `create_app()` constructs `OpenRouterClient(app_config.llm)` without a DB recorder, and recorder rows do not attach `agent_run_id` automatically.
- **Structured validation retries are incomplete:** malformed JSON extraction and fallback-model retries exist, but there is no explicit validation-repair retry loop that re-prompts the model with schema errors.
- **Provider/cost metadata is only pass-through:** invocation metadata stores fields when returned, but no cost estimator or provider normalization layer was implemented.
- **Escalation rules are not implemented:** confidence/complexity-based escalation from fast to balanced/reasoning models is not applied in agents.

### A.3 Persistence/API gaps

- **CRUD coverage is incomplete for several tables:** schemas exist for many entities, but API routes are missing for sources, KB versions, contradictions, graph snapshots/diffs/reuse candidates, scenario versions, scenario evidence links, feedback entries, agent messages, model invocations, and audit log browsing.
- **KB search API exposes only a subset of repository filters:** `/kb/search` supports query/topic/entity/scenario/current-only, but not temporal filters, updated-since, sentiment/perspective filters, confidence filters, decay scoring, confidence aggregation, or semantic/vector search mode.
- **Config model patching is in-memory only:** `PATCH /config/models` mutates the running config object but does not persist overrides to TOML/env/config files and has no safety/validation policy beyond raw assignment.
- **SSE/live update routes are not implemented:** `/events/runs` and `/events/scenarios/{id}` remain deferred.
- **Run retry is a stub:** `/runs/{id}/retry` creates a pending run record but does not re-dispatch the original agent/coordinator.
- **Background jobs are limited to manual in-process queue actions:** backup and seed jobs work, but phase runs are still synchronous request handlers rather than queued jobs with progress polling.

### A.4 Phase E — Context gathering misses

- **External retrieval is not implemented:** `InformationRetriever` searches only the existing KB and falls back to the scenario brief; it does not run web/news/API/forum searches, fetch documents, or perform 2-3 search variations per subquery.
- **No raw document ingestion pipeline:** there is no fetch/boilerplate stripping/relevance filtering layer for retrieved external documents.
- **Summarization is heuristic:** `InformationSummarizer` truncates/source-copies one retrieved source rather than extracting discrete factual claims from long documents with temporal, entity, sentiment, surprise, and contradiction tags.
- **Dedup/delta detection is basic:** it uses normalized text/source/topic checks rather than embeddings, semantic thresholds, update-vs-new decisions, or contradiction detection/resolution.
- **Coordinator loop is single-pass:** no coverage scoring, gap detection, new subquery generation, max rounds, or diminishing-return loop is implemented inside context gathering.
- **Embeddings/vector index writes are absent:** `KBWriter` does not compute embeddings or update a vector index.

### A.5 Phase F — Extraction misses

- **Extraction is heuristic, not LLM/schema-prompt based:** entity/event/topic extraction uses compact term rules and hints instead of model-backed extraction over KB batches.
- **Completeness check is missing:** `ExtractionCoordinator` does not ask whether obvious important entities/events/topics are missing and does not route targeted gaps back to Phase E.
- **Merge review is proposal-only and exact-match based:** no fuzzy semantic merge, ambiguous merge escalation, alias table, or durable alias preservation beyond proposal fields exists.
- **Destructive merge workflow is not implemented:** there is no UI/API action to approve merges and rewrite node references safely.

### A.6 Phase G — Relationship graph construction misses

- **Relationship detection is heuristic, not model-backed:** `PairwiseRelationshipDetector` infers relationship type from keywords rather than asking a bounded LLM relationship detector for concrete mechanisms.
- **Candidate generation is narrower than planned:** it uses shared/co-occurring evidence only; there is no first-pass plausible relationship classifier, cluster pruning, or missing-obvious-relationship suggestion pass.
- **Consistency checking is partial:** duplicate, unsupported, stale marker, and some reverse contradictions are checked; orphan nodes, disconnected subgraphs, overly dense clusters, and missing obvious relationships are not.
- **Importance scoring lacks graph centrality/PageRank:** it uses degree/evidence/scenario usage heuristics, not NetworkX/PageRank-style centrality.
- **Convergence loop ignores coverage target and gap semantics:** `coverage_target` is accepted but unused, contradictions resolved are not tracked, and the loop does not detect new implied nodes/subqueries beyond marginal counts.

### A.7 Phase H — Prediction engine misses

- **Node predictions are simplified:** `NodeStatePredictor` emits one direction/forecast per node, not 2-5 possible state changes with probabilities and reasoning per node.
- **Traversal simulation is shallow:** `GraphTraversalSimulator` inspects immediate edges touching forecast nodes; it does not perform DFS/BFS cascades from starting conditions, cumulative probability propagation, independence adjustments, convergence detection, or path instability loops.
- **Instability analysis is heuristic:** it flags low stability/evidence and strong low-confidence edges, but does not deeply analyze feedback-loop contradictions or propose graph corrections.
- **Scenario synthesis is fixed bull/base/bear:** it does not cluster traversal results into 3-7 arbitrary coherent scenarios ranked by probability/impact.
- **Prediction activation/red-team gate is incomplete:** red-team review exists in Phase J as a separate endpoint, but it is not run before activation in `PredictionCoordinator`.
- **Base rates are not integrated before prediction:** Phase J stores base-rate evidence after a prediction, but node state/synthesis does not consume base-rate priors.

### A.8 Phase I — Feedback and learning misses

- **Outcome monitoring is manual only:** feedback requires supplied actual outcome; it does not search external ground truth or run on a schedule for active scenarios.
- **Graph corrections are stored but not applied:** feedback records `graph_corrections`, but no add/modify/remove node/edge actions are executed.
- **Failed assumptions and superseded facts are not marked in core stores:** root cause diagnostics record failed assumptions, but assumption records/KB supersession are not updated automatically.
- **Calibration is basic:** Brier/log/buckets are computed, but per-agent/per-model metrics are mostly run/invocation counts rather than calibrated forecast accuracy by agent/model/profile.
- **Re-prediction trigger is missing:** feedback does not decide whether new evidence/corrections require a fresh scenario prediction.

### A.9 Phase J advanced intelligence misses

- **Advanced agents are mostly heuristic placeholders:** red-team, analogies, base rates, sentiment drift, expert perspectives, value of information, and cascade risk are deterministic approximations rather than model-backed or data-backed analyses.
- **Cross-scenario intelligence from the system plan is missing:** no Shared Graph Manager or Cross-Scenario Correlation Detector exists to propose starter graphs, flag shared dependency changes, detect contradictory predictions, or find scenario synergies.
- **Assumption registry is on-demand only:** there is no periodic assumption validity checker or automatic dependent-scenario flagging.
- **Historical/base-rate evidence lacks external datasets:** analogies and base rates are derived from existing KB/prediction probabilities, not historical series or comparable external data.

### A.10 Frontend misses

- **Only a single Mission Control page exists:** there are no dedicated Scenario Detail, KB Explorer, Graph Explorer, Agent Runs Console, Calibration/Feedback, or Settings pages.
- **Most frontend controls are read-only mock panels:** run buttons, merge approval, edge confidence/strength editing, scenario creation, feedback resolution, and settings persistence are not implemented.
- **Graph visualization library is not integrated:** the graph explorer is list-based, not React Flow/Sigma with relationship filters, overlays, neighborhood expansion, or responsive interactive graph controls.
- **Charts are not implemented:** probability history, calibration curves, confidence charts, uncertainty, sentiment drift, and cascade-risk visualizations are not present.
- **Frontend has no mutation flows:** API client reads data but does not expose UI workflows for creating scenarios, running phases, retrying runs, resolving predictions, or downloading backend-generated exports beyond a client-side markdown report.

### A.11 Phase K production/ops misses

- **Auth is minimal:** API-key middleware exists, but no user/session model, role policy, secrets guidance, or production auth integration exists.
- **Backups are DB-focused:** vector index backup is configured but only included when present; there is no restore workflow, retention policy, or scheduled backup job.
- **Docker compose is basic:** it starts API/web/Postgres but does not run migrations, configure pgvector, provide healthcheck-gated dependencies, or include production secrets handling.
- **CI is broad but not complete production hardening:** it runs lint/typecheck/tests/build, but no Docker build smoke, migration upgrade/downgrade check, security scan, or coverage gate is included.
- **Responsive graph explorer/export buttons are partial:** empty/loading/error states and a report download exist, but responsive interactive graph and backend scenario report export/download endpoints remain missing.

### A.12 Test coverage misses

- **Tests mostly validate deterministic skeleton behavior:** there are good unit/API/build checks, but not full model-backed agent contracts, external retrieval, vector search, graph traversal depth, red-team activation gates, correction application, or cross-scenario intelligence.
- **No end-to-end external-data workflow test:** there is no test that creates a scenario, retrieves external sources, writes KB entries with embeddings, extracts nodes, builds relationships, predicts, red-teams, resolves, calibrates, and re-predicts.
- **No frontend interaction tests:** there are no Playwright/React tests for dashboard workflows, error states, run buttons, merge approval, or feedback resolution.

### A.13 Implementation progress from Follow-up A batch 1

Implemented in the first follow-up batch:

- Added a first-class `seldon.kb` package with deterministic local embeddings and cosine ranking as a SQLite-friendly vector-search seam.
- Auto-populated KB `content_embedding`, `embedding_metadata`, and `vector_index_pointer` on create/update when embeddings are not supplied.
- Expanded API coverage for sources, KB versions/supersession/contradictions, graph node/edge updates, graph snapshots/diffs/reuse candidates, prediction CRUD/version/evidence links, run messages, model invocations, audit log browsing, feedback entries, historical analogies, base rates, and sentiment drift.
- Added queued phase execution via `/scenarios/{scenario_id}/jobs/{phase}` and registered a generic `phase` background job handler for context gathering, extraction, graph construction, and prediction.
- Improved `/runs/{run_id}/retry` so coordinator runs can be re-dispatched as phase jobs when the original scenario is known.
- Expanded KB search API with updated/valid-time filters, sentiment/confidence filters, semantic mode, and optional decay/confidence score metadata.
- Allowed context gathering requests to include explicit external documents, which are folded into retrieval results and written through the normal KB pipeline.
- Applied supported feedback graph corrections (`add_node`, `add_edge`, `modify_node`, `modify_edge`) instead of only storing them.
- Marked matching assumption records invalid when feedback flags failed assumptions.
- Added frontend API mutation helpers plus Mission Control forms for scenario creation, queued phase runs, and run retry.

Still remaining after batch 1: true external web/news retrieval, production pgvector, model-backed E-J agents, full LLM invocation recorder binding, deep graph traversal, red-team pre-activation gating, cross-scenario intelligence agents, dedicated frontend pages/interactive graph/charts, restore/retention ops, and end-to-end/browser tests.


## Follow-up B — Full GUI Integration and Dedicated UX Workstreams

Follow-up B turns the current single-page Mission Control skeleton into the full backend-integrated Seldon operating console described in the frontend plan. This work should use `design.md` as the shared design contract for layout, navigation, visual language, mutation behavior, graph interaction, charts, and backend integration rules. Every frontend element introduced in Follow-up B — pages, forms, cards, tables, charts, graph controls, drawers, dialogs, empty states, loading states, and errors — should be designed against the principles and conventions in `design.md` before implementation.

Current state to improve:

- `apps/web` exists and builds as a Next.js app.
- The GUI currently concentrates most functionality into `/` (`Mission Control`).
- It reads real backend endpoints for health, scenarios, runs, graph nodes/edges, predictions, and model config.
- It has a few real mutation flows: create scenario, queue phase jobs, and retry runs.
- Many planned UX surfaces are still missing or partial: dedicated pages, interactive graph visualization, charts, settings persistence, feedback resolution, merge approval, edge editing, KB exploration, run details, backend report exports, browser tests, and production auth/API-key handling.

### B.1 Routing, shell, and shared design system

Goal: establish the web app structure needed for multiple pages without duplicating UI logic.

Tasks:

- Add a persistent app shell with navigation for Mission Control, Scenarios, KB, Graph, Runs, Calibration, and Settings.
- Create dedicated routes:
  - `/`
  - `/scenarios`
  - `/scenarios/[id]`
  - `/kb`
  - `/kb/[id]`
  - `/graph`
  - `/runs`
  - `/runs/[id]`
  - `/calibration`
  - `/settings`
- Extract shared UI components guided by `design.md`:
  - `PageHeader`
  - `StatusBadge`
  - `MetricCard`
  - `EvidencePill`
  - `RunStatus`
  - `EmptyState`
  - `ErrorState`
  - `LoadingSkeleton`
  - `ConfirmMutationDialog`
  - `AuditTrail`
  - `SourceLink`
- Split typed API access into focused modules, for example:
  - `api/scenarios.ts`
  - `api/kb.ts`
  - `api/graph.ts`
  - `api/runs.ts`
  - `api/predictions.ts`
  - `api/calibration.ts`
  - `api/settings.ts`
- Add route-level loading and error states for every page.
- Keep Mission Control as an overview page that links into deeper pages instead of trying to contain all workflows.

Backend integration requirements:

- No page should rely on frontend-only mock records for persisted state.
- Each page must document the backend endpoints it consumes.
- Add missing backend read endpoints before wiring any page that needs data unavailable from the API.

Acceptance checks:

- `npm run typecheck`
- `npm run build`
- Basic navigation smoke test or Playwright route-load test for all routes.

### B.2 Scenario list and Scenario Detail page

Goal: make scenario creation, inspection, phase execution, prediction review, and scenario history usable outside the Mission Control overview.

Tasks:

- Build `/scenarios` with searchable/filterable scenario list, creation form, status filters, and latest prediction summary.
- Build `/scenarios/[id]` with:
  - scenario statement, timeframe, status, confidence, and metadata
  - latest prediction card
  - bull/base/bear or multi-branch probability display
  - evidence chain
  - assumptions registry preview
  - phase run controls for context gathering, extraction, graph construction, prediction, advanced intelligence, and feedback where applicable
  - scenario versions and diffs
  - related agent runs and job statuses
- Add mutation flows for:
  - create scenario
  - edit scenario metadata/status
  - queue workflow phases
  - run advanced intelligence for a prediction
  - download/export scenario report from the backend, not only a client-side generated markdown blob

Backend integration requirements:

- Use real scenario endpoints: `GET /scenarios`, `POST /scenarios`, `GET /scenarios/{scenario_id}`, `PATCH /scenarios/{scenario_id}`.
- Use job/agent endpoints: `POST /scenarios/{scenario_id}/jobs/{phase}`, phase-specific run endpoints where needed, `GET /ops/jobs/{job_id}`, `GET /runs`, and `GET /runs/{run_id}`.
- Use prediction endpoints: `GET /predictions?scenario_id=...`, `GET /predictions/{prediction_id}`, versions, evidence links, and advanced intelligence endpoints.
- Add a backend scenario report export endpoint if the UI needs server-generated downloads.

Acceptance checks:

- User can create a scenario, land on its detail page, queue a phase, see job/run status, and refresh to persisted backend state.
- Scenario detail renders useful empty states before agents have run.

### B.3 Knowledge Base Explorer and KB Entry Detail

Goal: expose KB search, provenance, versions, contradictions, supersession, and evidence inspection as first-class workflows.

Tasks:

- Build `/kb` with:
  - semantic and keyword search
  - filters for topic, entity, source, valid date, created/updated date, perspective, sentiment, confidence, current-only, and scenario
  - sortable result list with confidence/decay metadata
  - contradiction and supersession indicators
- Build `/kb/[id]` with:
  - content and summary
  - source/provenance panel
  - linked scenarios, graph nodes/edges, and predictions
  - versions timeline
  - contradictions list
  - supersession state
- Add mutation flows for:
  - create/edit KB entry where appropriate
  - supersede an entry
  - record/update contradiction status
  - link/unlink scenario evidence if needed by prediction workflows

Backend integration requirements:

- Use `GET /kb/search`, `POST /kb/entries`, `GET /kb/entries/{entry_id}`, `PATCH /kb/entries/{entry_id}`, version, supersession, and contradiction endpoints.
- If linked graph/prediction data is missing, add backend endpoints or query parameters rather than deriving relationships only on the client.

Acceptance checks:

- KB search filters round-trip to backend query parameters.
- KB detail shows backend versions and contradiction/supersession state.

### B.4 Dedicated interactive Graph Explorer

Goal: replace the current list-based graph panel with a proper interactive visualization integrated with persisted graph data.

Tasks:

- Add React Flow, Sigma.js, or an equivalent graph visualization library.
- Build `/graph` with:
  - graph canvas
  - node and edge tables as accessible alternatives
  - filters for scenario, node type, relationship type, confidence, strength, direction, lag, evidence count, and importance
  - layout controls: fit view, center selected node, expand neighborhood, reset filters, hide low-confidence edges
  - overlays for confidence, strength, importance, instability, and scenario path
  - node/edge detail drawer with evidence links, related KB entries, model/run provenance, editable fields, and audit history
- Add mutation flows for:
  - edit node state/description/stability/importance metadata
  - edit edge confidence/strength/relationship metadata
  - approve or reject merge proposals
  - create graph snapshots
  - compare graph snapshots/diffs
  - import/reuse cross-scenario candidate nodes/edges where supported

Backend integration requirements:

- Use real graph endpoints: `GET/POST/PATCH /graph/nodes`, `GET/POST/PATCH /graph/edges`, `GET /graph/neighborhood/{node_id}`, snapshot/diff endpoints, and reuse-candidate endpoints.
- Add explicit backend endpoints for merge approval/rejection if current extraction output only stores proposals in agent run output.
- Ensure graph mutations persist audit records and return updated graph rows.

Acceptance checks:

- Graph canvas renders persisted backend nodes/edges.
- Selecting a node/edge opens backend-sourced detail.
- Editing edge confidence/strength persists through refresh.
- Merge approval is not frontend-only; it calls backend mutation endpoints.

### B.5 Agent Runs Console and Run Detail

Goal: make agent execution observable, replayable, and debuggable.

Tasks:

- Build `/runs` with:
  - filters by scenario, phase, agent, status, model/profile, date, and failure state
  - run timeline grouped by scenario or phase
  - retry buttons for failed/retryable runs
  - links to created KB entries, graph changes, predictions, and feedback entries
- Build `/runs/[id]` with:
  - input/output JSON viewer
  - messages
  - model invocations, provider, token/cost metadata where available
  - errors and elapsed time
  - source references
  - retry/re-dispatch action
  - related audit log records

Backend integration requirements:

- Use `GET /runs`, `GET /runs/{run_id}`, messages, model invocation, retry, and audit-log endpoints.
- If run outputs reference generated records by ID, expose convenient backend relation endpoints or include relations in run detail responses.

Acceptance checks:

- User can inspect a run from list to detail, see model metadata, and retry a retryable run.

### B.6 Calibration, Feedback, and Outcome Resolution pages

Goal: make feedback loops and calibration visible and actionable.

Tasks:

- Build `/calibration` with:
  - calibration summary cards
  - Brier/log score display
  - bucketed confidence vs observed frequency chart
  - resolved predictions table
  - miss analysis list
  - root-cause analysis detail drawer
- Add feedback/resolution flows:
  - resolve a prediction with actual outcome
  - record missed factors
  - mark failed assumptions
  - submit graph corrections
  - trigger re-prediction when feedback indicates stale or corrected assumptions
- Add visual warnings for low sample sizes and stale calibration.

Backend integration requirements:

- Use `GET /calibration/summary`, feedback entries, outcome checks, prediction patch/resolution endpoints, and `POST /scenarios/{scenario_id}/run-feedback`.
- Add or refine backend endpoints for prediction resolution if the current feedback flow is not ergonomic for UI use.
- Ensure graph corrections submitted through feedback are persisted and auditable.

Acceptance checks:

- User can resolve a prediction, see calibration update from backend state, and inspect the resulting feedback/root-cause records.

### B.7 Charts and analytical visualizations

Goal: implement the charting promised in the frontend plan.

Tasks:

- Add a charting library such as Recharts or Visx.
- Implement:
  - probability history chart on scenario detail
  - prediction confidence chart
  - calibration curves and bucket charts
  - sentiment drift chart
  - uncertainty/cascade-risk visualization
  - model/profile performance by agent type where backend data exists
- Include empty/sample-size/error states for every chart.

Backend integration requirements:

- Use persisted prediction probability history, calibration summary, sentiment drift, advanced analyses, model invocations, and outcome checks.
- Add backend aggregation endpoints where raw rows would force duplicated chart calculations in the client.

Acceptance checks:

- Charts render from real backend records and survive page refresh.
- Charts clearly communicate missing or insufficient data.

### B.8 Settings page and model/source/backend configuration UX

Goal: replace the current read-only settings mock with a real settings surface.

Tasks:

- Build `/settings` with:
  - OpenRouter model profile IDs
  - agent-specific overrides
  - fallback models
  - source configuration/status
  - persistence backend status
  - vector backend status
  - auth/API-key status
- Add mutation flows for editable runtime settings where safe:
  - update model profiles
  - update fallback models
  - update agent overrides
- Clearly distinguish runtime-editable settings from deploy-time/environment settings.

Backend integration requirements:

- Use `GET /config/models` and `PATCH /config/models` where supported.
- Add backend validation for model/profile updates.
- Do not expose secrets in the UI. Show presence/status only for secret-backed config.

Acceptance checks:

- User can update a safe model/profile setting, see validation errors if invalid, and refresh to the persisted or active backend value.

### B.9 Backend API hardening specifically for GUI integration

Goal: make the backend ergonomic and safe for the full GUI, not just minimally reachable.

Tasks:

- Audit every planned GUI interaction and map it to a backend endpoint.
- Add missing endpoints for:
  - scenario report exports
  - merge proposal approval/rejection
  - prediction resolution if separate from feedback run submission
  - backend aggregation for charts
  - related-record lookups for scenario/KB/graph/run detail pages
  - job/run polling convenience where needed
- Add consistent response schemas for page-facing endpoints.
- Add pagination/sorting/filtering to list endpoints used by the GUI.
- Add API-key/auth support in frontend client helpers and document local vs production behavior.
- Ensure CORS and Docker networking work for local, compose, and production deployments.

Acceptance checks:

- Each GUI mutation has a backend test proving persistence and expected response shape.
- Each page-facing read endpoint has tests for filters, empty states, and not-found cases.

### B.10 Frontend testing, browser tests, and CI gates

Goal: prevent regressions as the GUI becomes multi-page and interactive.

Tasks:

- Add Playwright or equivalent browser tests.
- Add tests for:
  - route loads
  - scenario creation
  - phase job queueing
  - run retry
  - KB search filters
  - graph render and node/edge detail selection
  - edge edit persistence
  - feedback resolution
  - settings validation
- Add component/unit tests for complex UI state where browser tests would be too heavy.
- Keep CI running:
  - `npm run typecheck`
  - `npm run build`
  - frontend tests
  - backend API tests used by GUI flows

Acceptance checks:

- CI fails if a planned route does not build, a core mutation breaks, or backend API contracts used by the GUI drift unexpectedly.

### B.11 Implementation order recommendation

Implement Follow-up B in this order to keep integration risk low:

1. B.1 app shell, routes, shared components, and typed API split.
2. B.9 backend endpoint audit and small missing endpoint additions.
3. B.2 Scenario pages and workflow job status.
4. B.5 Runs console and run detail.
5. B.3 KB Explorer and KB detail.
6. B.4 interactive Graph Explorer and graph mutations.
7. B.6 Calibration/Feedback pages.
8. B.7 charts and analytical visualizations.
9. B.8 Settings persistence.
10. B.10 browser tests and final CI hardening.

Definition of done for Follow-up B:

- Dedicated pages exist for all major planned frontend surfaces.
- Mission Control is an overview, not the only GUI.
- All displayed persistent state is sourced from FastAPI.
- All mutation flows call backend endpoints and persist through refresh.
- Graph visualization uses a real graph library with interactive selection/filtering.
- Charts render from persisted backend data.
- Settings are either safely editable through backend APIs or explicitly marked deploy-time/read-only.
- Docker/local development documentation identifies how the web app reaches the API.
- Frontend build/typecheck and GUI-focused backend tests pass.

## Follow-up C — Remaining Plan Gaps After Full Repo Review

This review pass re-checked the current repo against both `implementation-plan.md` and `prediction-system-plan.md` after Follow-up B work. The project now has the multi-page Next.js console, broad FastAPI CRUD/read coverage, queued phase jobs, graph mutation endpoints, chart surfaces, settings UX, browser regression tests, Docker/CI basics, deterministic local embeddings, and complete Phase E-J skeleton workflows. The remaining work is no longer mostly GUI scaffolding; it is the deeper prediction-system functionality promised in the two plans: real external research, model-backed specialist agents, richer graph/prediction algorithms, production vector/Postgres behavior, durable orchestration, and harder end-to-end validation.

### C.1 External research and ingestion pipeline

- **True web/news/API/forum retrieval is still missing:** `InformationRetriever` searches the existing KB and accepts explicit external documents, but it does not execute 2-3 search variations per subquery, call search/news/forum APIs, fetch result pages, or rank external sources for relevance.
- **Raw document processing is not implemented:** there is no fetcher/reader layer for URL retrieval, boilerplate stripping, content normalization, source date extraction, duplicate URL handling, or raw-document provenance records before summarization.
- **Summarization remains deterministic and shallow:** `InformationSummarizer` creates compact observations from retrieved snippets rather than extracting multiple discrete factual claims from long documents with temporal relevance, entity tags, sentiment/perspective tags, surprise flags, and contradiction flags.
- **Contradiction resolution is not model-backed:** contradictions can be recorded, but there is no Sonnet/reasoning-model adjudication flow that weighs source reliability, dates, and context before marking likely truth or supersession.
- **Delta detection is not semantic enough:** local embeddings exist, but dedup/update decisions still need thresholded semantic comparison, update-vs-new classification, and richer supersession suggestions over existing KB entries.

### C.2 OpenRouter usage, agent intelligence, and model invocation auditability

- **Phase E-J agents are mostly heuristic placeholders:** the coordinator/specialist structure exists, but core agents do not use `llm_client.complete_json` for the planned extraction, relationship detection, prediction reasoning, red-team, root-cause, expert-perspective, and information-value work.
- **Per-agent model config is not consistently applied by live agents:** `AgentsConfig` and `OpenRouterClient` support agent overrides, but `AgentBase` does not provide a standard helper that every specialist uses with its `agent_id`, `model_profile`, temperature, max tokens, validation schema, and escalation policy.
- **Confidence/complexity escalation is not implemented:** specialists do not automatically escalate from fast to balanced/reasoning models when confidence is low, contradictions appear, or a task is inherently complex.
- **Validation-repair retries need to be agent-level:** OpenRouter JSON parsing and schema validation exist, but agents do not re-prompt with schema errors or partial output repair instructions when a structured result fails validation.
- **Relational invocation recording is not bound to app-created LLM clients:** `DatabaseModelInvocationRecorder` exists, but `create_app()` still constructs a plain `OpenRouterClient(app_config.llm)`, so live API/queued phase runs do not automatically attach model invocation rows to the active DB session and `agent_run_id`.
- **Provider/cost normalization remains minimal:** model invocation records store returned metadata, but there is no provider normalization, token-price table, estimated cost fallback, or per-provider reliability tracking.

### C.3 Vector search, embeddings, and storage backend completeness

- **Production pgvector is not implemented:** PostgreSQL is available through SQLAlchemy/compose, but there is no pgvector extension migration, vector column type, vector index, or backend-specific nearest-neighbor query.
- **Embeddings are deterministic local hashes, not model embeddings:** the current SQLite-friendly seam is useful for tests/dev, but the plan calls for OpenRouter-compatible embedding generation and production vector indexing.
- **Vector index lifecycle is incomplete:** KB writes populate `content_embedding`, but there is no separate vector index rebuild command/job, drift detection, embedding model version migration, or restore flow.
- **Semantic ranking is not combined with temporal decay and source confidence everywhere:** repository helpers exist, but retrieval, dedup, UI relevance, and scenario context selection do not consistently use a unified ranking formula.

### C.4 Graph algorithms, reuse, and cross-scenario intelligence

- **DB-to-NetworkX adapter is still missing:** NetworkX remains a dependency/legacy module, but current persisted ERG rows are not exposed as reusable NetworkX graph views for centrality, traversal, connected-components, PageRank, or scenario-path analysis.
- **Relationship detection is heuristic, not evidence-reasoned:** `PairwiseRelationshipDetector` infers relationships from keywords/co-occurrence instead of asking a bounded relationship detector to explain mechanisms, lag, direction, strength, and evidence sufficiency.
- **Importance scoring lacks true centrality:** degree/evidence/scenario heuristics should be replaced or augmented with NetworkX/PageRank-style centrality and dependency depth.
- **Graph consistency checking is partial:** duplicate/unsupported/stale/reverse checks exist, but orphan nodes, disconnected subgraphs, overly dense clusters, missing obvious relationships, and contradictory causal cycles are not fully handled.
- **Merge approval is endpoint-level but not fully discoverable:** approve/reject endpoints exist, but merge proposals are not first-class persisted records with list/detail APIs, review state, alias preservation, and safe reference-rewrite previews.
- **Shared Graph Manager is not implemented:** reuse candidates exist, but there is no agent that proposes starter graphs for new scenarios, imports accepted shared nodes/edges with lineage, and propagates updates across dependent scenarios.
- **Cross-Scenario Correlation Detector is missing:** the system does not detect contradictory predictions, shared dependency changes, scenario synergies, or correlation clusters across active scenarios.

### C.5 Prediction engine depth and activation workflow

- **Node forecasts are simplified:** `NodeStatePredictor` emits one deterministic forecast per node rather than 2-5 possible state changes with probabilities, confidence, reasoning traces, and key assumptions.
- **Traversal simulation is shallow:** `GraphTraversalSimulator` inspects local relationships rather than performing BFS/DFS cascades with cumulative probability propagation, independence adjustment, convergence detection, path logging, and feedback-loop instability.
- **Scenario synthesis is still bull/base/bear centric:** output should support 3-7 arbitrary coherent scenarios clustered from traversal results, not only fixed bull/base/bear branches.
- **Base rates are not consumed before prediction:** Phase J can create base-rate evidence after a prediction, but the prediction agents do not anchor forecasts to historical/base-rate priors or justify deviations.
- **Red-team activation gate is not enforced:** adversarial review exists as an advanced-intelligence endpoint, but `PredictionCoordinator` does not run it before activation or block/flag activation when critique thresholds fail.
- **Prediction version diffs are limited:** scenario/prediction versions exist, but richer diffs should explain probability shifts, driver changes, evidence additions/removals, assumption changes, and graph changes in a human-auditable way.

### C.6 Feedback, learning, and calibration automation

- **Outcome monitoring is manual only:** resolution requires supplied actual outcome; there is no scheduled monitor that searches external ground truth for active predictions near/after resolution dates.
- **Feedback does not trigger re-prediction:** graph corrections and failed assumptions can be stored/applied, but the system does not decide when corrected/stale assumptions require a fresh prediction job.
- **Assumption invalidation is incomplete:** matching assumptions can be marked invalid from feedback, but there is no periodic assumption checker, dependent-scenario alerting, or automatic KB supersession of failed premises.
- **Calibration remains small-sample/basic:** Brier/log/bucket metrics exist, but per-agent/per-model/profile calibration accuracy is not computed from attributed forecasts in a statistically meaningful way.
- **Root-cause analysis is heuristic:** missed-factor and graph-correction analysis should be model-backed and connected to concrete KB/ERG updates with confidence and audit trails.

### C.7 Message bus, orchestration, and live updates

- **Agent messages are persisted but not used as a real message bus:** coordinators call specialists directly; there is no structured inter-agent message envelope, routing state, or replayable message timeline as described in the system plan.
- **Phase jobs are in-process only:** queued jobs work for local use, but they are not durable across process restarts and do not support distributed workers, cancellation, leases, retry policies, or idempotency keys.
- **SSE/live update routes are still absent:** `/events/runs` and `/events/scenarios/{id}` remain unimplemented, so the frontend relies on refresh/navigation rather than streaming run/scenario updates.
- **Run retry remains narrow:** retry can re-dispatch known coordinator phases, but arbitrary specialist runs, advanced-intelligence runs, feedback runs, and failed child-run replay are not generally reconstructable.
- **Convergence loop semantics are still weak:** coverage targets, gap semantics, contradiction resolution counts, and new implied subqueries/nodes are not used as first-class stop/continue criteria.

### C.8 API and frontend workflow gaps that remain after Follow-up B

- **Pagination/sorting is incomplete across large lists:** many list endpoints and pages expose filters, but not consistent pagination, sort keys, cursors/limits, or total counts for scenarios, KB entries, runs, audit logs, model invocations, and graph rows.
- **Settings persistence is runtime-only:** model settings can be edited safely in the running app, but there is no persisted TOML/env/config write path, audit trail for config changes, or restart/deploy boundary policy.
- **Scenario report export is Markdown-only:** `/scenarios/{id}/report` returns text; richer PDF/HTML/JSON export packages and backend-generated downloadable artifacts remain unimplemented.
- **Frontend graph layout is basic:** React Flow is integrated, but layout is deterministic circular positioning rather than force/hierarchical layouts, large-graph virtualization, canvas performance tuning, and full interactive neighborhood expansion.
- **Merge review UX requires manual proposal IDs:** the UI can approve/reject by ID, but there is no first-class proposal inbox showing candidate pairs, rationale, aliases, affected references, and risk preview.
- **Feedback graph-correction UX is raw JSON:** calibration/feedback accepts graph corrections as JSON text rather than guided add/modify/remove node/edge forms with validation.

### C.9 Production operations and deployment hardening

- **No first-class CLI package exists:** `src/seldon/cli` is still absent, so local operations for scenarios, jobs, backups, seed/demo data, exports, migrations, and vector rebuilds require API calls or ad hoc scripts.
- **Docker compose does not run migrations or pgvector setup:** compose starts API/web/Postgres, but lacks migration-on-start, pgvector extension configuration, healthcheck-gated dependencies, and production secrets guidance.
- **Backup/restore is incomplete:** backups are DB-focused with optional vector directory inclusion; restore workflow, retention policy, scheduled backup jobs, and backup verification are missing.
- **Auth is API-key only:** there is no user/session model, roles, OAuth/OIDC integration, per-route authorization, or production-grade secret rotation guidance.
- **Observability is basic:** structured request logs exist, but there are no metrics, traces, run/job dashboards, alerting hooks, or cost/latency budgets.

### C.10 Test and CI gaps

- **No full external-data end-to-end test exists:** there is no test that creates a scenario, retrieves external sources, writes embedded KB entries, extracts graph nodes, detects relationships, predicts, red-teams, resolves, calibrates, and re-predicts.
- **Model-backed contract tests are missing:** current tests validate deterministic skeleton behavior; they do not fixture LLM outputs for each specialist schema, validation repair, escalation, or model metadata capture.
- **Deep graph/prediction algorithm tests are missing:** there are no tests for multi-hop traversal, centrality/PageRank, cascade propagation, scenario clustering, base-rate anchoring, or red-team activation gating.
- **Frontend browser coverage is still representative, not complete:** route and core workflow tests exist, but coverage should add KB filter round-trips, run detail/model metadata, graph selection/edit persistence, merge review, feedback guided corrections, settings validation persistence, and chart empty/error states.
- **CI lacks production hardening gates:** no Docker build/run smoke, migration upgrade/downgrade check, pgvector integration test, coverage threshold, security/dependency scan, or backup/restore smoke test is configured.

### C.11 Suggested implementation order for Follow-up C

1. Bind DB-backed model invocation recording to live agent runs, then add an `AgentBase` LLM helper that applies per-agent config, schema validation, repair retries, and escalation metadata.
2. Convert the highest-impact specialists to model-backed contracts first: summarizer, relationship detector, scenario synthesizer, red-team gate, and root-cause analyzer.
3. Build real external retrieval/document ingestion behind a small provider interface, with mocked-provider tests before adding live providers.
4. Replace deterministic-only embeddings with an embedding provider seam plus pgvector migrations/query path while keeping the SQLite fallback.
5. Add DB-to-NetworkX graph views, centrality scoring, and multi-hop traversal/cascade tests.
6. Enforce prediction activation gates: base-rate anchoring before synthesis and red-team review before activation.
7. Implement cross-scenario intelligence agents: Shared Graph Manager and Cross-Scenario Correlation Detector.
8. Upgrade orchestration from in-process-only jobs toward durable jobs/messages, then add SSE run/scenario event streams.
9. Harden production operations: CLI, migrations in compose, backup restore/retention, auth policy, observability, and Docker/pgvector CI smoke tests.
10. Finish high-risk UX gaps: merge proposal inbox, guided feedback graph corrections, richer report exports, large-graph layout, and broader Playwright coverage.

## 8. Initial Milestones

### Milestone 1 — Clean Seldon package

- Repo renamed.
- Package renamed to `seldon`.
- Existing tests pass.
- README updated.

### Milestone 2 — OpenRouter everywhere

- `OpenRouterClient` implemented.
- Existing prediction/entity extraction code uses profile-based model config.
- Mocked OpenRouter tests pass.

### Milestone 3 — API + DB skeleton

- FastAPI app runs locally.
- SQLite DB with migrations.
- Scenarios, KB entries, graph nodes/edges, and runs are persisted.
- Web app can read scenario and run lists.

### Milestone 4 — Context gathering to KB

- A scenario can trigger Phase 1.
- Agent runs are visible.
- KB entries are created with provenance.

### Milestone 5 — Graph construction

- Phase 2 and 3 agents populate ERG nodes/edges.
- Graph explorer displays relationships and evidence.

### Milestone 6 — Prediction synthesis

- Phase 4 produces versioned scenario predictions.
- Prediction detail page displays probabilities, evidence, drivers, and assumptions.

### Milestone 7 — Feedback/calibration

- Resolved predictions can be scored.
- Calibration dashboard works.
- Root-cause analyses are stored and searchable.

## 9. Migration Notes for Existing Code

Existing modules to preserve and evolve:

- `seldon.predictions.engine.PredictionEngine`
  - Keep as compatibility layer initially.
  - Move file persistence behind repository/exporter interfaces.
  - Replace monolithic `run()` with coordinator + specialist agents.

- `seldon.graph.knowledge_graph.KnowledgeGraph`
  - Keep NetworkX graph algorithms.
  - Stop treating the NetworkX JSON file as canonical once DB is ready.
  - Add adapter from DB graph rows to NetworkX graph views.

- `seldon.graph.entity_extractor.EntityExtractor`
  - Convert to Phase 2 schema-validated agent.
  - Route model through OpenRouter profile config.
  - Add provenance/evidence links to every created node.

- `seldon.llm.LLMClientProtocol`
  - Keep current minimal protocol for compatibility.
  - Add concrete OpenRouter implementation and model invocation logging.

## 10. Definition of Done

The Seldon Project is ready for serious use when:

- A user can create a scenario from the frontend.
- The backend gathers context, writes KB entries, extracts entities/events/topics, constructs graph relationships, and synthesizes versioned predictions.
- Every prediction shows provenance, evidence, assumptions, probability history, and model/agent run metadata.
- Models are fully configurable through OpenRouter model IDs without code changes.
- Resolved predictions feed calibration and root-cause analysis.
- Tests cover the core agent contracts, repositories, OpenRouter adapter, API routes, and frontend build.
