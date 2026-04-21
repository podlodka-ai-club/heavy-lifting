# Task 23 Review 1

- Verdict: `changes_requested`

## Findings

1. `src/backend/services/context_builder.py:100` / `src/backend/services/context_builder.py:273`
   `ContextBuilder.build_for_task()` parses `context`, `input_payload` and `result_payload` for every task in the whole root chain before it even identifies the current lineage. Because of that, one malformed sibling task can break context reconstruction for another otherwise valid `execute` / `deliver` / `pr_feedback` task under the same root. For future worker flows this is risky: an old broken feedback task can block delivery or processing of a new feedback task. The builder should fail only on the current lineage and on history entries it actually consumes, not on unrelated siblings. Add a regression test with an invalid sibling payload to prove isolation.

## Checks

- Reviewed against `instration/tasks/task23.md` and `instration/project.md`.
- Verified execute / deliver / pr_feedback reconstruction logic and feedback-history behavior.
- Ran `uv run pytest tests/test_context_builder.py tests/test_token_costs.py` — passed.

## Notes

- `TokenCostService` API looks suitable for later worker integration: single estimate, bulk enrichment, wildcard lookup, and total aggregation are covered.
- Current tests cover happy paths well, but they miss the sibling-isolation failure mode above.
