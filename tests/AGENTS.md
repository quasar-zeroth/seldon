# Verification

See the [root AGENTS.md](../AGENTS.md) for the project-wide lookup table. Implementation, schemas, migrations, CLI help, and executable tests are the source of truth; this map describes design and navigation.

## Design and routes

Test observable behavior and failure modes with real local database transactions and fake external providers. The `unit` directory includes service, API, and CLI integration coverage; its name does not mean every test is isolated to one function.

| Location | Responsibility |
| --- | --- |
| `conftest.py` | Environment loading, deterministic development defaults, `FakeLLM`, temporary data fixture, and default HTTP/search blocking. |
| [unit/AGENTS.md](unit/AGENTS.md) | Persistence, agents, graph, workspace, reports, perspectives, API, and operations regressions. |
| [integration/AGENTS.md](integration/AGENTS.md) | Database migrations, mocked provider contracts, and optional live OpenRouter checks. |
| [Frontend tests](../apps/web/tests/AGENTS.md) | Console route smoke checks and browser workflows. |

## Running checks

- From the repository root, use `uv run pytest -m "not live_openrouter"` for offline backend verification. Markers and dependencies live in [pyproject.toml](../pyproject.toml); actual CI gates live in [.github/workflows/ci.yml](../.github/workflows/ci.yml).
- `conftest.py` loads local environment configuration and sets development fallback/healthcheck defaults only when unset. Non-live tests block httpx network transports and DDGS text searches; MockTransport, ASGI, and TestClient remain available. This is targeted isolation, not a universal network sandbox.
- Only explicitly marked live tests bypass those guards. Plain `pytest` can make provider calls when a usable key is loaded. Do not remove isolation or relax production semantics to make tests pass.
- Read the integration guide before running migration tests with database-related environment settings; Alembic may prefer those settings over a test URL.

When behavior changes, preserve meaningful coverage and correct obsolete assertions. Update this and relevant nested AGENTS.md files for missing, incorrect, or newly discovered information. Keep maps concise; move lengthy procedures to a focused document and link it rather than expanding this file.
