"""Database helpers for Seldon's durable persistence layer."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


def sqlite_url(path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(url: str | None = None, *, sqlite_path: str | Path | None = None, echo: bool = False) -> Engine:
    db_url = url or sqlite_url(sqlite_path or "./data/seldon.db")
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine_kwargs = {"echo": echo, "future": True, "connect_args": connect_args}
    if db_url in {"sqlite://", "sqlite:///:memory:"}:
        engine_kwargs["poolclass"] = StaticPool
    return create_engine(db_url, **engine_kwargs)


def create_all(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
