# Embedding providers

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) explains adjacent storage.

This package supplies embedding primitives; durable KB rows, versioning, filtering and search orchestration belong to [data/repositories.py](../data/repositories.py).

- `vector.py`: embedding protocol/results with audit metadata, deterministic local hash vectors, an OpenAI-compatible remote embedding adapter, provider selection, cosine similarity and pgvector literals.
- `__init__.py`: convenience exports for vector helpers.

Local hash embeddings are the default; the remote adapter requires explicit selection/injection. PostgreSQL storage and indexed search depend on the repository and [migrations](../../../alembic/AGENTS.md). Keep provider/model/dimension metadata with embeddings and ensure stored and query vectors use a compatible representation. Do not describe hash similarity as learned semantic understanding or assume the remote adapter is active merely because a model API key exists.

Verification: [test_followup_c11_embeddings.py](../../../tests/unit/test_followup_c11_embeddings.py) covers injected providers, mocked remote requests, local fallback and pgvector migration expectations.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; move detailed procedures into focused linked docs or child maps and keep numerical settings in code.
