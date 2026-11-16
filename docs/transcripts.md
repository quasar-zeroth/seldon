# Video transcripts as research evidence

Agents add videos to research with the [seldon-transcripts skill](../skills/seldon-transcripts/SKILL.md). Code lives in [workspace/transcripts](../src/seldon/workspace/transcripts/AGENTS.md); `research transcripts catalog` and `schema` are authoritative for services, formats and limits.

## Services and what they return

`fetch` contacts an online transcript service. It is the only workspace command that uses the network, and none of these services is a model provider for Seldon's own reasoning.

- **YouTube captions** (default, no key): the video's caption tracks. Creator-uploaded (`manual`) tracks are preferred over YouTube's automatic speech recognition (`auto-generated`) in the same language. When no language is requested, the spoken language (the automatic track's language) is used. Seldon never silently translates.
- **Supadata** (`SUPADATA_API_KEY`): a hosted, metered API for YouTube, TikTok, Instagram, X, Facebook and media files. `mode` selects existing captions only, captions with AI fallback, or AI transcription. Its response does not say whether text came from captions or AI unless AI was forced or ran as a job, so such text is labelled `unknown`.
- **Supplied** (`import`): text the agent obtained elsewhere, with a required note on how it was obtained. Timings are required because evidence cites moments in the video.

Title, channel and upload date come from platform metadata on a best-effort basis. Missing values stay unknown and produce warnings; they are never guessed.

## Storage and versions

Transcripts are append-only `AgentRun` events (phase `media_transcript`) behind a `Source` lock row, like the cycle and perspective registries. The transcript ID is stable for a platform, video, service, language and caption kind. A retrieval whose segments or core metadata differ from the latest version adds a version. Unchanged retrievals record nothing unless they carry a new `request_id` or link the transcript to a new question. Network retrieval happens before the write lock is taken, so a slow service does not block other writers.

## Excerpts and evidence semantics

An excerpt is a cited time window. Ingestion checks that the window holds transcript text and that any quote occurs verbatim within it (ignoring case, punctuation and spacing, and allowing one neighbouring segment for boundary drift). Each excerpt becomes one evidence record:

- `source_url` is the canonical video URL. All excerpts of one video therefore share one origin in the perspectives graph, and repeated excerpts do not count as independent corroboration.
- `published_at` is the upload time and `retrieved_at` is the transcript retrieval time. Forecasts reject evidence published after their `as_of`.
- The content holds the agent's attributed finding, then the caption kind, time range, speaker (if given), the quote or window text, and a timestamped deep link.

Excerpts establish that something was said at that point in the video, as captured by the service. They do not establish that it is true or who said it (captions have no speaker labels), and a speaker's prediction is not evidence of the outcome. Automatic and AI transcription mis-hears names and numbers.

## Graph, sources and pipeline effects

Ingestion builds a normal workspace apply: evidence, nodes, edges, reuse lists, scope and an optional research round, validated and recorded in one transaction with the transcript provenance. Because evidence only enters a question through its in-scope nodes and edges, every excerpt must be attached, and entities without a path to the target are reported.

The video becomes a `document` source `published_by` its channel (`publication`) in the perspectives graph, using the same source ID the evidence indexer assigns. An existing reviewed profile is never overwritten. Speakers are distinct identities, added through `perspectives apply` only after verification.

The research pipeline shows the optional **Video transcripts** stage only for questions with transcript work. A fetch for a question records it as needing follow-up. Ingestion completes it with excerpt count and cited seconds, and records evidence, entity and graph stages from the same request. The question's knowledge revision changes, so saved forecasts show changed knowledge. `queue_rerun` can add a pending refresh request, which still needs an agent to research and forecast.
