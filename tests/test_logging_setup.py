from __future__ import annotations

import logging
from dataclasses import replace

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api import app as api_app
from backend.composition import RuntimeContainer
from backend.logging_setup import configure_flask_logging, configure_logging
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.workers import deliver_worker, execute_worker, fetch_worker


def test_configure_logging_reuses_shared_root_handler() -> None:
    _clear_shared_handler()

    first_logger = configure_logging(app_name="heavy-lifting-backend", component="api")
    second_logger = configure_logging(app_name="heavy-lifting-backend", component="worker2")
    root_logger = logging.getLogger()
    shared_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, "_heavy_lifting_handler", False)
    ]

    assert first_logger.name == "heavy-lifting-backend.api"
    assert second_logger.name == "heavy-lifting-backend.worker2"
    assert len(shared_handlers) == 1

    record = logging.LogRecord(
        name="backend.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    formatted = shared_handlers[0].formatter.format(record)
    assert "[heavy-lifting-backend:worker2]" in formatted
    assert "backend.test: hello" in formatted


def test_configure_flask_logging_enables_root_propagation() -> None:
    app = api_app.Flask(__name__)

    configure_flask_logging(app, app_name="heavy-lifting-backend", component="api")

    assert app.logger.propagate is True
    assert app.logger.handlers == []


def test_create_app_configures_flask_logging(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        api_app,
        "configure_flask_logging",
        lambda app, *, app_name, component: calls.append((app_name, component)),
    )

    api_app.create_app(runtime=_runtime(), session_factory=object())

    assert calls == [("heavy-lifting-backend", "api")]


def test_worker_entrypoints_configure_shared_logging(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class StubLogger:
        def info(self, message: str, once: bool, max_iterations: int | None) -> None:
            assert (
                message == "Starting fetch worker once=%s max_iterations=%s"
                or message == ("Starting execute worker once=%s max_iterations=%s")
                or message == "Starting deliver worker once=%s max_iterations=%s"
            )

    class StubWorker:
        def poll_once(self) -> None:
            return None

    settings = replace(get_settings(), app_name="heavy-lifting-backend")

    monkeypatch.setattr(fetch_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(execute_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(deliver_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(
        fetch_worker,
        "configure_logging",
        lambda *, app_name, component: calls.append((app_name, component)) or StubLogger(),
    )
    monkeypatch.setattr(
        execute_worker,
        "configure_logging",
        lambda *, app_name, component: calls.append((app_name, component)) or StubLogger(),
    )
    monkeypatch.setattr(
        deliver_worker,
        "configure_logging",
        lambda *, app_name, component: calls.append((app_name, component)) or StubLogger(),
    )
    monkeypatch.setattr(fetch_worker, "build_tracker_intake_worker", lambda: StubWorker())
    monkeypatch.setattr(execute_worker, "build_execute_worker", lambda: StubWorker())
    monkeypatch.setattr(deliver_worker, "build_deliver_worker", lambda: StubWorker())

    fetch_worker.run(once=True)
    execute_worker.run(once=True)
    deliver_worker.run(once=True)

    assert calls == [
        ("heavy-lifting-backend", "worker1"),
        ("heavy-lifting-backend", "worker2"),
        ("heavy-lifting-backend", "worker3"),
    ]


def _runtime() -> RuntimeContainer:
    return RuntimeContainer(
        settings=replace(get_settings(), app_name="heavy-lifting-backend"),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )


def _clear_shared_handler() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, "_heavy_lifting_handler", False):
            root_logger.removeHandler(handler)
