from __future__ import annotations

import threading
from dataclasses import dataclass

from flask import Flask
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.serving import make_server

from backend.api.app import create_app
from backend.composition import RuntimeContainer, create_runtime_container
from backend.db import get_session_factory
from backend.logging_setup import configure_logging
from backend.workers.deliver_worker import DeliverWorker, build_deliver_worker
from backend.workers.execute_worker import ExecuteWorker, build_execute_worker
from backend.workers.tracker_intake import TrackerIntakeWorker, build_tracker_intake_worker


@dataclass(frozen=True, slots=True)
class DemoComponents:
    runtime: RuntimeContainer
    session_factory: sessionmaker[Session]
    app: Flask
    intake_worker: TrackerIntakeWorker
    execute_worker: ExecuteWorker
    deliver_worker: DeliverWorker


def create_demo_components(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> DemoComponents:
    active_runtime = runtime or create_runtime_container()
    active_session_factory = session_factory or get_session_factory()
    app = create_app(runtime=active_runtime, session_factory=active_session_factory)
    return DemoComponents(
        runtime=active_runtime,
        session_factory=active_session_factory,
        app=app,
        intake_worker=build_tracker_intake_worker(
            runtime=active_runtime,
            session_factory=active_session_factory,
        ),
        execute_worker=build_execute_worker(
            runtime=active_runtime,
            session_factory=active_session_factory,
        ),
        deliver_worker=build_deliver_worker(
            runtime=active_runtime,
            session_factory=active_session_factory,
        ),
    )


def run_demo(
    *,
    runtime: RuntimeContainer | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> DemoComponents:
    demo = create_demo_components(runtime=runtime, session_factory=session_factory)
    settings = demo.runtime.settings
    logger = configure_logging(app_name=settings.app_name, component="demo")
    worker_threads = _start_worker_threads(demo)
    logger.info(
        "Starting demo mode host=%s port=%s worker_threads=%s",
        settings.app_host,
        settings.app_port,
        len(worker_threads),
    )
    server = make_server(settings.app_host, settings.app_port, demo.app)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping demo mode")
    finally:
        server.shutdown()

    return demo


def main() -> None:
    run_demo()


def _start_worker_threads(demo: DemoComponents) -> list[threading.Thread]:
    thread_specs = [
        ("worker1", demo.intake_worker.run_forever),
        ("worker2", demo.execute_worker.run_forever),
        ("worker3", demo.deliver_worker.run_forever),
    ]
    threads: list[threading.Thread] = []

    for name, worker_run in thread_specs:
        thread = threading.Thread(target=worker_run, name=name, daemon=True)
        thread.start()
        threads.append(thread)

    return threads


__all__ = ["DemoComponents", "create_demo_components", "main", "run_demo"]
