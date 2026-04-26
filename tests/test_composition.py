from dataclasses import replace

import pytest

from backend.adapters.github_scm import GitHubScm
from backend.adapters.linear_tracker import LinearTracker
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
from backend.task_constants import TaskStatus, TaskType
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


def _clear_tracker_env(monkeypatch) -> None:
    for var in (
        "TRACKER_ADAPTER",
        "SCM_ADAPTER",
        "AGENT_RUNNER_ADAPTER",
        "LINEAR_TEAM_ID",
        "LINEAR_TOKEN_ENV_VAR",
        "LINEAR_API_KEY",
        "LINEAR_STATE_ID_NEW",
        "LINEAR_STATE_ID_PROCESSING",
        "LINEAR_STATE_ID_DONE",
        "LINEAR_STATE_ID_FAILED",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()


def test_create_runtime_container_builds_linear_tracker_from_settings(monkeypatch) -> None:
    _clear_tracker_env(monkeypatch)
    settings = replace(
        get_settings(),
        tracker_adapter="linear",
        linear_team_id="team-1",
        linear_token_env_var="LINEAR_API_KEY",
    )

    runtime = create_runtime_container(settings=settings)

    assert isinstance(runtime.tracker, LinearTracker)
    assert runtime.tracker._config.team_id == "team-1"
    assert runtime.tracker._config.token_env_var == "LINEAR_API_KEY"
    # Token value is intentionally NOT validated at composition time —
    # _GraphqlClient.execute resolves it lazily on the first call.


def test_create_runtime_container_rejects_linear_without_team_id(monkeypatch) -> None:
    _clear_tracker_env(monkeypatch)
    settings = replace(
        get_settings(),
        tracker_adapter="linear",
        linear_team_id=None,
    )

    with pytest.raises(ValueError) as exc_info:
        create_runtime_container(settings=settings)
    assert "LINEAR_TEAM_ID must be set" in str(exc_info.value)


def test_create_runtime_container_rejects_linear_without_token_env_var(monkeypatch) -> None:
    _clear_tracker_env(monkeypatch)
    settings = replace(
        get_settings(),
        tracker_adapter="linear",
        linear_team_id="team-1",
        linear_token_env_var="",
    )

    with pytest.raises(ValueError) as exc_info:
        create_runtime_container(settings=settings)
    assert "LINEAR_TOKEN_ENV_VAR must be set" in str(exc_info.value)


def test_create_runtime_container_passes_through_linear_settings(monkeypatch) -> None:
    _clear_tracker_env(monkeypatch)
    settings = replace(
        get_settings(),
        tracker_adapter="linear",
        linear_team_id="team-2",
        linear_token_env_var="MY_LINEAR_TOKEN",
        linear_api_url="https://example.test/graphql",
        linear_state_id_new="state-new",
        linear_state_id_processing="state-proc",
        linear_state_id_done="state-done",
        linear_state_id_failed="state-failed",
        linear_task_type_label_mapping={"fetch": "lbl-fetch"},
        linear_fetch_state_types=("backlog",),
        linear_fetch_label_id="lbl-incoming",
        linear_max_pages=2,
        linear_description_warn_threshold=10,
        linear_request_timeout_seconds=7,
    )

    runtime = create_runtime_container(settings=settings)

    assert isinstance(runtime.tracker, LinearTracker)
    config = runtime.tracker._config
    assert config.api_url == "https://example.test/graphql"
    assert config.team_id == "team-2"
    assert config.timeout_seconds == 7
    assert config.fetch_label_id == "lbl-incoming"
    assert config.fetch_state_types == ("backlog",)
    assert config.max_pages == 2
    assert config.description_warn_threshold == 10
    assert config.explicit_status_to_state_id == {
        TaskStatus.NEW: "state-new",
        TaskStatus.PROCESSING: "state-proc",
        TaskStatus.DONE: "state-done",
        TaskStatus.FAILED: "state-failed",
    }
    assert config.task_type_to_label_id == {TaskType.FETCH: "lbl-fetch"}


def test_create_runtime_container_skips_unknown_task_type_label_mapping(monkeypatch) -> None:
    _clear_tracker_env(monkeypatch)
    settings = replace(
        get_settings(),
        tracker_adapter="linear",
        linear_team_id="team-3",
        linear_task_type_label_mapping={
            "unknown_type": "lbl-x",
            "fetch": "lbl-fetch",
        },
    )

    runtime = create_runtime_container(settings=settings)

    assert isinstance(runtime.tracker, LinearTracker)
    assert runtime.tracker._config.task_type_to_label_id == {
        TaskType.FETCH: "lbl-fetch",
    }


def test_create_runtime_container_builds_github_scm_from_settings(monkeypatch) -> None:
    monkeypatch.delenv("TRACKER_ADAPTER", raising=False)
    monkeypatch.delenv("SCM_ADAPTER", raising=False)
    monkeypatch.delenv("AGENT_RUNNER_ADAPTER", raising=False)
    get_settings.cache_clear()
    settings = replace(
        get_settings(),
        scm_adapter="github",
        github_default_repo_url="https://github.com/acme/widgets",
        workspace_root="/tmp/heavy",
    )

    runtime = create_runtime_container(settings=settings)

    assert isinstance(runtime.scm, GitHubScm)
    assert runtime.scm._config.default_repo_url == "https://github.com/acme/widgets"
    assert str(runtime.scm._config.workspace_root) in ("/tmp/heavy", "\\tmp\\heavy")


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
