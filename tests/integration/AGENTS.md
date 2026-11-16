# Migration and provider integration checks

See the [root AGENTS.md](../../AGENTS.md) for the project-wide lookup table and [tests guidance](../AGENTS.md) for shared fixtures. Implementation, schemas, migrations, CLI help, and executable tests are the source of truth.

| File | Responsibility |
| --- | --- |
| `test_phase_c_migration.py` | SQLite upgrade-to-head smoke test and preservation of an existing unversioned database while adding entity tags. |
| `test_openrouter_mocked.py` | HTTP MockTransport verification of malformed-JSON fallback to another model. |
| `test_nvidia_mocked.py` | NVIDIA NIM endpoint/authentication/header contracts and provider routing through the shared compatible client. |
| `test_openrouter_live.py` | Optional real OpenRouter structured-output and graph-extraction smoke checks, marked `live_openrouter` and skipped without a usable key. |

## Boundaries and isolation

- Offline integration checks use real SQLite or mocked HTTP, not a live PostgreSQL/provider deployment. Run them with `uv run pytest tests/integration -m "not live_openrouter"` from the repository root.
- `tests/conftest.py` loads `.env`. [Alembic configuration](../../alembic/AGENTS.md) prefers database environment selectors over `sqlalchemy.url`; the migration tests currently set temporary URLs without clearing those selectors. Ensure `SELDON_DATABASE_URL`, `DATABASE_URL`, and `SELDON_DATA_DIR` do not redirect these tests to an existing database.
- Current migrations are tested for fresh SQLite creation and the entity-tag upgrade case. PostgreSQL/pgvector execution, full historical-schema upgrades, and downgrade round trips are not covered here.
- Live tests bypass the default HTTP guard. Their checks establish limited provider compatibility, not forecast accuracy or comprehensive model coverage.

Update this and other relevant AGENTS.md files when behavior or coverage makes guidance missing, stale, or incorrect. Keep maps concise; move extensive setup or matrices into focused linked documents.
