# Built-in forecasting pipeline

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) covers adjacent systems.

Coordinators turn research into persisted evidence and graph structure, then synthesize forecasts and record outcome feedback. `AgentRun` and message records preserve execution provenance; the caller owns the database transaction.

| File/directory | Logic |
| --- | --- |
| `base.py`, `contracts.py`, `__init__.py` | Typed execution, run/message persistence, model invocation auditing, schema repair/escalation, shared research contracts and exports. |
| `factor_discovery.py`, `context_gathering.py` | Forecast-subject/driver decomposition, research coordination, summaries, deduplication and KB writes. |
| `retrieval.py`, [providers/](providers/AGENTS.md) | Search/fetch protocol, normalized documents, ranking/query variation, static test provider and external adapters. |
| `extraction.py` | Entity/event/topic discovery, candidate validation, identity resolution and merge proposals. |
| `graph_construction.py` | Relationships, consistency checks, graph importance and bounded convergence loops. |
| `prediction.py` | Node forecasts, propagation, base-rate priors, instability, synthesis, red-team/activation gates and versioned snapshots. |
| `advanced.py` | Adversarial review, historical analogies, uncertainty, assumptions, perspective heuristics, shared graph reuse and cross-scenario analysis. |
| `feedback.py` | Supplied outcome recording, root-cause review, Brier/log scores and calibration summaries. |

Forecast context comes from [workspace/knowledge.py](../workspace/knowledge.py), matching the GUI's target and dependency scope. Preserve evidence/graph snapshots, reject out-of-scope citations, and retain disagreements and dated source assessments from [perspectives](../workspace/perspectives/AGENTS.md). Subjective trust scores are neither calibrated probabilities nor independent votes. General ERG relationships can contain cycles; the external workspace imposes its own influence DAG.

Normal semantic execution needs a provider. Do not substitute deterministic development fallbacks for the external-agent workflow in [agent-workflow.md](../../../docs/agent-workflow.md). Inspect each specialist's actual fallback policy: it is not uniform. Several `advanced.py` outputs are heuristics/templates; its base-rate helper copies current forecast probabilities, while `prediction.py` derives priors from earlier forecasts or a neutral prior. Neither establishes empirical historical frequencies. `OutcomeMonitor` records supplied resolutions; it does not fetch outcomes autonomously.

`AdversarialRedTeamAgent` and `RootCauseAnalyzer` currently catch all model exceptions and use deterministic results without checking the development-fallback flag. Their authentication failures therefore do not propagate to the queue's pause handler. Treat uniform failure policy as remaining work, not an implemented guarantee.

Verification: phase E–J tests and `test_followup_c11_*` specialist/retrieval/graph/agent tests in [tests/unit](../../../tests/unit/); use mocked providers for offline work.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design plans. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; move detailed procedures into focused linked docs or child maps rather than copying prompts or settings.
