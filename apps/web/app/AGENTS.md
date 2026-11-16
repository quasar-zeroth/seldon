# Console routes and server actions

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table.

Next.js App Router pages fetch persisted backend data through `src/lib/api`. Most mutation forms use server actions, followed by route revalidation or redirects. Interactive drafting, graph rendering and charts live in shared client components.

- `page.tsx`: Mission Control health/counts and links to scenarios, predictions and recent runs; independently tolerates failed overview requests.
- `layout.tsx`: root HTML, metadata, shell and stylesheet imports; `styles.css`: shared visual styles.
- `error.tsx`, `loading.tsx`: shared route failure/loading boundaries; child page directories provide scoped equivalents.

| Route group | Local guide |
| --- | --- |
| Scenario list and detail | [scenarios/](scenarios/AGENTS.md) |
| Evidence library and entry detail | [kb/](kb/AGENTS.md) |
| Graph explorer | [graph/](graph/AGENTS.md) |
| Runs and execution detail | [runs/](runs/AGENTS.md) |
| Outcome resolution and analytics | [calibration/](calibration/AGENTS.md) |
| Runtime configuration and data clearing | [settings/](settings/AGENTS.md) |
| Same-origin scenario request proxies | [api/](api/AGENTS.md) |

Keep domain calculations, validation and persistence on the backend. Existing pages generally refresh after actions; there is no live polling/event subscription here.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
