from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApplicationSettingSpec:
    key: str
    env_var: str
    value_type: str
    default_value: str
    description: str
    display_order: int

    def env_default(self) -> str:
        value = os.getenv(self.env_var)
        if value is None or not value.strip():
            return self.default_value
        return value.strip()


DEFAULT_APPLICATION_SETTINGS: tuple[ApplicationSettingSpec, ...] = (
    ApplicationSettingSpec(
        key="tracker_fetch_limit",
        env_var="TRACKER_FETCH_LIMIT",
        value_type="int",
        default_value="100",
        description="Maximum tracker tasks fetched by worker1 in one poll.",
        display_order=10,
    ),
    ApplicationSettingSpec(
        key="execute_worker_batch_size",
        env_var="EXECUTE_WORKER_BATCH_SIZE",
        value_type="int",
        default_value="1",
        description="Number of execute tasks processed per worker poll cycle.",
        display_order=15,
    ),
    ApplicationSettingSpec(
        key="pr_feedback_fetch_limit",
        env_var="PR_FEEDBACK_FETCH_LIMIT",
        value_type="int",
        default_value="100",
        description="Maximum pull request feedback items fetched per execute task.",
        display_order=20,
    ),
    ApplicationSettingSpec(
        key="local_agent_provider",
        env_var="LOCAL_AGENT_PROVIDER",
        value_type="string",
        default_value="openai",
        description="Provider recorded by the local placeholder agent runner.",
        display_order=30,
    ),
    ApplicationSettingSpec(
        key="local_agent_model",
        env_var="LOCAL_AGENT_MODEL",
        value_type="string",
        default_value="gpt-5.4",
        description="Model recorded by the local placeholder agent runner.",
        display_order=40,
    ),
    ApplicationSettingSpec(
        key="local_agent_name",
        env_var="LOCAL_AGENT_NAME",
        value_type="string",
        default_value="local-placeholder-runner",
        description="Runner name recorded by the local placeholder agent runner.",
        display_order=50,
    ),
    ApplicationSettingSpec(
        key="cli_agent_preview_chars",
        env_var="CLI_AGENT_PREVIEW_CHARS",
        value_type="int",
        default_value="1000",
        description="Maximum number of characters kept in CLI stdout/stderr previews.",
        display_order=60,
    ),
)

APPLICATION_SETTING_SPECS_BY_KEY = {
    spec.key: spec for spec in DEFAULT_APPLICATION_SETTINGS
}


__all__ = [
    "APPLICATION_SETTING_SPECS_BY_KEY",
    "ApplicationSettingSpec",
    "DEFAULT_APPLICATION_SETTINGS",
]
