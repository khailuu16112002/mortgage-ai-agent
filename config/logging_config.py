"""Structured logging setup using Python's logging module."""
import logging
import json
import sys
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.COLORS["RESET"]
        ts = datetime.utcnow().strftime("%H:%M:%S")
        return f"{color}[{ts}] [{record.levelname:8s}] {record.name}: {record.getMessage()}{reset}"


def setup_logging(level: str = "INFO", fmt: str = "text", log_file: str | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())
    root.addHandler(handler)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(JSONFormatter())
        root.addHandler(fh)

    # Suppress noisy libraries
    for lib in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
