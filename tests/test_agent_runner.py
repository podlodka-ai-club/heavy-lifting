from __future__ import annotations

import subprocess
from decimal import Decimal

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


def test_local_agent_runner_describes_tracker_feedback_follow_up(tmp_path) -> None:
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
                context={
                    "title": "Estimate task",
                    "description": "Estimate only. Do not modify code.",
                },
                input_payload={"instructions": "Estimate only. Do not modify code."},
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.TRACKER_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "tracker_feedback": {
                        "external_task_id": "TASK-24",
                        "comment_id": "comment-2",
                        "body": "Please explain the estimate.",
                    }
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

    assert result.payload.summary == "Prepared follow-up response for tracker comment comment-2."
    assert result.summary_metadata["has_feedback"] is True


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
            preview_chars=250,
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
    assert runner.config.preview_chars == 250


def test_cli_agent_runner_uses_configured_preview_limit() -> None:
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(
            command="opencode",
            subcommand="run",
            timeout_seconds=900,
            preview_chars=8,
        )
    )

    assert runner._build_preview("abcdefghijklmnop") == "abcde..."


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
        "--format",
        "json",
        "--model",
        "openai/gpt-5.4",
        "prompt body",
    ]


def test_cli_agent_runner_prompt_requires_concrete_edits_for_normal_execute(tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    prompt = runner._build_prompt(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert "runtime_contract:" in prompt
    assert "- Apply concrete file changes directly in the workspace." in prompt
    assert "- Do not stop at analysis, explanation, or a plan when edits are required." in prompt
    assert "- This is an estimate-only task." not in prompt


def test_cli_agent_runner_prompt_marks_estimate_only_execute_without_code_changes(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                context={
                    "title": "Estimate task",
                    "description": "Estimate only. Do not modify code.",
                },
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                context={"title": "Estimate task"},
                input_payload={"instructions": "Estimate only. Do not modify code."},
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=execute_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    prompt = runner._build_prompt(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert "- This is an estimate-only task." in prompt
    assert "- Do not modify code or create SCM artifacts." in prompt
    assert "- Apply concrete file changes directly in the workspace." not in prompt


def test_cli_agent_runner_prompt_prefers_explicit_estimate_only_mode(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                context={
                    "title": "Assess task",
                    "description": "Assess complexity for planning.",
                },
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                context={"title": "Assess task"},
                input_payload={
                    "instructions": "Assess complexity and provide estimate.",
                    "metadata": {"estimate_only": True},
                },
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=execute_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    prompt = runner._build_prompt(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert "- This is an estimate-only task." in prompt
    assert "- Do not modify code or create SCM artifacts." in prompt
    assert "- Apply concrete file changes directly in the workspace." not in prompt


def test_cli_agent_runner_prompt_keeps_tracker_feedback_estimate_thread_comment_only(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                context={
                    "title": "Estimate task",
                    "description": "Estimate only. Do not modify code.",
                },
            )
        )
        execute_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                context={"title": "Estimate task"},
                input_payload={"instructions": "Estimate only. Do not modify code."},
                result_payload={
                    "summary": "Estimate delivered.",
                    "tracker_comment": "2 story points\nReason: small change.",
                    "metadata": {"delivery_mode": "estimate_only"},
                },
            )
        )
        feedback_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.TRACKER_FEEDBACK,
                parent_id=execute_task.id,
                input_payload={
                    "tracker_feedback": {
                        "external_task_id": "TASK-46",
                        "comment_id": "comment-3",
                        "body": "Почему такая оценка?",
                    }
                },
            )
        )

        task_context = ContextBuilder().build_for_task(
            task=feedback_task,
            task_chain=repository.load_task_chain(fetch_task.root_id),
        )

    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    prompt = runner._build_prompt(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert "- Reply in the existing tracker thread." in prompt
    assert "- Do not modify code or create SCM artifacts." in prompt
    assert "- Apply concrete file changes directly in the workspace." not in prompt


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
            stdout=(
                '{"type":"step_start","part":{"type":"step-start"}}\n'
                '{"type":"text","part":{"type":"text","text":"Applied requested changes."}}\n'
                '{"type":"text","part":{"type":"text","text":"Created patch."}}\n'
                '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":144,'
                '"input":101,"output":33,"reasoning":10,"cache":{"read":7,"write":2}},'
                '"cost":"0.004321"}}\n'
            ),
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
        "--format",
        "json",
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
    assert [entry.model_dump() for entry in result.payload.token_usage] == [
        {
            "model": "gpt-5.4",
            "provider": "openai",
            "input_tokens": 101,
            "output_tokens": 33,
            "cached_tokens": 7,
            "estimated": False,
            "cost_usd": Decimal("0.004321"),
        }
    ]
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
            "--format",
            "json",
            "--model",
            "openai/gpt-5.4",
            captured["command"][-1],
        ],
        "exit_code": 0,
        "execution_status": "succeeded",
        "stdout_preview": "Applied requested changes.\nCreated patch.",
        "stdout_raw_preview": (
            '{"type":"step_start","part":{"type":"step-start"}}\n'
            '{"type":"text","part":{"type":"text","text":"Applied requested changes."}}\n'
            '{"type":"text","part":{"type":"text","text":"Created patch."}}\n'
            '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":144,'
            '"input":101,"output":33,"reasoning":10,"cache":{"read":7,"write":2}},'
            '"cost":"0.004321"}}'
        ),
        "stdout_preview_source": "text_events",
        "stdout_event_count": 4,
        "stdout_event_types": ["step_start", "text", "text", "step_finish"],
        "stdout_error_event": {"status": "not_found"},
        "stderr_preview": None,
        "stderr_analysis": {"status": "empty", "error_like": False},
        "usage": {
            "status": "parsed",
            "model": "gpt-5.4",
            "provider": "openai",
            "input_tokens": 101,
            "output_tokens": 33,
            "cached_tokens": 7,
            "cost_usd": "0.004321",
            "reasoning_tokens": 10,
            "total_tokens": 144,
            "cache_write_tokens": 2,
        },
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
            stdout='{"type":"text","part":{"type":"text","text":"Model request failed."}}\n',
            stderr="failed to complete model request.",
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
    assert (
        result.payload.details
        == "stdout:\nModel request failed.\nstderr:\nfailed to complete model request."
    )
    assert result.summary_metadata["exit_code"] == 17
    assert result.summary_metadata["stdout_preview"] == "Model request failed."
    assert result.summary_metadata["stdout_preview_source"] == "text_events"
    assert result.summary_metadata["usage"] == {
        "status": "missing",
        "reason": "step_finish_not_found",
    }
    assert result.summary_metadata["stderr_preview"] == "failed to complete model request."
    assert result.summary_metadata["stdout_error_event"] == {"status": "not_found"}
    assert result.summary_metadata["stderr_analysis"] == {
        "status": "error_like",
        "error_like": True,
        "reason": "failed_prefix",
    }
    assert result.summary_metadata["runner_metadata"] == {
        "subcommand": "run",
        "profile": None,
        "provider_hint": None,
        "model_hint": None,
        "model_argument": None,
        "api_key_env_var": None,
        "base_url_env_var": None,
    }


def test_cli_agent_runner_falls_back_when_usage_is_missing(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"step_start","part":{"type":"step-start"}}\n'
                '{"type":"text","part":{"type":"text","text":"No usage payload returned."}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.details == "stdout:\nNo usage payload returned."
    assert result.payload.token_usage == []
    assert result.summary_metadata["execution_status"] == "succeeded"
    assert result.summary_metadata["usage"] == {
        "status": "missing",
        "reason": "step_finish_not_found",
    }


def test_cli_agent_runner_fails_on_stdout_error_event_with_zero_exit(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"text","part":{"type":"text","text":"Starting run."}}\n'
                '{"type":"error","part":{"type":"error","text":"Invalid model: openai/oops"}}\n'
                '{"type":"step_finish","part":{"type":"step-finish","tokens":{"input":8,'
                '"output":3,"cache":{"read":1}},"cost":"0.0004"}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.summary == "CLI agent run failed: Invalid model: openai/oops"
    assert result.payload.details == "stdout:\nStarting run.\nInvalid model: openai/oops"
    assert [entry.model_dump() for entry in result.payload.token_usage] == [
        {
            "model": "unknown",
            "provider": "unknown",
            "input_tokens": 8,
            "output_tokens": 3,
            "cached_tokens": 1,
            "estimated": False,
            "cost_usd": Decimal("0.0004"),
        }
    ]
    assert result.summary_metadata["execution_status"] == "failed"
    assert result.summary_metadata["failure_message"] == (
        "CLI agent run failed: Invalid model: openai/oops"
    )
    assert result.summary_metadata["stdout_error_event"] == {
        "status": "detected",
        "message": "Invalid model: openai/oops",
        "event_type": "error",
    }
    assert result.summary_metadata["stderr_analysis"] == {
        "status": "empty",
        "error_like": False,
    }


def test_cli_agent_runner_fails_on_error_like_stderr_with_zero_exit(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"text","part":{"type":"text","text":"Model lookup failed."}}\n',
            stderr="ProviderModelNotFoundError: model openai/oops was not found",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.summary == (
        "CLI agent run failed: ProviderModelNotFoundError: model openai/oops was not found"
    )
    assert result.payload.details == (
        "stdout:\nModel lookup failed.\nstderr:\n"
        "ProviderModelNotFoundError: model openai/oops was not found"
    )
    assert result.payload.token_usage == []
    assert result.summary_metadata["execution_status"] == "failed"
    assert result.summary_metadata["failure_message"] == (
        "CLI agent run failed: ProviderModelNotFoundError: model openai/oops was not found"
    )
    assert result.summary_metadata["stdout_error_event"] == {"status": "not_found"}
    assert result.summary_metadata["stderr_analysis"] == {
        "status": "error_like",
        "error_like": True,
        "reason": "error_class",
    }


def test_cli_agent_runner_keeps_benign_stderr_successful(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"text","part":{"type":"text","text":"Run completed."}}\n',
            stderr="warning: using fallback cache path",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.summary == "CLI agent run completed successfully."
    assert result.summary_metadata["execution_status"] == "succeeded"
    assert "failure_message" not in result.summary_metadata
    assert result.summary_metadata["stderr_analysis"] == {
        "status": "benign",
        "error_like": False,
    }


def test_cli_agent_runner_keeps_zero_failed_stderr_successful(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"text","part":{"type":"text","text":"Run completed."}}\n',
            stderr="tests finished successfully: 0 failed, 12 passed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.summary == "CLI agent run completed successfully."
    assert result.summary_metadata["execution_status"] == "succeeded"
    assert "failure_message" not in result.summary_metadata
    assert result.summary_metadata["stderr_analysis"] == {
        "status": "benign",
        "error_like": False,
    }


def test_cli_agent_runner_keeps_failed_over_warning_stderr_successful(
    monkeypatch, tmp_path
) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"text","part":{"type":"text","text":"Run completed."}}\n',
            stderr="warning: network probe failed over to cached endpoint",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.summary == "CLI agent run completed successfully."
    assert result.summary_metadata["execution_status"] == "succeeded"
    assert "failure_message" not in result.summary_metadata
    assert result.summary_metadata["stderr_analysis"] == {
        "status": "benign",
        "error_like": False,
    }


def test_cli_agent_runner_marks_malformed_usage_explicitly(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"text","part":{"type":"text","text":"Malformed usage."}}\n'
                '{"type":"step_finish","part":{"type":"step-finish","tokens":{"input":"oops",'
                '"output":3,"cache":{"read":0}},"cost":0}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.token_usage == []
    assert result.summary_metadata["usage"]["status"] == "malformed"
    assert result.summary_metadata["usage"]["reason"] == "invalid_usage_fields"
    assert "tokens.input" in result.summary_metadata["usage"]["error"]


def test_cli_agent_runner_falls_back_when_cost_is_missing(monkeypatch, tmp_path) -> None:
    task_context = _build_task_context(tmp_path)
    runner = CliAgentRunner(
        config=CliAgentRunnerConfig(command="opencode", subcommand="run", timeout_seconds=120)
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"type":"text","part":{"type":"text","text":"Usage without cost."}}\n'
                '{"type":"step_finish","part":{"type":"step-finish","tokens":{"input":8,'
                '"output":3,"cache":{"read":1}}}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run(
        AgentRunRequest(task_context=task_context, workspace_path=str(tmp_path / "workspace"))
    )

    assert result.payload.details == "stdout:\nUsage without cost."
    assert result.payload.token_usage == []
    assert result.summary_metadata["usage"] == {
        "status": "missing",
        "reason": "cost_not_found",
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

    assert captured["command"][:6] == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path / "workspace"),
        "--format",
        "json",
    ]
    assert captured["command"][6] == "--model"
    assert captured["command"][7] == "gpt-5.4"
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
