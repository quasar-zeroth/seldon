"""Tests for PredictionEngine (stage2/predictor.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


from seldon.predictions.engine import PredictionEngine


def make_prediction(slug: str = "test-pred", confidence: float = 0.70, **kwargs) -> dict:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return {
        "slug": slug,
        "title": f"Prediction: {slug}",
        "category": "Macro",
        "confidence": confidence,
        "status": "Active",
        "created_at": today,
        "updated_at": kwargs.pop("updated_at", today),
        "bull_scenario": {"probability": 0.40, "description": "Bull.", "impact": "", "triggers": []},
        "base_scenario": {"probability": 0.40, "description": "Base.", "impact": "", "triggers": []},
        "bear_scenario": {"probability": 0.20, "description": "Bear.", "impact": "", "triggers": []},
        "tickers": kwargs.pop("tickers", ["SPY"]),
        "timeframe_days": 30,
        "rationale": "Test rationale.",
        "probability_history": [],
        "evidence_chain": [],
        "contrarian_flag": False,
        **kwargs,
    }


# ── _apply_confidence_decay ───────────────────────────────────────────────────

class TestConfidenceDecay:
    def get_engine(self, tmp_data_dir):
        return PredictionEngine.__new__(PredictionEngine)

    def test_zero_days_no_change(self, tmp_data_dir):
        engine = self.get_engine(tmp_data_dir)
        today = datetime.now(tz=timezone.utc)
        pred = make_prediction(confidence=0.80, updated_at=today.isoformat())
        result = engine._apply_confidence_decay([pred], today)
        assert abs(result[0]["confidence"] - 0.80) < 0.002

    def test_ten_days_decay(self, tmp_data_dir):
        engine = self.get_engine(tmp_data_dir)
        today = datetime(2025, 3, 24, tzinfo=timezone.utc)
        updated = (today - timedelta(days=10)).isoformat()
        pred = make_prediction(confidence=0.80, updated_at=updated)
        result = engine._apply_confidence_decay([pred], today)
        expected = 0.80 * (0.98 ** 10)
        assert abs(result[0]["confidence"] - expected) < 0.002, (
            f"Expected ~{expected:.4f}, got {result[0]['confidence']:.4f}"
        )

    def test_floor_at_0_20(self, tmp_data_dir):
        engine = self.get_engine(tmp_data_dir)
        today = datetime(2025, 6, 1, tzinfo=timezone.utc)
        updated = (today - timedelta(days=100)).isoformat()
        pred = make_prediction(confidence=0.25, updated_at=updated)
        result = engine._apply_confidence_decay([pred], today)
        assert result[0]["confidence"] == 0.20

    def test_adds_evidence_when_decayed(self, tmp_data_dir):
        engine = self.get_engine(tmp_data_dir)
        today = datetime(2025, 3, 24, tzinfo=timezone.utc)
        updated = (today - timedelta(days=15)).isoformat()
        pred = make_prediction(confidence=0.80, updated_at=updated)
        result = engine._apply_confidence_decay([pred], today)
        # Decay should be > 0.005, so evidence_chain should have entry
        assert len(result[0]["evidence_chain"]) >= 1
        assert "decay" in result[0]["evidence_chain"][-1]["text"].lower()

    def test_no_evidence_when_same_day(self, tmp_data_dir):
        """0-day decay shouldn't add spurious evidence entries."""
        engine = self.get_engine(tmp_data_dir)
        today = datetime.now(tz=timezone.utc)
        pred = make_prediction(confidence=0.80, updated_at=today.isoformat())
        pred["evidence_chain"] = []
        result = engine._apply_confidence_decay([pred], today)
        assert len(result[0]["evidence_chain"]) == 0

    def test_multiple_predictions_decayed_independently(self, tmp_data_dir):
        engine = self.get_engine(tmp_data_dir)
        today = datetime(2025, 3, 24, tzinfo=timezone.utc)
        p1 = make_prediction("p1", 0.80, updated_at=(today - timedelta(days=5)).isoformat())
        p2 = make_prediction("p2", 0.60, updated_at=(today - timedelta(days=0)).isoformat())
        result = engine._apply_confidence_decay([p1, p2], today)
        # p1 should decay, p2 should not
        assert result[0]["confidence"] < 0.80
        assert abs(result[1]["confidence"] - 0.60) < 0.002


# ── _check_contrarian_flag ────────────────────────────────────────────────────

class TestContrarianFlag:
    def _write_topic_with_sentiment(self, data_dir: Path, date_str: str, slug: str, sentiment: str, tickers: list):
        topic_dir = data_dir / "news" / "daily" / date_str
        topic_dir.mkdir(parents=True, exist_ok=True)
        content = (
            f"# Topic: {slug}\n"
            f"**Status:** Active | **First Seen:** {date_str} | **Last Updated:** {date_str}\n"
            f"**Tickers:** {', '.join(tickers)}\n"
            f"**Sentiment:** {sentiment}\n\n"
            "## Summary\nSome summary.\n"
        )
        (topic_dir / f"{slug}.md").write_text(content)

    def test_contrarian_flag_when_majority_bullish(self, tmp_data_dir):
        engine = PredictionEngine(data_dir=tmp_data_dir)
        date_str = "2025-03-20"
        # 5 bullish, 1 bearish → 83% bullish → should flag
        for i in range(5):
            self._write_topic_with_sentiment(tmp_data_dir, date_str, f"topic-bull-{i}", "Bullish", ["SPY"])
        self._write_topic_with_sentiment(tmp_data_dir, date_str, "topic-bear", "Bearish", ["SPY"])

        pred = make_prediction(tickers=["SPY"])
        assert engine._check_contrarian_flag(pred) is True

    def test_no_contrarian_flag_when_mixed(self, tmp_data_dir):
        engine = PredictionEngine(data_dir=tmp_data_dir)
        date_str = "2025-03-20"
        # 3 bullish, 3 bearish → 50/50 → no flag
        for i in range(3):
            self._write_topic_with_sentiment(tmp_data_dir, date_str, f"topic-bull-{i}", "Bullish", ["TSLA"])
        for i in range(3):
            self._write_topic_with_sentiment(tmp_data_dir, date_str, f"topic-bear-{i}", "Bearish", ["TSLA"])

        pred = make_prediction(tickers=["TSLA"])
        assert engine._check_contrarian_flag(pred) is False

    def test_no_contrarian_flag_insufficient_data(self, tmp_data_dir):
        engine = PredictionEngine(data_dir=tmp_data_dir)
        # Only 2 topics → not enough data (needs ≥3)
        date_str = "2025-03-20"
        self._write_topic_with_sentiment(tmp_data_dir, date_str, "t1", "Bullish", ["TLT"])
        self._write_topic_with_sentiment(tmp_data_dir, date_str, "t2", "Bullish", ["TLT"])

        pred = make_prediction(tickers=["TLT"])
        assert engine._check_contrarian_flag(pred) is False

    def test_no_contrarian_flag_when_no_ticker_match(self, tmp_data_dir):
        engine = PredictionEngine(data_dir=tmp_data_dir)
        date_str = "2025-03-20"
        for i in range(5):
            self._write_topic_with_sentiment(tmp_data_dir, date_str, f"t-{i}", "Bullish", ["NVDA"])

        # Prediction for TSLA — NVDA topics shouldn't count
        pred = make_prediction(tickers=["TSLA"])
        assert engine._check_contrarian_flag(pred) is False


# ── run() ─────────────────────────────────────────────────────────────────────

class TestPredictionEngineRun:
    def test_creates_prediction_files(self, tmp_data_dir, mock_llm):
        """New prediction should create both .json and .md files."""
        mock_llm["_default"] = {
            "new_predictions": [
                {
                    "slug": "fed-cuts-july-2025",
                    "title": "Prediction: Fed Will Cut Rates by July 2025",
                    "category": "Macro",
                    "confidence": 0.65,
                    "bull_scenario": {
                        "probability": 0.35,
                        "description": "Fed cuts in June.",
                        "impact": "SPY +3%",
                        "triggers": ["NFP miss"],
                    },
                    "base_scenario": {
                        "probability": 0.45,
                        "description": "Fed cuts in September.",
                        "impact": "SPY flat",
                        "triggers": ["CPI cools"],
                    },
                    "bear_scenario": {
                        "probability": 0.20,
                        "description": "Fed holds all year.",
                        "impact": "SPY -5%",
                        "triggers": ["Inflation re-accelerates"],
                    },
                    "tickers": ["TLT", "SPY"],
                    "timeframe_days": 120,
                    "rationale": "Multiple sources signal rate cuts ahead.",
                }
            ],
            "updates": [],
            "deactivate": [],
        }

        engine = PredictionEngine(data_dir=tmp_data_dir, llm_client=mock_llm)
        stats = engine.run()

        pred_dir = tmp_data_dir / "predictions" / "active"
        json_files = list(pred_dir.glob("*.json"))
        md_files = list(pred_dir.glob("*.md"))

        assert len(json_files) >= 1, "Expected at least one .json prediction file"
        assert len(md_files) >= 1, "Expected at least one .md prediction file"
        assert stats["new"] >= 1

    def test_below_min_confidence_not_created(self, tmp_data_dir, mock_llm):
        """Predictions below min_confidence_to_create (0.40) are rejected."""
        mock_llm["_default"] = {
            "new_predictions": [
                {
                    "slug": "low-confidence-pred",
                    "title": "Prediction: Very Uncertain Outcome",
                    "category": "Crypto",
                    "confidence": 0.30,  # below 0.40 threshold
                    "bull_scenario": {"probability": 0.33, "description": "", "impact": "", "triggers": []},
                    "base_scenario": {"probability": 0.34, "description": "", "impact": "", "triggers": []},
                    "bear_scenario": {"probability": 0.33, "description": "", "impact": "", "triggers": []},
                    "tickers": [],
                    "timeframe_days": 30,
                    "rationale": "Weak evidence.",
                }
            ],
            "updates": [],
            "deactivate": [],
        }
        engine = PredictionEngine(data_dir=tmp_data_dir, llm_client=mock_llm)
        stats = engine.run()
        assert stats["new"] == 0

    def test_generates_prediction_summary(self, tmp_data_dir, mock_llm):
        """run() should always generate PREDICTION_SUMMARY.md."""
        mock_llm["_default"] = {"new_predictions": [], "updates": [], "deactivate": []}
        engine = PredictionEngine(data_dir=tmp_data_dir, llm_client=mock_llm)
        engine.run()

        summary = tmp_data_dir / "predictions" / "PREDICTION_SUMMARY.md"
        assert summary.exists()
