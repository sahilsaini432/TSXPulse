from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from TSXPulse.config import PROJECT_ROOT, AppConfig


_CONFIGURED = False


def setup_logging(cfg: AppConfig) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_path = PROJECT_ROOT / cfg.logging.file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(cfg.logging.level.upper())

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=cfg.logging.max_bytes,
        backupCount=cfg.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)

    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream)

    _CONFIGURED = True
