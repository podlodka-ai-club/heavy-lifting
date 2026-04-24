# Runtime Scenario Skill

## Purpose

Этот skill сокращает токены на подготовку real runtime verification run.

Вместо длинного ручного prompt основной агент может использовать короткий вызов вида:

```text
runtime_scenario <scenario-id>
```

Дальше skill опирается на:

- `instration/RUNTIME_SCENARIO_RUNNER_SUBAGENT.md` как контракт выполнения;
- `instration/runtime_scenarios/<scenario-id>.json` как компактный шаблон сценария;
- `instration/runtime_scenarios/render_runtime_scenario.py` как helper для сборки полного prompt.

## Invocation

Базовый вызов:

```text
runtime_scenario cli-nonzero-exit
```

Recommended internal translation:

```bash
uv run python instration/runtime_scenarios/render_runtime_scenario.py cli-nonzero-exit
```

Если нужны override-параметры, их можно передать helper script:

```bash
uv run python instration/runtime_scenarios/render_runtime_scenario.py cli-nonzero-exit --port 8011
```

## Agent Workflow

1. Прочитать `instration/RUNTIME_SCENARIO_RUNNER_SUBAGENT.md`.
2. Запустить helper script для нужного `scenario-id`.
3. Передать полученный prompt в `Task` для execution-only subagent run.
4. Вернуть пользователю только итоговый structured report.
5. Если run важен для локальной истории, сохранить findings в active `worklog/`.

## Rules

- Используй только заранее описанные scenario templates, если пользователь не просит новый сценарий явно.
- По умолчанию используй disposable resources.
- Для demo startup используй `uv run heavy-lifting-demo`, если шаблон не требует иного.
- Не модифицируй product code в рамках scenario run, если пользователь явно не просит implementation.
- Если сценарий требует другого failure trigger или env override, передай override в helper script вместо переписывания полного prompt вручную.

## Supported Scenarios

- `cli-estimate-only`
- `cli-token-accounting`

## Experimental Scenarios

- `cli-nonzero-exit` - requires a reproducible trigger that makes `opencode run` exit non-zero in the current environment; if the trigger exits `0`, the subagent should report the scenario as failed with evidence instead of pretending the failure branch was verified.

## When To Add A New Scenario

Добавляй новый template в `instration/runtime_scenarios/`, если:

- сценарий планируется запускать повторно;
- у него есть собственные assertions и artifact collection;
- ручное описание сценария заметно раздувает prompt.

## Output Expectation

Subagent должен вернуть только normalized report из `instration/RUNTIME_SCENARIO_RUNNER_SUBAGENT.md`:

- `status`
- `scenario_id`
- `goal`
- `environment`
- `executed_steps`
- `observed_result`
- `expected_vs_actual`
- `artifacts`
- `key_evidence`
- `gaps_or_risks`
