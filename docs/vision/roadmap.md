# Roadmap

## Phase 0 - Repository Foundation

Establish the documentation and workflow baseline for the orchestrator project.

- Move durable system knowledge into `docs/`.
- Treat `worklog/` as local short-term memory instead of a shared registry.
- Keep the MVP scope explicit so implementation choices stay aligned.

## Phase 1 - Operational MVP

Deliver the smallest end-to-end orchestration loop that proves the core concept.

- Intake work from the tracker through an HTTP API.
- Persist orchestrator tasks and token usage in PostgreSQL.
- Run the three-stage worker pipeline for intake, execution, and delivery.
- Support local development with mock tracker and SCM adapters.
- Produce a branch and PR-oriented implementation flow with basic delivery back to the tracker.

## Phase 2 - Iterative PR Loop

Strengthen the system so follow-up work feels like a native part of the platform.

- Treat PR feedback as a first-class task type with traceable lineage.
- Reuse branch and PR context across implementation iterations.
- Improve delivery payloads so the tracker can distinguish initial implementation from follow-up review handling.
- Capture clearer audit history for execution attempts and review outcomes.

## Phase 3 - Reliability And Control

Make the orchestrator safer and easier to operate under sustained usage.

- Add stronger retry, timeout, and failure-recovery behavior around worker execution.
- Expand observability for task transitions, runner behavior, and SCM actions.
- Harden workspace preparation and cleanup rules.
- Clarify operational controls for reruns, cancellations, and partial failures.

## Phase 4 - Integration Maturity

Broaden the system from a mock-friendly MVP into a more complete integration backend.

- Add production-grade tracker and SCM adapters behind the existing protocols.
- Support richer PR metadata, review synchronization, and status reporting.
- Improve authentication, secret handling, and environment-specific configuration.
- Document integration contracts in `docs/` so new adapters remain consistent.

## Phase 5 - Scaled Orchestration

Evolve the platform for larger throughput and broader operational use.

- Support more advanced scheduling, concurrency control, and queue management.
- Add richer usage reporting and operational analytics.
- Introduce clearer policy boundaries for who can trigger which workflows.
- Consider multi-repository and multi-team usage only after the single-flow system is stable.

## Planning Principles

- Keep each phase independently valuable and reviewable.
- Prefer explicit workflow behavior over hidden automation.
- Expand surface area only after the previous phase is documented and operationally understood.
