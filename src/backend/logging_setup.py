from __future__ import annotations

import logging
import sys

from flask import Flask


class _ProcessFormatter(logging.Formatter):
    def __init__(self, *, app_name: str, component: str) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s [%(app_name)s:%(component)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._app_name = app_name
        self._component = component

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "app_name"):
            record.app_name = self._app_name
        if not hasattr(record, "component"):
            record.component = self._component
        return super().format(record)


class _SharedStreamHandler(logging.StreamHandler):
    _heavy_lifting_handler = True


def configure_logging(
    *, app_name: str, component: str, level: int = logging.INFO
) -> logging.Logger:
    root_logger = logging.getLogger()
    handler = _get_shared_handler(root_logger)

    if handler is None:
        handler = _SharedStreamHandler(sys.stderr)
        root_logger.addHandler(handler)

    handler.setFormatter(_ProcessFormatter(app_name=app_name, component=component))
    handler.setLevel(level)
    root_logger.setLevel(level)

    return logging.getLogger(f"{app_name}.{component}")


def configure_flask_logging(app: Flask, *, app_name: str, component: str) -> logging.Logger:
    logger = configure_logging(app_name=app_name, component=component)
    app.logger.handlers.clear()
    app.logger.propagate = True
    app.logger.setLevel(logging.getLogger().level)
    return logger


def _get_shared_handler(root_logger: logging.Logger) -> logging.Handler | None:
    for handler in root_logger.handlers:
        if getattr(handler, "_heavy_lifting_handler", False):
            return handler
    return None


__all__ = ["configure_flask_logging", "configure_logging"]
