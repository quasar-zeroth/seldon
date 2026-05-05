"""Prediction and knowledge graph backend for The Seldon Project."""

from .config import (
    AgentModelConfig,
    AgentsConfig,
    KnowledgeGraphConfig,
    OpenRouterConfig,
    PredictionConfig,
    PredictionContextConfig,
    SeldonConfig,
)
from .client import SeldonClient

__version__ = "0.1.0"

__all__ = [
    "SeldonClient",
    "SeldonConfig",
    "OpenRouterConfig",
    "AgentModelConfig",
    "AgentsConfig",
    "PredictionConfig",
    "PredictionContextConfig",
    "KnowledgeGraphConfig",
]
