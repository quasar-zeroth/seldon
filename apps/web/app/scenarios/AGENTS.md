# Scenario list and creation

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` searches persisted scenarios, joins their latest predictions for summaries, embeds the conversational draft editor, and deletes scenarios through a server action. Creation uses shared client UI plus same-origin API proxies.

- [[id]/]([id]/AGENTS.md): scenario workspace, phase requests, predictions, evidence, exports and feedback.
- `error.tsx`, `loading.tsx`: scoped route boundaries.

Keep the original research prompt separate from editable scenario metadata. Drafting is preparation; a record exists only after backend creation succeeds.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
