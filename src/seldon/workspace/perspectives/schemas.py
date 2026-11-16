"""Evidence and source judgments are attributed assertions, never objective scores."""
from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from ..schemas import Contract


class Record(Contract):
    id: str = Field(min_length=1, max_length=128)


class Topic(Record):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Source(Record):
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["writer", "publication", "conglomerate", "institution", "document", "unknown"] = "unknown"
    url: str | None = None
    description: str = ""
    region: str = "Unspecified"
    aliases: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list, description="Explicit matches to shared research entities; never inferred from a similar name")


class Claim(Record):
    topic_ids: list[str] = Field(min_length=1)
    statement: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    kind: Literal["reported", "assumption"] = "reported"
    evidence_ids: list[str] = Field(default_factory=list)
    # Same wire story/release/eyewitness is one origin, even if republished many times.
    origin_id: str | None = None
    derived_from_claim_ids: list[str] = Field(default_factory=list)
    import_note: str | None = None

    @model_validator(mode="after")
    def provenance(self):
        if self.kind == "reported" and (not self.source_ids or not (self.source_url or "").startswith(("http://", "https://"))):
            raise ValueError("Reported claims require source identities and an HTTP(S) URL")
        for name in ("published_at", "retrieved_at", "valid_from", "valid_until"):
            value = getattr(self, name)
            if value and value.tzinfo is None:
                raise ValueError(f"{name} must include a timezone")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class TopicLink(Record):
    source: str
    target: str
    relationship: Literal["subtopic", "related"] = "related"
    rationale: str = Field(min_length=1)


class SourceLink(Record):
    source: str
    target: str
    relationship: Literal["owns", "writes_for", "affiliated_with", "funds", "syndicates_from", "published_by", "authored_by"]
    rationale: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: Literal["reported", "verified", "disputed", "ended"] = "reported"

    @model_validator(mode="after")
    def dates(self):
        for value in (self.valid_from, self.valid_until):
            if value and not value.tzinfo:
                raise ValueError("Affiliation dates require timezones")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Affiliation end must follow start")
        return self


class ClaimLink(Record):
    source: str
    target: str
    relationship: Literal["contradicts", "supports", "supersedes"]
    rationale: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)


class Leaning(Contract):
    dimension: str = Field(min_length=1, description="E.g. geopolitics, economics, labor, religion or a named issue")
    position: str = Field(min_length=1)
    region: str = Field(min_length=1, description="Political/cultural frame; no universal left/right scale")
    context: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)


class Assessment(Record):
    target_kind: Literal["claim", "source"]
    target_id: str
    assessed_at: datetime
    scope: str = Field(default="general", min_length=1, description="General or a specific topic/region/time context")
    trust_percent: float | None = Field(default=None, ge=0, le=100)
    status: Literal["unassessed", "reported", "fact", "disputed", "refuted", "retracted"] = "unassessed"
    rationale: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)
    verification_method: str | None = None
    leanings: list[Leaning] = Field(default_factory=list)

    @model_validator(mode="after")
    def judgment(self):
        if self.assessed_at.tzinfo is None:
            raise ValueError("Assessment date requires timezone")
        if self.trust_percent is not None and not self.citations:
            raise ValueError("A trust score needs cited grounds; leave it null if unassessed")
        if self.target_kind == "source" and self.status != "unassessed":
            raise ValueError("Fact/disputed/refuted are claim statuses, not labels for a source")
        if self.target_kind == "claim" and self.leanings:
            raise ValueError("Leanings describe sources; assess claim truth separately")
        if self.status == "fact" and (not self.citations or not self.verification_method):
            raise ValueError("A fact assessment needs citations and a verification method")
        return self


class PerspectiveApply(Contract):
    request_id: str = Field(min_length=1, max_length=128)
    base_revision: str
    agent: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1)
    topics: list[Topic] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    topic_links: list[TopicLink] = Field(default_factory=list)
    source_links: list[SourceLink] = Field(default_factory=list)
    claim_links: list[ClaimLink] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def citation_urls(self):
        for row in [*self.source_links, *self.claim_links, *self.assessments]:
            urls = list(row.citations)
            if isinstance(row, Assessment):
                urls += [url for leaning in row.leanings for url in leaning.citations]
            if any(not url.startswith(("https://", "http://")) for url in urls):
                raise ValueError("Citations must be HTTP(S) URLs")
        return self
