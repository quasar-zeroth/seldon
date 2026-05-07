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
