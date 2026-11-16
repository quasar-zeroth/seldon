# Repository automation

See the [root AGENTS.md](../AGENTS.md) for the project-wide lookup table. Implementation, schemas, migrations, CLI help, tests, and executable workflow definitions are the source of truth.

This directory contains repository-hosted CI configuration. [workflows/AGENTS.md](workflows/AGENTS.md) maps the backend, container, and frontend gates in `workflows/ci.yml`. There are currently no other maintained configuration files here.

Keep automation consistent with [pyproject.toml](../pyproject.toml), [frontend package scripts](../apps/web/package.json), and [test isolation guidance](../tests/AGENTS.md). Treat recorded CI steps as checks that are configured, not proof of a successful run or production readiness.

Update relevant AGENTS.md files when workflow behavior or directory contents make guidance missing, stale, or incorrect. Keep maps brief; move extensive automation procedures into focused linked documentation.
