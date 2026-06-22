# Scenario chat simplification plan

## Goal

Make scenario creation feel more like a chat app: the user should be able to describe what they are looking for in plain language, then Seldon uses one short LLM call to derive the structured scenario fields:

- Scenario name
- Time horizon
- Target question
- Description / scope notes

At the same time, remove scenario-level status from the user-facing scenarios experience unless there is a clear backend reason to keep it.

## Current structure

### Backend

- FastAPI app: `src/seldon/api/app.py`
- Scenario database model: `src/seldon/data/models.py::Scenario`
- Scenario Pydantic schemas: `src/seldon/data/schemas.py::ScenarioCreate`, `ScenarioRead`, `ScenarioUpdate`
- Scenario persistence/audit repository: `src/seldon/data/repositories.py::ScenarioRepository`
- LLM adapter: `src/seldon/llm/openrouter.py::OpenRouterClient`
- Model/profile config: `src/seldon/config.py`
- Backend tests: `tests/unit/test_phase_d_api.py` and follow-up tests

### Frontend

- Scenario list/create page: `apps/web/app/scenarios/page.tsx`
- Scenario detail/edit page: `apps/web/app/scenarios/[id]/page.tsx`
- Scenario API wrapper: `apps/web/src/lib/api/scenarios.ts`
- Shared API types: `apps/web/src/lib/api/types.ts`
- Shared UI primitives/styles: `apps/web/src/components/ui.tsx`, `apps/web/app/styles.css`
- Frontend smoke/E2E tests: `apps/web/tests/route-smoke.mjs`, `apps/web/tests/e2e/gui-workflows.spec.ts`, `apps/web/tests/mock-api.mjs`

## What scenario status is doing today

Scenario-level `status` is distinct from prediction/job/run statuses:

- `Scenario.status` currently supports `active`, `paused`, `archived`, `completed`.
- The scenarios list has a status filter.
- The scenario list and detail header display a status badge.
- The edit form can change scenario status.
- `GET /scenarios?status=...` filters by status.
- Reports print `Status: {scenario.status}`.
- Tests assert status filtering and patching.

I do not see strong functional behavior attached to scenario status beyond filtering/display/reporting. Workflows do not appear to branch on it. Prediction statuses, run statuses, job statuses, KB contradiction statuses, and merge proposal statuses are still meaningful and should stay.

Recommendation: remove scenario status from the UI and from the new scenario creation/update flow first. Keep the DB column and API field for backwards compatibility in the first pass, but stop exposing it to users. A later migration can fully drop `scenarios.status` after consumers are checked.

## Proposed UX

### Scenarios list page

Replace the current create form with a chat-style panel:

1. Large prompt textarea with conversational placeholder, e.g.
   `Tell Seldon what you want to forecast. Example: I want to understand whether gold breaks above $2,800 in the next six months, including Fed cuts, dollar strength, and central-bank demand.`
2. Primary button: `Draft scenario`
3. Optional generated preview card after submission:
   - Scenario name
   - Time horizon
   - Target question
   - Scope notes
4. Primary confirmation button: `Create scenario`
5. Secondary affordance: `Edit fields manually` or editable preview fields before creation.

For implementation simplicity in Next server actions, this can be a two-step flow backed by query/session state or a single backend endpoint that both derives and creates. I recommend keeping it two-step:

- `POST /scenarios/draft` derives fields only.
- Existing `POST /scenarios` persists the reviewed draft.

This keeps LLM drafting auditable, debuggable, and safer: the model suggests metadata, the user still confirms creation.

### Scenario list simplification

- Remove the status dropdown filter.
- Keep keyword search.
- Scenario cards should show name, target question, horizon, updated time, and latest prediction if available.
- No scenario status badge.

### Scenario detail simplification

- Remove status from the scenario metadata edit form and header.
- Keep prediction status in the latest prediction card because prediction lifecycle status is meaningful.
- Consider re-labelling detail page sections to be less backend-y later, but that is separate from this pass.

## Backend plan

### 1. Add a draft schema

In `src/seldon/data/schemas.py`, add:

- `ScenarioDraftRequest`
  - `prompt: str`
  - optional `default_time_horizon: str | None = None`
- `ScenarioDraftResponse`
  - `name: str`
  - `target_question: str`
  - `time_horizon: str`
  - `description: str`
  - optional `source_prompt: str`

Use Pydantic constraints for max lengths and non-empty prompt.

### 2. Add an LLM draft endpoint

In `src/seldon/api/app.py`, add:

`POST /scenarios/draft`

Behavior:

- Accept natural-language prompt.
- Call `OpenRouterClient.complete_json(...)` with `model_profile="fast"`, low temperature, small `max_tokens`.
- System prompt: extract concise structured scenario metadata, do not answer the forecast, do not invent overly specific facts.
- JSON schema keys:
  - `name`
  - `time_horizon`
  - `target_question`
  - `description`
- Validate response with `ScenarioDraftResponse`.
- Normalize/sanitize: trim whitespace, fallback values if the LLM omits something.
- Return only the draft fields.

Suggested fallback behavior if LLM fails:

- Return HTTP 502 with a friendly error code like `scenario_draft_failed`, OR
- Return deterministic fallback draft from the prompt, e.g. name first 60 chars, target question prompt as a question, empty horizon.

Recommendation: for UX, use deterministic fallback with a warning field only if the codebase already supports warning fields cleanly. Otherwise use a structured 502 and let the frontend show “Couldn’t draft automatically — fill fields manually.”

### 3. Keep creation endpoint mostly unchanged

Leave `POST /scenarios` as the persistence endpoint for reviewed fields.

In `ScenarioCreate`, consider making `status` internal/backcompat:

- Keep default `active` for DB compatibility.
- Do not require frontend to send it.
- Eventually remove `status` from public create/update docs and frontend types.

### 4. Remove scenario status filtering from public route or de-emphasize it

First pass: keep `GET /scenarios?status=` working for backward compatibility, but stop advertising/using it in the frontend and endpoint list.

Later pass: remove the query param and update tests/migrations after checking downstream clients.

### 5. Reports

Remove scenario-level `Status:` from report output, or leave it only if the field remains semantically meaningful internally. Recommendation: remove it from markdown/html reports to align with the simplified UX.

## Frontend plan

### 1. API wrapper updates

In `apps/web/src/lib/api/scenarios.ts`:

- Add `draft(prompt: string)` -> `POST /scenarios/draft`.
- Remove `status` from `list()` filters used by the UI.
- Keep create payload fields: `name`, `target_question`, `time_horizon`, `description`.

In `apps/web/src/lib/api/types.ts`:

- Add `ScenarioDraft` type.
- Keep `Scenario.status?: string` optional during transition, or leave it but stop rendering it.

### 2. Scenarios page redesign

In `apps/web/app/scenarios/page.tsx`:

- Replace `createScenarioAction` with:
  - `draftScenarioAction` for natural-language prompt
  - `createScenarioAction` for reviewed draft fields
- Remove status filter select and status badge.
- Introduce chat-like classes:
  - `.chat-panel`
  - `.chat-bubble.user`
  - `.chat-bubble.assistant`
  - `.draft-grid`
- Copy should guide non-technical users, e.g. “Describe the forecast you want Seldon to set up.”

Implementation note: because server actions cannot easily hold local component state in a server component, either:

- Convert only the drafting form into a small client component, or
- Use URL search params with hidden fields, or
- Add a client component under `apps/web/src/components/scenario-draft-chat.tsx` that calls a route/API wrapper from the browser.

Recommendation: create a focused client component. It will be cleaner and feel much more like chat.

### 3. Detail page cleanup

In `apps/web/app/scenarios/[id]/page.tsx`:

- Remove `status` from `editScenarioAction` payload.
- Remove scenario status badge from `PageHeader`.
- Remove the status `<select>` from the metadata form.
- Keep latest prediction status display.

### 4. Styles

In `apps/web/app/styles.css` add lightweight chat styles:

- Chat panel card width/full row
- Assistant/user bubble styling
- Draft field grid
- Clear primary CTA
- Mobile-friendly layout

## Tests to update/add

### Backend

In `tests/unit/test_phase_d_api.py` or a new focused test file:

- `POST /scenarios/draft` with mocked `OpenRouterClient` returns valid draft fields.
- LLM malformed response or exception returns the chosen failure behavior.
- `POST /scenarios` still creates from drafted fields without status.
- Update existing scenario filter/patch/report tests:
  - Remove assertions that depend on scenario status filtering/patching/report status, or split them into a backwards-compat API test if status is kept internally.

### Frontend

Update `apps/web/tests/mock-api.mjs`:

- Handle `POST /scenarios/draft`.
- Existing scenario objects may still include status, but tests should not require UI to render it.

Update `apps/web/tests/e2e/gui-workflows.spec.ts`:

- Scenario creation workflow should fill the natural-language prompt, click `Draft scenario`, review generated fields, click `Create scenario`, then expect redirect.

Update `apps/web/tests/route-smoke.mjs`:

- Replace checks for `GET /scenarios?q=&status=` and old create labels with new route strings/affordances like `POST /scenarios/draft`, `Draft scenario`, `Create scenario`.

## Suggested implementation order

1. Backend: add draft request/response schemas and `POST /scenarios/draft`.
2. Backend tests: mocked LLM draft endpoint tests.
3. Frontend API/types: add `ScenarioDraft`, `scenariosApi.draft`.
4. Frontend UI: add chat-style draft component and simplify scenarios list.
5. Detail cleanup: remove scenario status controls/display.
6. Test mocks/E2E/smoke updates.
7. Run gates:
   - `uv run pytest tests/unit/test_phase_d_api.py -q`
   - `cd apps/web && npm run test:frontend`

## Open decisions

1. Should scenario drafting only create metadata, or should it also immediately enqueue context gathering? Recommendation: metadata only for this pass.
2. Should failed LLM drafting fall back to manual fields or show an error? Recommendation: show graceful manual fallback.
3. Should `scenarios.status` be fully dropped from the database now? Recommendation: no, remove from UX first; drop later if no consumers need it.
