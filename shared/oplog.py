from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from shared.paths import gw_root, llm_root


def _enabled() -> bool:
    v = os.environ.get("SHERIFF_OPLOG_ENABLED", "1").strip().lower()
    return v not in {"0", "false", "no", "off"}


def get_op_logger(name: str, *, island: str = "gw") -> logging.Logger:
    logger = logging.getLogger(f"sheriff.op.{island}.{name}")
    if logger.handlers:
        return logger

    if not _enabled():
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return logger

    root_factory = llm_root if island == "llm" else gw_root
    log_dir: Path = root_factory() / "logs" / "ops"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}.log"

    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="H",
        interval=1,
        backupCount=24,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
    handler.setFormatter(fmt)

    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_rotating_logger(
    name: str,
    log_file: Path,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    level: int = logging.INFO,
) -> logging.Logger:
    logger = logging.getLogger(f"sheriff.rot.{name}")
    if logger.handlers:
        return logger

    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
    handler.setFormatter(fmt)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class RotatingTextLog:
    def __init__(self, log_file: Path, *, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 5):
        self.log_file = log_file
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.Lock()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def append(self, text: str) -> None:
        if not text:
            return
        try:
            with self._lock:
                self._rotate_if_needed(len(text.encode("utf-8", errors="ignore")))
                with self.log_file.open("a", encoding="utf-8", errors="replace") as fh:
                    fh.write(text)
        except PermissionError:
            return

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        current_size = self.log_file.stat().st_size if self.log_file.exists() else 0
        if current_size + incoming_bytes <= self.max_bytes:
            return
        oldest = self.log_file.with_name(f"{self.log_file.name}.{self.backup_count}")
        if oldest.exists():
            oldest.unlink()
        for idx in range(self.backup_count - 1, 0, -1):
            src = self.log_file.with_name(f"{self.log_file.name}.{idx}")
            dst = self.log_file.with_name(f"{self.log_file.name}.{idx + 1}")
            if src.exists():
                src.replace(dst)
        if self.log_file.exists():
            self.log_file.replace(self.log_file.with_name(f"{self.log_file.name}.1"))
