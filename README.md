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

## Local API + web development

Run the FastAPI backend locally:

```bash
uv run uvicorn seldon.api.app:app --reload --host 0.0.0.0 --port 8000
```

Run the Next.js operating console in another shell:

```bash
cd apps/web
npm ci
SELDON_API_URL=http://localhost:8000 NEXT_PUBLIC_SELDON_API_URL=http://localhost:8000 npm run dev
```

The web app intentionally supports two API base URLs:

- `SELDON_API_URL` is server-side only and is used by Next.js server components/actions.
- `NEXT_PUBLIC_SELDON_API_URL` / `NEXT_PUBLIC_SELDON_BROWSER_API_URL` are browser-visible and are used for links such as backend report downloads.

In Docker Compose, the web container talks to the API over `SELDON_API_URL=http://api:8000`, while browser-visible links use `http://localhost:8000` so they work from the host browser.

If API-key enforcement is enabled, set `SELDON_API_KEY` for server-side web requests and `NEXT_PUBLIC_SELDON_API_KEY` only for local/dev browser calls where exposing the key is acceptable. Production deployments should prefer same-origin routing or a server-side proxy rather than exposing secrets to the browser.

## Follow-up B GUI verification

The GUI integration work is guarded by both backend API tests and frontend route/browser tests:

```bash
uv run pytest tests/unit/test_phase_d_api.py -q
cd apps/web
npm run test:frontend
```

`npm run test:frontend` runs TypeScript checks, a production build, route/contract smoke checks, and Playwright browser workflows against a local mock Seldon API. Install the browser once on fresh machines with:

```bash
cd apps/web
npx playwright install chromium
```

CI installs Chromium with Playwright and runs the same frontend gate, so route build failures, broken core mutations, or frontend/backend API drift should fail before merge.

## Live OpenRouter tests

Most tests are mocked/offline. Live API tests are marked separately and skipped unless `OPENROUTER_API_KEY` is present. The test harness loads simple key/value pairs from the project `.env`, so either export the key in your shell or set it in `.env`:

```bash
uv run pytest -m live_openrouter
```

To exclude them explicitly:

```bash
uv run pytest -m "not live_openrouter"
```
