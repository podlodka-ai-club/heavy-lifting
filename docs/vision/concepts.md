# System Concepts

## Economics MVP

The economics concept answers one narrow question for the MVP: for closed root tasks, what revenue is known, what token cost was spent, and what profit can be computed without inventing missing cost inputs.

### Root Closure

A root task chain is closed when any task in that chain has `task_type = deliver` and `status = done`.

`closed_at` is the earliest `updated_at` among successful deliver tasks for the root. Open roots are excluded from economics snapshots even if they already have token usage or revenue metadata.

### Revenue

Revenue is stored in `task_revenue` and is unique per `root_task_id`.

- `amount_usd` is `Numeric(12, 6)` and non-negative.
- `source` is one of `mock`, `expert`, or `external`.
- `confidence` is one of `estimated` or `actual`.
- `metadata` is optional JSON for source-specific details.

Manual API upserts accept only `expert` and `external` sources. `mock` revenue is generated only by `POST /economics/mock-revenue` so synthetic data remains distinguishable from entered or imported business data.

### Token Cost

Token cost is read from `token_usage.cost_usd` and summed across every task whose root key belongs to the closed root chain. This includes descendants such as execute, feedback, and delivery tasks.

### Snapshot API

`GET /economics` returns:

- `generated_at`;
- `period` with `from`, `to`, and `bucket`;
- `totals` for closed roots, monetized roots, missing revenue, revenue, token cost, and profit;
- `series` bucketed by `closed_at`;
- `roots` with root identifiers, tracker metadata, close time, revenue, cost, profit, source, and confidence;
- `data_gaps`.

When no period is supplied, the snapshot applies the last 30 days and returns the actual ISO `from` and `to` bounds used for the query. If only `from` is supplied, `to` defaults to request time. If only `to` is supplied, `from` defaults to 30 days before `to`.

Root-level `profit_usd` is `null` when revenue is missing. Aggregate `totals.profit_usd` and each `series[*].profit_usd` are always financially consistent with the displayed aggregates: `revenue_usd - token_cost_usd`. Token cost is shown for every closed root so missing revenue does not hide spend.

### Mock Revenue

`POST /economics/mock-revenue` creates deterministic mock revenue for closed roots that do not already have revenue by default.

Defaults:

- `min_usd = 100`;
- `max_usd = 2500`;
- `seed = heavy-lifting-economics-v1`;
- `overwrite = false`.

The generated value is deterministic from `seed + root_task_id`, so repeated calls with the same inputs are stable. With `overwrite = true`, existing revenue for closed roots can be replaced by deterministic mock values.

### Manual Revenue

`PUT /economics/revenue/{root_task_id}` upserts one revenue row for an existing root task. It validates non-negative amount, `expert|external` source, `estimated|actual` confidence, and optional object metadata.

### Explicit Data Gaps

The MVP economics model does not yet compute:

- infra cost;
- runner hours;
- external accounting import;
- retry waste.

These are returned as `data_gaps` so product decisions do not mistake token-only profitability for complete business accounting.
