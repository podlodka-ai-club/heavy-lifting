from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

AgentPromptSource = Literal["default", "runtime"]
ApiKeySource = Literal["runtime", "env", "none"]


@dataclass(frozen=True, slots=True)
class AgentPromptSettings:
    name: str
    prompt: str
    source: AgentPromptSource


@dataclass(frozen=True, slots=True)
class RuntimeSettingsSnapshot:
    api_key_configured: bool
    api_key_source: ApiKeySource
    api_key_env_var: str | None
    agent_prompts: tuple[AgentPromptSettings, ...]


class RuntimeSettingsStore:
    def __init__(
        self,
        *,
        storage_path: Path,
        prompts_dir: Path,
        api_key_env_var: str | None,
    ) -> None:
        self._storage_path = storage_path
        self._prompts_dir = prompts_dir
        self._api_key_env_var = api_key_env_var

    def snapshot(self) -> RuntimeSettingsSnapshot:
        data = self._read_data()
        runtime_api_key = _extract_runtime_api_key(data)
        env_api_key = os.getenv(self._api_key_env_var) if self._api_key_env_var else None
        if runtime_api_key:
            api_key_source: ApiKeySource = "runtime"
        elif env_api_key:
            api_key_source = "env"
        else:
            api_key_source = "none"

        overrides = _extract_prompt_overrides(data)
        agent_prompts = tuple(
            AgentPromptSettings(
                name=name,
                prompt=overrides.get(name, default_prompt),
                source="runtime" if name in overrides else "default",
            )
            for name, default_prompt in self._default_prompts().items()
        )
        return RuntimeSettingsSnapshot(
            api_key_configured=api_key_source != "none",
            api_key_source=api_key_source,
            api_key_env_var=self._api_key_env_var,
            agent_prompts=agent_prompts,
        )

    def update(
        self,
        *,
        api_key_provided: bool,
        api_key: str | None,
        prompts: Mapping[str, str] | None,
    ) -> RuntimeSettingsSnapshot:
        data = self._read_data()

        if api_key_provided:
            normalized_api_key = api_key.strip() if api_key is not None else ""
            if normalized_api_key:
                data["api_key"] = normalized_api_key
            else:
                data.pop("api_key", None)

        if prompts is not None:
            defaults = self._default_prompts()
            unknown_agents = sorted(set(prompts) - set(defaults))
            if unknown_agents:
                agents = ", ".join(unknown_agents)
                raise ValueError(f"Unknown agent prompt: {agents}")

            overrides = _extract_prompt_overrides(data)
            for name, prompt in prompts.items():
                if prompt == defaults[name]:
                    overrides.pop(name, None)
                else:
                    overrides[name] = prompt

            if overrides:
                data["prompts"] = dict(sorted(overrides.items()))
            else:
                data.pop("prompts", None)

        self._write_data(data)
        return self.snapshot()

    def _default_prompts(self) -> dict[str, str]:
        if not self._prompts_dir.exists():
            return {}

        return {
            path.stem: path.read_text(encoding="utf-8")
            for path in sorted(self._prompts_dir.glob("*.md"))
            if path.is_file()
        }

    def _read_data(self) -> dict[str, Any]:
        return _read_runtime_data(self._storage_path)

    def _write_data(self, data: Mapping[str, Any]) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_name(f".{self._storage_path.name}.tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)


def load_runtime_api_key(storage_path: Path) -> str | None:
    return _extract_runtime_api_key(_read_runtime_data(storage_path))


def _read_runtime_data(storage_path: Path) -> dict[str, Any]:
    if not storage_path.exists():
        return {}

    try:
        parsed = json.loads(storage_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}

    if not isinstance(parsed, dict):
        return {}

    return cast(dict[str, Any], parsed)


def _extract_runtime_api_key(data: Mapping[str, Any]) -> str | None:
    api_key = data.get("api_key")
    if isinstance(api_key, str) and api_key:
        return api_key
    return None


def _extract_prompt_overrides(data: Mapping[str, Any]) -> dict[str, str]:
    prompts = data.get("prompts")
    if not isinstance(prompts, dict):
        return {}

    return {str(name): prompt for name, prompt in prompts.items() if isinstance(prompt, str)}


__all__ = [
    "AgentPromptSettings",
    "RuntimeSettingsSnapshot",
    "RuntimeSettingsStore",
    "load_runtime_api_key",
]
