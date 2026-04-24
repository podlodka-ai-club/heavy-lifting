from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a full runtime scenario prompt from a compact scenario id."
    )
    parser.add_argument("scenario_id", help="Scenario template name without .json suffix")
    parser.add_argument("--port", type=int, help="Override APP_PORT and scenario port")
    parser.add_argument(
        "--database-path",
        help="Override SQLite database path. Defaults to /tmp/heavy_lifting_<suffix>.sqlite3",
    )
    parser.add_argument(
        "--artifacts-dir",
        help="Override artifacts directory. Defaults to /tmp/heavy_lifting_<suffix>",
    )
    parser.add_argument(
        "--workspace-root",
        help="Override workspace root label used in the prompt. Defaults to /tmp/mock-scm/<workspace_key>",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional environment variable override. Can be passed multiple times.",
    )
    parser.add_argument(
        "--preserve-artifacts",
        choices=["yes", "no"],
        default="yes",
        help="Whether artifacts should be kept after the scenario run.",
    )
    args = parser.parse_args()

    template = load_template(args.scenario_id)
    prompt = render_prompt(template=template, args=args)
    print(prompt)


def load_template(scenario_id: str) -> dict[str, object]:
    path = ROOT / f"{scenario_id}.json"
    if not path.exists():
        available = ", ".join(sorted(file.stem for file in ROOT.glob("*.json")))
        raise SystemExit(f"Unknown scenario '{scenario_id}'. Available scenarios: {available}")
    return json.loads(path.read_text())


def render_prompt(*, template: dict[str, object], args: argparse.Namespace) -> str:
    scenario_id = require_str(template, "scenario_id")
    goal = require_str(template, "goal")
    workspace_key = require_str(template, "workspace_key")
    port = args.port or require_int(template, "port")
    database_suffix = require_str(template, "database_suffix")
    artifacts_suffix = require_str(template, "artifacts_suffix")

    database_path = args.database_path or f"/tmp/heavy_lifting_{database_suffix}.sqlite3"
    artifacts_dir = args.artifacts_dir or f"/tmp/heavy_lifting_{artifacts_suffix}"
    workspace_root = args.workspace_root or f"/tmp/mock-scm/{workspace_key}"

    env = {
        "APP_PORT": str(port),
        "DATABASE_URL": f"sqlite:////{database_path.lstrip('/')}",
        "TRACKER_POLL_INTERVAL": "1",
        "PR_POLL_INTERVAL": "1",
        "PYTHONUNBUFFERED": "1",
    }
    env.update(require_dict(template, "env"))
    env.update(parse_env_overrides(args.env))

    lines = [
        "Run a real MVP pipeline scenario and return only a structured execution report.",
        "",
        "Scenario identity:",
        f"- scenario_id: {scenario_id}",
        f"- goal: {goal}",
        "",
        "Environment setup:",
        "- workspace_strategy: disposable_copy",
        "- database:",
        f"  - path: {database_path}",
        f"  - bootstrap: DATABASE_URL=sqlite:////{database_path.lstrip('/')} uv run make bootstrap-db",
        f"- port: {port}",
        "- env:",
    ]
    for key, value in env.items():
        lines.append(f"  - {key}={value}")
    lines.extend(
        [
            "- startup:",
            "  - command: uv run heavy-lifting-demo",
            "- healthcheck:",
            "  - GET /health returns 200",
            "",
            "Scenario execution:",
            "- steps:",
        ]
    )
    for index, step in enumerate(require_list(template, "steps"), start=1):
        lines.append(f"  {index}. {step}")
    lines.extend(["- inputs:"])
    for item in require_list(template, "inputs"):
        lines.append(f"  - {item}")
    lines.extend(
        [
            f"  - workspace root expectation: {workspace_root}",
            "  - intake payload:",
            indent_block(json.dumps(template["intake_payload"], ensure_ascii=True, indent=2), 4),
            "- assertions:",
        ]
    )
    for item in require_list(template, "assertions"):
        lines.append(f"  - {item}")
    lines.extend(["", "Artifact collection:", "- collect:"])
    for item in require_list(template, "collect"):
        lines.append(f"  - {item}")
    lines.extend(
        [
            f"  - artifacts directory: {artifacts_dir}",
            f"  - temp workspace: {workspace_root}",
            f"- preserve_artifacts: {args.preserve_artifacts}",
            "",
            "Constraints:",
            "- Use disposable resources unless the prompt explicitly allows otherwise.",
            "- Do not modify repository source files.",
            "- Clean up background processes before finishing.",
            "- If any required field is missing, return blocked instead of guessing.",
            "",
            "Output:",
            "- Return only one final report with: status, scenario_id, goal, environment, executed_steps, observed_result, expected_vs_actual, artifacts, key_evidence, gaps_or_risks.",
        ]
    )
    return "\n".join(lines)


def parse_env_overrides(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise SystemExit(f"Invalid --env override '{item}'. Expected KEY=VALUE.")
        result[key] = value
    return result


def require_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"Template field '{key}' must be a non-empty string.")
    return value


def require_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise SystemExit(f"Template field '{key}' must be an integer.")
    return value


def require_list(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SystemExit(f"Template field '{key}' must be a list of strings.")
    return value


def require_dict(data: dict[str, object], key: str) -> dict[str, str]:
    value = data.get(key)
    if not isinstance(value, dict) or not all(
        isinstance(dict_key, str) and isinstance(dict_value, str)
        for dict_key, dict_value in value.items()
    ):
        raise SystemExit(f"Template field '{key}' must be a string-to-string object.")
    return dict(value)


def indent_block(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


if __name__ == "__main__":
    main()
