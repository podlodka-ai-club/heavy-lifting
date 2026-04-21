# Task 24 Review 1

- Verdict: `changes_requested`

## Findings

1. `src/backend/protocols/agent_runner.py:3`
   `AgentRunnerProtocol` depends on `backend.services.agent_runner.AgentRunRequest` and `AgentRunResult`. This inverts the intended boundary: the protocol layer now imports concrete service-layer contract types instead of owning the runner contract itself. For a task whose goal is to introduce a reusable execution boundary, this makes replacement runners depend on the current service implementation module and weakens the abstraction. Move the request/result contract next to the protocol (or another neutral contract module) so implementations depend on the boundary, not vice versa.

2. `src/backend/composition.py:42` / `src/backend/composition.py:72`
   Composition still hardcodes `LocalAgentRunner()` and does not allow the runner to be selected or overridden through the registry the way tracker/SCM adapters are. That makes the new abstraction only partial: Worker 2 can call a protocol, but swapping in a real runner or a dedicated test double still requires editing composition code. Add runner factory wiring to `AdapterRegistry` (or equivalent injectable composition input) and cover it with a composition test.

## Checks

- Reviewed against `instration/tasks/task24.md`, `instration/project.md`, and `instration/tasks/task4.md`.
- Verified runner result normalization, token usage presence, local-flow behavior, and runtime wiring.
- Ran `uv run pytest tests/test_agent_runner.py tests/test_composition.py` — passed.

## Notes

- `LocalAgentRunner` looks acceptable as an MVP placeholder for local flows: it returns a normalized `TaskResultPayload`, preserves branch/PR linkage from `EffectiveTaskContext`, and always emits token usage enriched with estimated cost.
- Current tests cover happy-path execute and `pr_feedback` flows well, but they do not yet protect the boundary ownership and runner-injection gaps above.
