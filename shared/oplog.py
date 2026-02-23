from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from shared.paths import gw_root


def _enabled() -> bool:
    v = os.environ.get("SHERIFF_OPLOG_ENABLED", "1").strip().lower()
    return v not in {"0", "false", "no", "off"}


def get_op_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"sheriff.op.{name}")
    if logger.handlers:
        return logger

    if not _enabled():
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return logger

    log_dir: Path = gw_root() / "logs" / "ops"
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
