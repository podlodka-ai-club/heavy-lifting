# Triage And Routing

## Purpose

This page defines how the MVP triage step interprets a new tracker task and chooses the next business path.

It complements `docs/contracts/task-handoff.md`:

- this page defines triage signals, outcomes, and routing decisions;
- `docs/contracts/task-handoff.md` defines how those decisions are represented in `input_payload` and `result_payload`.

## Triage Responsibility

Triage is the mandatory first business step for every newly ingested tracker task.

In the MVP:

- `worker1` ingests the external task and creates the first executable task;
- `worker2` runs triage inside an `execute` task with `input_payload.action = triage`;
- triage decides whether the system should stop at a tracker reply or continue into another executable step.

Triage does not implement the task itself. It produces a business classification, an estimate, and a routing decision.

## MVP Business Task Kinds

The MVP supports these business task kinds:

- `research` - the system should inspect context and answer with findings or use research to prepare a later implementation step;
- `implementation` - the system should modify code, configuration, or repository state;
- `clarification` - the request is potentially valid, but required information is missing or ambiguous;
- `review_response` - a follow-up iteration driven by PR feedback rather than a new intake task;
- `rejected` - the request should not be taken into work in its current form.

For new tracker intake, triage normally classifies into `research`, `implementation`, `clarification`, or `rejected`. `review_response` is primarily produced by the PR feedback flow, not by first-intake triage.

## Triage Signals

Triage should rely on explicit signals rather than free-text intuition alone.

The MVP signal set is:

- `goal_defined` - the request states a concrete desired outcome;
- `repo_scope_present` - the repository or target code area is known when code work is requested;
- `acceptance_clear` - success conditions are explicit enough to evaluate completion;
- `code_change_requested` - the task explicitly asks for implementation work;
- `analysis_only_requested` - the task asks for investigation, explanation, or estimation without code changes;
- `missing_required_info` - a blocker exists because essential inputs are absent;
- `out_of_scope` - the request falls outside the MVP or current delivery boundaries;
- `unsafe_or_prohibited` - the requested action violates project rules or execution constraints.

Signals may be derived from tracker fields, normalized task metadata, or structured heuristics captured in `result_payload.classification.signals`.

Signal roles in the MVP are:

- `missing_required_info`, `out_of_scope`, and `unsafe_or_prohibited` can directly determine the routing outcome.
- `code_change_requested` and `analysis_only_requested` determine the primary work mode when no blocker wins first.
- `goal_defined`, `repo_scope_present`, and `acceptance_clear` are support signals: they raise confidence when present and may justify deriving `missing_required_info` when an implementation or research request is too underspecified to continue safely.

## Triage Outcomes

Triage must end in one of these routing outcomes:

- `route_to_research` - create a follow-up `execute` task with `input_payload.action = research`;
- `route_to_implementation` - create a follow-up `execute` task with `input_payload.action = implementation`;
- `reply_with_research_only` - create a downstream `deliver` task that returns findings without opening a longer execution branch;
- `reply_with_clarification` - ask for missing information; by default this can be a downstream `deliver` reply, but when Telegram clarification is required it enters the configured Telegram group flow instead;
- `reply_with_rejection` - create a downstream `deliver` task that explains why the task is not accepted;
- `reply_with_estimate_only` - create a downstream `deliver` task that returns an estimate or intake decision without further execution yet.

The "only estimate" scenario is a routing outcome, not a separate business task kind.

`reply_with_estimate_only` is used when the intake explicitly asks for estimation or take-in-work assessment, and triage has enough information to answer that question without launching research or implementation.

In the current MVP runtime, estimate-only intake is detected with an explicit text heuristic taken from the observed CLI verification flow: the normalized tracker title, description, or step instructions must contain both an estimate marker such as `story point`, `estimate only`, or `оцен...` and a no-code marker such as `do not modify code`, `without code changes`, or `не изменять код`.

When that heuristic matches, `worker2` still runs the agent once to produce the estimate content, but the pipeline skips branch creation, commit, push, and PR creation and proceeds directly to a downstream `deliver` task.

Telegram clarification is the full-cycle clarification path for large or unclear tasks. `worker2` detects it from structured `TaskResultPayload.metadata` when any of these signals are present:

- `routing.outcome == "reply_with_clarification"`;
- `telegram.required == true`;
- a detected story point estimate above `TELEGRAM_STORY_POINTS_THRESHOLD`.

For this path `worker2` still runs the agent once, but skips branch creation, commit, push, PR creation, and downstream `deliver`. It posts the clarification question to the configured Telegram group and creates a local pending `execute` task with `role = "telegram_clarification"`. Completion requires a later explicit confirmation in Telegram after the backend posts its final proposed summary and subtask decomposition.

## Routing Matrix

The MVP routing matrix is:

| Primary signals                                                         | Classification   | Outcome                    | Next task            |
| ----------------------------------------------------------------------- | ---------------- | -------------------------- | -------------------- |
| `missing_required_info`, Telegram not required                          | `clarification`  | `reply_with_clarification` | downstream `deliver` |
| `missing_required_info`, Telegram required or story points above threshold | `clarification` | `reply_with_clarification` | `execute` with `role=telegram_clarification` |
| `unsafe_or_prohibited` or `out_of_scope`                                | `rejected`       | `reply_with_rejection`     | downstream `deliver` |
| explicit estimate-only request and enough context to assess now         | `research`       | `reply_with_estimate_only` | downstream `deliver` |
| `analysis_only_requested` and enough context to answer now              | `research`       | `reply_with_research_only` | downstream `deliver` |
| `analysis_only_requested` and more investigation is needed              | `research`       | `route_to_research`        | follow-up `execute`  |
| `code_change_requested` and inputs are clear enough to proceed directly | `implementation` | `route_to_implementation`  | follow-up `execute`  |
| `code_change_requested` but extra investigation is needed before coding | `research`       | `route_to_research`        | follow-up `execute`  |

When multiple signals conflict, triage resolves them in this priority order:

1. rejection conditions;
2. clarification blockers;
3. research-only requests;
4. implementation requests.

Rejection wins over clarification when both apply. If a request is clearly prohibited or out of scope, triage should reject it rather than ask for more detail.

## Result Payload Expectations

The triage step must populate at least:

- `classification.task_kind`
- `classification.signals`
- `estimate.story_points`
- `estimate.complexity`
- `estimate.can_take_in_work`
- `routing.next_task_type`
- `routing.next_role`
- `routing.create_followup_task`
- `delivery.tracker_status`
- `delivery.comment_body`

If triage stops at a tracker reply, `routing.next_task_type` should be `deliver`, `routing.next_role` should be `deliver`, and `routing.create_followup_task` should be `true`.

If triage routes to another executable step, `routing.next_task_type` should be `execute`, `routing.next_role` should reflect the next action, and `delivery` should still contain enough tracker-facing context for later delivery if needed.

If triage returns `reply_with_estimate_only`, `classification.task_kind` should remain `research` for MVP purposes because the system is still answering an analysis-style intake without entering a code-execution branch.

If triage returns a Telegram clarification route, the result payload should include the question and, when known, a draft decomposition under `metadata.telegram`, for example `metadata.telegram.question`, `metadata.telegram.required`, and `metadata.telegram.subtasks`. The backend may still build a deterministic proposal from the Telegram transcript if no structured subtasks are supplied.

## MVP Limits

- Triage is not a product-prioritization engine.
- Triage does not split one intake task into multiple parallel execution branches.
- Triage does not make permanent roadmap decisions; it chooses the next operational step only.
- Triage does not bypass the structured contract by encoding decisions only in `summary` or `details`.
