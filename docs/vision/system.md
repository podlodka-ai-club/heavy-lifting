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
- delivers status, artifacts, and outcome summaries back to the tracker;
- tracks token usage and other execution metadata needed for operational visibility.

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

For new intake, triage may route the task into research, route it into implementation, or stop with a tracker reply such as clarification, rejection, research-only output, or estimate-only output.

### Research

Before code changes are applied, the runner may need to inspect repository context, read supporting documentation, and collect constraints from the task payload. Research produces enough structured context for implementation without trying to become a general knowledge system.

### Implementation

The runner prepares a repository workspace, applies the requested changes, runs the required project checks, and produces artifacts such as branch metadata, commit information, and candidate pull request content.

For CLI-backed execution, the orchestrator runs `opencode run --format json` and extracts the final `step_finish` usage block into the normalized `token_usage` records. Human-readable delivery details still come from the streamed text events, while missing or malformed usage data remains explicit in execution metadata instead of silently fabricating token rows. `worker2` treats the run as failed when the CLI exits non-zero, when JSON stdout emits an explicit error event, or when stderr contains clearly error-like diagnostics even if the process exits `0`; in all of those cases it records the failed result on the task and stops before commit, push, PR, or downstream delivery side effects.

Estimate-only intake is the current exception: `worker2` still runs the agent to obtain the estimate text, but it skips branch, commit, push, and PR side effects and hands the result straight to `worker3` for tracker delivery.

### PR Feedback

If a pull request receives review comments or requested changes, the orchestrator creates a follow-up task linked to the original implementation thread. The same branch and PR remain the center of the iteration so the history stays continuous.

Follow-up feedback enters the system through the event-ingestion path rather than as a new top-level intake task.

### Delivery

After execution completes, the orchestrator reports the result back to the tracker. Delivery includes status, a concise summary of what changed, links to branches or pull requests when available, and failure context when execution does not succeed. Delivery is driven by structured handoff data rather than free-text parsing.

Any upstream step that produces tracker-ready `delivery` instructions may trigger a downstream `deliver` task. Delivery is therefore not limited to code implementation outcomes.

## Contract Model

The orchestration pipeline relies on a stable handoff contract documented in `docs/contracts/task-handoff.md`.

- `context` carries stable task facts and source material.
- `input_payload` carries the current-step command.
- `result_payload` carries machine-readable outcome, routing, delivery instructions, and generated artifacts.

This separation keeps worker boundaries explicit and allows triage, implementation, PR feedback, and delivery to reuse one contract model.

The triage-specific signal set and routing matrix are documented in `docs/contracts/triage-routing.md`.

The follow-up event taxonomy, normalization rules, and monitor responsibilities are documented in `docs/contracts/event-ingestion.md`.

## Runtime Observability

Runtime logs are emitted as structured JSON events from the API, workers, and agent runner boundary.

- Stable event names cover intake, worker pickup, workspace preparation, agent execution, result handoff, and tracker delivery.
- Correlation fields such as `task_id`, `root_task_id`, `workspace_key`, `branch_name`, and `pr_external_id` make it possible to follow one execution thread across workers.
- Logs are intended for operational tracing only; durable task routing and delivery decisions still flow through `context`, `input_payload`, and `result_payload`.

The read-only factory API exposes the current pipeline view through `GET /factory`. It aggregates existing `tasks` rows into the ordered stations `fetch`, `execute`, `pr_feedback`, and `deliver`, reports WIP and queue/active/failed counts, and names the current bottleneck by largest WIP. It does not fabricate throughput, transition history, worker capacity, rework-loop, or business-kind analytics that are not present in the MVP data model.

## MVP Scope

The MVP intentionally stays narrow:

- one backend service stack built with Flask and PostgreSQL;
- explicit worker pipeline for intake, execution, and delivery;
- protocol boundaries around tracker and SCM integrations;
- local development support through `MockTracker` and `MockScm`;
- durable persistence for orchestration tasks, token usage, and seeded default agent prompts;
- machine-readable OpenAPI schema through `GET /openapi.json`;
- read-only operational factory view through `GET /factory`;
- prompt-management API for listing stored agent prompts, reading one prompt, and updating prompt content;
- support for implementation and PR feedback loops, with enough metadata to continue follow-up work.
- estimate-only delivery-only routing that avoids SCM side effects while preserving the same execute-to-deliver pipeline.
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
