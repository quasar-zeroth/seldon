# Continuous integration workflows

See the [root AGENTS.md](../../AGENTS.md) for the project-wide lookup table. Implementation, schemas, migrations, CLI help, executable tests, and `ci.yml` are authoritative.

`ci.yml` runs on pull requests and pushes to `main`, with independent backend and frontend jobs.

| Job | Configured gates |
| --- | --- |
| Backend | Install Python/development dependencies with uv; Ruff; Python compilation; pytest; Docker image build and container CLI healthcheck. |
| Frontend | Install npm dependencies and Playwright Chromium; run `test:frontend`, which performs typechecking, production build, route smoke checks, and browser tests. |

Language/tool versions and exact commands belong in the workflow and package manifests. Backend tests currently run plain `uv run pytest`; optional live OpenRouter tests skip without a usable key but would run if credentials became available. Local offline verification explicitly excludes `live_openrouter` as explained in [tests/AGENTS.md](../../tests/AGENTS.md).

No PostgreSQL service, dedicated live-provider job, or deployment step is configured here. Container healthcheck and mocked provider tests do not establish real-provider forecast quality. See [integration coverage](../../tests/integration/AGENTS.md) before interpreting migration success.

Update relevant AGENTS.md files for missing, stale, incorrect, or newly discovered guidance. Keep this map concise; split detailed CI procedures into focused documents and link them.
