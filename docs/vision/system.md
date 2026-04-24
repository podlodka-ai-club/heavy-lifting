# System Vision

## Purpose

Heavy Lifting is an MVP backend orchestrator that accepts implementation work from a tracker, coordinates research and coding execution through external agents, manages pull request loops, and delivers results back to the tracker with a predictable workflow.

The system exists to reduce manual coordination overhead between task intake, execution, review feedback, and result delivery while preserving a clear audit trail of what happened for each task.

## Target State

The target system is a reliable orchestration backend that:

- receives well-structured work requests from an upstream tracker;
- turns them into explicit internal task stages with durable state transitions;
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

### Triage

The orchestration layer normalizes the incoming request, determines the next executable steps, and fans out internal work such as fetch, execute, and deliver tasks. Triage is responsible for shaping the pipeline, not for performing the implementation itself.

### Research

Before code changes are applied, the runner may need to inspect repository context, read supporting documentation, and collect constraints from the task payload. Research produces enough structured context for implementation without trying to become a general knowledge system.

### Implementation

The runner prepares a repository workspace, applies the requested changes, runs the required project checks, and produces artifacts such as branch metadata, commit information, and candidate pull request content.

### PR Feedback

If a pull request receives review comments or requested changes, the orchestrator creates a follow-up task linked to the original implementation thread. The same branch and PR remain the center of the iteration so the history stays continuous.

### Delivery

After execution completes, the orchestrator reports the result back to the tracker. Delivery includes status, a concise summary of what changed, links to branches or pull requests when available, and failure context when execution does not succeed.

## MVP Scope

The MVP intentionally stays narrow:

- one backend service stack built with Flask and PostgreSQL;
- explicit worker pipeline for intake, execution, and delivery;
- protocol boundaries around tracker and SCM integrations;
- local development support through `MockTracker` and `MockScm`;
- durable persistence limited to `tasks` and `token_usage`;
- support for implementation and PR feedback loops, with enough metadata to continue follow-up work.

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
