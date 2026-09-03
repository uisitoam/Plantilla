"""Centralised logging configuration."""

from __future__ import annotations

import logging
import logging.config
from typing import Any

from packagename.config import LoggingSettings, Settings, get_settings

__all__ = ["get_logger", "setup_logging"]


def setup_logging(settings: Settings | None = None, *, level: str | None = None) -> None:
    """Configure the root logger from settings.

    When called more than once, the previous configuration is replaced rather
    than added to, so repeated calls cannot duplicate log lines. Entrypoints
    should call this before anything else, so it also overrides any handler
    installed by a framework earlier in the process.

    Args:
        settings: Settings to read the logging section from. Defaults to the
            process-wide settings.
        level: Overrides ``logging.level``, for a ``--verbose`` style flag.
    """
    config = (settings or get_settings()).logging
    logging.config.dictConfig(_dict_config(config, level=level or config.level))


def _dict_config(config: LoggingSettings, *, level: str) -> dict[str, Any]:
    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stderr",
        }
    }

    if config.file is not None:
        config.file.parent.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "filename": str(config.file),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 3,
            "encoding": "utf-8",
        }

    return {
        "version": 1,
        # Loggers created at import time by already-imported modules must keep
        # working, so they are not disabled.
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": config.format, "datefmt": config.datefmt},
        },
        "handlers": handlers,
        "root": {"level": level, "handlers": list(handlers)},
        "loggers": {name: {"level": "WARNING"} for name in config.quiet_loggers},
    }


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under the project.

    Modules should use ``get_logger(__name__)`` so that log levels can be tuned
    per subpackage from the config file.
    """
    return logging.getLogger(name)
