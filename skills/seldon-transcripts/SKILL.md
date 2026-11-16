---
name: seldon-transcripts
description: Turn video links (mostly YouTube; also TikTok, Instagram, X, Facebook, podcasts or media files) into Seldon research. Fetches the transcript from an online service (YouTube captions, or the Supadata API with AI transcription for videos without captions), stores it with versioned provenance, finds shared entities it mentions, and ingests timestamped, quote-checked excerpts as evidence together with the entities and influence relationships they support. The question's research pipeline updates automatically (a "Video transcripts" stage plus evidence, entity and graph stages), its forecast is marked as having changed knowledge, and a forecast refresh can be queued. Use when the user posts or pastes a video/podcast link, asks to "add this video", "what does this video say about X", or wants a talk, interview, earnings call or speech reflected in a forecast.
---

# Seldon transcripts

Seldon fetches a video's transcript, keeps every retrieved version, and checks the excerpts you cite against it. You do the semantic work: read the transcript, decide what matters for which question, write attributed findings, and choose the entities and relationships. Ingestion then goes through the same validated transaction as `research apply`. Provenance rules and limits: [docs/transcripts.md](../../docs/transcripts.md). Terms: [GLOSSARY.md](../../GLOSSARY.md).

## Setup

- Run from the Seldon repository: `uv run seldon research --db /ABSOLUTE/PATH.db transcripts <command>`. Use the shared research database (root `AGENTS.md`); `parallax research transcripts ...` uses Parallax's installed database.
- HTTP equivalents are under `/workspace/transcripts` on the Seldon API, with the same authentication.
- Discover before writing: `transcripts catalog` (services, caption kinds, URL forms, import formats, excerpt rules, limits) and `transcripts schema --part fetch|import|ingest`.
- `transcripts fetch` is the only command that uses the network. YouTube captions need no key. For videos without captions, other platforms, or when YouTube blocks the address, set `SUPADATA_API_KEY` in the environment of the CLI or API process (metered service).
- Add `--out FILE` to any command to save its output.

## Workflow

1. **Pick the question.** If the user named one, use it. Otherwise list questions (`research list`) and, after step 2, use `transcripts mentions` to see which questions share the video's entities. If none fits and the user wants one, create it with `research start` (see [agent-workflow.md](../../docs/agent-workflow.md)). Do not create a question per video.
2. **Fetch.** `transcripts fetch URL --scenario SCENARIO_ID [--lang en] [--request-id fetch-VIDEOID]`.
   - Returns `transcript_id`, version, title, channel, upload date, language, `caption_kind` and `warnings`. The question's pipeline now shows **Video transcripts: needs follow-up**.
   - Refetching unchanged text records nothing. Changed captions become a new version; old versions stay readable (`--version N`).
   - Fetch failed? See Troubleshooting. If you obtained the text elsewhere (a caption file, the platform's transcript panel, a paid service), store it with `transcripts import FILE --url URL --title ... --channel ... --published-at ... --obtained-from "..."`. WebVTT, SRT, JSON segments and timestamped text are accepted; untimed text is not.
3. **Read it.** `transcripts show TRANSCRIPT_ID --out talk.md` gives timestamped paragraphs with deep links. Page long videos with `--from 20:00 --to 40:00`. Read the whole range you rely on; do not cite from the title or description.
4. **Find shared entities.** `transcripts mentions TRANSCRIPT_ID` lists existing library entities named in the transcript, with timestamps, and the questions they belong to. A name match is not an identity match: confirm the same thing is meant, then reuse its UUID. Also run `research library QUERY` for concepts the video describes without naming them.
5. **Export the question** (`research export SCENARIO_ID`) for its `revision`, nodes, target and `graph_scope`.
6. **Write the ingest request** (`transcripts ingest ingest.json`):

   ```json
   {
     "transcript_id": "FROM_FETCH",
     "scenario_id": "SCENARIO_ID",
     "base_revision": "FROM_EXPORT",
     "request_id": "video-VIDEOID-1",
     "agent": "your-agent-name",
     "reason": "Fed official's interview on balance-sheet policy",
     "excerpts": [{
       "id": "fed-qt-pace",
       "start": "12:34", "end": "13:10",
       "speaker": "Interviewed Fed governor",
       "quote": "we expect to slow the pace of runoff",
       "content": "The governor says the Fed expects to slow balance-sheet runoff.",
       "confidence": 0.8
     }],
     "nodes": [{"id": "qt-pace", "name": "Fed balance-sheet runoff pace", "type": "policy", "tags": ["country:us"], "evidence_ids": ["fed-qt-pace"]}],
     "edges": [{"id": "qt-to-yields", "source": "qt-pace", "target": "EXISTING_YIELDS_UUID", "relationship": "causes", "direction": "positive", "description": "Faster runoff adds duration supply", "evidence_ids": ["fed-qt-pace"]}],
     "reuse_node_ids": ["EXISTING_YIELDS_UUID"],
     "attach": [{"kind": "node", "id": "EXISTING_GOLD_UUID", "evidence_ids": ["fed-qt-pace"]}]
   }
   ```

   - **Excerpts** become evidence citing the video URL, its upload date and the retrieval time. Seldon appends the time range, speaker, quote and a deep link to your `content`. `end` defaults to `start` + 30 s; windows are capped (see catalog).
   - **`quote`** must be verbatim transcript words inside the window (case and punctuation ignored); otherwise the request is rejected. Omit it to cite the window's text.
   - **Attribute, don't assert.** Write "The guest argues/predicts/reports ...". A speaker's forecast is an opinion about the future: use `kind: assumption` if it is a premise you rely on, never an observation of the outcome.
   - Every excerpt must be cited by a node or edge (`nodes`, `edges` or `attach`), or it would be invisible to the question.
   - **`attach`** appends excerpts to existing nodes/edges and keeps their current evidence. Listing an existing node under `nodes` instead replaces its evidence list with the one you send.
   - Edges point **driver → effect** and must keep the question a DAG. Connect new entities to the forecast target; the result lists `out_of_scope_node_ids` that cannot inform forecasts yet.
   - Shared entities edited from another question need `allow_shared_updates: true` after you review their other uses.
   - Optional: `research_round` (queries can be the URL and follow-up searches), `graph_scope`, `reuse_*_ids`, `version` to pin a transcript version.
7. **Read the result.**
   - `ids` maps your keys to UUIDs.
   - The pipeline now shows **Video transcripts: completed** (excerpt count and seconds cited) with evidence, entity and graph stages.
   - The video and its channel are recorded as distinct sources (`document` published by `publication`) in the perspectives graph.
   - `warnings` cover unknown upload dates and disconnected entities.
   - `rerun` reports whether a forecast refresh was queued.
8. **Verify what the video says** before it moves a forecast. Find independent sources for material claims (a channel repeating a wire story is not independent), record disputes with `perspectives apply`, and continue the normal research loop. Use other questions' evidence through `reuse_evidence_ids` rather than re-ingesting the same excerpt.
9. **Refresh the forecast if asked.** `queue_rerun` (`auto` by default) queues a refresh request when the question already has a forecast and none is pending; `always` or `never` override that. A queued request is a handoff, not a forecast. Complete it per [agent-workflow.md](../../docs/agent-workflow.md) with `prediction_request_id`.

| Situation | Do this |
| --- | --- |
| YouTube video with captions | `fetch` (default `auto`) |
| No captions, TikTok/X/Instagram/Facebook, or a media file URL | `fetch --service supadata` (`--mode generate` forces AI transcription) |
| Captions in several languages | `--lang` in order of preference; default is the spoken language. Translate in `content`, keep `quote` in the original language |
| Video relevant to two questions | Ingest into the main one; in the other, `reuse_evidence_ids` with the evidence UUIDs |
| Same video refetched later | Pin `version` in ingest if you read an older version |
| Panel discussion, several speakers | Set `speaker` per excerpt from what the video shows; leave it out when unsure |

## Guardrails

- A transcript records what was said, not what is true. Captions mishear names and numbers. Check figures against the video or a primary source before relying on them, and lower `confidence` for automatic captions.
- Do not invent quotes, timestamps or speakers. Use the stored transcript, not memory or the video description.
- Keep requests idempotent: reuse a `request_id` only for identical input. On a 409 or stale revision, re-export and reconcile.
- Do not delete or rewrite earlier transcript versions or evidence. Correct by adding a new excerpt and explaining it.
- Respect the user's choice of video. Do not fetch unrelated videos or channels without being asked. Research requests do not authorize trades.

## Troubleshooting

- `No captions in ...; available: ...`: pass an available `--lang`, or use `--service supadata`.
- `YouTube captions request failed` (blocked address, rate limit) or `Supadata ... not configured`: set `SUPADATA_API_KEY`, retry later, or `transcripts import` a caption file.
- `quote does not occur in the transcript`: copy the words from `transcripts show` for that range, or widen `start`/`end`.
- `Excerpt ... is not attached to any node or edge`: cite it in a node, edge or `attach`.
- `Reference belongs to another scenario` / `Shared records require explicit cross-scenario review`: add the UUID to `reuse_node_ids`, or set `allow_shared_updates` after review.
- `Upload date unknown`: find the date and re-import with `--published-at`, otherwise forecasts cannot check that the evidence predates their `as_of`.
