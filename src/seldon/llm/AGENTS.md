# Model client boundary

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) covers callers.

Model transport is independent of research storage and host orchestration. Provider selection and model settings live in [config.py](../config.py); the provider-free [workspace](../workspace/AGENTS.md) does not call this package for reasoning.

- `__init__.py`: sync/async JSON completion protocols, the empty-response `NullLLMClient`, provider-neutral `LLMClient` alias and `build_llm_client` factory.
- `openrouter.py`: shared OpenAI-compatible transport used for OpenRouter and NVIDIA NIM; sync/async completion, model fallback, transient retries, JSON extraction/schema validation, model health checks and invocation metadata/JSONL recording.

Authentication failures are distinct from unavailable models: invalid credentials must stop the call, while model/transport/output failures can follow configured retry/fallback policy. Specialists add schema repair and profile escalation in [agents/base.py](../agents/base.py); database invocation recording comes from [data/repositories.py](../data/repositories.py). Keep provider credentials out of logs and guidance. `NullLLMClient` returns empty JSON and is not a research model.

Verification: [test_openrouter_client.py](../../../tests/unit/test_openrouter_client.py), provider configuration tests and mocked OpenRouter/NVIDIA integration tests. The separately marked live suite makes real provider calls. Model catalogue verification procedure: [openrouter-models.md](../../../docs/openrouter-models.md).

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; move detailed procedures into focused linked docs or child maps rather than copying model IDs or settings.
