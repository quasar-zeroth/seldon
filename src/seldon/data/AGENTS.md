# Persistence and graph views

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) distinguishes SQL state from legacy files.

The database is canonical runtime state for the research system; exports and NetworkX graphs are derived views. Preserve evidence provenance, shared UUIDs, version history and replayable mutations.

| File | Responsibility |
| --- | --- |
| `models.py` | SQLAlchemy rows for sources/KB, scenarios/ERG, snapshots and prediction versions, feedback/advanced analyses, runs/messages, jobs, model calls and audits. |
| `schemas.py` | Pydantic HTTP contracts; provider-free workspace contracts live separately in `workspace/schemas.py`. |
| `repositories.py` | Audited writes, KB versions/contradictions/search, graph projections/centrality/snapshots/reuse, prediction versions, run messages and Markdown export. |
| `database.py` | Engine and session factories, SQLite connection handling and transactional session context. |
| `tags.py` | Normalized entity categories and conservative automatic type/class inference. |
| `__init__.py` | Database/repository public exports. |

Use repositories inside caller-owned transactions. Reassign JSON fields so SQLAlchemy tracks changes; preserve tags unless explicitly replaced. Search/reuse shared records before creating duplicates. Read [alembic](../../../alembic/AGENTS.md) for schema evolution; avoid new tables for data already represented by existing graph/evidence/run/prediction records.

General ERG relationships are not globally acyclic. The [workspace](../workspace/AGENTS.md) validates scenario influence edges from upstream driver to downstream outcome; keep feedback time-indexed or outside that DAG. Never delete global edges merely to make a projection acyclic. Parallel relationship rows are folded into a NetworkX edge with their source IDs retained. KB search supports pgvector when available and local cosine ranking otherwise; default repository embeddings are local hashes.

Verification: repository, graph algorithm and embedding tests under [tests/unit](../../../tests/unit/); migration checks in [tests/integration](../../../tests/integration/).

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; split detailed material into focused linked docs or child maps and leave bounds/settings in code.
