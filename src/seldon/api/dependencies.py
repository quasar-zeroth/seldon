"""FastAPI dependency wiring for The Seldon Project."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.llm.openrouter import OpenRouterClient


@lru_cache(maxsize=1)
def get_config() -> SeldonConfig:
    return SeldonConfig()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    config = get_config()
    engine = make_engine(config.database.url, sqlite_path=config.database.sqlite_path, echo=config.database.echo)
    create_all(engine)
    return make_session_factory(engine)


def get_db_session() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_llm_client() -> OpenRouterClient:
    return OpenRouterClient(get_config().llm)
