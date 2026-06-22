"""Structured logging setup for API and operations."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("seldon_"):
                data[key.removeprefix("seldon_")] = value
        return json.dumps(data, default=str, separators=(",", ":"))


def _formatter(json_logs: bool) -> logging.Formatter:
    if json_logs:
        return JsonFormatter()
    return logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")


def configure_structured_logging(*, json_logs: bool = True, level: str = "INFO", log_file: str | Path | None = None, max_bytes: int = 10_000_000, backup_count: int = 5) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_formatter(json_logs))
    handlers: list[logging.Handler] = [stream_handler]
    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setFormatter(_formatter(json_logs))
        handlers.append(file_handler)
    root.handlers[:] = handlers
