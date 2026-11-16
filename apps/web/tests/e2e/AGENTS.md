# Console browser tests

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`gui-routes.spec.ts` checks navigation/rendering across the console routes against the mock backend. `gui-workflows.spec.ts` covers scenario drafting/creation, phase/feedback submission, KB filtering/links, graph layouts/merge display/edits, run retry, report-link formats and settings saves.

The harness is in [../](../AGENTS.md), with browser settings in `../../playwright.config.ts`. These are mock-backed interaction checks, not live provider or durable-persistence tests. Preserve existing test edits and favor meaningful user interactions/error states over checks that merely repeat implementation strings.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
