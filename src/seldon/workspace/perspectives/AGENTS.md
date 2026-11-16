# Topics and source provenance

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table; [workspace map](../AGENTS.md) covers research integration. Procedures and semantics: [topic-source-graphs.md](../../../../docs/topic-source-graphs.md).

Preserve incompatible accounts and dated human/agent judgments rather than replacing them with a consensus fact. These shared graph layers use append-only events in the existing database and require no model provider or network calls.

- `schemas.py`: attributed claims, topic/source/claim relationships and contextual leaning/trust assessments. Claim trust is separate from source trust; unassessed values remain unknown. Fact status requires recorded verification and remains revisable.
- `__init__.py`: reconstruct shared graphs from `AgentRun` events, serialize writers with a `Source` lock row, enforce reference/revision/replay rules and acyclic hierarchies, conservatively index saved evidence and select research context.
- `api.py`: HTTP adapter sharing host authentication; [../cli.py](../cli.py) exposes the same workflow.
- `connections.py`: read-only joins over explicit entity/topic, evidence/claim and source identity/affiliation references, with bounded navigation and explained paths. Associations do not imply causal influence or independent confirmation; retain actual direction/status even when traversing either way.

Documents, writers, publishers and owners are distinct records. Use `published_by`/`authored_by` for verified attribution and `source.entity_ids` for explicit canonical identity matches, never similar-name guesses. Topic parent/subtopic edges are acyclic; related-topic cross-links and source affiliations are separate from forecast causal edges. Keep common origins, contradictions and supersessions visible in scoped context, and never infer ownership, ideology or reliability from a source label. Claims/assessments retain history rather than silently rewriting it.

[knowledge.py](../knowledge.py) freezes relevant claims/assessments with forecasts; [reports.py](../reports.py) includes them in new reports. Old snapshots/reports remain frozen, and source reviews do not automatically execute a prediction.

Verification: [test_perspectives.py](../../../../tests/unit/test_perspectives.py) exercises rollback, replay, concurrency/stale revisions, scoped counterevidence and persistence with real local databases.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; split growing procedures into focused linked docs or child maps rather than duplicating contracts.
