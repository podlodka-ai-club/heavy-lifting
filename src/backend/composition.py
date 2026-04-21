from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from flask import Flask

from backend.adapters.mock_scm import MockScm
from backend.adapters.mock_tracker import MockTracker
from backend.protocols.agent_runner import AgentRunnerProtocol
from backend.protocols.scm import ScmProtocol
from backend.protocols.tracker import TrackerProtocol
from backend.services.agent_runner import LocalAgentRunner
from backend.settings import Settings, get_settings

TrackerFactory = Callable[[Settings], TrackerProtocol]
ScmFactory = Callable[[Settings], ScmProtocol]
AgentRunnerFactory = Callable[[Settings], AgentRunnerProtocol]


@dataclass(frozen=True, slots=True)
class AdapterRegistry:
    tracker_factories: Mapping[str, TrackerFactory]
    scm_factories: Mapping[str, ScmFactory]
    agent_runner_factories: Mapping[str, AgentRunnerFactory]


@dataclass(frozen=True, slots=True)
class RuntimeContainer:
    settings: Settings
    tracker: TrackerProtocol
    scm: ScmProtocol
    agent_runner: AgentRunnerProtocol


def _build_mock_tracker(_: Settings) -> TrackerProtocol:
    return MockTracker()


def _build_mock_scm(_: Settings) -> ScmProtocol:
    return MockScm()


def _build_local_agent_runner(_: Settings) -> AgentRunnerProtocol:
    return LocalAgentRunner()


DEFAULT_ADAPTER_REGISTRY = AdapterRegistry(
    tracker_factories={"mock": _build_mock_tracker},
    scm_factories={"mock": _build_mock_scm},
    agent_runner_factories={"local": _build_local_agent_runner},
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

    return RuntimeContainer(
        settings=active_settings,
        tracker=tracker_factory(active_settings),
        scm=scm_factory(active_settings),
        agent_runner=agent_runner_factory(active_settings),
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
