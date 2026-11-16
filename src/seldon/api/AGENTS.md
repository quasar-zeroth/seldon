# HTTP service

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) covers service ownership.

Expose persisted backend truth through typed inputs, explicit errors and auditable mutations. This package is the HTTP boundary; repositories and workspace services own reusable domain logic.

- `app.py`: application/session/client factories, lifespan and authentication middleware; scenario/KB/graph/prediction CRUD, specialist execution, job chaining, run timelines/SSE, analytics, exports, model configuration and operations endpoints.
- `dependencies.py`: cached standalone configuration, session and model-client dependency factories. `create_app` also accepts injected dependencies for tests and hosts.
- `__init__.py`: package marker. Workspace and perspective routers are implemented in [workspace/](../workspace/AGENTS.md) and mounted by `create_app`.

Direct specialist routes execute coordinators in the request transaction; `/jobs/` routes use the durable in-process queue. Do not infer asynchronous execution from an HTTP status alone. Merge-proposal approve/reject routes currently record audit decisions; they do not themselves execute a graph merge. Derive the complete route contract from `app.py` and generated OpenAPI.

Provider-free workspace routes share host sessions/authentication and must not invoke the built-in model pipeline. Keep read/export access useful without provider keys and model health separate from API/database availability. Preserve local-versus-production authentication configuration. Coordinate client contracts with [apps/web](../../../apps/web/AGENTS.md).

Verification: `test_phase_d_api.py`, phase K operations and follow-up orchestration/exports tests under [tests/unit](../../../tests/unit/), plus workspace API tests. Inject clients and databases for offline checks.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; split detailed material into focused linked docs or child maps rather than maintaining a second endpoint catalogue.
