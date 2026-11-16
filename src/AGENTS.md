# Python source tree

[Root AGENTS.md](../AGENTS.md) contains the project-wide lookup table.

This is the installable Python source tree. Packaging, dependency groups and the `seldon` command entry point live in [pyproject.toml](../pyproject.toml); tests live outside the package in [tests/](../tests/).

- [seldon/AGENTS.md](seldon/AGENTS.md) maps backend ownership, the database research system, provider adapters, operations, and the legacy file-backed facade.
- The console in [apps/web/](../apps/web/) consumes HTTP contracts. Parallax owns the primary frontend/orchestration boundary; keep this package independent of Parallax imports.

Implementation is the source of truth: inspect code, schemas, migrations, CLI help and tests before relying on design notes. Update relevant AGENTS.md files when guidance is incorrect, missing, or newly needed. Keep these maps concise; move detailed procedures into focused linked docs or child maps rather than duplicating implementation or settings.
