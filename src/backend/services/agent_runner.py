from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from backend.logging_setup import get_logger
from backend.protocols.agent_runner import AgentRunRequest, AgentRunResult
from backend.schemas import TaskContext, TaskResultPayload, TokenUsagePayload
from backend.services.token_costs import TokenCostService
from backend.task_constants import TaskType
from backend.task_context import EffectiveTaskContext


@dataclass(frozen=True, slots=True)
class CliAgentRunnerConfig:
    command: str
    subcommand: str
    timeout_seconds: int
    provider_hint: str | None = None
    model_hint: str | None = None
    profile: str | None = None
    api_key_env_var: str | None = None
    base_url_env_var: str | None = None
    preview_chars: int = 1000


@dataclass(slots=True)
class LocalAgentRunner:
    token_cost_service: TokenCostService = field(default_factory=TokenCostService)
    provider: str = "openai"
    model: str = "gpt-5.4"
    name: str = "local-placeholder-runner"

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        logger = _runner_logger(
            request,
            runner_adapter="local",
            runner=self.name,
            provider=self.provider,
            model=self.model,
        )
        logger.info("agent_run_started")
        usage = self.token_cost_service.with_estimated_cost(self._build_token_usage(request))
        metadata = self._build_summary_metadata(request=request, usage=usage)
        payload = TaskResultPayload(
            summary=self._build_summary(request.task_context),
            details=self._build_details(request.task_context, request.workspace_path),
            branch_name=request.task_context.branch_name,
            pr_url=request.task_context.pr_url,
            token_usage=[usage],
            metadata=metadata,
        )
        logger.info(
            "agent_run_finished",
            token_usage_entries=1,
            estimated_cost_usd=str(usage.cost_usd),
        )
        return AgentRunResult(payload=payload)

    def _build_token_usage(self, request: AgentRunRequest) -> TokenUsagePayload:
        instruction_text = request.task_context.instructions or ""
        tracker_title = (
            request.task_context.tracker_context.title
            if request.task_context.tracker_context
            else ""
        )
        execution_title = (
            request.task_context.execution_context.title
            if request.task_context.execution_context
            else ""
        )
        feedback_body = (
            request.task_context.current_feedback.body
            if request.task_context.current_feedback
            else ""
        )
        history_size = sum(
            len(entry.feedback.body) for entry in request.task_context.feedback_history
        )
        input_size = (
            len(instruction_text) + len(tracker_title) + len(execution_title) + len(feedback_body)
        )
        input_tokens = max(1, (input_size + history_size) // 4)

        output_tokens = 120 if request.task_context.flow_type == TaskType.EXECUTE else 80
        cached_tokens = history_size // 4
        return TokenUsagePayload(
            model=self.model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )

    def _build_summary(self, context: EffectiveTaskContext) -> str:
        execution_title = context.execution_context.title if context.execution_context else "task"
        if (
            context.flow_type in {TaskType.PR_FEEDBACK, TaskType.TRACKER_FEEDBACK}
            and context.current_feedback is not None
        ):
            comment_id = context.current_feedback.comment_id
            feedback_label = "review comment"
            if context.flow_type == TaskType.TRACKER_FEEDBACK:
                feedback_label = "tracker comment"
            return f"Prepared follow-up response for {feedback_label} {comment_id}."
        if context.flow_type == TaskType.EXECUTE:
            return f"Prepared local agent execution for {execution_title}."
        return f"Prepared local agent result for {execution_title}."

    def _build_details(self, context: EffectiveTaskContext, workspace_path: str) -> str:
        details = [f"Workspace: {workspace_path}", f"Flow: {context.flow_type.value}"]
        if context.instructions:
            details.append(f"Instructions: {context.instructions}")
        if context.current_feedback is not None:
            details.append(f"Feedback: {context.current_feedback.body}")
        return "\n".join(details)

    def _build_summary_metadata(
        self,
        *,
        request: AgentRunRequest,
        usage: TokenUsagePayload,
    ) -> dict[str, object]:
        total_cost = self.token_cost_service.total_estimated_cost([usage])
        return {
            "runner_adapter": "local",
            "runner": self.name,
            "mode": "placeholder",
            "provider": self.provider,
            "model": self.model,
            "flow_type": request.task_context.flow_type.value,
            "workspace_path": request.workspace_path,
            "has_feedback": request.task_context.current_feedback is not None,
            "feedback_history_count": len(request.task_context.feedback_history),
            "estimated_cost_usd": str(total_cost),
        }


@dataclass(slots=True)
class CliAgentRunner:
    config: CliAgentRunnerConfig

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        prompt = self._build_prompt(request)
        command = self._build_command(request=request, prompt=prompt)
        logger = _runner_logger(
            request,
            runner_adapter="cli",
            runner=self.config.command,
            subcommand=self.config.subcommand,
            command_preview=command[:-1] + ["<prompt>"],
            prompt_length=len(prompt),
        )
        logger.info("agent_run_started")
        completed_process = subprocess.run(
            command,
            cwd=request.workspace_path,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
        )
        payload = self._build_payload(
            request=request,
            command=command,
            completed_process=completed_process,
        )
        usage_metadata = payload.metadata.get("usage")
        usage_status = usage_metadata.get("status") if isinstance(usage_metadata, dict) else None
        logger.info(
            "agent_run_finished",
            exit_code=completed_process.returncode,
            stdout_length=len(completed_process.stdout),
            stderr_length=len(completed_process.stderr),
            token_usage_entries=len(payload.token_usage),
            usage_status=usage_status,
        )
        return AgentRunResult(payload=payload)

    def _build_command(self, *, request: AgentRunRequest, prompt: str) -> list[str]:
        command = [
            self.config.command,
            self.config.subcommand,
            "--dir",
            request.workspace_path,
            "--format",
            "json",
        ]

        model = self._resolve_model()
        if model is not None:
            command.extend(["--model", model])

        command.append(prompt)
        return command

    def _resolve_model(self) -> str | None:
        if self.config.provider_hint and self.config.model_hint:
            return f"{self.config.provider_hint}/{self.config.model_hint}"
        if self.config.model_hint:
            return self.config.model_hint
        return None

    def _build_prompt(self, request: AgentRunRequest) -> str:
        context = request.task_context
        parts = [
            f"workspace_path: {request.workspace_path}",
            f"flow_type: {context.flow_type.value}",
        ]

        if context.repo_url:
            parts.append(f"repo_url: {context.repo_url}")
        if context.repo_ref:
            parts.append(f"repo_ref: {context.repo_ref}")
        if context.branch_name:
            parts.append(f"branch_name: {context.branch_name}")
        if context.base_branch:
            parts.append(f"base_branch: {context.base_branch}")
        if context.instructions:
            parts.extend(["instructions:", context.instructions])

        tracker_context = context.tracker_context
        if tracker_context is not None:
            parts.extend(self._render_context_block("tracker_context", tracker_context))

        execution_context = context.execution_context
        if execution_context is not None:
            parts.extend(self._render_context_block("execution_context", execution_context))

        if context.current_feedback is not None:
            parts.extend(
                [
                    "current_feedback:",
                    f"comment_id: {context.current_feedback.comment_id}",
                    f"body: {context.current_feedback.body}",
                ]
            )

        if context.feedback_history:
            parts.append(f"feedback_history_count: {len(context.feedback_history)}")
            for index, entry in enumerate(context.feedback_history, start=1):
                parts.extend(
                    [
                        f"feedback_history[{index}].comment_id: {entry.feedback.comment_id}",
                        f"feedback_history[{index}].body: {entry.feedback.body}",
                    ]
                )

        return "\n".join(parts)

    def _render_context_block(self, label: str, context: TaskContext) -> list[str]:
        lines = [f"{label}:"]
        title = context.title
        lines.append(f"title: {title}")

        description = context.description
        if description:
            lines.append(f"description: {description}")

        acceptance_criteria = context.acceptance_criteria
        if acceptance_criteria:
            lines.append("acceptance_criteria:")
            lines.extend(f"- {criterion}" for criterion in acceptance_criteria)

        return lines

    def _build_payload(
        self,
        *,
        request: AgentRunRequest,
        command: list[str],
        completed_process: subprocess.CompletedProcess[str],
    ) -> TaskResultPayload:
        exit_code = completed_process.returncode
        stdout_parse = self._parse_stdout(completed_process.stdout)
        stdout_preview = stdout_parse.preview
        stderr_parse = self._parse_stderr(completed_process.stderr)
        stderr_preview = stderr_parse.preview
        details = self._build_details(stdout_preview=stdout_preview, stderr_preview=stderr_preview)
        execution_status = self._resolve_execution_status(
            exit_code=exit_code,
            stdout_parse=stdout_parse,
            stderr_parse=stderr_parse,
        )
        failure_message = self._build_failure_message(
            exit_code=exit_code,
            stdout_parse=stdout_parse,
            stderr_parse=stderr_parse,
        )
        runner_metadata: dict[str, object] = {
            "subcommand": self.config.subcommand,
            "profile": self.config.profile,
            "provider_hint": self.config.provider_hint,
            "model_hint": self.config.model_hint,
            "model_argument": self._resolve_model(),
            "api_key_env_var": self.config.api_key_env_var,
            "base_url_env_var": self.config.base_url_env_var,
        }
        metadata: dict[str, object] = {
            "runner_adapter": "cli",
            "runner": self.config.command,
            "flow_type": request.task_context.flow_type.value,
            "workspace_path": request.workspace_path,
            "request_metadata": dict(request.metadata),
            "command": command,
            "exit_code": exit_code,
            "stdout_preview": stdout_preview,
            "stdout_raw_preview": stdout_parse.raw_preview,
            "stdout_preview_source": stdout_parse.preview_source,
            "stdout_event_count": stdout_parse.event_count,
            "stdout_event_types": stdout_parse.event_types,
            "stdout_error_event": stdout_parse.error_event_metadata,
            "stderr_preview": stderr_preview,
            "stderr_analysis": stderr_parse.metadata,
            "usage": stdout_parse.usage_metadata,
            "runner_metadata": runner_metadata,
            "execution_status": execution_status,
        }
        if failure_message is not None:
            metadata["failure_message"] = failure_message
        return TaskResultPayload(
            summary=failure_message or self._build_summary(exit_code),
            details=details,
            branch_name=request.task_context.branch_name,
            pr_url=request.task_context.pr_url,
            token_usage=stdout_parse.token_usage,
            metadata=metadata,
        )

    def _build_summary(self, exit_code: int) -> str:
        if exit_code == 0:
            return "CLI agent run completed successfully."
        return f"CLI agent run failed with exit code {exit_code}."

    def _build_details(
        self, *, stdout_preview: str | None, stderr_preview: str | None
    ) -> str | None:
        details: list[str] = []
        if stdout_preview:
            details.extend(["stdout:", stdout_preview])
        if stderr_preview:
            details.extend(["stderr:", stderr_preview])
        if not details:
            return None
        return "\n".join(details)

    def _build_preview(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        limit = self.config.preview_chars
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."

    def _resolve_execution_status(
        self,
        *,
        exit_code: int,
        stdout_parse: _CliStdoutParseResult,
        stderr_parse: _CliStderrParseResult,
    ) -> str:
        if exit_code != 0 or stdout_parse.has_error_event or stderr_parse.is_error_like:
            return "failed"
        return "succeeded"

    def _build_failure_message(
        self,
        *,
        exit_code: int,
        stdout_parse: _CliStdoutParseResult,
        stderr_parse: _CliStderrParseResult,
    ) -> str | None:
        if exit_code != 0:
            return self._build_summary(exit_code)

        stdout_message = stdout_parse.error_message
        stderr_message = stderr_parse.preview

        if (
            stdout_parse.has_error_event
            and stdout_message
            and stderr_parse.is_error_like
            and stderr_message
        ):
            if stdout_message == stderr_message:
                return f"CLI agent run failed: {stdout_message}"
            return f"CLI agent run failed: {stdout_message} (stderr: {stderr_message})"
        if stdout_parse.has_error_event and stdout_message:
            return f"CLI agent run failed: {stdout_message}"
        if stdout_parse.has_error_event:
            return "CLI agent run failed: CLI emitted an error event."
        if stderr_parse.is_error_like and stderr_message:
            return f"CLI agent run failed: {stderr_message}"
        if stderr_parse.is_error_like:
            return "CLI agent run failed due to error output on stderr."
        return None

    def _parse_stdout(self, stdout: str) -> _CliStdoutParseResult:
        raw_preview = self._build_preview(stdout)
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            return _CliStdoutParseResult(
                preview=None,
                raw_preview=raw_preview,
                preview_source=None,
                token_usage=[],
                event_count=0,
                event_types=[],
                has_error_event=False,
                error_message=None,
                error_event_metadata={"status": "not_found"},
                usage_metadata={"status": "missing", "reason": "stdout_empty"},
            )

        events: list[dict[str, object]] = []
        event_types: list[str] = []
        text_parts: list[str] = []
        step_finish_part: dict[str, object] | None = None
        error_event: dict[str, object] | None = None
        error_message: str | None = None

        for index, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                return _CliStdoutParseResult(
                    preview=raw_preview,
                    raw_preview=raw_preview,
                    preview_source="raw_stdout",
                    token_usage=[],
                    event_count=len(events),
                    event_types=event_types,
                    has_error_event=False,
                    error_message=None,
                    error_event_metadata={"status": "not_found"},
                    usage_metadata={
                        "status": "malformed",
                        "reason": "invalid_json_line",
                        "line": index,
                        "error": str(exc),
                    },
                )

            if not isinstance(event, dict):
                return _CliStdoutParseResult(
                    preview=raw_preview,
                    raw_preview=raw_preview,
                    preview_source="raw_stdout",
                    token_usage=[],
                    event_count=len(events),
                    event_types=event_types,
                    has_error_event=False,
                    error_message=None,
                    error_event_metadata={"status": "not_found"},
                    usage_metadata={
                        "status": "malformed",
                        "reason": "non_object_event",
                        "line": index,
                    },
                )

            events.append(event)
            event_type = event.get("type")
            if isinstance(event_type, str):
                event_types.append(event_type)

            part = event.get("part")
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())

                if event_type == "step_finish":
                    step_finish_part = part

            if error_event is None and self._is_error_event(
                event, event_type=event_type, part=part
            ):
                error_event = event
                error_message = self._extract_error_message(event, part=part)

        preview = self._build_preview("\n".join(text_parts))
        preview_source = "text_events" if preview else None
        if preview is None:
            preview = raw_preview
            preview_source = "raw_stdout" if raw_preview else None

        error_event_metadata = self._build_error_event_metadata(error_event, error_message)

        if step_finish_part is None:
            return _CliStdoutParseResult(
                preview=preview,
                raw_preview=raw_preview,
                preview_source=preview_source,
                token_usage=[],
                event_count=len(events),
                event_types=event_types,
                has_error_event=error_event is not None,
                error_message=error_message,
                error_event_metadata=error_event_metadata,
                usage_metadata={"status": "missing", "reason": "step_finish_not_found"},
            )

        usage_parse_result = self._build_token_usage(step_finish_part)
        return _CliStdoutParseResult(
            preview=preview,
            raw_preview=raw_preview,
            preview_source=preview_source,
            token_usage=usage_parse_result.token_usage,
            event_count=len(events),
            event_types=event_types,
            has_error_event=error_event is not None,
            error_message=error_message,
            error_event_metadata=error_event_metadata,
            usage_metadata=usage_parse_result.metadata,
        )

    def _is_error_event(
        self,
        event: dict[str, object],
        *,
        event_type: object,
        part: dict[str, object] | None,
    ) -> bool:
        if event_type == "error":
            return True
        if part is not None and part.get("type") == "error":
            return True
        level = event.get("level")
        if isinstance(level, str) and level.lower() == "error":
            return True
        return False

    def _extract_error_message(
        self,
        event: dict[str, object],
        *,
        part: dict[str, object] | None,
    ) -> str | None:
        candidates: list[object] = []
        if part is not None:
            candidates.extend(
                [
                    part.get("text"),
                    part.get("message"),
                    part.get("error"),
                    part.get("code"),
                ]
            )
        candidates.extend([event.get("text"), event.get("message"), event.get("error")])

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return self._build_preview(candidate)
        return None

    def _build_error_event_metadata(
        self,
        error_event: dict[str, object] | None,
        error_message: str | None,
    ) -> dict[str, object]:
        if error_event is None:
            return {"status": "not_found"}

        metadata: dict[str, object] = {"status": "detected", "message": error_message}
        event_type = error_event.get("type")
        if isinstance(event_type, str):
            metadata["event_type"] = event_type
        level = error_event.get("level")
        if isinstance(level, str):
            metadata["level"] = level
        return metadata

    def _parse_stderr(self, stderr: str) -> _CliStderrParseResult:
        preview = self._build_preview(stderr)
        if preview is None:
            return _CliStderrParseResult(
                preview=None,
                is_error_like=False,
                metadata={"status": "empty", "error_like": False},
            )

        for line in stderr.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            reason = self._classify_stderr_line(normalized)
            if reason is not None:
                return _CliStderrParseResult(
                    preview=preview,
                    is_error_like=True,
                    metadata={"status": "error_like", "error_like": True, "reason": reason},
                )

        return _CliStderrParseResult(
            preview=preview,
            is_error_like=False,
            metadata={"status": "benign", "error_like": False},
        )

    def _classify_stderr_line(self, line: str) -> str | None:
        lowered = line.lower()
        if lowered.startswith("warning:") or lowered.startswith("warn:"):
            return None
        if lowered.startswith("note:"):
            return None
        if "traceback (most recent call last):" in lowered:
            return "python_traceback"
        if lowered.startswith("fatal:"):
            return "fatal_prefix"
        if re.search(r"\b[A-Za-z_][\w.]*Error\b", line):
            return "error_class"
        if re.search(r"\b[A-Za-z_][\w.]*Exception\b", line):
            return "exception_class"
        if "error:" in lowered:
            return "error_prefix"
        if lowered.startswith("failed:") or lowered.startswith("failed to "):
            return "failed_prefix"
        return None

    def _build_token_usage(self, step_finish_part: dict[str, object]) -> _CliUsageParseResult:
        tokens = step_finish_part.get("tokens")
        if not isinstance(tokens, dict):
            return _CliUsageParseResult(
                token_usage=[],
                metadata={"status": "missing", "reason": "tokens_not_found"},
            )

        cache = tokens.get("cache")
        if cache is None:
            cache = {}
        if not isinstance(cache, dict):
            return _CliUsageParseResult(
                token_usage=[],
                metadata={"status": "malformed", "reason": "cache_not_object"},
            )

        cost = step_finish_part.get("cost")
        if cost is None:
            return _CliUsageParseResult(
                token_usage=[],
                metadata={"status": "missing", "reason": "cost_not_found"},
            )

        try:
            usage = TokenUsagePayload(
                model=self._resolve_usage_model(),
                provider=self._resolve_usage_provider(),
                input_tokens=self._require_int(tokens.get("input"), field_name="tokens.input"),
                output_tokens=self._require_int(tokens.get("output"), field_name="tokens.output"),
                cached_tokens=self._require_int(
                    cache.get("read", 0), field_name="tokens.cache.read"
                ),
                estimated=False,
                cost_usd=self._require_decimal(cost, field_name="cost"),
            )
        except ValueError as exc:
            return _CliUsageParseResult(
                token_usage=[],
                metadata={
                    "status": "malformed",
                    "reason": "invalid_usage_fields",
                    "error": str(exc),
                },
            )

        return _CliUsageParseResult(
            token_usage=[usage],
            metadata={
                "status": "parsed",
                "model": usage.model,
                "provider": usage.provider,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cached_tokens": usage.cached_tokens,
                "cost_usd": str(usage.cost_usd),
                "reasoning_tokens": self._optional_int(tokens.get("reasoning")),
                "total_tokens": self._optional_int(tokens.get("total")),
                "cache_write_tokens": self._optional_int(cache.get("write")),
            },
        )

    def _resolve_usage_provider(self) -> str:
        return self.config.provider_hint or "unknown"

    def _resolve_usage_model(self) -> str:
        resolved_model = self._resolve_model()
        if resolved_model and "/" in resolved_model:
            _, _, model = resolved_model.partition("/")
            if model:
                return model
        return self.config.model_hint or resolved_model or "unknown"

    def _require_int(self, value: object, *, field_name: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")
        return value

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def _require_decimal(self, value: object, *, field_name: str) -> Decimal:
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be a non-negative decimal")

        if isinstance(value, int | float | str):
            try:
                decimal_value = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError(f"{field_name} must be a non-negative decimal") from exc
            if decimal_value < 0:
                raise ValueError(f"{field_name} must be a non-negative decimal")
            return decimal_value

        raise ValueError(f"{field_name} must be a non-negative decimal")


@dataclass(frozen=True, slots=True)
class _CliUsageParseResult:
    token_usage: list[TokenUsagePayload]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CliStdoutParseResult:
    preview: str | None
    raw_preview: str | None
    preview_source: str | None
    token_usage: list[TokenUsagePayload]
    event_count: int
    event_types: list[str]
    has_error_event: bool
    error_message: str | None
    error_event_metadata: dict[str, object]
    usage_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CliStderrParseResult:
    preview: str | None
    is_error_like: bool
    metadata: dict[str, object]


__all__ = ["CliAgentRunner", "CliAgentRunnerConfig", "LocalAgentRunner"]


def _runner_logger(request: AgentRunRequest, **fields: object):
    task = request.task_context.current_task.task
    return get_logger(__name__, component="agent_runner").bind(
        task_id=task.id,
        root_task_id=request.task_context.root_task.task.id,
        parent_id=task.parent_id,
        flow_type=request.task_context.flow_type.value,
        workspace_key=request.task_context.workspace_key,
        branch_name=request.task_context.branch_name,
        pr_external_id=request.task_context.pr_external_id,
        workspace_path=request.workspace_path,
        **fields,
    )
