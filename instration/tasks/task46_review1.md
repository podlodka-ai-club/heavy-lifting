# Task Review

## Metadata

- Task ID: `task46`
- Review Round: `1`
- Reviewer: `REVIEW (gpt-5.4)`
- Review Date: `2026-04-21`
- Status: `changes_requested`

## Scope Reviewed

- `instration/tasks/task46.md`
- `instration/tasks/task46_progress.md`
- `src/backend/services/agent_runner.py`
- `src/backend/composition.py`
- `src/backend/settings.py`
- `tests/test_agent_runner.py`
- `tests/test_composition.py`
- `tests/test_settings.py`
- `tests/test_execute_worker.py`
- `tests/test_orchestration_e2e.py`

## Findings

- `src/backend/services/agent_runner.py:140` builds a command that does not match the real `opencode run` CLI contract. In the current environment `opencode run --help` shows positional `message..`, `--model provider/model`, `--agent`, and `--dir`, but there are no `--profile` or `--provider` flags. The implementation currently sends the prompt via stdin and emits `--profile backend --provider openai --model gpt-5.4`, so the runner will fail against the real CLI instead of running the task.
- The tests lock in the incorrect contract instead of protecting the real one. `tests/test_agent_runner.py:166` and `tests/test_composition.py:98` assert the unsupported flags and never verify how the prompt is passed to `opencode run`, so the task's main deliverable can be green while the real integration is broken.

## Risks

- If merged as is, switching `AGENT_RUNNER_ADAPTER=cli` will route execute tasks into a broken subprocess invocation and produce deterministic task failures for all real CLI runs.
- The current config surface (`provider_hint`, `model_hint`, `profile`) bakes in a CLI mapping that does not correspond to `opencode run`, which will make the next integration tasks harder and increase churn in settings/composition.

## Required Changes

- Rework `CliAgentRunner` to follow the actual `opencode run` invocation contract: pass the prompt as the command message (or another documented input mechanism), map model selection to the supported flag shape, and remove or rename unsupported options.
- Update tests so they validate the real command line contract for `opencode run` rather than the current synthetic one.
- Re-run the relevant test suite after the command contract is corrected.

## Final Decision

- `changes_requested`

## Notes

- Related regression suite currently passes: `uv run pytest tests/test_agent_runner.py tests/test_composition.py tests/test_settings.py tests/test_execute_worker.py tests/test_orchestration_e2e.py`.
- The main blocker is functional correctness of the real CLI integration, not coverage breadth.

## Follow-Up

- After fixes, create `instration/tasks/task46_review2.md` for the next review round.
