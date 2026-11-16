# Durable schema migrations

See the [root AGENTS.md](../AGENTS.md) for the project-wide lookup table. Actual implementation, schemas, migration code, CLI help, and tests are the source of truth; this file records the storage design and navigation.

Seldon's SQLAlchemy models define durable shared knowledge, graph, scenario, prediction, and execution records. Alembic supplies ordered changes for existing databases; runtime `create_all` creates missing tables but does not upgrade existing columns.

| Location | Responsibility |
| --- | --- |
| `env.py` | Model metadata, database selection, and online/offline Alembic entry points. |
| [versions/AGENTS.md](versions/AGENTS.md) | Revision chain, schema changes, and migration limitations. |
| [alembic.ini](../alembic.ini) | Migration directory, source import path, default database URL, and logging. |
| [Data layer](../src/seldon/data/AGENTS.md) | Models, database helpers, and repositories that consume the schema. |
| [Migration tests](../tests/integration/AGENTS.md) | Current SQLite upgrade/preservation coverage. |

`env.py` uses the configured Alembic URL unless `SELDON_DATABASE_URL`, `DATABASE_URL`, or `SELDON_DATA_DIR` selects application configuration. Verify the effective target before running migrations; a programmatically supplied Alembic URL does not override those environment selectors. Preserve existing data and use the installed service settings to locate the shared live database.

Add schema evolution in a new revision and assess upgrade compatibility with existing records. The baseline imports current model metadata, so a successful fresh install is not evidence that every historical database upgrades correctly. Consult the revision map before assuming PostgreSQL or offline SQL generation was exercised by SQLite checks.

Update relevant AGENTS.md files for missing, stale, incorrect, or newly discovered guidance. Keep this map brief; place lengthy migration procedures in a focused linked document instead of duplicating implementation details.
