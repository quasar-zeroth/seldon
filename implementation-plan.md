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
