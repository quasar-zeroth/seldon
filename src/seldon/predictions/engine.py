"""PredictionEngine: creates, updates, and deactivates market predictions."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from ..config import PredictionConfig
from ..llm import LLMClientProtocol, NullLLMClient

console = Console()

PREDICTION_SYSTEM = """You are a financial forecaster managing a portfolio of market predictions.

Given recent news summaries and existing predictions, respond with a JSON object:
{
  "new_predictions": [
    {
      "slug": "kebab-case-slug",
      "title": "Prediction: <clear statement>",
      "category": "Macro | Tech | Energy | Finance | Earnings | Crypto | Geopolitical",
      "confidence": 0.0-1.0,
      "bull_scenario": {
        "probability": 0.0-1.0,
        "description": "What happens in bull case",
        "impact": "Market impact",
        "triggers": ["specific measurable trigger"]
      },
      "base_scenario": {
        "probability": 0.0-1.0,
        "description": "Base case",
        "impact": "Market impact",
        "triggers": ["trigger"]
      },
      "bear_scenario": {
        "probability": 0.0-1.0,
        "description": "Bear case",
        "impact": "Market impact",
        "triggers": ["trigger"]
      },
      "tickers": ["AAPL"],
      "timeframe_days": 30,
      "rationale": "Why this prediction is worth making"
    }
  ],
  "updates": [
    {
      "slug": "existing-slug",
      "new_evidence": "What new info changes this prediction",
      "bull_probability": 0.35,
      "base_probability": 0.45,
      "bear_probability": 0.20,
      "confidence": 0.62,
      "sentiment_change": "more_bullish | more_bearish | same"
    }
  ],
  "deactivate": [
    {
      "slug": "existing-slug",
      "reason": "Why deactivating",
      "outcome": "bull | base | bear | unknown",
      "outcome_description": "What actually happened"
    }
  ]
}

Rules:
- Probabilities in each scenario MUST sum to 1.0
- Only create predictions with clear, measurable outcomes
- Only create if supported by multiple sources
- Min confidence to create: 0.40
"""


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:60].rstrip("-")


class PredictionEngine:
    """Manages market predictions lifecycle."""

    def __init__(
        self,
        data_dir: str | Path = "./data",
        pred_cfg: PredictionConfig | Any | None = None,
        llm_client: LLMClientProtocol | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.pred_cfg = pred_cfg or PredictionConfig()
        self.llm = llm_client or NullLLMClient()

    @property
    def active_dir(self) -> Path:
        return self.data_dir / "predictions" / "active"

    @property
    def resolved_dir(self) -> Path:
        return self.data_dir / "predictions" / "resolved"

    def _load_active_predictions(self) -> list[dict]:
        """Load all active prediction metadata from JSON sidecar files."""
        self.active_dir.mkdir(parents=True, exist_ok=True)
        predictions = []
        for f in self.active_dir.glob("*.json"):
            try:
                with open(f) as fp:
                    predictions.append(json.load(fp))
            except Exception:
                pass
        return predictions

    def _save_prediction(self, pred: dict, resolved: bool = False):
        """Save prediction JSON and Markdown files."""
        slug = pred["slug"]
        target_dir = self.resolved_dir if resolved else self.active_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        json_path = target_dir / f"{slug}.json"
        md_path = target_dir / f"{slug}.md"

        with open(json_path, "w") as f:
            json.dump(pred, f, indent=2, default=str)

        md_content = self._render_markdown(pred)
        md_path.write_text(md_content)

    def _render_markdown(self, pred: dict) -> str:
        """Render prediction dict to Markdown."""
        bull = pred.get("bull_scenario", {})
        base = pred.get("base_scenario", {})
        bear = pred.get("bear_scenario", {})
        tickers = ", ".join(pred.get("tickers", []))
        history = pred.get("probability_history", [])

        history_rows = "\n".join(
            f"| {h['date']} | {h['bull']:.0%} | {h['base']:.0%} | {h['bear']:.0%} | {h.get('trigger', '')} |"
            for h in history[-10:]
        )

        evidence = pred.get("evidence_chain", [])
        evidence_text = "\n".join(f"- {e['date']}: {e['text']}" for e in evidence[-10:])

        contrarian_block = "\n\n> ⚠️ **Contrarian Opportunity**: >80% of linked topic sentiment agrees on direction. Markets may have already priced in the consensus." if pred.get("contrarian_flag") else ""

        return f"""# {pred.get("title", "Prediction")}

**ID:** {pred["slug"]}
**Status:** {pred.get("status", "Active")} | **Created:** {pred.get("created_at", "")[:10]} | **Last Updated:** {pred.get("updated_at", "")[:10]}
**Category:** {pred.get("category", "Unknown")} | **Confidence:** {pred.get("confidence", 0):.0%}
**Linked Tickers:** {tickers}
**Timeframe:** {pred.get("timeframe_days", 30)} days{contrarian_block}

## Current Scenario Analysis

### Positive Scenario (Bull) — P({bull.get("probability", 0):.0%})
{bull.get("description", "")}
- **Impact:** {bull.get("impact", "")}
- **Triggers:** {", ".join(bull.get("triggers", []))}

### Neutral Scenario (Base) — P({base.get("probability", 0):.0%})
{base.get("description", "")}
- **Impact:** {base.get("impact", "")}
- **Triggers:** {", ".join(base.get("triggers", []))}

### Negative Scenario (Bear) — P({bear.get("probability", 0):.0%})
{bear.get("description", "")}
- **Impact:** {bear.get("impact", "")}
- **Triggers:** {", ".join(bear.get("triggers", []))}

## Probability History
| Date | Bull | Base | Bear | Trigger |
|------|------|------|------|---------|
{history_rows}

## Evidence Chain
{evidence_text or "_No evidence recorded yet_"}

## Rationale
{pred.get("rationale", "")}
"""

    def _read_context(self) -> str:
        """Read recent news summaries as context for predictions."""
        parts = []
        today = datetime.now(tz=timezone.utc)

        # Daily summaries
        for i in range(self.pred_cfg.context.daily_summaries):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            path = self.data_dir / "news" / "daily" / date_str / "DAILY_SUMMARY.md"
            if path.exists():
                parts.append(f"## Daily Summary {date_str}\n{path.read_text()[:1500]}")

        # Weekly summaries
        weekly_dir = self.data_dir / "news" / "weekly"
        if weekly_dir.exists():
            weekly_files = sorted(
                [f for year_dir in weekly_dir.iterdir() if year_dir.is_dir()
                 for f in year_dir.glob("*.md")],
                reverse=True,
            )
            for wf in weekly_files[: self.pred_cfg.context.weekly_summaries]:
                parts.append(f"## {wf.stem}\n{wf.read_text()[:1000]}")

        # Monthly summaries
        monthly_dir = self.data_dir / "news" / "monthly"
        if monthly_dir.exists():
            monthly_files = sorted(
                [f for year_dir in monthly_dir.iterdir() if year_dir.is_dir()
                 for f in year_dir.glob("*.md")],
                reverse=True,
            )
            for mf in monthly_files[: self.pred_cfg.context.monthly_summaries]:
                parts.append(f"## {mf.stem}\n{mf.read_text()[:800]}")

        return "\n\n---\n\n".join(parts) if parts else "No news summaries available yet."

    def _apply_confidence_decay(self, predictions: list[dict], today: datetime) -> list[dict]:
        """Apply exponential confidence decay for predictions not updated recently.

        Formula: new_confidence = confidence * (0.98 ^ days_since_update)
        Minimum confidence after decay: 0.20
        """
        for pred in predictions:
            updated_str = pred.get("updated_at", pred.get("created_at", ""))
            if not updated_str:
                continue
            try:
                updated_dt = datetime.fromisoformat(updated_str)
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                days_since = (today - updated_dt).days
                if days_since > 0:
                    decay_factor = 0.98 ** days_since
                    old_conf = pred.get("confidence", 0.5)
                    new_conf = max(0.20, old_conf * decay_factor)
                    if abs(new_conf - old_conf) > 0.005:
                        pred["confidence"] = round(new_conf, 4)
                        pred.setdefault("evidence_chain", []).append({
                            "date": today.strftime("%Y-%m-%d"),
                            "text": f"Confidence decayed from {old_conf:.2%} to {new_conf:.2%} ({days_since}d without update)",
                        })
            except Exception:
                pass
        return predictions

    def _check_contrarian_flag(self, pred: dict) -> bool:
        """Return True if >80% of linked topic sentiments agree on direction.

        This flags potential contrarian opportunities — when consensus is very high.
        """
        topics_dir = self.data_dir / "news" / "daily"
        if not topics_dir.exists():
            return False

        tickers = pred.get("tickers", [])
        if not tickers:
            return False

        # Collect sentiment from topic files that mention these tickers
        sentiments = []
        today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        for date_dir in sorted(topics_dir.iterdir(), reverse=True)[:7]:  # last 7 days
            if not date_dir.is_dir():
                continue
            for topic_file in date_dir.glob("*.md"):
                if topic_file.stem == "DAILY_SUMMARY":
                    continue
                try:
                    content = topic_file.read_text()
                    # Check if any ticker is mentioned
                    if not any(ticker.upper() in content.upper() for ticker in tickers):
                        continue
                    # Extract sentiment line
                    for line in content.split("\n"):
                        if "**Sentiment:**" in line:
                            line_lower = line.lower()
                            if "bullish" in line_lower:
                                sentiments.append("bullish")
                            elif "bearish" in line_lower:
                                sentiments.append("bearish")
                            elif "neutral" in line_lower:
                                sentiments.append("neutral")
                except Exception:
                    pass

        if len(sentiments) < 3:
            return False

        # Count majority direction (exclude neutral)
        directional = [s for s in sentiments if s != "neutral"]
        if not directional:
            return False

        bullish_count = directional.count("bullish")
        bearish_count = directional.count("bearish")
        total = len(directional)

        return bullish_count / total > 0.80 or bearish_count / total > 0.80

    def run(self) -> dict:
        """Run prediction engine: create/update/deactivate predictions."""
        today = datetime.now(tz=timezone.utc)
        today_str = today.strftime("%Y-%m-%d")

        context = self._read_context()
        active_preds = self._load_active_predictions()

        # Apply confidence decay before LLM call
        active_preds = self._apply_confidence_decay(active_preds, today)

        # Deactivate expired predictions
        expired_slugs = []
        for pred in active_preds:
            created = datetime.fromisoformat(pred.get("created_at", today_str))
            age_days = (today - created.replace(tzinfo=timezone.utc)).days
            if age_days > self.pred_cfg.deactivate_after_days:
                expired_slugs.append(pred["slug"])

        # Build active predictions summary for context
        active_summary = "\n".join(
            f"- {p['slug']}: {p.get('title', '')} (conf: {p.get('confidence', 0):.0%})"
            for p in active_preds
            if p["slug"] not in expired_slugs
        )

        messages = [
            {
                "role": "user",
                "content": f"Recent news:\n\n{context}\n\n---\n\nActive predictions ({len(active_preds)}):\n{active_summary or 'None yet'}\n\nCurrent date: {today_str}",
            }
        ]

        result = self.llm.complete_json(messages=messages, system=PREDICTION_SYSTEM)

        stats = {
            "date": today_str,
            "new": 0,
            "updated": 0,
            "deactivated": 0,
            "errors": [],
        }

        # Process new predictions
        for new_pred in result.get("new_predictions", []):
            if new_pred.get("confidence", 0) < self.pred_cfg.min_confidence_to_create:
                continue
            if len(active_preds) >= self.pred_cfg.max_active_predictions:
                break

            slug = new_pred.get("slug") or _slugify(new_pred.get("title", "unknown"))

            # Avoid duplicates
            existing_slugs = {p["slug"] for p in active_preds}
            if slug in existing_slugs:
                continue

            pred_obj = {
                "slug": slug,
                "title": new_pred.get("title", ""),
                "category": new_pred.get("category", "Unknown"),
                "confidence": new_pred.get("confidence", 0.5),
                "status": "Active",
                "created_at": today_str,
                "updated_at": today_str,
                "bull_scenario": new_pred.get("bull_scenario", {}),
                "base_scenario": new_pred.get("base_scenario", {}),
                "bear_scenario": new_pred.get("bear_scenario", {}),
                "tickers": new_pred.get("tickers", []),
                "timeframe_days": new_pred.get("timeframe_days", 30),
                "rationale": new_pred.get("rationale", ""),
                "probability_history": [
                    {
                        "date": today_str,
                        "bull": new_pred.get("bull_scenario", {}).get("probability", 0.33),
                        "base": new_pred.get("base_scenario", {}).get("probability", 0.34),
                        "bear": new_pred.get("bear_scenario", {}).get("probability", 0.33),
                        "trigger": "Initial creation",
                    }
                ],
                "evidence_chain": [],
                "contrarian_flag": False,
            }
            # Check contrarian flag
            if self._check_contrarian_flag(pred_obj):
                pred_obj["contrarian_flag"] = True
            self._save_prediction(pred_obj)
            stats["new"] += 1

        # Process updates
        active_map = {p["slug"]: p for p in active_preds}
        for update in result.get("updates", []):
            slug = update.get("slug")
            if slug not in active_map:
                continue

            pred = active_map[slug]
            pred["updated_at"] = today_str
            pred["confidence"] = update.get("confidence", pred["confidence"])

            # Update scenario probabilities
            if "bull_probability" in update:
                pred.setdefault("bull_scenario", {})["probability"] = update["bull_probability"]
            if "base_probability" in update:
                pred.setdefault("base_scenario", {})["probability"] = update["base_probability"]
            if "bear_probability" in update:
                pred.setdefault("bear_scenario", {})["probability"] = update["bear_probability"]

            # Add to history
            pred.setdefault("probability_history", []).append({
                "date": today_str,
                "bull": pred.get("bull_scenario", {}).get("probability", 0),
                "base": pred.get("base_scenario", {}).get("probability", 0),
                "bear": pred.get("bear_scenario", {}).get("probability", 0),
                "trigger": update.get("new_evidence", "")[:100],
            })

            # Add to evidence chain
            if update.get("new_evidence"):
                pred.setdefault("evidence_chain", []).append({
                    "date": today_str,
                    "text": update["new_evidence"],
                })

            # Update contrarian flag on each update
            pred["contrarian_flag"] = self._check_contrarian_flag(pred)
            self._save_prediction(pred)
            stats["updated"] += 1

        # Deactivate
        for deact in result.get("deactivate", []) + [{"slug": s, "reason": "Expired", "outcome": "unknown"} for s in expired_slugs]:
            slug = deact.get("slug")
            if slug not in active_map:
                continue

            pred = active_map[slug]
            pred["status"] = "Resolved"
            pred["resolved_at"] = today_str
            pred["outcome"] = deact.get("outcome", "unknown")
            pred["outcome_description"] = deact.get("outcome_description", deact.get("reason", ""))

            self._save_prediction(pred, resolved=True)

            # Remove from active
            active_json = self.active_dir / f"{slug}.json"
            active_md = self.active_dir / f"{slug}.md"
            for f in [active_json, active_md]:
                if f.exists():
                    f.unlink()

            stats["deactivated"] += 1

        # Generate prediction summary
        self._generate_summary()

        console.print(f"[green]Predictions:[/green] {stats['new']} new, {stats['updated']} updated, {stats['deactivated']} deactivated")
        return stats

    def _generate_summary(self):
        """Generate PREDICTION_SUMMARY.md."""
        preds = self._load_active_predictions()
        if not preds:
            content = "# Active Predictions Summary\n\n_No active predictions._\n"
        else:
            rows = "\n".join(
                f"| {p['slug'][:30]} | {p.get('title', '')[:50]} | {p.get('confidence', 0):.0%} | "
                f"{p.get('bull_scenario', {}).get('probability', 0):.0%}/"
                f"{p.get('base_scenario', {}).get('probability', 0):.0%}/"
                f"{p.get('bear_scenario', {}).get('probability', 0):.0%} | "
                f"{p.get('updated_at', '')[:10]} |"
                for p in sorted(preds, key=lambda x: x.get("confidence", 0), reverse=True)
            )
            content = f"""# Active Predictions Summary

| Slug | Prediction | Confidence | Bull/Base/Bear | Last Updated |
|------|-----------|-----------|----------------|-------------|
{rows}

**Total Active:** {len(preds)}
"""

        summary_path = self.data_dir / "predictions" / "PREDICTION_SUMMARY.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(content)

    def list_active(self) -> list[dict]:
        return sorted(self._load_active_predictions(), key=lambda x: x.get("confidence", 0), reverse=True)

    def status(self) -> dict:
        preds = self._load_active_predictions()
        return {
            "active_predictions": len(preds),
            "model": self.pred_cfg.model,
        }
