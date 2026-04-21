from __future__ import annotations

import subprocess

from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base
from backend.protocols.agent_runner import AgentRunRequest
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.services.agent_runner import CliAgentRunner, CliAgentRunnerConfig, LocalAgentRunner
from backend.services.context_builder import ContextBuilder
from backend.task_constants import TaskType


def test_local_agent_runner_returns_normalized_execute_result(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-24",
                context={"title": "Tracker task"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task24/runner",
                context={"title": "Implement runner abstraction"},
                input_payload={
                    "instructions": "Implement a placeholder agent runner and tests.",
                    "base_branch": "main",
                    "branch_name": "task24/runner",
                },
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=execute_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    result = LocalAgentRunner().run(
        AgentRunRequest(task_context=task_context, workspace_path="/workspace/repos/repo-24")
    )

    assert (
        result.payload.summary == "Prepared local agent execution for Implement runner abstraction."
    )
    assert result.payload.branch_name == "task24/runner"
    assert result.payload.pr_url is None
    assert len(result.token_usage) == 1
    assert result.token_usage[0].estimated is True
    assert result.summary_metadata == {
        "runner_adapter": "local",
        "runner": "local-placeholder-runner",
        "mode": "placeholder",
        "provider": "openai",
        "model": "gpt-5.4",
        "flow_type": "execute",
        "workspace_path": "/workspace/repos/repo-24",
        "has_feedback": False,
        "feedback_history_count": 0,
        "estimated_cost_usd": str(result.token_usage[0].cost_usd),
    }


def test_local_agent_runner_includes_feedback_metadata_for_pr_feedback(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(task_type=TaskType.FETCH, context={"title": "Tracker task"})
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task24/runner-feedback",
                context={"title": "Implement runner abstraction"},
                input_payload={"instructions": "Initial implementation."},
                result_payload={"summary": "Opened PR", "pr_url": "https://example.test/pr/24"},
            )
        )
        repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "instructions": "Address first review comment.",
                    "pr_feedback": {
                        "pr_external_id": "pr-24",
                        "comment_id": "c-1",
                        "body": "Please add token metadata.",
                    },
                },
                result_payload={"summary": "Updated metadata"},
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.PR_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "instructions": "Address latest review comment.",
                    "pr_feedback": {
                        "pr_external_id": "pr-24",
                        "comment_id": "c-2",
                        "body": "Please keep the API small.",
                        "pr_url": "https://example.test/pr/24",
                    },
                },
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=feedback_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    result = LocalAgentRunner().run(
        AgentRunRequest(task_context=task_context, workspace_path="/workspace/repos/repo-24")
    )

    assert result.payload.summary == "Prepared follow-up response for review comment c-2."
    assert result.payload.pr_url == "https://example.test/pr/24"
    assert result.summary_metadata["has_feedback"] is True
    assert result.summary_metadata["feedback_history_count"] == 1
    assert result.summary_metadata["runner_adapter"] == "local"
    assert result.token_usage[0].cached_tokens > 0


def test_cli_agent_runner_exposes_stable_config_contract() -> None:
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=900,
            provider_hint="openai",
            model_hint="gpt-5.4",
            profile="backend",
            api_key_env_var="OPENAI_API_KEY",
            base_url_env_var="OPENAI_BASE_URL",
        )
    )

    assert runner.config.command == "opencode"
    assert runner.config.subcommand == "run"
    assert runner.config.timeout_seconds == 900
    assert runner.config.provider_hint == "openai"
    assert runner.config.model_hint == "gpt-5.4"
    assert runner.config.profile == "backend"
    assert runner.config.api_key_env_var == "OPENAI_API_KEY"
    assert runner.config.base_url_env_var == "OPENAI_BASE_URL"


def test_cli_agent_runner_builds_command_from_config() -> None:
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=900,
            provider_hint="openai",
            model_hint="gpt-5.4",
            profile="backend",
        )
    )
    task_context = _build_task_context_for_command()

    assert runner._build_command(
        request=AgentRunRequest(task_context=task_context, workspace_path="/workspace/task46"),
        prompt="prompt body",
    ) == [
        "opencode",
        "run",
        "--dir",
        "/workspace/task46",
        "--model",
        "openai/gpt-5.4",
        "prompt body",
    ]


def test_cli_agent_runner_normalizes_happy_path(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=900,
            provider_hint="openai",
            model_hint="gpt-5.4",
            profile="backend",
            api_key_env_var="OPENAI_API_KEY",
            base_url_env_var="OPENAI_BASE_URL",
        )
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="Applied requested changes.\nCreated patch.",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(
            task_context=task_context,
            workspace_path=str(tmp_path / "workspace"),
            metadata={"task_id": 46, "workspace_key": "repo-46"},
        )
    )

    assert captured["command"] == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path / "workspace"),
        "--model",
        "openai/gpt-5.4",
        captured["command"][-1],
    ]
    assert captured["cwd"] == str(tmp_path / "workspace")
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 900
    assert "input" not in captured
    assert "workspace_path: " in captured["command"][-1]
    assert "instructions:" in captured["command"][-1]
    assert "Implement CLI agent runner." in captured["command"][-1]
    assert "OPENAI_API_KEY" not in captured["command"][-1]
    assert "--agent" not in captured["command"]

    assert result.payload.summary == "CLI agent run completed successfully."
    assert result.payload.branch_name == "task46/cli-runner"
    assert result.payload.details == "stdout:\nApplied requested changes.\nCreated patch."
    assert result.payload.token_usage == []
    assert result.summary_metadata == {
        "runner_adapter": "cli",
        "runner": "opencode",
        "flow_type": "execute",
        "workspace_path": str(tmp_path / "workspace"),
        "request_metadata": {"task_id": 46, "workspace_key": "repo-46"},
        "command": [
            "opencode",
            "run",
            "--dir",
            str(tmp_path / "workspace"),
            "--model",
            "openai/gpt-5.4",
            captured["command"][-1],
        ],
        "exit_code": 0,
        "stdout_preview": "Applied requested changes.\nCreated patch.",
        "stderr_preview": None,
        "runner_metadata": {
            "subcommand": "run",
            "profile": "backend",
            "provider_hint": "openai",
            "model_hint": "gpt-5.4",
            "model_argument": "openai/gpt-5.4",
            "api_key_env_var": "OPENAI_API_KEY",
            "base_url_env_var": "OPENAI_BASE_URL",
        },
    }


def test_cli_agent_runner_normalizes_failure_path(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=120,
        )
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=17,
            stdout="",
            stderr="Model request failed.",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(
            task_context=task_context,
            workspace_path=str(tmp_path / "workspace"),
            metadata={"task_id": 46},
        )
    )

    assert result.payload.summary == "CLI agent run failed with exit code 17."
    assert result.payload.details == "stderr:\nModel request failed."
    assert result.summary_metadata["exit_code"] == 17
    assert result.summary_metadata["stdout_preview"] is None
    assert result.summary_metadata["stderr_preview"] == "Model request failed."
    assert result.summary_metadata["runner_metadata"] == {
        "subcommand": "run",
        "profile": None,
        "provider_hint": None,
        "model_hint": None,
        "model_argument": None,
        "api_key_env_var": None,
        "base_url_env_var": None,
    }


def test_cli_agent_runner_uses_model_hint_without_provider(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=120,
            model_hint="gpt-5.4",
            profile="backend",
        )
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert captured["command"][:5] == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path / "workspace"),
        "--model",
    ]
    assert captured["command"][5] == "gpt-5.4"
    assert "--agent" not in captured["command"]


def _build_task_context(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-46",
                context={"title": "Tracker task", "description": "Implement real CLI execution"},
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                branch_name="task46/cli-runner",
                context={"title": "Implement CLI runner"},
                input_payload={
                    "instructions": "Implement CLI agent runner.",
                    "base_branch": "main",
                    "branch_name": "task46/cli-runner",
                },
            )
        )

        return ContextBuilder().build_for_task(
            task=execute_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )


def _build_task_context_for_command():
    class _Context:
        flow_type = TaskType.EXECUTE
        repo_url = None
        repo_ref = None
        branch_name = None
        base_branch = None
        instructions = None
        tracker_context = None
        execution_context = None
        current_feedback = None
        feedback_history = ()

    return _Context()
