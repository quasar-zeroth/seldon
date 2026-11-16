"""Discovery catalog: services, caption kinds, excerpt rules and shared guidance."""

from __future__ import annotations

from .providers import SUPADATA_KEY_ENV
from .schemas import MAX_EXCERPTS, MAX_IMPORT_CHARS, MAX_QUOTE_CHARS, MAX_SEGMENTS, MAX_WINDOW_SECONDS

TRANSCRIPT_GUIDANCE = (
    "When the user supplies video or podcast links, fetch each transcript with research transcripts fetch "
    "(skills/seldon-transcripts/SKILL.md), read it, and ingest timestamped excerpts as attributed evidence with the nodes "
    "and edges they support. A speaker's statement is evidence of what was said, not a verified fact."
)

SERVICES = {
    "youtube": {
        "label": "YouTube caption tracks",
        "network": True,
        "credentials": None,
        "platforms": ["youtube"],
        "notes": "Creator-uploaded captions are preferred over YouTube's automatic speech recognition in the same language. Fails for videos without captions, members-only or age-restricted videos, or when YouTube blocks the network address.",
    },
    "supadata": {
        "label": "Supadata transcript API",
        "network": True,
        "credentials": SUPADATA_KEY_ENV,
        "platforms": ["youtube", "tiktok", "instagram", "x", "facebook", "media file URLs"],
        "modes": {"native": "Existing platform captions only", "auto": "Captions, else AI transcription", "generate": "Always AI transcription"},
        "notes": "Hosted, metered service; AI transcription of long videos runs as a job that Seldon polls until it finishes.",
    },
    "auto": {"label": "YouTube captions first, then Supadata when its key is set", "network": True},
    "supplied": {"label": "Transcript imported by the agent (research transcripts import)", "network": False},
}

CAPTION_KINDS = {
    "manual": "Uploaded by the creator or a captioning service. Usually accurate, may be edited or condensed.",
    "auto-generated": "Platform speech recognition. Expect misheard names, numbers and jargon, no punctuation and no speaker labels.",
    "ai-generated": "Machine transcription by the transcript service. Same caveats as auto-generated.",
    "unknown": "The service did not report how the text was produced. Treat it like auto-generated text.",
}


def catalog() -> dict:
    return {
        "services": SERVICES,
        "caption_kinds": CAPTION_KINDS,
        "urls": [
            "https://www.youtube.com/watch?v=ID",
            "https://youtu.be/ID",
            "https://www.youtube.com/shorts/ID",
            "https://www.youtube.com/live/ID",
            "a bare 11-character YouTube ID",
            "other platform or media-file URLs (Supadata only)",
        ],
        "import_formats": {
            "vtt": "WebVTT caption file",
            "srt": "SubRip caption file",
            "json": "Array of {start, duration, text} (seconds), or Supadata-style {offset, duration, text} (milliseconds)",
            "text": "Timestamped text: '0:05 words' / '[00:05] words' lines, or a timestamp line followed by its text (YouTube's transcript panel)",
        },
        "excerpts": {
            "addressing": "start/end in seconds or [h:]mm:ss; end defaults to start + 30 s",
            "quote": "Optional verbatim words; must occur in the transcript inside the window (case, punctuation and spacing are ignored)",
            "evidence": "Each excerpt becomes one evidence record citing the video URL, its upload date and the transcript retrieval time. The content keeps your finding plus the timestamped deep link and quote.",
            "max_window_seconds": MAX_WINDOW_SECONDS,
            "max_quote_chars": MAX_QUOTE_CHARS,
            "max_excerpts": MAX_EXCERPTS,
        },
        "limits": {"import_chars": MAX_IMPORT_CHARS, "segments": MAX_SEGMENTS},
        "pipeline": "Fetching for a question records a 'Video transcripts' stage that needs follow-up; ingesting excerpts completes it and records evidence, entity and graph stages in the same transaction.",
        "reruns": "queue_rerun=auto queues a forecast refresh request when the question already has a forecast and none is pending. A request is a handoff for an agent, not a new forecast.",
        "semantics": {
            "transcripts": "Versioned, append-only copies of what a service returned at a retrieval time. A changed caption track becomes a new version; earlier versions stay readable.",
            "excerpts": "Record what was said at a time in a video. They do not verify the statement, establish who spoke, or make a speaker's forecast evidence of the outcome.",
            "mentions": "Lexical matches of shared entity names in the transcript. A name match does not prove the same entity is meant.",
        },
        "guidance": TRANSCRIPT_GUIDANCE,
    }
