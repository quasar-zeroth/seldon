# Plan: LLM-first entity pipeline + auth-fail queue pause

## Problem observed

A gold-price scenario produced graph nodes like `likely`, `outcome`, `want`, `know`, `would`, `look`, and `like`.

Root cause chain:

1. OpenRouter calls returned `401 Unauthorized`.
2. Scenario drafting fell back to a generic deterministic draft: `What is the likely outcome for: ...`.
3. Context gathering had no external/LLM-backed retrieval and fell back to a `scenario_brief` KB entry.
4. `compact_terms()` selected generic words from the question and treated them as topics.
5. Extraction used deterministic term scraping from KB content/topics, so generic words became ERG nodes.
6. Prediction consumed those bad graph nodes as real forecast drivers.

The pipeline should not continue graph/prediction work when model auth is broken, and entity discovery/resolution should be LLM-first with deterministic logic only as validation/support, not as the primary extractor.

## Goals

- Pause the whole background queue immediately on LLM authentication failures.
- Make LLM availability a hard requirement for phases that need semantic judgment.
- Replace heuristic entity/topic extraction with fast-model structured extraction.
- Add entity resolution/merge using an LLM-backed resolver.
- Prevent generic query words from becoming graph nodes.
- Make failure mode obvious in `/ops/jobs`, `/config/status`, and logs.

## Non-goals

- Do not delete existing KB/graph data automatically without explicit cleanup/migration.
- Do not rely on expensive reasoning models for extraction by default; fast structured-output models are fine.
- Do not silently fall back to low-quality deterministic extraction for production workflows.

## Implementation plan

### 1. Queue pause on auth failure

Add queue state to `InProcessJobQueue`:

- `paused: bool`
- `pause_reason: str | None`
- `paused_at: datetime | None`
- `pause()` / `resume()` methods
- `status()` method exposing paused state and counts

Worker behavior:

- If paused, do not execute queued jobs.
- Leave jobs in `queued` state.
- Allow explicit admin resume endpoint.

Add endpoints:

- `GET /ops/queue` → queue paused/running state, reason, counts
- `POST /ops/queue/pause` → manual pause
- `POST /ops/queue/resume` → manual resume

Detection:

- Introduce a dedicated exception, e.g. `LLMAuthenticationError`.
- In `OpenRouterClient`, map HTTP 401/403 auth responses to this exception.
- In `InProcessJobQueue._execute`, if a handler raises `LLMAuthenticationError`:
  - mark current job failed or blocked with the auth error
  - pause the queue immediately
  - do not retry the job automatically
  - log a high-signal structured event: `queue paused due to llm_auth_failed`

### 2. Disable weak semantic fallbacks in workflow phases

Current fallback behavior is useful for tests but unsafe for real graph creation.

Add config flags:

- `agents.require_llm_for_semantic_phases = true` by default
- `agents.allow_deterministic_dev_fallback = false` by default outside tests/demo

Apply to:

- scenario drafting
- query decomposition
- information summarization
- entity discovery
- entity resolution
- graph construction/prediction where semantic classification is required

If LLM fails and `require_llm_for_semantic_phases` is true:

- raise the error
- queue pauses if auth-related
- job does not produce fallback graph artifacts

### 3. LLM query decomposition

Replace `QueryDecomposer` deterministic `compact_terms()` primary-topic selection with a fast-model structured call.

Desired schema:

```json
{
  "forecast_subject": "gold price",
  "primary_topic": "gold price outlook",
  "key_entities": [
    {"name": "Gold", "type": "commodity"},
    {"name": "US dollar", "type": "currency"},
    {"name": "Federal Reserve", "type": "institution"}
  ],
  "metrics": ["spot gold price", "real yields", "USD index"],
  "subqueries": [
    {"query": "gold price outlook 6 months 1 year drivers", "topic": "gold price outlook", "rationale": "..."}
  ]
}
```

Validation rules:

- Reject generic words: likely, outcome, want, know, would, look, like, question, scenario.
- Prefer noun phrases over single words.
- Require at least one concrete subject/entity or metric.

### 4. LLM entity discovery

Replace `EntityExtractor._extract()` scraping from `compact_terms()` with a fast-model extractor.

Input:

- scenario question
- timeframe
- KB evidence entries with source metadata

Output schema:

```json
{
  "entities": [
    {
      "name": "Gold",
      "type": "commodity",
      "description": "Precious metal whose price is being forecast",
      "aliases": ["XAU", "gold bullion"],
      "evidence_kb_entry_ids": ["..."],
      "confidence": 0.85
    }
  ],
  "metrics": [...],
  "events": [...],
  "topics": [...]
}
```

Mapping to ERG node types:

- commodity/company/person/institution/country/currency/asset → `entity` or `actor` depending on role
- price/index/rate/yield/demand/supply/inflation → `metric`
- macro theme like monetary policy/geopolitical risk → `topic`
- dated occurrence/shock/announcement → `event`

Validation gates:

- no generic stopword nodes
- no one-word node unless it is a known/concrete noun (`Gold`, `OPEC`, `China`, etc.)
- require evidence link unless node is directly derived from the scenario subject
- cap low-confidence nodes from being persisted

### 5. LLM entity resolution / deduplication

Replace `NodeDeduplicatorMerger._propose()` exact-name-only matching with LLM-assisted resolution.

Inputs:

- new candidates
- existing similar graph nodes from lexical/embedding search
- aliases
- KB evidence snippets

Output schema:

```json
{
  "resolved_nodes": [
    {
      "candidate_name": "Gold price",
      "action": "create|merge|alias|reject",
      "canonical_name": "Gold spot price",
      "existing_node_id": null,
      "reason": "...",
      "confidence": 0.9
    }
  ]
}
```

Rules:

- Auto-merge only high confidence.
- Reject generic words and malformed candidates.
- Persist merge proposals for medium confidence.
- Never destructively merge without explicit confidence/validation.

### 6. Graph construction safeguards

Before writing ERG nodes:

- Run `validate_node_candidate()`.
- Reject known generic terms and interrogative/scaffolding words.
- Reject candidates whose description/current_state is only the scenario question unless the node is the direct scenario subject.
- Require minimum semantic confidence.

Before prediction:

- If graph has too few valid domain nodes, mark prediction job blocked instead of forecasting over garbage nodes.
- Add a job error like: `insufficient_valid_graph_nodes`.

### 7. Tests

Add unit tests for:

- OpenRouter 401 pauses queue and prevents subsequent jobs from executing.
- `GET /ops/queue` reports pause reason.
- Entity discovery on gold-price scenario returns `Gold` / `gold price` / macro drivers, not `likely/outcome/would`.
- Deterministic fallback cannot persist generic graph nodes when semantic LLM is required.
- Entity resolver merges aliases and rejects generic terms.
- Prediction refuses to run with only generic/scaffolding nodes.

Add e2e-ish API test:

1. Create scenario: “What will gold price look like in 6 months and 1 year?”
2. Run auto pipeline with mocked LLM responses.
3. Assert graph contains domain nodes and no stopword nodes.
4. Assert prediction references valid drivers.

### 8. Cleanup existing bad graph data

After code fixes, provide an explicit admin cleanup script/endpoint for this dev DB:

- identify nodes for scenario `693bb9a8-f48b-4087-9c12-ad1be5b97f48`
- remove/reject nodes in generic denylist
- optionally delete predictions generated from those bad nodes
- rerun context → extraction → graph → prediction

Do this only after confirmation.

## Suggested implementation order

1. Add auth exception + queue pause/resume/status.
2. Add hard LLM-required mode for semantic phases.
3. Implement LLM query decomposition.
4. Implement LLM entity discovery with validators.
5. Implement LLM entity resolution.
6. Add graph/prediction quality gates.
7. Add tests and rerun the gold scenario.
8. Optional cleanup of existing bad dev artifacts.
