# OpenRouter defaults

Verified against https://openrouter.ai/api/v1/models on 2026-09-29; code/config remain authoritative. Defaults use named free models, without paid chat fallbacks:

| Role | Model | Selection rationale |
| --- | --- | --- |
| General / extraction / fast | qwen/qwen3.8-27b:free | Recent general model with structured outputs and tool support |
| Reasoning / prediction | nvidia/nemotron-3-ultra-550b-a55b:free | Large reasoning model with long context |
| Fallbacks | nvidia/nemotron-3-super-120b-a12b:free; qwen/qwen3.8-27b:free | Another provider/model family and structured-output fallback |

These are practical defaults, not a claim that a benchmark proves universal superiority. Avoid anonymous or imminently expiring previews for persistent defaults. Check the catalogue for current availability, zero prompt/completion pricing, supported parameters and expiration before changing IDs. Free capacity is rate limited and can disappear. Provider-backed execution still requires the provider account/key; the external-agent workspace/report workflow requires neither and runs no model calls.

Seldon: src/seldon/config.py (base config and OpenRouter preset). Parallax: src/parallax/config.py and config.yaml (global and stage model overrides). Explicit environment, UI or local configuration overrides take precedence. NVIDIA NIM is a separate provider preset. Existing local hash embeddings remain local; the remote embedding setting is a separate opt-in service and has not been changed because vector dimensions/index compatibility require a migration when changing embedding models. Existing stored research is never regenerated merely by changing model defaults.
