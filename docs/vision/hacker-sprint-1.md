# Hacker Sprint 1: source context

## Source

- Notion: `https://www.notion.so/Hacker-Sprint-1-33f2db4c860e8064a657e199b4578f66`
- Page title: `Hacker Sprint #1: Фабрика фичей`
- Extracted on: `2026-04-24`

## Purpose

Hacker Sprint 1 is framed as a two-week practical sprint where each team builds an agent orchestrator. The expected result is not a universal production platform, but a working minimum pipeline that can take a task, run it through an agent workflow, and bring the result to a pull request.

This repository implements that sprint idea as an MVP backend orchestrator with Flask, PostgreSQL, workers, tracker and SCM boundaries, execution flow, PR feedback handling, delivery back to the tracker, and token cost tracking.

## Sprint Theme

The core product idea:

- take a task from a backlog;
- run it through a chosen agent workflow;
- produce code changes;
- bring the result to a pull request.

The sprint explicitly allows teams to choose their own technical stack, models, agents, libraries, and workflow details. The important constraint is that the project must be demonstrable on a real repository and must contain the team's own contribution.

## Minimum Requirements

For the orchestrator to count as complete, it must be able to:

- take a task from a source automatically, such as a tracker or queue;
- write code through an agent;
- create a pull request with the result;
- detect when something went wrong and send the work back for correction;
- work on a real repository so the result can be shown in a demo.

## Optional Extension Blocks

The Notion page lists these optional areas as useful extensions beyond the baseline:

| Extension | Description |
| --- | --- |
| Task completeness check | The system validates whether the task has enough requirements and asks the user for missing input when needed. |
| Decomposition | Large or parallelizable tasks are split into smaller parts and assigned to separate agents. |
| Merge conflict resolution | On merge conflicts, the orchestrator starts an agent that resolves them. |
| Agentic code review | The orchestrator runs its own review and decides whether a PR can be merged based on heuristics. |
| Strategy selection by task type | The orchestrator distinguishes task classes, such as feature work and bugfixes, and chooses a fitting pipeline. |
| Code verification and quality gates | Linters, unit tests, or stronger checks validate the produced code. |
| Observability | The system logs pipeline stages, errors, and request costs. |
| Parallel implementations | The orchestrator generates several approaches, compares them, and picks the best one. |
| Long-term memory | The system accumulates experience between sessions and reuses it in later tasks. |

## Mapping To Current MVP Architecture

The current MVP scope maps the sprint requirements as follows:

| Sprint requirement | Current repository concept |
| --- | --- |
| Take a task from a source | `TrackerProtocol`, `MockTracker`, `POST /tasks/intake`, Worker 1 fetch/intake flow |
| Write code through an agent | Worker 2, `AgentRunnerProtocol`, execution task context |
| Create a PR | `ScmProtocol`, `MockScm`, branch and PR fields on `tasks` |
| Send work back for correction | PR feedback polling, `pr_feedback` child tasks, reuse of branch and PR |
| Work on a real repository | SCM workspace abstraction with `repo_url`, `repo_ref`, `workspace_key`, and branch metadata |
| Track cost and pipeline state | `token_usage`, task statuses, stats API, logging expectations |

## Architecture Notes

The Notion page is a sprint brief, not a full architecture document. It does not define a concrete database schema, endpoint contract, worker split, or module layout. Those details are owned by this repository's project specification and durable docs.

The important architectural implication from the sprint brief is the closed loop:

1. Intake or fetch a task.
2. Build execution context.
3. Run an agent workflow.
4. Persist results, token usage, and errors.
5. Create or update a PR for code changes.
6. Poll review feedback.
7. Convert feedback into follow-up work.
8. Deliver the final result back to the tracker.

The MVP should stay biased toward this loop instead of growing into a general agent platform too early.

## Current Scope Decisions

The repository currently treats these sprint ideas as MVP baseline:

- tracker intake and fetch;
- coding execution;
- PR creation/update;
- PR feedback converted to follow-up tasks;
- delivery back to tracker;
- observability through logs, task statuses, stats, token usage, and costs.

The repository currently treats these sprint ideas as future extensions unless a task explicitly promotes them into scope:

- automatic task completeness clarification;
- automatic task decomposition across multiple agents;
- merge conflict resolution agent;
- autonomous merge decision after agentic review;
- multiple task-type strategies;
- parallel implementation tournament;
- long-term memory across tasks.
