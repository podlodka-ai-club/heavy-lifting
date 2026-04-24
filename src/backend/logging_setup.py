from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from flask import Flask
from structlog.typing import EventDict, WrappedLogger

from backend.settings import get_settings


class _SharedStreamHandler(logging.StreamHandler):
    _heavy_lifting_handler = True


class _StaticContextFilter(logging.Filter):
    def __init__(self, *, app_name: str, component: str) -> None:
        super().__init__()
        self._app_name = app_name
        self._component = component

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "app_name"):
            record.app_name = self._app_name
        if not hasattr(record, "component"):
            record.component = self._component
        return True


def configure_logging(
    *, app_name: str, component: str, level: int = logging.INFO
) -> structlog.stdlib.BoundLogger:
    _configure_structlog()
    _ensure_root_handler(level=level)

    return get_logger(component=component, app_name=app_name)


def configure_flask_logging(
    app: Flask, *, app_name: str, component: str
) -> structlog.stdlib.BoundLogger:
    logger = configure_logging(app_name=app_name, component=component)
    app.logger.handlers.clear()
    app.logger.filters.clear()
    app.logger.addFilter(_StaticContextFilter(app_name=app_name, component=component))
    app.logger.propagate = True
    app.logger.setLevel(logging.getLogger().level)
    return logger


def get_logger(
    name: str | None = None,
    *,
    component: str,
    app_name: str | None = None,
    **fields: Any,
) -> structlog.stdlib.BoundLogger:
    resolved_app_name = app_name or get_settings().app_name
    _configure_structlog()
    root_logger = logging.getLogger()
    _ensure_root_handler(level=root_logger.level or logging.INFO)
    return structlog.stdlib.get_logger(name).bind(
        app_name=resolved_app_name,
        component=component,
        **fields,
    )


def _get_shared_handler(root_logger: logging.Logger) -> logging.Handler | None:
    for handler in root_logger.handlers:
        if getattr(handler, "_heavy_lifting_handler", False):
            return handler
    return None


def _configure_structlog() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _copy_stdlib_record_context,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _ensure_root_handler(*, level: int) -> logging.Handler:
    root_logger = logging.getLogger()
    handler = _get_shared_handler(root_logger)

    if handler is not None and getattr(getattr(handler, "stream", None), "closed", False):
        root_logger.removeHandler(handler)
        handler = None

    if handler is None:
        handler = _SharedStreamHandler(sys.stderr)
        root_logger.addHandler(handler)

    handler.setFormatter(_build_shared_formatter())
    handler.setLevel(level)
    root_logger.setLevel(level)
    return handler


def _build_shared_formatter() -> structlog.stdlib.ProcessorFormatter:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            _copy_stdlib_record_context,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
    )


def _copy_stdlib_record_context(
    _: WrappedLogger,
    __: str,
    event_dict: EventDict,
) -> EventDict:
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        app_name = getattr(record, "app_name", None)
        component = getattr(record, "component", None)
        if app_name is not None and "app_name" not in event_dict:
            event_dict["app_name"] = app_name
        if component is not None and "component" not in event_dict:
            event_dict["component"] = component
    return event_dict


__all__ = ["configure_flask_logging", "configure_logging", "get_logger"]
