"""Logs JSON lines com rotação por tamanho (10 MB × 5) e redação de segredos."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.settings import LoggingSettings
from security.redactor import redact


class JsonFormatter(logging.Formatter):
    def __init__(self, redact_secrets: bool = True):
        super().__init__()
        self.redact_secrets = redact_secrets

    def _clean(self, text: str) -> str:
        return redact(text) if self.redact_secrets else text

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": self._clean(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = self._clean(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_dir: Path, cfg: LoggingSettings) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "aider.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter(redact_secrets=cfg.redact_secrets))
    root = logging.getLogger()
    root.setLevel(cfg.level.upper())
    root.handlers = [h for h in root.handlers if not isinstance(h, RotatingFileHandler)]
    root.addHandler(handler)
