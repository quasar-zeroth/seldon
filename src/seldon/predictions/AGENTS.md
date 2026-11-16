# Legacy prediction files

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table; [backend map](../AGENTS.md) distinguishes legacy files from database forecasts.

This package implements the original market-prediction lifecycle used through `SeldonClient`. It reads local context and persists active/resolved JSON plus human-readable Markdown; it is not the SQL scenario prediction coordinator.

- `engine.py`: `PredictionEngine` loads context/predictions, applies confidence decay and contrarian checks, uses an injected LLM protocol to create/update/resolve forecasts, writes artifacts and generates a summary/status view.
- `__init__.py`: public engine export.

Preserve caller compatibility and existing artifact layout. Database-backed node forecasts, synthesis and activation gates belong in [agents/prediction.py](../agents/prediction.py); externally supplied forecasts and immutable snapshots belong in [workspace](../workspace/AGENTS.md). Prediction output does not authorize trading. Tests for this facade live in [test_predictor.py](../../../tests/unit/test_predictor.py) and phase A baseline coverage.

Implementation is the source of truth: code, schemas, migrations, CLI help and tests outrank design notes. Update relevant AGENTS.md files for incorrect, missing or new guidance. Keep maps concise; move detailed procedures into focused linked docs or child maps rather than duplicating prompts or settings.
