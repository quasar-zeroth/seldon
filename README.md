# seldon

**The Seldon Project** is a prediction and knowledge-graph backend for probabilistic scenario forecasting.

The Python package and app are named `seldon`. User-facing prose can refer to the broader system as **The Seldon Project**.

Parallax can consume this package as a Python dependency while keeping frontend, pipeline orchestration, market execution, and GUI code in the main `parallax` repo until those pieces are migrated or replaced by the Seldon frontend/API.

## Research without provider API keys

Use your existing agent session to research and author forecasts through Seldon's validated DAG workspace. Start with [the agent workflow](docs/agent-workflow.md) and [AGENTS.md](AGENTS.md).

```bash
uv sync
uv run seldon research --help
uv run python examples/gold/replay.py --db data/gold-example.db --out data/gold-example
```

The gold replay uses checked-in dated evidence and agent judgments; it performs no live search or model calls. JSON/Markdown exports expose every saved research step. Parallax delegates `parallax research` to this same engine and its `/research` page displays saved scenarios.

Entities carry normalized tags; `research --db PATH library --tag data-center` finds reusable campuses across questions. `research --db PATH reports generate SCENARIO_ID --request-id UNIQUE_ID` saves an immutable summary/detailed bundle, optionally with agent-authored sections and CSV/JSON attachments. Use `research reports list` and `research reports download --help` to retrieve it, or Parallax's **Reports** page. Reports are stored in the same database as the graph; see the [agent workflow](docs/agent-workflow.md) for schemas, pagination and migration instructions.

Recurring macro cycles (credit and speculation, war intensity, globalization, generational and political moods) are modeled with `research --db PATH cycles ...`: load dated series, fit and test harmonic or inertia/whiplash oscillator models, combine factors, render SVG charts, and link cycle priors to forecasts. Agents follow the [seldon-cycles skill](skills/seldon-cycles/SKILL.md); models and verdicts are explained in [docs/cycles.md](docs/cycles.md).

Video links (mostly YouTube) become research with `research --db PATH transcripts ...`: fetch the transcript from YouTube captions or the Supadata API (`SUPADATA_API_KEY`, for videos without captions and other platforms), find shared entities it mentions, and ingest timestamped, quote-checked excerpts as evidence with the entities and relationships they support. The question's pipeline gains a **Video transcripts** stage. Agents follow the [seldon-transcripts skill](skills/seldon-transcripts/SKILL.md); see [docs/transcripts.md](docs/transcripts.md).

## Optional built-in model pipeline

The built-in semantic coordinators still require a provider. Set credentials outside git using `.env.example` as the configuration reference. Supported provider presets, current model IDs, fallback policy, and environment overrides live in `src/seldon/config.py`; derive them there rather than relying on copied model lists.

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

Topic and source graphs, conflicting claims, contextual trust/leaning reviews and ownership/affiliation provenance are available through Parallax Topics/Sources and `research perspectives`. See [the agent workflow](docs/topic-source-graphs.md).
