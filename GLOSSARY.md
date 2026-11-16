# Seldon glossary

Use the [root AGENTS.md lookup table](AGENTS.md) to locate owning modules and [project status](docs/project-status.md) for capability/limitation details. Definitions describe the current system; actual implementation, schemas, CLI help and tests are authoritative. Update terms when their meaning changes, keeping field-level contracts in code.

## Systems and execution

| Term | Meaning in this project |
| --- | --- |
| Seldon / The Seldon Project | Python package and evidence/forecast backend; the longer name is product prose. |
| Parallax | Separate consumer/orchestration/frontend repository. Seldon remains import-independent of it. |
| Operating console | The Next.js application in `apps/web`, consuming the Seldon HTTP API. |
| Built-in pipeline | Provider-backed coordinator/specialist execution in `src/seldon/agents`; fallback policy varies by specialist and must be checked in code. |
| External-agent workspace | Validated CLI/HTTP exchange in `src/seldon/workspace`; the hosting agent supplies research and reasoning, and Seldon persists it without a model call. |
| Provider-free | No model-provider credentials/calls required by the workspace operation; the hosting agent still needs its usual capabilities, and HTTP authentication can still apply. |
| Legacy facade | `SeldonClient` plus file-backed `KnowledgeGraph` and `PredictionEngine`; separate from database scenario persistence. |
| Coordinator / specialist | A coordinator composes a phase; a specialist performs one bounded task. Runs retain parent/child provenance. |
| Agent run / model invocation | A recorded unit of agent work versus a particular provider request and its metadata. An external run need not contain a provider invocation. |
| Job / rerun request | An operations job is dispatched to a registered local worker handler. A workspace prediction-rerun request is a durable handoff awaiting an external agent. |
| Pipeline projection | A common view of recorded built-in and external research stages; it does not schedule or invent work. |

## Evidence and graphs

| Term | Meaning in this project |
| --- | --- |
| Scenario / question | Persisted investigation, scope and horizon. It can collect sourced findings without yet containing a forecast. |
| Knowledge base (KB) / KB entry | Reusable evidence storage; entries retain source details, dates, context, versions and contradiction relationships. |
| Evidence / assumption | Evidence records attributed observations or reports; an assumption is an explicitly unsupported premise or judgment. Recording a source does not prove its truth. |
| Entity / canonical UUID | A reusable concept represented by a durable graph node. Its UUID can be shared across questions; scenario-local mutation keys are not global identities. |
| Entity tags | Normalized categories for discovery and reuse, defined by `data/tags.py`; they are not separate entities. |
| Entity-relationship graph (ERG) | Persisted nodes/edges in the relational store. General ERG relationships can contain cycles and more relationship types than a forecast influence DAG. |
| Influence DAG | Directed acyclic graph used for workspace forecasts. Edges point from driver to effect; feedback needs time-indexed nodes or a separate representation. |
| Graph scope / dependency depth | Target and bounded incoming causal dependencies used as prediction context. Depth measures shortest upstream distance to the target, not visual layout distance. |
| Topological order | Ordering that places every driver before its effects, used for DAG node assessment. |
| Membership / detach | Association with a question; detaching removes that association while preserving shared records and history. Incident edges require explicit handling. |
| Knowledge revision / base revision | Token identifying exported knowledge; a mutation supplies the revision it read so stale writes can be rejected. Perspective writes use their own global graph revision. |
| Idempotency / request ID | Exact replay of an accepted workspace request does not duplicate work; changing its payload under the same ID is rejected. Operations job keys have their own contract. |
| Snapshot / version | Frozen context or a historical record of state. New shared knowledge does not rewrite saved forecast snapshots or report bundles. |
| Embedding / pgvector | Numeric text representation for similarity; pgvector provides a PostgreSQL vector path. Local hash embeddings are available and are not learned semantic embeddings. |

## Forecasts and evaluation

| Term | Meaning in this project |
| --- | --- |
| Research round / convergence | Recorded searches, reviewed nodes, findings and gaps; convergence describes a bounded stopping judgment, not exhaustive knowledge. |
| Exhausted / budget stop | Exhausted means a bounded follow-up found no material addition. A budget stop records unresolved gaps; it does not assert saturation. |
| Node assessment | Evidence-backed forecast/judgment for one included node, connected to upstream reasoning. |
| Forecast / prediction | Saved judgment about future outcomes, with context and uncertainty. External forecasts append records; built-in updates also use version history. |
| Branch / outcome key | One possible forecast outcome and its identifier. Workspace branches must form a declared mutually exclusive/exhaustive distribution whose probabilities sum to one. |
| Probability / confidence | Probability expresses an outcome likelihood; confidence expresses support/certainty about a judgment. Neither becomes calibrated merely by validation. |
| Horizon / resolution criterion | The time scope and measurable rule used to judge an outcome. Current-state research can use an as-of scope; forecasts require appropriate future resolution information. |
| Base rate / prior | Reference probability before scenario-specific reasoning. Current built-in anchors can derive from stored forecast probabilities or defaults, not empirical outcome frequencies. |
| Red team / activation gate | Adversarial review of assumptions and alternatives; built-in prediction checks can hold a result for review before activation. |
| Calibration / Brier / log score | Comparison of forecasts with recorded outcomes. Brier scores squared probability error; log score penalizes low probability on the realized outcome. Calculations alone do not establish reliable forecasting. |
| Stale knowledge | Current evidence/graph/context differs from a forecast's frozen context. This flag measures change, not forecast accuracy. |
| Report bundle | Immutable summary, detail and optional attachments generated from saved research; generation is not fresh investigation. |

## Topics, claims and provenance

| Term | Meaning in this project |
| --- | --- |
| Perspectives graph | Append-only event-backed topic/claim/source knowledge in `workspace/perspectives`, distinct from forecast causal relationships. |
| Topic | Subject grouping claims and linking to relevant entities. Parent/subtopic relationships are acyclic; related-topic links are associations. |
| Claim | Attributed statement with source and time context. Corrections preserve the original and link a new claim rather than replacing its historical meaning. |
| Source | Context-dependent: relational `data.models.Source` stores ingestion-source metadata; a perspectives source profile identifies a writer, publication, document, institution, owner or unresolved identity. The two are not automatically identical. |
| Assessment / trust / leaning | Dated, scoped judgment about a claim or source. Trust is attributed and may be unknown; source leaning is contextual, not proof that a claim is true or false. |
| Common origin / derivation | Shared report, release or eyewitness provenance. Repeated publication is not independent corroboration. |
| Contradiction / supersession | A documented disagreement versus a correction/replacement link. Claim supersession points from new to old and preserves both accounts. |
| Ownership / affiliation / attribution | Separate cited relationships between owners, publishers, writers and documents. Similar names do not establish identity or ownership. |
| Connections / explained path | Bounded navigation across entity, evidence, topic, claim and source references. Traversal may go either way while preserving recorded direction; association does not imply causation. |
