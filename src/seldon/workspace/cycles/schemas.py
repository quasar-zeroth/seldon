"""Cycle factor, observation, fit and composite contracts.

Generate the complete schema with `seldon research cycles schema`. Values are
attributed data or explicit codings; fitted cycles are model output, never facts.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from ..schemas import Contract

KEY = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
Domain = Literal[
    "economics", "finance", "conflict", "politics", "society", "demography", "technology", "climate", "other"
]


def _http(urls: list[str]) -> None:
    if any(not url.startswith(("https://", "http://")) for url in urls):
        raise ValueError("References and citations must be HTTP(S) URLs")


class FitSpec(Contract):
    model: Literal["harmonic", "oscillator"] = Field(
        default="harmonic",
        description="harmonic: deterministic sin/cos cycle(s) with period search. oscillator: stochastic damped AR(p) cycle measuring inertia and overshoot",
    )
    trend: Literal["none", "linear", "quadratic"] = Field(
        default="linear", description="Secular trend fitted jointly; none still removes the mean"
    )
    period_years: float | None = Field(
        default=None, gt=0, le=2000, description="Harmonic: fix the period to test a stated theory instead of searching"
    )
    period_min_years: float | None = Field(default=None, gt=0, le=2000)
    period_max_years: float | None = Field(default=None, gt=0, le=5000)
    harmonics: int = Field(
        default=1, ge=1, le=4, description="Harmonic: overtones per cycle; 2-3 capture asymmetric slow-boom/fast-bust shapes"
    )
    cycles: int = Field(default=1, ge=1, le=3, description="Harmonic: number of distinct periods fitted jointly")
    order: int = Field(default=2, ge=1, le=6, description="Oscillator: autoregressive order; 2 is the minimal damped oscillator")
    step_years: float | None = Field(
        default=None, gt=0, le=50, description="Oscillator: regular resampling interval; defaults to the median observation spacing"
    )
    since: dt.date | None = Field(default=None, description="Ignore observations before this date, e.g. to fit one regime")
    until: dt.date | None = Field(default=None, description="Ignore observations after this date, e.g. for a manual backtest")
    horizon_years: float = Field(default=30, gt=0, le=300, description="Projection length after the last observation")
    holdout_fraction: float = Field(
        default=0.2, ge=0, le=0.5, description="Final share of the time span withheld for an out-of-sample check; 0 disables it"
    )
    surrogates: int = Field(
        default=200, ge=0, le=2000, description="Red-noise surrogate series for the significance test; 0 disables it"
    )

    @model_validator(mode="after")
    def consistent(self):
        low, high = self.period_min_years, self.period_max_years
        if low and high and low >= high:
            raise ValueError("period_min_years must be below period_max_years")
        if self.period_years is not None:
            if self.cycles != 1:
                raise ValueError("A fixed period applies to a single cycle")
            if (low and self.period_years < low) or (high and self.period_years > high):
                raise ValueError("Fixed period lies outside the period bounds")
        if self.since and self.until and self.since >= self.until:
            raise ValueError("since must precede until")
        return self


class PhaseLabels(Contract):
    """Domain names for the four cycle quadrants of the fitted cyclical component."""

    peak: str = Field(default="peak", min_length=1, max_length=120)
    declining: str = Field(default="declining", min_length=1, max_length=120)
    trough: str = Field(default="trough", min_length=1, max_length=120)
    rising: str = Field(default="rising", min_length=1, max_length=120)


class Component(Contract):
    factor_id: str = Field(pattern=KEY)
    weight: float = Field(default=1.0, ge=-10, le=10, description="Relative weight; negative inverts the factor")
    lag_years: float = Field(
        default=0, ge=-100, le=100, description="Positive values delay this factor's influence by that many years"
    )

    @model_validator(mode="after")
    def nonzero(self):
        if self.weight == 0:
            raise ValueError("Component weight cannot be zero; omit the component instead")
        return self


class Factor(Contract):
    id: str = Field(pattern=KEY, description="Stable key reused across questions")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    domain: Domain = "other"
    region: str = Field(default="Global", min_length=1, max_length=255, description="Cycles are regional; name the population")
    measurement: Literal["measured", "coded", "derived"] = Field(
        default="measured",
        description="measured: quantitative source data. coded: values assigned to historical records with a rubric. derived: latent factor computed from other factors",
    )
    units: str = Field(default="index", min_length=1, max_length=255)
    low_label: str = Field(default="", max_length=255, description="Meaning of low values")
    high_label: str = Field(default="", max_length=255, description="Meaning of high values")
    rubric: str = Field(default="", max_length=10000, description="Required for coded factors: how each value is assigned")
    hypothesis: str = Field(default="", max_length=10000, description="Proposed mechanism; a hypothesis, not established fact")
    references: list[str] = Field(default_factory=list, max_length=50)
    template: str | None = Field(default=None, description="Catalog template that fills unspecified period bounds and labels")
    phase_labels: PhaseLabels | None = None
    entity_ids: list[str] = Field(
        default_factory=list, description="Explicit shared research entity UUIDs; links this factor to forecasts"
    )
    tags: list[str] = Field(default_factory=list, max_length=50)
    derived_from: list[Component] = Field(default_factory=list, max_length=20)
    fit: FitSpec = Field(default_factory=FitSpec, description="Preferred model; drives automatic refits and forecast context")
    status: Literal["active", "retired"] = "active"

    @model_validator(mode="after")
    def provenance(self):
        _http(self.references)
        if (self.measurement == "derived") != bool(self.derived_from):
            raise ValueError("Derived factors need derived_from components, and only derived factors may have them")
        if self.measurement == "coded" and not self.rubric:
            raise ValueError("Coded factors require a rubric describing how historical records map to values")
        if len({c.factor_id for c in self.derived_from}) != len(self.derived_from):
            raise ValueError("Derived components must be distinct factors")
        if any(c.factor_id == self.id for c in self.derived_from):
            raise ValueError("A factor cannot derive from itself")
        return self


class Observation(Contract):
    id: str | None = Field(
        default=None, pattern=KEY, description="Omit to derive a stable key from factor, date and source; reuse to revise a value"
    )
    factor_id: str = Field(pattern=KEY)
    date: dt.date = Field(description="Observation date; use the period midpoint for annual or multi-year codings")
    value: float
    uncertainty: float | None = Field(default=None, gt=0, description="Standard error in factor units; weights the fit")
    kind: Literal["measured", "coded", "assumption"] = "measured"
    source_name: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    retrieved_at: dt.datetime
    note: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, description="Existing research evidence UUIDs supporting this value")
    status: Literal["active", "withdrawn"] = Field(
        default="active", description="withdrawn removes a value from fits while preserving its history"
    )

    @model_validator(mode="after")
    def provenance(self):
        if self.kind != "assumption" and not (self.source_url or "").startswith(("https://", "http://")):
            raise ValueError("Measured or coded observations require an HTTP(S) source URL; label unsupported values as assumptions")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must include a timezone")
        return self


class Composite(Contract):
    id: str = Field(pattern=KEY)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    components: list[Component] = Field(min_length=1, max_length=20)
    entity_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["active", "retired"] = "active"

    @model_validator(mode="after")
    def distinct(self):
        if len({c.factor_id for c in self.components}) != len(self.components):
            raise ValueError("Composite components must be distinct factors")
        return self


class CycleTopic(Contract):
    """A reusable research subject, matched to questions by explicit entities or entity tags."""

    id: str = Field(pattern=KEY, description="Stable key, e.g. gold-price or ai-investment")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    entity_ids: list[str] = Field(default_factory=list, description="Shared research entity UUIDs that belong to this topic")
    tags: list[str] = Field(default_factory=list, max_length=50, description="Normalized entity tags that also place an entity in this topic, e.g. role:hyperscaler")
    status: Literal["active", "retired"] = "active"

    @model_validator(mode="after")
    def matchable(self):
        if not self.entity_ids and not self.tags:
            raise ValueError("A topic needs entity_ids or tags so questions can be matched to it explicitly")
        return self


class Relevance(Contract):
    """Judged relevance of one cycle to one topic. A scored judgment with reasons, not a correlation."""

    id: str | None = Field(default=None, pattern=KEY, description="Omit to key by topic and cycle; resubmit to revise the score")
    topic_id: str = Field(pattern=KEY)
    factor_id: str | None = Field(default=None, pattern=KEY)
    composite_id: str | None = Field(default=None, pattern=KEY)
    score: float = Field(
        ge=0, le=1, description="0 = irrelevant, 0.25 = background context (the default context floor), 0.5 = material driver, 0.8+ = central to the topic's outcomes"
    )
    direction: Literal["positive", "negative", "mixed", "unknown"] = Field(
        default="unknown", description="Typical effect on the topic's outcome when the cycle is high (its high_label pole)"
    )
    channel: str = Field(min_length=1, max_length=2000, description="Mechanism by which the cycle reaches the topic")
    horizon: Literal["short", "medium", "long", "all"] = Field(
        default="all", description="Forecast horizons where it matters: short (< 1 year), medium (1-5 years), long (> 5 years)"
    )
    rationale: str = Field(min_length=1, max_length=5000)
    citations: list[str] = Field(default_factory=list, max_length=20)
    assessed_at: dt.datetime

    @model_validator(mode="after")
    def target(self):
        if bool(self.factor_id) == bool(self.composite_id):
            raise ValueError("Relevance names exactly one of factor_id or composite_id")
        _http(self.citations)
        if self.assessed_at.tzinfo is None:
            raise ValueError("assessed_at must include a timezone")
        return self


class CyclesApply(Contract):
    request_id: str = Field(min_length=1, max_length=128)
    base_revision: str
    agent: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1)
    factors: list[Factor] = Field(default_factory=list, max_length=200)
    observations: list[Observation] = Field(default_factory=list, max_length=50000)
    composites: list[Composite] = Field(default_factory=list, max_length=100)
    topics: list[CycleTopic] = Field(default_factory=list, max_length=200)
    relevance: list[Relevance] = Field(default_factory=list, max_length=2000)
    refit: bool = Field(default=True, description="Refit affected factors with their preferred specification in the same change")


class FitRequest(Contract):
    agent: str = Field(default="cycle-fitter", min_length=1, max_length=128)
    reason: str = Field(default="Fit cycle model", min_length=1)
    spec: FitSpec | None = Field(default=None, description="Omit to use the factor's preferred specification")


class RefitRequest(Contract):
    agent: str = Field(default="cycle-fitter", min_length=1, max_length=128)
    reason: str = Field(default="Refit stale cycle factors after new data", min_length=1)


class ImportRequest(Contract):
    csv: str = Field(min_length=1, max_length=20_000_000)
    source_name: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    kind: Literal["measured", "coded", "assumption"] = "measured"
    retrieved_at: dt.datetime | None = None
    date_column: str | None = None
    value_column: str | None = None
    uncertainty_column: str | None = None
    year_anchor: Literal["start", "mid", "end"] = "mid"
    note: str = Field(default="", max_length=2000)
    request_id: str | None = Field(default=None, max_length=128)
    agent: str = Field(default="cycle-importer", min_length=1, max_length=128)
    reason: str = Field(default="Import historical series", min_length=1)
    refit: bool = True


class CombineRequest(Contract):
    composite_id: str | None = Field(default=None, pattern=KEY)
    components: list[Component] = Field(default_factory=list, max_length=20)
    start: dt.date | None = None
    end: dt.date | None = None
    at: dt.date | None = Field(default=None, description="Evaluation date for phases and alignment; defaults to today")
    step_years: float = Field(default=1.0, gt=0, le=10)

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.composite_id) == bool(self.components):
            raise ValueError("Provide either composite_id or components")
        return self
