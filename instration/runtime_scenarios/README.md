# Runtime Scenario Templates

Этот каталог хранит compact scenario definitions для skill `runtime_scenario`.

## Files

- `render_runtime_scenario.py` - helper script, который печатает полный prompt для subagent.
- `cli-estimate-only.json` - real CLI estimate-only verification.
- `cli-token-accounting.json` - real CLI token accounting verification.
- `cli-nonzero-exit.json` - real CLI failure-path verification template that still requires a reproducible non-zero-exit trigger.

## Usage

```bash
uv run python instration/runtime_scenarios/render_runtime_scenario.py cli-nonzero-exit
```

Optional overrides:

```bash
uv run python instration/runtime_scenarios/render_runtime_scenario.py cli-nonzero-exit --port 8011
```

The script prints a full prompt that can be passed directly to the general-purpose runtime scenario subagent.
