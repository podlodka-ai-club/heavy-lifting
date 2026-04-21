from dataclasses import replace

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import (
    AdapterRegistry,
    RuntimeContainer,
    create_runtime_container,
)
from backend.protocols.agent_runner import AgentRunnerProtocol
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import get_settings
from backend.workers import deliver_worker, execute_worker, fetch_worker


class CustomTracker(MockTracker):
    pass


class CustomScm(MockScm):
    pass


class CustomRunner(LocalAgentRunner):
    pass


def test_create_runtime_container_uses_mock_adapters_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()

    runtime = create_runtime_container()

    assert isinstance(runtime.tracker, MockTracker)
    assert isinstance(runtime.scm, MockScm)
    assert isinstance(runtime.agent_runner, LocalAgentRunner)
    assert runtime.settings.tracker_adapter == "mock"
    assert runtime.settings.scm_adapter == "mock"
    assert runtime.settings.agent_runner_adapter == "local"


def test_create_runtime_container_supports_custom_registry(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(
        get_settings(),
        tracker_adapter="custom-tracker",
        scm_adapter="custom-scm",
        agent_runner_adapter="custom-runner",
    )
    registry = AdapterRegistry(
        tracker_factories={"custom-tracker": lambda _: CustomTracker()},
        scm_factories={"custom-scm": lambda _: CustomScm()},
        agent_runner_factories={"custom-runner": lambda _: CustomRunner()},
    )

    runtime = create_runtime_container(settings=settings, registry=registry)

    assert isinstance(runtime.tracker, CustomTracker)
    assert isinstance(runtime.scm, CustomScm)
    assert isinstance(runtime.agent_runner, CustomRunner)


def test_create_runtime_container_rejects_unknown_adapter(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(get_settings(), tracker_adapter="unknown")

    try:
        create_runtime_container(settings=settings)
    except ValueError as exc:
        assert str(exc) == "Unsupported tracker adapter: unknown"
    else:
        raise AssertionError("Expected ValueError for unknown tracker adapter")


def test_create_runtime_container_rejects_unknown_agent_runner(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(get_settings(), agent_runner_adapter="unknown-runner")

    try:
        create_runtime_container(settings=settings)
    except ValueError as exc:
        assert str(exc) == "Unsupported agent runner adapter: unknown-runner"
    else:
        raise AssertionError("Expected ValueError for unknown agent runner adapter")


def test_create_app_stores_runtime_container_extension(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    runtime = create_runtime_container()

    app = create_app(runtime)

    assert app.extensions["runtime_container"] is runtime


def test_deliver_worker_uses_shared_runtime_initialization(monkeypatch) -> None:
    expected_runtime = RuntimeContainer(
        settings=replace(get_settings()),
        tracker=MockTracker(),
        scm=MockScm(),
        agent_runner=LocalAgentRunner(),
    )

    monkeypatch.setattr(deliver_worker, "create_runtime_container", lambda: expected_runtime)

    assert deliver_worker.run() is expected_runtime


def test_execute_worker_uses_execute_worker_entrypoint(monkeypatch) -> None:
    class StubWorker:
        def __init__(self) -> None:
            self.poll_count = 0
            self.max_iterations = None

        def poll_once(self) -> None:
            self.poll_count += 1

        def run_forever(self, *, max_iterations=None, sleep_fn=None) -> None:
            self.max_iterations = max_iterations

    expected_worker = StubWorker()

    monkeypatch.setattr(execute_worker, "build_execute_worker", lambda: expected_worker)

    assert execute_worker.run(once=True) is expected_worker
    assert expected_worker.poll_count == 1

    assert execute_worker.run(max_iterations=2) is expected_worker
    assert expected_worker.max_iterations == 2


def test_fetch_worker_uses_tracker_intake_worker_entrypoint(monkeypatch) -> None:
    class StubWorker:
        def __init__(self) -> None:
            self.poll_count = 0
            self.max_iterations = None

        def poll_once(self) -> None:
            self.poll_count += 1

        def run_forever(self, *, max_iterations=None, sleep_fn=None) -> None:
            self.max_iterations = max_iterations

    expected_worker = StubWorker()

    monkeypatch.setattr(fetch_worker, "build_tracker_intake_worker", lambda: expected_worker)

    assert fetch_worker.run(once=True) is expected_worker
    assert expected_worker.poll_count == 1

    assert fetch_worker.run(max_iterations=3) is expected_worker
    assert expected_worker.max_iterations == 3


def test_runtime_container_exposes_agent_runner_protocol(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()

    runtime = create_runtime_container()

    assert isinstance(runtime.agent_runner, AgentRunnerProtocol)
