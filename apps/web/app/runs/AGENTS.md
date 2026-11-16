# Agent Runs console

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` passes scenario/phase/agent/status/model/date/failure filters to the backend, groups runs into phase or scenario timelines, and retries runs through a server action.

- [[id]/]([id]/AGENTS.md): execution payloads, messages, model invocations and related records.
- `error.tsx`, `loading.tsx`: scoped route boundaries.

Backend dispatch determines retry semantics. A successful request or pending record does not prove an execution completed; these views currently update through navigation/refresh.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
