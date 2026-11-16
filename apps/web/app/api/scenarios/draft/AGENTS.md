# Scenario draft proxy

[Root AGENTS.md](../../../../../../AGENTS.md) contains the project-wide lookup table.

`route.ts` accepts a prompt and optional default horizon, rejects an empty prompt, calls `scenariosApi.draft`, and returns draft fields or a JSON error. Drafting does not create a scenario; the parent route handles persistence after user review.

The client fallback/editing experience lives in `src/components/scenario-draft-chat.tsx`, not this handler.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
