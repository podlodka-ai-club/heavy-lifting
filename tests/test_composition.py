from dataclasses import replace

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import (
    AdapterRegistry,
    RuntimeContainer,
    create_runtime_container,
)
from backend.settings import get_settings
from backend.workers import deliver_worker, execute_worker, fetch_worker


class CustomTracker(MockTracker):
    pass


class CustomScm(MockScm):
    pass


def test_create_runtime_container_uses_mock_adapters_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    get_settings.cache_clear()

    runtime = create_runtime_container()

    assert isinstance(runtime.tracker, MockTracker)
    assert isinstance(runtime.scm, MockScm)
    assert runtime.settings.tracker_adapter == "mock"
    assert runtime.settings.scm_adapter == "mock"


def test_create_runtime_container_supports_custom_registry(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(
        get_settings(),
        tracker_adapter="custom-tracker",
        scm_adapter="custom-scm",
    )
    registry = AdapterRegistry(
        tracker_factories={"custom-tracker": lambda _: CustomTracker()},
        scm_factories={"custom-scm": lambda _: CustomScm()},
    )

    runtime = create_runtime_container(settings=settings, registry=registry)

    assert isinstance(runtime.tracker, CustomTracker)
    assert isinstance(runtime.scm, CustomScm)


def test_create_runtime_container_rejects_unknown_adapter(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(get_settings(), tracker_adapter="unknown")

    try:
        create_runtime_container(settings=settings)
    except ValueError as exc:
        assert str(exc) == "Unsupported tracker adapter: unknown"
    else:
        raise AssertionError("Expected ValueError for unknown tracker adapter")


def test_create_app_stores_runtime_container_extension(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    get_settings.cache_clear()
    runtime = create_runtime_container()

    app = create_app(runtime)

    assert app.extensions["runtime_container"] is runtime


def test_workers_use_shared_runtime_initialization(monkeypatch) -> None:
    expected_runtime = RuntimeContainer(
        settings=replace(get_settings()),
        tracker=MockTracker(),
        scm=MockScm(),
    )

    monkeypatch.setattr(fetch_worker, "create_runtime_container", lambda: expected_runtime)
    monkeypatch.setattr(execute_worker, "create_runtime_container", lambda: expected_runtime)
    monkeypatch.setattr(deliver_worker, "create_runtime_container", lambda: expected_runtime)

    assert fetch_worker.run() is expected_runtime
    assert execute_worker.run() is expected_runtime
    assert deliver_worker.run() is expected_runtime
