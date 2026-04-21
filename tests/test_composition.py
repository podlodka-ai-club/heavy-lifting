from dataclasses import replace

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.api.app import create_app
from backend.composition import (
    AdapterRegistry,
    create_runtime_container,
)
from backend.protocols.agent_runner import AgentRunnerProtocol
from backend.services.agent_runner import CliAgentRunner, LocalAgentRunner
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


def test_create_runtime_container_builds_cli_agent_runner_from_settings(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(
        get_settings(),
        agent_runner_adapter="cli",
        cli_agent_command="codex",
        cli_agent_subcommand="exec",
        cli_agent_timeout_seconds=900,
        cli_agent_provider_hint="openai",
        cli_agent_model_hint="gpt-5.4",
        cli_agent_profile="backend",
        cli_agent_api_key_env_var="CUSTOM_API_KEY",
        cli_agent_base_url_env_var="CUSTOM_BASE_URL",
    )

    runtime = create_runtime_container(settings=settings)

    assert isinstance(runtime.agent_runner, CliAgentRunner)
    assert runtime.agent_runner.config.command == "codex"
    assert runtime.agent_runner.config.subcommand == "exec"
    assert runtime.agent_runner.config.timeout_seconds == 900
    assert runtime.agent_runner.config.provider_hint == "openai"
    assert runtime.agent_runner.config.model_hint == "gpt-5.4"
    assert runtime.agent_runner.config.profile == "backend"
    assert runtime.agent_runner.config.api_key_env_var == "CUSTOM_API_KEY"
    assert runtime.agent_runner.config.base_url_env_var == "CUSTOM_BASE_URL"


def test_create_runtime_container_rejects_invalid_cli_runner_timeout(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(
        get_settings(),
        agent_runner_adapter="cli",
        cli_agent_timeout_seconds=0,
    )

    try:
        create_runtime_container(settings=settings)
    except ValueError as exc:
        assert str(exc) == "CLI agent runner timeout must be greater than 0"
    else:
        raise AssertionError("Expected ValueError for invalid cli runner timeout")


def test_create_app_stores_runtime_container_extension(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    runtime = create_runtime_container()

    app = create_app(runtime)

    assert app.extensions["runtime_container"] is runtime


def test_deliver_worker_uses_shared_runtime_initialization(monkeypatch) -> None:
    class StubWorker:
        def __init__(self) -> None:
            self.poll_count = 0
            self.max_iterations = None

        def poll_once(self) -> None:
            self.poll_count += 1

        def run_forever(self, *, max_iterations=None, sleep_fn=None) -> None:
            self.max_iterations = max_iterations

    expected_worker = StubWorker()

    monkeypatch.setattr(deliver_worker, "build_deliver_worker", lambda: expected_worker)

    assert deliver_worker.run(once=True) is expected_worker
    assert expected_worker.poll_count == 1

    assert deliver_worker.run(max_iterations=4) is expected_worker
    assert expected_worker.max_iterations == 4


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


def test_cli_runtime_container_exposes_agent_runner_protocol(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    runtime = create_runtime_container(settings=replace(get_settings(), agent_runner_adapter="cli"))

    assert isinstance(runtime.agent_runner, AgentRunnerProtocol)
