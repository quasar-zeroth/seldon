"""Prediction and knowledge graph backend for The Seldon Project."""

from .config import SeldonConfig, PredictionConfig, PredictionContextConfig, KnowledgeGraphConfig
from .client import SeldonClient

__version__ = "0.1.0"

__all__ = [
    "SeldonClient",
    "SeldonConfig",
    "PredictionConfig",
    "PredictionContextConfig",
    "KnowledgeGraphConfig",
]
