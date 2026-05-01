from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask

from backend.adapters.github_scm import GitHubScm, build_github_scm_config
from backend.adapters.linear_tracker import LinearTracker, LinearTrackerConfig
from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_telegram import MockTelegram
from backend.adapters.mock_tracker import MockTracker
from backend.adapters.telegram_bot import TelegramBotApi, TelegramBotConfig
from backend.logging_setup import get_logger
from backend.protocols.agent_runner import AgentRunnerProtocol
from backend.protocols.scm import ScmProtocol
from backend.protocols.telegram import TelegramProtocol
from backend.protocols.tracker import TrackerProtocol
from backend.services.agent_runner import CliAgentRunner, CliAgentRunnerConfig, LocalAgentRunner
from backend.settings import Settings, get_settings
from backend.task_constants import TaskStatus, TaskType

_logger = get_logger(component="composition")

_TASK_STATUS_BY_STATE_ENV: Mapping[TaskStatus, str] = {
    TaskStatus.NEW: "linear_state_id_new",
    TaskStatus.PROCESSING: "linear_state_id_processing",
    TaskStatus.DONE: "linear_state_id_done",
    TaskStatus.FAILED: "linear_state_id_failed",
}

TrackerFactory = Callable[[Settings], TrackerProtocol]
ScmFactory = Callable[[Settings], ScmProtocol]
AgentRunnerFactory = Callable[[Settings], AgentRunnerProtocol]
TelegramFactory = Callable[[Settings], TelegramProtocol]


@dataclass(frozen=True, slots=True)
class AdapterRegistry:
    tracker_factories: Mapping[str, TrackerFactory]
    scm_factories: Mapping[str, ScmFactory]
    agent_runner_factories: Mapping[str, AgentRunnerFactory]
    telegram_factories: Mapping[str, TelegramFactory] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeContainer:
    settings: Settings
    tracker: TrackerProtocol
    scm: ScmProtocol
    agent_runner: AgentRunnerProtocol
    telegram: TelegramProtocol | None = None


def _build_mock_tracker(_: Settings) -> TrackerProtocol:
    return MockTracker()


def _build_linear_tracker(settings: Settings) -> TrackerProtocol:
    if not settings.linear_team_id:
        raise ValueError(
            "LINEAR_TEAM_ID must be set when tracker_adapter='linear'"
        )
    if not settings.linear_token_env_var:
        raise ValueError(
            "LINEAR_TOKEN_ENV_VAR must be set when tracker_adapter='linear'"
        )

    explicit_status_to_state_id: dict[TaskStatus, str] = {}
    for status, attr in _TASK_STATUS_BY_STATE_ENV.items():
        state_id = getattr(settings, attr)
        if state_id:
            explicit_status_to_state_id[status] = state_id

    task_type_to_label_id: dict[TaskType, str] = {}
    for raw_key, label_id in settings.linear_task_type_label_mapping.items():
        try:
            task_type = TaskType(raw_key)
        except ValueError:
            _logger.warning(
                "linear_task_type_label_mapping_unknown_key",
                key=raw_key,
            )
            continue
        if label_id:
            task_type_to_label_id[task_type] = label_id

    config = LinearTrackerConfig(
        api_url=settings.linear_api_url,
        token_env_var=settings.linear_token_env_var,
        team_id=settings.linear_team_id,
        timeout_seconds=settings.linear_request_timeout_seconds,
        fetch_label_id=settings.linear_fetch_label_id,
        explicit_status_to_state_id=explicit_status_to_state_id,
        fetch_state_types=settings.linear_fetch_state_types,
        task_type_to_label_id=task_type_to_label_id,
        max_pages=settings.linear_max_pages,
        description_warn_threshold=settings.linear_description_warn_threshold,
    )
    return LinearTracker(config)


def _build_mock_scm(_: Settings) -> ScmProtocol:
    return MockScm()


def _build_github_scm(settings: Settings) -> ScmProtocol:
    config = build_github_scm_config(
        api_base_url=settings.github_api_base_url,
        token_env_var=settings.github_token_env_var,
        user_name=settings.github_user_name,
        user_email=settings.github_user_email,
        default_remote=settings.github_default_remote,
        workspace_root=Path(settings.workspace_root),
        default_repo_url=settings.github_default_repo_url,
    )
    return GitHubScm(config)


def _build_mock_telegram(_: Settings) -> TelegramProtocol:
    return MockTelegram()


def _build_telegram_bot(settings: Settings) -> TelegramProtocol:
    if not settings.telegram_bot_token_env_var:
        raise ValueError("TELEGRAM_BOT_TOKEN_ENV_VAR must be set when telegram_adapter='bot'")
    return TelegramBotApi(
        TelegramBotConfig(token_env_var=settings.telegram_bot_token_env_var)
    )


def _build_local_agent_runner(settings: Settings) -> AgentRunnerProtocol:
    return LocalAgentRunner(
        provider=settings.local_agent_provider,
        model=settings.local_agent_model,
        name=settings.local_agent_name,
    )


def _build_cli_agent_runner(settings: Settings) -> AgentRunnerProtocol:
    if not settings.cli_agent_command:
        raise ValueError("CLI agent runner command must not be empty")
    if not settings.cli_agent_subcommand:
        raise ValueError("CLI agent runner subcommand must not be empty")
    if settings.cli_agent_timeout_seconds <= 0:
        raise ValueError("CLI agent runner timeout must be greater than 0")
    if settings.cli_agent_preview_chars <= 0:
        raise ValueError("CLI agent runner preview chars must be greater than 0")

    return CliAgentRunner(
        config=CliAgentRunnerConfig(
            command=settings.cli_agent_command,
            subcommand=settings.cli_agent_subcommand,
            timeout_seconds=settings.cli_agent_timeout_seconds,
            provider_hint=settings.cli_agent_provider_hint,
            model_hint=settings.cli_agent_model_hint,
            profile=settings.cli_agent_profile,
            api_key_env_var=settings.cli_agent_api_key_env_var,
            base_url_env_var=settings.cli_agent_base_url_env_var,
            preview_chars=settings.cli_agent_preview_chars,
        )
    )


DEFAULT_ADAPTER_REGISTRY = AdapterRegistry(
    tracker_factories={
        "mock": _build_mock_tracker,
        "linear": _build_linear_tracker,
    },
    scm_factories={"mock": _build_mock_scm, "github": _build_github_scm},
    agent_runner_factories={
        "local": _build_local_agent_runner,
        "cli": _build_cli_agent_runner,
    },
    telegram_factories={
        "mock": _build_mock_telegram,
        "bot": _build_telegram_bot,
    },
)


def create_runtime_container(
    settings: Settings | None = None,
    registry: AdapterRegistry = DEFAULT_ADAPTER_REGISTRY,
) -> RuntimeContainer:
    active_settings = settings or get_settings()

    try:
        tracker_factory = registry.tracker_factories[active_settings.tracker_adapter]
    except KeyError as exc:
        raise ValueError(f"Unsupported tracker adapter: {active_settings.tracker_adapter}") from exc

    try:
        scm_factory = registry.scm_factories[active_settings.scm_adapter]
    except KeyError as exc:
        raise ValueError(f"Unsupported SCM adapter: {active_settings.scm_adapter}") from exc

    try:
        agent_runner_factory = registry.agent_runner_factories[active_settings.agent_runner_adapter]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported agent runner adapter: {active_settings.agent_runner_adapter}"
        ) from exc

    telegram: TelegramProtocol | None = None
    if active_settings.telegram_adapter != "none":
        try:
            telegram_factory = registry.telegram_factories[active_settings.telegram_adapter]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported Telegram adapter: {active_settings.telegram_adapter}"
            ) from exc
        telegram = telegram_factory(active_settings)

    return RuntimeContainer(
        settings=active_settings,
        tracker=tracker_factory(active_settings),
        scm=scm_factory(active_settings),
        agent_runner=agent_runner_factory(active_settings),
        telegram=telegram,
    )


def init_app_container(
    app: Flask,
    runtime: RuntimeContainer | None = None,
) -> RuntimeContainer:
    active_runtime = runtime or create_runtime_container()
    app.extensions["runtime_container"] = active_runtime
    return active_runtime


__all__ = [
    "AdapterRegistry",
    "DEFAULT_ADAPTER_REGISTRY",
    "RuntimeContainer",
    "create_runtime_container",
    "init_app_container",
]
