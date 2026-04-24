# Contracts

This directory stores durable interface contracts for the Heavy Lifting orchestrator.

## Available Pages

- `task-handoff.md` - v1 contract for task `context`, `input_payload`, and `result_payload` across triage, execution, PR feedback, and delivery.
- `triage-routing.md` - MVP triage signals, supported outcomes, and routing matrix for new tracker tasks.
- `event-ingestion.md` - normalized follow-up event taxonomy, deduplication rules, and task-creation rules for tracker and SCM events.

## Usage

- Read these pages when changing task schemas, worker responsibilities, or payload routing semantics.
- Keep migration-era summaries in `instration/project.md`, but store the durable contract shape here.
