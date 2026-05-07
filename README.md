# seldon

**The Seldon Project** is a prediction and knowledge-graph backend for probabilistic scenario forecasting.

The Python package and app are named `seldon`. User-facing prose can refer to the broader system as **The Seldon Project**.

Parallax can consume this package as a Python dependency while keeping frontend, pipeline orchestration, market execution, and GUI code in the main `parallax` repo until those pieces are migrated or replaced by the Seldon frontend/API.

## OpenRouter configuration

Set your OpenRouter API key outside git:

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

For local Docker Compose runs, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` there. `.env` files are gitignored.

Default model config lives in `src/seldon/config.py`:

- Default/balanced: `tencent/hy3-preview:free`
- Fast: `tencent/hy3-preview:free`
- Reasoning: `tencent/hy3-preview:free`
- Fallbacks: `openrouter/owl-alpha`, `minimax/minimax-m2.5:free`, `nvidia/nemotron-3-super-120b-a12b:free`

## Live OpenRouter tests

Most tests are mocked/offline. Live API tests are marked separately and skipped unless `OPENROUTER_API_KEY` is present. The test harness loads simple key/value pairs from the project `.env`, so either export the key in your shell or set it in `.env`:

```bash
uv run pytest -m live_openrouter
```

To exclude them explicitly:

```bash
uv run pytest -m "not live_openrouter"
```
