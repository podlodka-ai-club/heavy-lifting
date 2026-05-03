# System Vision

## Purpose

Heavy Lifting is an MVP backend orchestrator that accepts implementation work from a tracker, coordinates research and coding execution through external agents, manages pull request loops, and delivers results back to the tracker with a predictable workflow.

The system exists to reduce manual coordination overhead between task intake, execution, review feedback, and result delivery while preserving a clear audit trail of what happened for each task.

The product direction comes from Hacker Sprint 1: build an agent orchestrator that takes a backlog task, runs it through a selected workflow, and brings the result to a pull request. The distilled sprint brief lives in `docs/vision/hacker-sprint-1.md`, and the companion Excalidraw architecture scheme lives in `docs/vision/architecture-scheme.md`.

## Target State

The target system is a reliable orchestration backend that:

- receives well-structured work requests from an upstream tracker;
- turns them into explicit internal task stages with durable state transitions;
- classifies each task into a business-level execution path before work begins;
- prepares a reproducible workspace and runs an external coding agent or local runner;
- creates or updates pull requests through an SCM boundary;
- processes follow-up review feedback as first-class work;
- processes estimate-only tracker-thread follow-up comments as first-class work;
- delivers status, artifacts, and outcome summaries back to the tracker;
- tracks token usage, root-task revenue, and other execution metadata needed for operational and MVP economics visibility.

## Primary Actors

- Tracker operator: creates work items, observes status, and receives final delivery.
- Orchestrator API: accepts intake requests and exposes runtime state.
- Worker services: advance tasks through the orchestration pipeline.
- Coding agent runner: performs research and implementation work inside a prepared workspace.
- SCM platform: hosts branches, commits, pull requests, and review feedback.
- Reviewer: leaves PR feedback that may trigger a follow-up iteration.

## Key Scenarios

### Intake

The tracker submits a new task to the orchestrator through the intake API. The orchestrator validates the payload, records the incoming request, and creates the initial internal task state needed for downstream processing.

For tracker flows that persist estimate-selection metadata, the orchestrator may also query previously estimated tracker tasks, select one eligible small parent task through explicit metadata, create a fresh tracker subtask that re-enters the same intake path as a normal executable request, and mark the selected parent as taken in work in the tracker so it is not selected again.

### Triage

The orchestration layer normalizes the incoming request, determines the business task kind, and fans out internal work such as fetch, execute, and deliver tasks. In the MVP, triage itself runs as an `execute` step owned by `worker2`, while `worker1` remains responsible for ingestion and task creation. Triage is responsible for shaping the pipeline, not for performing the implementation itself.

Every new tracker intake starts with a triage execute task: `worker1` sets `input_payload.action = "triage"` on the first execute it creates, and `worker2` runs the triage agent before any code-touching path. Triage produces a Story Point estimate from the fixed set `1/2/3/5/8/13`. Story Points `1/2/3` route into a sibling implementation execute under the same fetch task; Story Points `5/8/13` stop at a tracker reply (RFI, decomposition plan, or system-design escalation) and wait for the tracker user to edit the issue before a new triage cycle starts.

For new intake, triage may route the task into research, route it into implementation, or stop with a tracker reply such as clarification, rejection, research-only output, or estimate-only output.

### Research

Before code changes are applied, the runner may need to inspect repository context, read supporting documentation, and collect constraints from the task payload. Research produces enough structured context for implementation without trying to become a general knowledge system.

### Implementation

The runner prepares a repository workspace, applies the requested changes, runs the required project checks, and produces artifacts such as branch metadata, commit information, and candidate pull request content.

For CLI-backed execution, the orchestrator runs `opencode run --format json` and extracts the final `step_finish` usage block into the normalized `token_usage` records. Human-readable delivery details still come from the streamed text events, while missing or malformed usage data remains explicit in execution metadata instead of silently fabricating token rows. `worker2` treats the run as failed when the CLI exits non-zero, when JSON stdout emits an explicit error event, or when stderr contains clearly error-like diagnostics even if the process exits `0`; in all of those cases it records the failed result on the task and stops before commit, push, PR, or downstream delivery side effects. In single-repo deployments, when an `execute` task omits `workspace_key`, `worker2` now derives a deterministic fallback from the tracker lineage before SCM sync and persists it so later polling and child tasks reuse the same workspace identity. The CLI prompt now includes an explicit runtime contract: normal `execute` and `pr_feedback` runs must edit files but must not perform `git commit`, `git push`, or PR creation on their own because these publish side effects are backend-owned. As a resilience fallback, when SCM commit handling finds no uncommitted diff, backend commit handling reuses current `HEAD` only when it is a descendant of the pre-run `HEAD` (that is, the branch truly advanced during the run); otherwise the step still fails with `no changes to commit`.

Estimate-only intake is the current exception: new top-level tracker tasks are persisted by `worker1` with an explicit execute mode (`input_payload.metadata.estimate_only = true`). `worker2` and the CLI prompt contract prefer that explicit mode first (while keeping legacy phrasing heuristics as fallback), skip branch/commit/push/PR side effects, and hand the result straight to `worker3` for tracker delivery. For CLI runs, the estimate contract now requires one machine-readable line `ESTIMATE_JSON: {"story_points": <int>, "rationale": "<non-empty>"}` (optional human explanation may follow). Before handoff, `worker2` normalizes both tracker comment text and structured estimate metadata (`story_points`, `can_take_in_work`, `rationale`) so delivery and later selection use a stable contract while still failing fast when required estimate fields cannot be derived.

The same estimate-only branch now supports the first tracker-thread conversation loop. `worker1` polls new tracker comments on eligible estimate-only execute threads, ignores orchestrator-authored comments, stores a per-thread cursor, and creates one `tracker_feedback` child task per new actionable comment. `worker2` answers that child without SCM side effects, and `worker3` posts the reply back into the same tracker thread. When estimate-thread lineage misses `workspace_key`, `worker2` derives a deterministic fallback workspace identity from tracker lineage so reply generation can proceed. For estimate-thread follow-up replies, `worker2` reuses normalized estimate metadata from the ancestor execute result when present, so the follow-up answer can focus on explanation instead of re-emitting `story_points`/`rationale`. During estimate-only delivery, `worker3` also persists normalized `metadata.estimate` back to the tracker record while preserving existing `metadata.selection`.

### PR Feedback

If a pull request receives review comments or requested changes, the orchestrator creates a follow-up task linked to the original implementation thread. The same branch and PR remain the center of the iteration so the history stays continuous.

Follow-up feedback enters the system through the event-ingestion path rather than as a new top-level intake task.

### Agent Retro Feedback

After `execute` and `pr_feedback` agent runs, the runner may include optional structured feedback in `TaskResultPayload.metadata["agent_retro"]`. The accepted v1 shapes are either a list of entries or an object with an `entries` list. Each valid entry is append-only, has `source: "agent"` assigned by the backend, a required slug `tag`, required `message`, `category` defaulting to `other`, `severity` defaulting to `info`, optional `suggested_action`, and optional JSON `metadata`. The persisted row also snapshots `task_id`, `root_id`, `task_type`, nullable `role`, and the current task `attempt`.

Missing retro feedback has no effect on task execution. Invalid retro feedback is logged as a warning and ignored so that retrospective collection cannot break implementation or PR feedback processing.

The read-only retro API exposes the collected data:

- `GET /retro/entries` returns raw persisted feedback with optional `task_type`, `tag`, `severity`, `source`, and `limit` filters.
- `GET /retro/tags` aggregates entries by tag and returns total count, severity counts, first and last seen timestamps, and affected task count.

This v1 slice does not run a separate analyzer agent, infer embeddings, merge or split tags, create actions from tags, or provide a frontend visualization.

### Delivery

After execution completes, the orchestrator reports the result back to the tracker. Delivery includes status, a concise summary of what changed, links to branches or pull requests when available, and failure context when execution does not succeed. Delivery is driven by structured handoff data rather than free-text parsing.

Any upstream step that produces tracker-ready `delivery` instructions may trigger a downstream `deliver` task. Delivery is therefore not limited to code implementation outcomes.

## Contract Model

The orchestration pipeline relies on a stable handoff contract documented in `docs/contracts/task-handoff.md`.

- `context` carries stable task facts and source material.
- `input_payload` carries the current-step command.
- `result_payload` carries machine-readable outcome, routing, delivery instructions, and generated artifacts.

This separation keeps worker boundaries explicit and allows triage, implementation, PR feedback, tracker feedback, and delivery to reuse one contract model.

The triage-specific signal set and routing matrix are documented in `docs/contracts/triage-routing.md`.

The follow-up event taxonomy, normalization rules, and monitor responsibilities are documented in `docs/contracts/event-ingestion.md`.

## Runtime Observability

Runtime logs are emitted as structured JSON events from the API, workers, and agent runner boundary.

- Stable event names cover intake, worker pickup, workspace preparation, agent execution, result handoff, and tracker delivery.
- Correlation fields such as `task_id`, `root_task_id`, `workspace_key`, `branch_name`, and `pr_external_id` make it possible to follow one execution thread across workers.
- Logs are intended for operational tracing only; durable task routing and delivery decisions still flow through `context`, `input_payload`, and `result_payload`.

The read-only factory API exposes the current pipeline view through `GET /factory`. It aggregates existing `tasks` rows into the ordered stations `fetch`, `execute`, `pr_feedback`, `tracker_feedback`, and `deliver`, reports WIP and queue/active/failed counts, and names the current bottleneck by largest WIP. It does not fabricate throughput, transition history, worker capacity, rework-loop, or business-kind analytics that are not present in the MVP data model.

The operator API also exposes `POST /tasks/{task_id}/restart` for best-effort local retries of failed worker-owned tasks. It accepts only `failed` tasks of type `execute`, `pr_feedback`, `tracker_feedback`, or `deliver`, clears the task's stored failure/result state, and requeues the same row back to `new` without changing its `attempt` counter until a worker picks it up again. Workspace, branch, and PR context stay on the task so the next run can reuse the same execution thread. Because the original failure may have happened after a partial external side effect, a restart may repeat tracker, git, or PR actions and should be used as an operator-controlled retry rather than as an exactly-once guarantee.

The economics API exposes the current money view through `GET /economics`, `POST /economics/mock-revenue`, and `PUT /economics/revenue/{root_task_id}`. It treats a root chain as closed when the chain has a successful `deliver` task and uses the first such `deliver.updated_at` as `closed_at`. Revenue is stored once per root in `task_revenue`, token cost is summed from `token_usage` across all tasks in the closed root chain, and aggregate profit is reported as displayed revenue minus displayed token cost. `GET /economics` defaults to the last 30 days when no period is supplied. Known gaps such as infra cost, runner hours, external accounting import, and retry waste remain explicit rather than being estimated silently.

## MVP Scope

The MVP intentionally stays narrow:

- one backend service stack built with Flask and PostgreSQL;
- explicit worker pipeline for intake, execution, and delivery;
- protocol boundaries around tracker and SCM integrations;
- local development support through `MockTracker` and `MockScm`;
- durable persistence for orchestration tasks, token usage, seeded default agent prompts, and non-secret runtime settings;
- durable persistence for root-task revenue in `task_revenue`;
- machine-readable OpenAPI schema through `GET /openapi.json`;
- read-only operational factory view through `GET /factory`;
- MVP economics view through `GET /economics`, deterministic mock revenue generation, and manual expert/external revenue upsert;
- append-only agent retro feedback persistence plus read-only `/retro/entries` and `/retro/tags`;
- prompt-management API for listing stored agent prompts, reading one prompt, and updating prompt content;
- runtime-settings API for listing and updating persisted non-secret operational settings;
- authenticated operator API for restarting a failed worker-owned local task by id;
- authenticated operator API support for posting a manual tracker comment to an existing task thread by local task id;
- support for implementation and PR feedback loops, with enough metadata to continue follow-up work.
- estimate-only delivery-only routing that avoids SCM side effects while preserving the same execute-to-deliver pipeline.
- support for estimate-only tracker-comment follow-up loops that stay inside the original tracker thread and avoid SCM artifacts.
- selection of previously estimated small tracker tasks into one executable subtask through the tracker boundary contract, with duplicate parent selection blocked through tracker metadata.

## Non-Goals

The MVP does not aim to provide:

- a full multi-tenant workflow platform;
- broad project management features or a replacement for the upstream tracker;
- autonomous product planning or prioritization;
- generalized long-term knowledge storage inside the worklog;
- complex analytics, billing, or policy engines;
- deep SCM portability beyond the needs of the current protocol abstraction.

## Success Criteria

The system is successful when:

- a task can travel from intake to delivery through the defined stages without manual glue work;
- the state of each task is observable through the API and persisted task records;
- implementation and PR feedback iterations reuse the same operational model;
- local development can exercise the pipeline with mock integrations;
- durable system knowledge stays current in `docs/`, while task-local memory lives in `worklog/`;
- contributors can understand the system scope and workflow from repository documentation without relying on tribal knowledge.
