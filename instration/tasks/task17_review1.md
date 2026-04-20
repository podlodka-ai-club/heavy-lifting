# Review 1

- verdict: `changes_requested`
- findings:
  - `src/backend/adapters/mock_tracker.py:34`, `src/backend/adapters/mock_tracker.py:49`, `src/backend/adapters/mock_tracker.py:30`, `src/backend/adapters/mock_tracker.py:75` — `MockTracker` stores incoming Pydantic objects and returns the same live instances from its in-memory state. Because of that, caller code can mutate tracker state indirectly by changing `payload.context` / `payload.metadata` after `create_task`, or by modifying objects returned from `fetch_tasks`, without going through `update_status` / `attach_links`. For the next MVP step this makes the mock behave unlike a real tracker API and can hide orchestration bugs. The adapter should isolate its state with deep copies on write/read (`model_copy(deep=True)` or equivalent).
