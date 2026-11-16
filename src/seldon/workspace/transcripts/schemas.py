"""Transcript contracts. Generate them with `research transcripts schema --part ...`."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..schemas import Contract, EdgeWrite, GraphScope, NodeWrite, ResearchRound

MAX_IMPORT_CHARS = 5_000_000
MAX_SEGMENTS = 50_000
MAX_EXCERPTS = 200
MAX_WINDOW_SECONDS = 600.0
MAX_QUOTE_CHARS = 1_000

Service = Literal["auto", "youtube", "supadata"]
CaptionKind = Literal["manual", "auto-generated", "ai-generated", "unknown"]
_TIME = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")


def seconds(value: float | int | str | None) -> float | None:
    """Accept 754, 754.5, "754", "12:34" or "1:02:03.5"."""
    if value is None or isinstance(value, (int, float)):
        return None if value is None else float(value)
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = _TIME.match(text)
    if not match:
        raise ValueError(f"Time must be seconds or [h:]mm:ss, got {value!r}")
    hours, minutes, secs = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + float(secs)


def _http(url: str | None) -> str | None:
    if url is not None and not url.startswith(("https://", "http://")):
        raise ValueError("URLs must be HTTP(S)")
    return url


def _aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return value


class FetchRequest(Contract):
    url: str = Field(min_length=1, max_length=2048, description="Video URL (YouTube watch/short/live/youtu.be links, or another platform/file URL for Supadata)")
    languages: list[str] = Field(default_factory=list, max_length=10, description="Preferred ISO 639-1 codes in order; empty keeps the spoken/original language")
    service: Service = Field(default="auto", description="auto: YouTube captions, then Supadata when SUPADATA_API_KEY is set; youtube: captions only; supadata: hosted transcript API")
    mode: Literal["native", "auto", "generate"] = Field(default="auto", description="native: existing captions only; auto: captions, else AI transcription (Supadata); generate: always AI transcription (Supadata)")
    scenario_id: str | None = Field(default=None, description="Research question this video was posted for; shows the transcript in that question's pipeline")
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    agent: str = Field(default="transcript-fetcher", min_length=1, max_length=128)
    reason: str = Field(default="Fetch video transcript", min_length=1)

    @field_validator("languages")
    @classmethod
    def codes(cls, value: list[str]) -> list[str]:
        out = [code.strip().lower() for code in value if code.strip()]
        if any(not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", code) for code in out):
            raise ValueError("Languages must be ISO codes such as en, es or pt-br")
        return out


class Segment(Contract):
    start: float = Field(ge=0)
    duration: float = Field(default=0, ge=0)
    text: str = Field(min_length=1)


class ImportRequest(Contract):
    """A transcript obtained elsewhere (a caption file, the platform's transcript panel or a paid service)."""

    url: str = Field(min_length=1, max_length=2048, description="Canonical media URL that excerpts will cite")
    content: str | None = Field(default=None, max_length=MAX_IMPORT_CHARS, description="WebVTT, SRT, JSON segments or timestamped text ('0:05 words' or a timestamp line followed by text)")
    segments: list[Segment] = Field(default_factory=list, max_length=MAX_SEGMENTS)
    format: Literal["auto", "vtt", "srt", "json", "text"] = "auto"
    language: str | None = Field(default=None, max_length=16)
    caption_kind: CaptionKind = "unknown"
    title: str | None = Field(default=None, max_length=500)
    channel: str | None = Field(default=None, max_length=255)
    channel_url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    obtained_from: str = Field(default="Supplied by the research agent", min_length=1, max_length=500, description="How and where the transcript text was obtained")
    scenario_id: str | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    agent: str = Field(default="transcript-importer", min_length=1, max_length=128)
    reason: str = Field(default="Import supplied video transcript", min_length=1)

    @model_validator(mode="after")
    def check(self):
        _http(self.url)
        _http(self.channel_url)
        _aware(self.published_at, "published_at")
        _aware(self.retrieved_at, "retrieved_at")
        if bool(self.content) == bool(self.segments):
            raise ValueError("Provide either content or segments")
        return self


class Excerpt(Contract):
    id: str = Field(min_length=1, max_length=128, description="Evidence key: a stable local key (scenario-scoped, as in research apply)")
    start: float | str = Field(description="Seconds or [h:]mm:ss where the cited passage begins")
    end: float | str | None = Field(default=None, description="Defaults to start + 30 seconds")
    content: str = Field(min_length=1, max_length=4000, description="Attributed finding, e.g. 'The guest argues that ...'; not a verified fact")
    quote: str | None = Field(default=None, max_length=MAX_QUOTE_CHARS, description="Verbatim words that must occur in the transcript within the window")
    speaker: str | None = Field(default=None, max_length=255, description="Who said it, when identifiable from the video; captions carry no speaker labels")
    kind: Literal["observation", "assumption"] = "observation"
    confidence: float = Field(ge=0, le=1, description="Confidence that the excerpt is accurately captured and attributed, not that it is true")

    @model_validator(mode="after")
    def window(self):
        start, end = seconds(self.start), seconds(self.end)
        if start < 0:
            raise ValueError("Excerpt start must be nonnegative")
        end = start + 30 if end is None else end
        if end <= start:
            raise ValueError("Excerpt end must follow its start")
        if end - start > MAX_WINDOW_SECONDS:
            raise ValueError(f"Excerpt windows are limited to {MAX_WINDOW_SECONDS:.0f} seconds; split longer passages")
        self.start, self.end = start, end
        return self


class Attach(Contract):
    kind: Literal["node", "edge"] = "node"
    id: str = Field(min_length=1, description="Existing node/edge UUID, or a local key of this question")
    evidence_ids: list[str] = Field(min_length=1, description="Excerpt keys or evidence UUIDs to append; existing attachments are kept")


class IngestRequest(Contract):
    """Turn reviewed transcript passages into evidence and graph updates for one research question."""

    schema_version: Literal[1] = 1
    transcript_id: str
    version: int | None = Field(default=None, ge=1, description="Transcript version; defaults to the latest")
    scenario_id: str
    base_revision: str = Field(description="Scenario revision from research export")
    request_id: str = Field(min_length=1, max_length=128)
    agent: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1)
    excerpts: list[Excerpt] = Field(min_length=1, max_length=MAX_EXCERPTS)
    nodes: list[NodeWrite] = Field(default_factory=list)
    edges: list[EdgeWrite] = Field(default_factory=list)
    attach: list[Attach] = Field(default_factory=list, description="Append excerpts to existing nodes/edges without restating their evidence lists")
    reuse_node_ids: list[str] = Field(default_factory=list)
    reuse_edge_ids: list[str] = Field(default_factory=list)
    reuse_evidence_ids: list[str] = Field(default_factory=list)
    graph_scope: GraphScope | None = None
    allow_shared_updates: bool = False
    research_round: ResearchRound | None = None
    queue_rerun: Literal["auto", "always", "never"] = Field(default="auto", description="auto: queue a forecast refresh when the question already has a forecast and none is pending")

    @model_validator(mode="after")
    def unique(self):
        keys = [e.id for e in self.excerpts]
        if len(set(keys)) != len(keys):
            raise ValueError("Excerpt IDs must be unique")
        return self
