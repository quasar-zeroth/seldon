"""Configuration models for the seldon package."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PredictionContextConfig(BaseModel):
    daily_summaries: int = 3
    weekly_summaries: int = 4
    monthly_summaries: int = 2


class LLMProviderConfig(BaseModel):
    """Configuration for an OpenAI-compatible chat-completions provider.

    OpenRouter and NVIDIA NIM both speak the same ``/chat/completions`` wire
    format, so a single client serves both — only ``base_url``, ``api_key_env``,
    the model IDs, and a couple of optional headers differ. Build a fully
    populated config for a named provider with :func:`provider_preset`.
    """

    provider: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
    app_name: str | None = "The Seldon Project"  # OpenRouter X-Title header; ignored by NIM
    site_url: str | None = None  # OpenRouter HTTP-Referer header; ignored by NIM
    extra_headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 90
    default_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    fast_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    reasoning_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    embedding_model: str = "text-embedding-3-small"
    fallback_models: list[str] = Field(default_factory=lambda: [
        "poolside/laguna-m.1:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    ])

    def model_for_profile(self, profile: str) -> str:
        if profile == "fast":
            return self.fast_model
        if profile == "reasoning":
            return self.reasoning_model
        if profile == "embedding":
            return self.embedding_model
        return self.default_model


# Back-compat alias: the config was OpenRouter-specific before NVIDIA NIM support.
OpenRouterConfig = LLMProviderConfig


# Per-provider presets — base_url, key env var, and known-good model IDs. The
# model IDs here are verified to exist on each provider's catalog.
_PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "app_name": "The Seldon Project",
        "default_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "fast_model": "meta-llama/llama-3.3-70b-instruct:free",
        "reasoning_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "fallback_models": [
            "poolside/laguna-m.1:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        ],
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "app_name": None,
        "default_model": "qwen/qwen3.5-397b-a17b",
        "fast_model": "qwen/qwen3.5-122b-a10b",
        "reasoning_model": "qwen/qwen3.5-397b-a17b",
        "fallback_models": [
            "qwen/qwen3.5-122b-a10b",
            "qwen/qwen3-next-80b-a3b-instruct",
        ],
    },
}


def provider_preset(provider: str) -> LLMProviderConfig:
    """Return a fully-populated LLMProviderConfig for a named provider.

    Unknown provider names degrade to the OpenRouter preset rather than crash.
    """
    name = provider if provider in _PROVIDER_PRESETS else "openrouter"
    return LLMProviderConfig(provider=name, **_PROVIDER_PRESETS[name])


class AgentModelConfig(BaseModel):
    model_profile: str = "balanced"
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


def _default_allow_dev_fallback() -> bool:
    """Tests set SELDON_ALLOW_DEV_FALLBACK=1 to keep deterministic fallbacks on."""
    return os.getenv("SELDON_ALLOW_DEV_FALLBACK", "").lower() in {"1", "true", "yes", "on"}


class AgentsConfig(BaseModel):
    allow_deterministic_dev_fallback: bool = Field(default_factory=_default_allow_dev_fallback)
    """When True, semantic agents fall back to deterministic heuristics on LLM failure.
    Default False so misconfigured LLM surfaces as visible errors instead of garbage output.
    Override per-process via SELDON_ALLOW_DEV_FALLBACK=1 — tests do this in conftest."""

    context_gathering_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    query_decomposer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    information_retriever: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    information_summarizer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    deduplication_delta_detector: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    kb_writer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    prediction_engine: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.2)
    )
    extraction_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    entity_extractor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    event_extractor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    topic_theme_extractor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    node_deduplicator_merger: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    graph_construction_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    pairwise_relationship_detector: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    graph_consistency_checker: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.0)
    )
    importance_scorer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    convergence_loop_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    prediction_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="reasoning", temperature=0.2)
    )
    node_state_predictor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    graph_traversal_simulator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    instability_analyzer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="reasoning", temperature=0.1)
    )
    scenario_synthesizer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="reasoning", temperature=0.2)
    )


class PredictionConfig(BaseModel):
    model_profile: str = "balanced"
    model: str | None = None
    max_active_predictions: int = 30
    min_confidence_to_create: float = 0.40
    deactivate_after_days: int = 90
    context: PredictionContextConfig = Field(default_factory=PredictionContextConfig)
    update_frequency: str = "daily"


class KnowledgeGraphConfig(BaseModel):
    backend: str = "networkx"
    entity_extraction_model_profile: str = "fast"
    entity_extraction_model: str | None = None
    auto_extract_entities: bool = True


class RetrievalConfig(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["duckduckgo", "google_news"])
    per_subquery_limit: int = 5
    per_run_max_documents: int = 30
    fetch_timeout_seconds: int = 20
    per_domain_throttle_ms: int = 1000
    max_query_variations: int = 3  # cap engine queries per subquery to limit 429s
    user_agent: str = "SeldonBot/0.1 (+https://github.com/anthropics/seldon)"


class DatabaseConfig(BaseModel):
    url: str | None = None
    sqlite_path: Path = Path("./data/seldon.db")
    echo: bool = False


class OpsConfig(BaseModel):
    structured_logs: bool = True
    log_level: str = "INFO"
    log_file: Path | None = None
    log_max_bytes: int = 10_000_000
    log_backup_count: int = 5
    api_key_env: str = "SELDON_API_KEY"
    require_api_key: bool = False
    allow_localhost_without_api_key: bool = True
    backup_dir: Path = Path("./data/backups")
    vector_index_path: Path = Path("./data/vector-index")


class SeldonConfig(BaseModel):
    data_dir: Path = Path("./data")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    predictions: PredictionConfig = Field(default_factory=PredictionConfig)
    knowledge_graph: KnowledgeGraphConfig = Field(default_factory=KnowledgeGraphConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    ops: OpsConfig = Field(default_factory=OpsConfig)

    model_config = {"arbitrary_types_allowed": True}


def load_env_file(env_path: Path | None = None) -> None:
    """Load simple KEY=VALUE pairs from the project ``.env`` into ``os.environ``.

    This mirrors docker-compose's ``${VAR}`` interpolation for processes started
    directly (uvicorn/CLI), where nothing else loads ``.env``. Only variables not
    already present are set, preserving real-environment precedence, and it needs
    no python-dotenv dependency. No-op if the file is absent.
    """
    path = env_path or (Path(__file__).resolve().parents[2] / ".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.getenv(key):
            os.environ[key] = value


def select_llm_provider() -> str:
    """Choose the active LLM provider from env, else auto-detect by key presence.

    Explicit ``SELDON_LLM_PROVIDER`` wins. Otherwise prefer NVIDIA NIM when
    ``NVIDIA_API_KEY`` is set, then OpenRouter when ``OPENROUTER_API_KEY`` is set,
    defaulting to OpenRouter.
    """
    explicit = os.getenv("SELDON_LLM_PROVIDER")
    if explicit and explicit.strip():
        return explicit.strip().lower()
    if os.getenv("NVIDIA_API_KEY"):
        return "nvidia"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return "openrouter"


def config_from_env() -> SeldonConfig:
    """Build config from documented deployment environment variables."""
    load_env_file()
    cfg = SeldonConfig()

    # LLM provider selection + per-role model overrides. Presets carry verified
    # base_url/api_key_env/model IDs; SELDON_* env vars override individual fields.
    cfg.llm = provider_preset(select_llm_provider())
    if os.getenv("SELDON_LLM_BASE_URL"):
        cfg.llm.base_url = os.environ["SELDON_LLM_BASE_URL"]
    if os.getenv("SELDON_LLM_API_KEY_ENV"):
        cfg.llm.api_key_env = os.environ["SELDON_LLM_API_KEY_ENV"]
    if os.getenv("SELDON_DEFAULT_MODEL"):
        cfg.llm.default_model = os.environ["SELDON_DEFAULT_MODEL"]
    if os.getenv("SELDON_FAST_MODEL"):
        cfg.llm.fast_model = os.environ["SELDON_FAST_MODEL"]
    if os.getenv("SELDON_REASONING_MODEL"):
        cfg.llm.reasoning_model = os.environ["SELDON_REASONING_MODEL"]

    data_dir = os.getenv("SELDON_DATA_DIR")
    if data_dir:
        cfg.data_dir = Path(data_dir)
        cfg.database.sqlite_path = cfg.data_dir / "seldon.db"
        cfg.ops.backup_dir = cfg.data_dir / "backups"
        cfg.ops.vector_index_path = cfg.data_dir / "vector-index"
    database_url = os.getenv("SELDON_DATABASE_URL") or os.getenv("DATABASE_URL")
    if database_url:
        cfg.database.url = database_url
    cfg.ops.require_api_key = os.getenv("SELDON_REQUIRE_API_KEY", str(cfg.ops.require_api_key)).lower() in {"1", "true", "yes", "on"}
    cfg.ops.allow_localhost_without_api_key = os.getenv("SELDON_ALLOW_LOCALHOST_WITHOUT_API_KEY", str(cfg.ops.allow_localhost_without_api_key)).lower() in {"1", "true", "yes", "on"}
    if os.getenv("SELDON_BACKUP_DIR"):
        cfg.ops.backup_dir = Path(os.environ["SELDON_BACKUP_DIR"])
    if os.getenv("SELDON_LOG_FILE"):
        cfg.ops.log_file = Path(os.environ["SELDON_LOG_FILE"])
    if os.getenv("SELDON_LOG_MAX_BYTES"):
        cfg.ops.log_max_bytes = int(os.environ["SELDON_LOG_MAX_BYTES"])
    if os.getenv("SELDON_LOG_BACKUP_COUNT"):
        cfg.ops.log_backup_count = int(os.environ["SELDON_LOG_BACKUP_COUNT"])
    if os.getenv("SELDON_VECTOR_INDEX_PATH"):
        cfg.ops.vector_index_path = Path(os.environ["SELDON_VECTOR_INDEX_PATH"])
    return cfg
