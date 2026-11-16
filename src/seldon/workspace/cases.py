"""Shared bounds-first case generation and display, without provider dependencies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


CASE_GENERATION_GUIDANCE = (
    "Start case generation with hot takes: construct an extreme lower bound where all "
    "material drivers compound adversely and an extreme upper bound where they compound "
    "favourably for the target metric, within the stated horizon. Save these in case_bounds "
    "(lower and upper: outcome, rationale, assumptions, evidence_ids, optional numeric value "
    "in the forecast units). Explain causal chains, nonlinear feedback, constraints, "
    "counterevidence and which assumptions must hold together; reject incompatible premises. "
    "These are conditional stress bounds, not guaranteed limits, confidence intervals, "
    "or extra probability-bearing branches. Then derive bear, base and bull cases (or "
    "natural equivalents) informed by that envelope. Explain why each central case stops "
    "short of the extremes. Use mutually exclusive, collectively exhaustive resolution "
    "rules, including outcomes beyond the stress bounds in the tails. Assign probabilities "
    "only after constructing cases, using evidence and honest base-rate limitations; do "
    "not widen ranges or inflate tail probabilities just to sound bold. Distinguish sourced "
    "observations from speculative assumptions and disclose residual risk beyond the bounds."
)


class HotTake(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)

    outcome: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    assumptions: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    value: float | None = Field(default=None, description="Conditional stress value in forecast units, not a hard limit")


class CaseBounds(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    lower: HotTake
    upper: HotTake

    @model_validator(mode="after")
    def ordered_values(self):
        if (self.lower.value is None) != (self.upper.value is None):
            raise ValueError("Provide both numeric stress bounds or neither")
        if self.lower.value is not None and self.lower.value >= self.upper.value:
            raise ValueError("Lower stress bound must be below upper stress bound")
        return self


def case_bounds_markdown(bounds: dict | None) -> list[str]:
    """Render saved bounds; missing bounds on historical forecasts stay missing."""
    if not bounds:
        return []
    lines = [
        "### Hot takes: conditional stress bounds",
        "",
        "Constructed before the central cases. These are conditional scenarios, not guaranteed limits or additional probability mass.",
        "",
    ]
    for key, label in (("lower", "Everything goes wrong — lower bound"), ("upper", "Everything goes right — upper bound")):
        bound = bounds[key]
        value = f" ({bound['value']:g} in forecast units)" if bound.get("value") is not None else ""
        lines += [f"**{label}{value}:** {bound['outcome']}", "", bound["rationale"], ""]
        lines += [f"- Assumption: {item}" for item in bound["assumptions"]]
        lines += ["- Evidence: " + ", ".join(bound["evidence_ids"]), ""]
    return lines
