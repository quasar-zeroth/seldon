# Video transcripts

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table; [workspace map](../AGENTS.md) covers research integration. Agent procedure: [seldon-transcripts skill](../../../../skills/seldon-transcripts/SKILL.md). Provenance semantics: [docs/transcripts.md](../../../../docs/transcripts.md).

Video links become versioned transcripts, then timestamped, quote-checked excerpts that enter a question as evidence alongside agent-chosen entities and influence edges.

| File | Logic |
| --- | --- |
| `schemas.py` | Fetch, import, excerpt, attach and ingest contracts; time parsing; limits. |
| `providers.py` | URL canonicalization, YouTube captions (youtube-transcript-api) and watch-page/oEmbed metadata, Supadata transcript/metadata API with job polling, `retrieve` fallback order. The only network code. |
| `catalog.py` | Discovery catalog, caption-kind meanings and `TRANSCRIPT_GUIDANCE` (included in research handoffs). |
| `__init__.py` | Append-only `AgentRun` registry (`media_transcript`) with `Source` lock, versioning/replay, supplied-format parsing, views and Markdown, lexical entity mentions, and `ingest`. |
| `cli.py`, `api.py` | `seldon research transcripts ...` and `/workspace/transcripts` adapters over the same functions. |

Invariants:

- Fetch performs network retrieval before `_lock`, then re-checks `request_id` replay under the lock. Never hold the write lock during network calls.
- Versions are append-only. A version hash covers segments, language, caption kind and core metadata. Unchanged retrievals write nothing unless they carry a new `request_id` or link a new question.
- `ingest` builds a `WorkspaceApply` and passes provenance through `WorkspaceService.apply(..., media=[...])`. `media` is part of the run input and fingerprint only when present, so older replay hashes stay valid. It is not a public apply field.
- Exact ingest replay is detected by `ingest_hash` before rebuilding from a possibly newer transcript version.
- Evidence `source_url` is the canonical video URL, so one video stays one origin. Deep links live in the content.
- Every excerpt must be cited by a node or edge. `attach` appends to existing evidence lists. Quotes must occur in the transcript window.
- Source registration reuses the evidence indexer's source ID, and never overwrites a reviewed profile.
- Rerun queuing records a pending request only. It never produces a forecast.

Pipeline: [pipeline.py](../pipeline.py) shows the optional `transcription` stage only when a question has transcript events or transcript-backed applies.

Verification: [test_transcripts.py](../../../../tests/unit/test_transcripts.py) covers URL forms, supplied formats, caption selection, Supadata sync/async/errors, fallback order, versioning/replay/conflicts, quote and window checks with rollback, attach, source identities, pipeline stages, rerun queuing, mentions, CLI and HTTP. All offline: `httpx` and `requests` are blocked.

Implementation is the source of truth: code, schemas, CLI help and tests outrank design notes. Update this guide and the skill when behavior changes; keep numbers and contracts in code.
