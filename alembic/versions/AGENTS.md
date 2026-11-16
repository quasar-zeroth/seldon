# Revision chain

See the [root AGENTS.md](../../AGENTS.md) for the project-wide lookup table and [migration guide](../AGENTS.md) for database selection. Implementation, schemas, migration code, CLI help, and executable tests are authoritative.

| Revision file | Role |
| --- | --- |
| `0001_phase_c_persistence.py` | Baseline creates all tables from the current `Base.metadata`; downgrade drops them. |
| `0002_pgvector_embeddings.py` | PostgreSQL-only vector extension, KB vector column, and similarity index; other dialects skip it. |
| `0003_durable_ops_jobs.py` | Adds durable job state, attempts, leases, idempotency, and indexes if the table is absent. |
| `0004_scenario_original_prompt.py` | Adds the original scenario prompt when absent. |
| `0005_entity_tags.py` | Adds persistent JSON entity tags when absent; reports reuse existing AgentRun storage. |

Read each file's `revision` and `down_revision` for the actual chain. Keep numerical SQL settings in migration code, not this map.

The baseline's use of current metadata means a fresh upgrade may already contain columns added by later revisions. Do not infer old-schema compatibility from that path alone. Existing tests cover SQLite creation and preservation during the tags upgrade; they do not execute PostgreSQL vector DDL or downgrade round trips. Several revisions inspect the live database, so offline SQL generation is not established by merely having an offline entry point in `env.py`.

Preserve data through additive, tested migrations and avoid rewriting applied history to hide compatibility problems. Update relevant AGENTS.md files whenever guidance is missing, stale, incorrect, or newly needed. Keep maps concise and move detailed upgrade procedures to focused linked documentation.
