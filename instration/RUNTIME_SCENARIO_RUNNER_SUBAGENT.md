# Runtime Scenario Runner Subagent

## Purpose

Use this subagent when the main agent needs a real execution of the MVP pipeline in a temporary environment and wants a structured result back instead of manually orchestrating the shell steps itself.

This subagent is intended for scenario-based runtime verification, such as:

- intake -> execute -> deliver runs with `AGENT_RUNNER_ADAPTER=cli`;
- estimate-only scenarios;
- failure-path scenarios;
- verification of token accounting, payload delivery, commit/PR side effects, and runtime logs.

## Operating Rules

- The subagent runs the selected scenario end to end.
- The subagent should prefer disposable resources: temporary database files, temporary workspace copies, temporary log files, and disposable ports.
- The subagent must not silently choose between incompatible interpretations; if the scenario contract is incomplete, it should return `blocked` with the missing field.
- The subagent should not modify repository source files unless the caller explicitly asks for code changes. By default this subagent is execution-only.
- The subagent should clean up background processes when the scenario finishes or fails.

## Required Input Contract

The caller should provide a prompt that includes all of the following sections.

### 1. Scenario Identity

- `scenario_id`: stable short id such as `cli-estimate-only` or `cli-nonzero-exit`
- `goal`: what the scenario is validating

### 2. Environment Setup

- `workspace_strategy`: usually `disposable_copy`
- `database`: temporary path and bootstrap command
- `port`: preferred port or port-selection rule
- `env`: required environment variables
- `startup`: exact command used to launch the runtime
- `healthcheck`: how to determine that the service is ready

### 3. Scenario Execution

- `steps`: ordered actions to perform after startup
- `inputs`: payloads, prompts, endpoints, or files used by the scenario
- `assertions`: what must be checked in API responses, logs, stored data, or filesystem artifacts

### 4. Artifact Collection

- `collect`: which files, logs, database rows, or command outputs must be inspected
- `preserve_artifacts`: whether to keep temporary paths for later manual inspection

### 5. Output Format

- the final response must use the normalized report described below

## Normalized Output Contract

The subagent should return one final structured report in plain text with these fields.

- `status`: `passed`, `failed`, or `blocked`
- `scenario_id`
- `goal`
- `environment`: key paths, port, adapter, and startup command used
- `executed_steps`: concise list of what actually ran
- `observed_result`: the main runtime outcome
- `expected_vs_actual`: explicit pass/fail comparison against the assertions
- `artifacts`: paths to logs, temp database, temp workspace, and any saved outputs
- `key_evidence`: the most important payload snippets, log events, or DB observations
- `gaps_or_risks`: follow-up issues or ambiguities discovered during the run

If the run is blocked, the report should clearly state which required input was missing or which external dependency failed.

## Recommended Prompt Template

Use this template when launching the subagent through the general-purpose task runner.

```text
Run a real MVP pipeline scenario and return only a structured execution report.

Scenario identity:
- scenario_id: <id>
- goal: <what this scenario validates>

Environment setup:
- workspace_strategy: <disposable_copy|in_place_if_explicitly_allowed>
- database:
  - path: <temp db path>
  - bootstrap: <command>
- port: <port or rule>
- env:
  - KEY=value
- startup:
  - command: <runtime start command>
- healthcheck:
  - <how to verify readiness>

Scenario execution:
- steps:
  1. <step>
  2. <step>
- inputs:
  - <request payload, prompt, or fixture>
- assertions:
  - <expected API/log/db/runtime outcome>

Artifact collection:
- collect:
  - <logs>
  - <db rows>
  - <stored payloads>
- preserve_artifacts: <yes|no>

Constraints:
- Use disposable resources unless the prompt explicitly allows otherwise.
- Do not modify repository source files.
- Clean up background processes before finishing.
- If any required field is missing, return blocked instead of guessing.

Output:
- Return only one final report with: status, scenario_id, goal, environment, executed_steps, observed_result, expected_vs_actual, artifacts, key_evidence, gaps_or_risks.
```

## Example Scenario

```text
Scenario identity:
- scenario_id: cli-estimate-only
- goal: verify that a real `opencode` run is invoked through the full pipeline and determine whether token usage is persisted

Environment setup:
- workspace_strategy: disposable_copy
- database:
  - path: /tmp/heavy_lifting_cli_runtime.sqlite3
  - bootstrap: DATABASE_URL=sqlite:////tmp/heavy_lifting_cli_runtime.sqlite3 uv run make bootstrap-db
- port: 8010
- env:
  - APP_PORT=8010
  - DATABASE_URL=sqlite:////tmp/heavy_lifting_cli_runtime.sqlite3
  - AGENT_RUNNER_ADAPTER=cli
- startup:
  - command: uv run python -m src.backend.demo
- healthcheck:
  - GET /health returns 200

Scenario execution:
- steps:
  1. Start the demo in the background and wait for healthcheck success.
  2. POST an estimate-only intake task.
  3. Inspect logs and persisted task/token usage data.
- inputs:
  - intake payload asking only for estimation and explanation
- assertions:
  - CLI runner is invoked.
  - Task reaches delivery.
  - Report captures whether token usage rows were created.

Artifact collection:
- collect:
  - demo log file
  - temp database observations
  - task payload summary
- preserve_artifacts: yes
```

## When To Use It

- Use it when the main agent wants a reproducible full-pipeline run.
- Use it when scenario execution is operationally heavy enough that separating orchestration from interpretation improves clarity.
- Do not use it for small code searches, static analysis, or simple one-command checks.
