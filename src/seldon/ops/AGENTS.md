# Runtime operations

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) covers API/CLI integration.

Operations support the database-backed service. [api/app.py](../api/app.py) registers job handlers and starts/stops the worker; [cli.py](../cli.py) exposes migration, backup/restore/retention, seed, vector rebuild and health commands.

- `jobs.py`: single-worker FIFO execution with optional persistent `OpsJob` rows, idempotency keys, restart recovery, leases, retry counts and queue pause/resume. Authentication failures pause processing; this is an in-process worker, not a distributed queue.
- `backups.py`: archive/restore SQLite and local vector artifacts, using SQLite's online backup API when an engine is supplied; archive retention pruning. PostgreSQL needs external dump/restore or volume procedures.
- `logging.py`: structured JSON/plain logs, optional rotating file handlers and request/operation metadata.
- `seed.py`: idempotent demonstration scenario, evidence and graph creation. Demo records must remain distinguishable from researched evidence.
- `__init__.py`: public operations exports.

Preserve existing data on restore and honor overwrite guards; isolate operational tests from the configured live database. Do not describe persisted queue records as proof that queued work ran successfully. Test jobs, auth, backups, restore, retention and metrics in phase K and `test_followup_c11_durable_orchestration.py`/`test_followup_c11_production_ops.py` under [tests/unit](../../../tests/unit/).

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; split detailed procedures into focused linked docs or child maps and keep operational limits in configuration.
