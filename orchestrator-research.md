# A Codex CLI operating model for Heavy Lifting

## Section 1 — Executive summary

**The best model for a solo developer on GPT Codex CLI is a central-orchestrator / file-handoff pipeline with three mandatory roles (Implementer, QA, CI/CD) plus a human-played Orchestrator, scaling up to six optional specialist roles only when a change crosses an explicit risk threshold.** Every role is a fresh `codex exec` session; state lives in the git tree as short, schema-validated markdown/JSON artifacts; `AGENTS.md` supplies durable rules; `--output-schema` + exit codes turn each handoff into a machine-checkable gate. This beats "one big chat session" because coding is a tight-state task where clean per-role contexts outperform long rolling histories, and it beats swarm / peer handoff because separate CLI sessions cannot share in-memory state — the filesystem has to be the bus (confirmed by Codex's documented fresh-session behavior and by Anthropic's own finding that multi-agent is weaker on shared-state tasks than on breadth-first research).

**Recommended default for solo dev (standard tier, ~80% of Heavy Lifting tickets):** Orchestrator (you) → Implementer → QA → CI/CD, with Test Writer fused into Implementer. Three Codex sessions, three artifacts, three gates, one PR. Iteration cap 3 inner build/test loops; hard wall-clock 20 min per role.

**Recommended expanded model for higher-risk work (new protocol, schema change, cross-worker contract, production adapter replacing Mock):** add Task PM (clarify + Given/When/Then AC), Architect (ADR + interface note, no code), Reviewer (independent diff review), and optionally Researcher (decision memo). Test Writer becomes its own session when the change has non-trivial behavioral surface.

**Essential roles:** Orchestrator, Implementer, QA / Acceptance, CI/CD. **Optional, risk-gated:** Task PM, Architect, Researcher, Reviewer, Test Writer. Three roles you will almost never need at solo-dev scale are Task PM (you already know the ticket), Researcher (skip unless a real decision is blocked), and a standalone Test Writer (fold tests into Implementer unless the test surface is large or safety-critical).

---

## Section 2 — Evidence-based findings

**F1. Codex CLI sessions are fresh by default; state must be file-based.** Every `codex` / `codex exec` invocation starts a new thread, re-loads the `AGENTS.md` chain, and has no memory of prior runs unless you explicitly `codex resume` or `codex fork`. Why it matters: it forces the orchestration design — the filesystem (and git) is the only reliable inter-role bus. Evidence: **strong** (OpenAI docs, `codex exec` reference). Trade-off: you pay for AGENTS.md re-parsing each run (trivial) and lose cross-session chain-of-thought (a feature, not a bug — prevents contamination). Proven practice. Sources: https://developers.openai.com/codex/cli/reference, https://developers.openai.com/codex/noninteractive.

**F2. Codex offers three complementary durable channels — `AGENTS.md`, custom agents (`.codex/agents/*.toml`), and Agent Skills (`.agents/skills/<name>/SKILL.md`).** (a) `AGENTS.md`: walked git-root → cwd, concatenated closest-wins, capped at 32 KiB, injected as a user-role message headed `# AGENTS.md instructions for <dir>`. Best for project-wide rules, commands, conventions. (b) Custom agents: TOML files defining a role with pinned model, instructions, and tool surface — Codex ships built-ins `default`/`worker`/`explorer` and lets you add your own under `~/.codex/agents/` (personal) or `.codex/agents/` (project-scoped). Best for the role definitions themselves. (c) Agent Skills: directory with `SKILL.md` plus optional scripts/refs, loaded with progressive disclosure — Codex sees only `name`/`description` until it decides to use the skill, then loads the body. Best for reusable workflows (risk scoring, schema validation, PR opening). Why it matters: putting role definitions and reusable workflows in their proper channel reduces AGENTS.md sprawl and gives Codex first-class invocation paths. Evidence: **strong** ([AGENTS.md docs](https://developers.openai.com/codex/guides/agents-md), [Subagents](https://developers.openai.com/codex/subagents), [Agent Skills](https://developers.openai.com/codex/skills)). Trade-off: three channels to keep coherent — see Section 6 for the assignment.

**F3. `--output-schema` + `-o` converts handoffs into machine-checkable contracts.** Codex validates the final message against a JSON Schema, so the driver can reject "done" claims that don't match the expected shape. Why it matters: this is the single most effective mitigation for "confidently-wrong done" in long-horizon runs. Evidence: **strong** (https://developers.openai.com/codex/noninteractive). Trade-off: you must design and maintain schemas. Proven practice — this is Codex's strongest differentiation from Claude Code for orchestration.

**F4. Orchestrator-worker beats graph frameworks at solo-dev scale, and Codex now ships a native subagent runtime.** Anthropic's multi-agent research system used a lead planner + specialist workers with their own contexts and beat a single Opus agent by a wide margin on research evals; **token spend explained ~80% of variance**. Codex CLI now natively supports subagents: built-in `default`/`worker`/`explorer`, plus user-defined agents under `~/.codex/agents/` or `.codex/agents/`, with `agents.max_threads = 6` and `agents.max_depth = 1` by default. So the orchestrator-worker pattern is no longer something we have to glue together with bash for read-heavy work — Codex parents-and-children it for us. LangGraph-style runtimes remain overkill: git + shell + Codex's own subagent dispatch are enough. Evidence: **strong**. Sources: [Anthropic multi-agent](https://www.anthropic.com/engineering/multi-agent-research-system), [Codex subagents](https://developers.openai.com/codex/subagents).

**F5. Write-heavy coding loops stay sequential; read-heavy work should parallelize.** Anthropic reports multi-agent is weak on shared-state tasks like coding implementation, and Codex's own guidance recommends starting subagent use with read-heavy tasks (exploration, tests, triage, summarization). Why it matters: keep the implement → fix → verify chain strictly sequential (one writer at a time, file-handoff checkpoints), but use Codex subagents in parallel for Researcher, codebase explorer, docs lookup, and the read-only Reviewer pass over a frozen diff. Evidence: **strong**. Trade-off: parallelism on the wrong stage corrupts shared state; on the right stage it's a major latency and quality win. Sources: [Anthropic multi-agent](https://www.anthropic.com/engineering/multi-agent-research-system), [Codex subagents](https://developers.openai.com/codex/subagents).

**F6. Long-horizon runs drift; cap iterations hard.** "Lost in the middle" shows U-shaped accuracy: mid-context instructions are ~20 pts worse than start/end (Liu et al. 2023). Canonical-path deviation is self-reinforcing (+22.7 pp per off-canonical step). Practical caps: Implementer ≤ 3 inner build/test loops per task; Reviewer ↔ Implementer ≤ 2 rounds; total tool calls ≤ 30 simple / ≤ 80 complex; wall-clock 10 min soft / 20 min hard. Evidence: **strong** (Liu et al.), **moderate** (practitioner caps). Sources: https://arxiv.org/abs/2307.03172, Anthropic engineering post.

**F7. OpenAI's GPT-5/Codex prompting guide explicitly warns that verbose preambles cause premature "done".** Keep role prompts ≤ ~1.5 KB / ~400 tokens, with critical rules at the top AND bottom (countering lost-in-the-middle). Evidence: **strong** (https://cookbook.openai.com/examples/gpt-5/gpt-5-1-codex-max_prompting_guide). Trade-off: less room for persona/backstory framing that Claude Code rewards — Codex rewards concrete commands and explicit stop conditions instead.

**F8. Sandbox + approvals are network-off by default in `workspace-write`.** To install packages inside a Codex session you must opt in via `[sandbox_workspace_write] network_access = true`. Why it matters: deterministic runs; you control blast radius per role. Evidence: **strong** (https://developers.openai.com/codex/concepts/sandboxing). Trade-off: extra config; surprising for newcomers.

**F9. Role boundaries from human software delivery map directly onto agent roles.** Google's code review guide ("reviewer evaluates, does not redesign"), Nygard ADRs (1–2 pages), Given/When/Then acceptance criteria (Fowler), Google/SRE design-doc culture, and Scrum's Definition of Done all translate 1:1 to artifact contracts for agents. Evidence: **strong**. Sources: https://google.github.io/eng-practices/review/reviewer/, https://martinfowler.com/bliki/GivenWhenThen.html, https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions, https://agilealliance.org/glossary/definition-of-done/.

**F10. Specialist prompts beat generalist prompts.** Both CrewAI's "task with `expected_output`" pattern and Anthropic's "each subagent needs an explicit objective + output format + tool guidance + boundaries" make the same point: narrow role + structured contract = less drift, fewer tokens. Evidence: **strong**. Source: https://docs.crewai.com/en/guides/agents/crafting-effective-agents, Anthropic post.

**F11. Change-risk rubric (blast radius, reversibility, complexity, dependency surface, exposure) decides process tier.** Solo dev on a reversible single-file change is minimal tier; solo dev on an irreversible schema migration is high-rigor tier — rigor tracks risk, not team size. Evidence: **strong** (SRE book, Fowler). Source: https://sre.google/sre-book/release-engineering/, https://cloud.google.com/blog/products/devops-sre/how-sres-analyze-risks-to-evaluate-slos.

**F12. Deterministic external checks outperform model self-report.** Exit codes from `pytest`, `ruff`, `mypy`, `docker compose up` are the only trustworthy "done" signals. Model's own `status: "done"` is unreliable without a paired external check. Evidence: **strong** (Hamel Husain on evals, Anthropic, Thoughtworks). Source: https://hamel.dev/blog/posts/evals/.

---

## Section 3 — Recommended orchestration model

**Narrative.** You (human) are the Orchestrator. For each task pulled from `instration/tasks/`, you start a Codex CLI session per role in a fixed order, passing artifacts through files in `artifacts/<task-id>/`. Each session runs `codex exec` with a role-specific profile, a compact role prompt, and a JSON output schema. Exit codes and schema validation gate progression. Git commits between stages are checkpoints. AGENTS.md carries durable rules so prompts stay small.

**Step-by-step workflow (standard tier).**

1. **Intake.** Orchestrator reads the task file (`instration/tasks/NN-title.md`), creates `artifacts/<task-id>/` and stages a `00-brief.md`. Classify risk with the rubric (Section 9). Pick tier.
2. **(Optional) Task PM session.** Only if AC missing/ambiguous or risk ≥ standard and story isn't already Given/When/Then. Writes `01-requirements.md`.
3. **(Optional) Research session.** Only if a blocking unknown exists. Writes `02-research.md` with a recommendation.
4. **(Optional) Architect session.** Only if change is architecturally significant. Writes `03-architecture.md` (ADR format).
5. **Implementer session (mandatory).** Reads `00–03`; writes code + tests + `04-change-summary.md` + `04-status.json` (schema-validated).
6. **(Optional) Test Writer session.** Only if Implementer's test coverage is insufficient for the risk tier. Writes `05-test-plan.md` and additional tests.
7. **(Optional) Reviewer session.** Only at standard+ tier. Reads diff + `04-change-summary.md`; writes `06-review.md` with `{status: approve|request_changes}`. Request-changes returns to Implementer (max 2 rounds).
8. **QA / Acceptance session (mandatory).** Reads `01-requirements.md` + runtime behavior; writes `07-qa-report.json` (pass/fail per AC, black-box only).
9. **CI/CD session (mandatory).** Runs the readiness checklist; writes `08-cicd-report.json`. Must be green to merge.
10. **Orchestrator finalizes.** If all gates pass, opens PR via the SCM adapter, posts results back to tracker.

**Lightweight state machine.**

```
                ┌─────────── rework (≤2) ───────────┐
                │                                   │
 INTAKE ─► [PM] ─► [RESEARCH] ─► [ARCH] ─► IMPLEMENT ─► [REVIEW] ─► QA ─► CI ─► DONE
   00       01        02          03         04/05        06        07    08
                                                │             ▲
                                                └─ build/test inner loop ≤3 ─┘

[ ] = optional session, gated by tier + risk rubric.
Each arrow = a fresh `codex exec` reading prior artifacts + role prompt, writing next artifacts.
Any `status: "blocked"` from any role → halt-and-report to human.
```

**Invocation order.** The write-heavy spine — Implementer → (Reviewer) → QA → CI/CD — is strictly sequential, file-handoff between stages, one writer at a time. Read-heavy roles can run in parallel as Codex subagents (`agents.max_threads = 6` by default): Researcher, codebase exploration during Architect, docs lookup, and a read-only diff scan during Reviewer can all be dispatched concurrently. Concretely: Architect can spawn an `explorer` subagent to map the touched modules while drafting the ADR; Reviewer can fan out a docs-lookup subagent for any cited library while reading the diff. The implement → fix → verify loop never parallelizes — multi-agent on shared state is where it breaks.

**Rework loops with caps.**

- Implementer inner loop (edit → run tests): **max 3** consecutive failures on same test/file before halting.
- Reviewer ↔ Implementer: **max 2** rounds. Third round = human escalation.
- QA → Implementer: **max 1** round for requirements misalignment; a second failure escalates.
- CI/CD → Implementer: **max 2** rounds for deterministic fixes (lint, type, migration). Repeated failure escalates.
- Global per-task iteration budget: **≤ 30** tool calls simple / **≤ 80** complex; **≤ 200 K** tokens/session.

**Mandatory gates.** Implementer produces a valid `04-status.json` with `status: "ready-for-review"`. QA report has every AC marked pass. CI/CD readiness checklist fully green.

**Optional gates.** Architect ADR (risk ≥ standard), Reviewer approval (risk ≥ standard), Test Writer plan (risk high-rigor or large behavior surface), Research memo (only when a decision is blocked).

**Stop conditions.** Any role emits `{status: "blocked", reason: "..."}` → pipeline halts, human resolves. Iteration cap breach → halt. Wall-clock breach → halt. Schema validation failure → role re-runs once with the validation error appended; second failure halts.

---

## Section 4 — Role cards

### 4.1 Task PM Agent (optional)
1. **Purpose.** Convert a raw tracker ticket into testable acceptance criteria and crisp scope.
2. **When to invoke.** AC missing or ambiguous; risk ≥ standard and story isn't Given/When/Then.
3. **When NOT.** Ticket already has AC and scope is clear; you are the PM and know the ticket.
4. **Inputs.** `00-brief.md`, linked tracker issue text, `instration/project.md`.
5. **Outputs.** `01-requirements.md` with Given/When/Then AC, explicit in-scope/out-of-scope, open questions.
6. **Quality bar.** Every AC is testable and binary; no technical prescription.
7. **Failure modes.** Inventing technical requirements; padding with generic user-story prose; ambiguous AC.
8. **Hand-off contract.** Downstream reads `01-requirements.md` as the AC source of truth.
9. **Metrics.** AC count, % ACs that became automated tests, % rework from ambiguous AC.
10. **Prompt principles.** Forbid technology choices; enforce GWT; demand questions section.

### 4.2 Architect Agent (optional)
1. **Purpose.** Make architecturally-significant decisions and document them; do not implement.
2. **When to invoke.** Touches Protocol boundaries, data model, cross-worker contracts, irreversible decisions, or introduces a new abstraction.
3. **When NOT.** In-method refactor, single-file change, behavior change behind an existing interface.
4. **Inputs.** `00-brief.md`, `01-requirements.md`, `src/backend/**` relevant files (read-only).
5. **Outputs.** `03-architecture.md` in ADR format (Context, Decision, Consequences, Alternatives) + list of files to touch + interface stubs.
6. **Quality bar.** Decision is testable, alternatives enumerated, consequences honest; ≤ 1 page.
7. **Failure modes.** Writing the code; pseudo-ADRs that don't decide anything; bikeshedding style.
8. **Hand-off contract.** Implementer treats the ADR's Decision section as binding.
9. **Metrics.** ADR-to-rework ratio; number of Implementer escalations due to missing architectural info.
10. **Prompt principles.** Hard-forbid editing `src/**` (enforced by the diff guard, since `read-only` sandbox would block needed git/grep under approval=never); require "Alternatives considered".

### 4.3 Implementer Agent (required)
1. **Purpose.** Produce minimal, correct code + tests that satisfies the plan and ACs.
2. **When to invoke.** Every task.
3. **When NOT.** Never skipped.
4. **Inputs.** `00-brief.md`, `01-requirements.md` (if present), `03-architecture.md` (if present), repo code.
5. **Outputs.** Code diff committed/staged, unit tests, `04-change-summary.md`, `04-status.json` (schema-validated).
6. **Quality bar.** All new/changed tests pass locally; lint/type clean; diff bounded to declared scope.
7. **Failure modes.** Silent scope creep; disabling tests; redesign; long unbounded edit loops; abusing scope-expansion for refactor.
8. **Hand-off contract.** `04-status.json` must include `{status, files_changed[], tests_added[], commands_run[], tests_passed: bool, iteration_count, scope_expansions[]}`.
9. **Metrics.** First-pass test-green rate; scope-expansion count and reason mix; iteration count.
10. **Prompt principles.** Enforce declared scope; allow controlled expansion (≤2, allowed reasons only, recorded with evidence); cap inner loop at 3; explicit "stop when tests green and status.json written".

### 4.4 Researcher Agent (optional)
1. **Purpose.** Resolve a single specific blocker with a recommendation.
2. **When to invoke.** A decision is blocked on a specific unknown (library choice, protocol semantics, vendor behavior).
3. **When NOT.** General "learn about X"; no pending decision.
4. **Inputs.** A one-sentence question + decision context.
5. **Outputs.** `02-research.md` with Question, Options (≥2) with trade-offs, Recommendation, Sources (URLs).
6. **Quality bar.** Decision-enabling (not summary); ≥ 2 primary sources with URLs; recommendation explicit.
7. **Failure modes.** Generic overviews; no recommendation; no sources; unbounded scope.
8. **Hand-off contract.** Architect or Implementer cites the recommendation in the next artifact.
9. **Metrics.** % memos that produced a concrete decision; time to decision.
10. **Prompt principles.** Template enforces Question/Options/Recommendation/Sources; reject outputs without a recommendation.

### 4.5 Reviewer Agent (optional)
1. **Purpose.** Independent review of the diff against code-health bar.
2. **When to invoke.** Risk ≥ standard; change touches Protocol or worker orchestration.
3. **When NOT.** Trivial docs/typos; single-file internal refactor with passing tests at minimal tier.
4. **Inputs.** Diff (`git diff`), `04-change-summary.md`, `01-requirements.md`, `03-architecture.md`.
5. **Outputs.** `06-review.md` with `{status: approve|request_changes, findings[{severity, file, line, issue, suggestion}]}`.
6. **Quality bar.** Findings cite file+line; blockers separated from nits; no redesign demands.
7. **Failure modes.** Redesigning the solution; "just one more thing"; stylistic nit-blocking; rubber-stamping.
8. **Hand-off contract.** `request_changes` returns to Implementer with findings; max 2 rounds.
9. **Metrics.** Findings/1K LOC; blocker-to-nit ratio; review rounds per task.
10. **Prompt principles.** Hard-forbid editing code (enforced by post-session diff guard, not `--sandbox read-only` — that would also block needed `git diff` under `approval=never`); explicit "you may propose one alternative but must accept author's valid approach"; nit-prefix rule.

### 4.6 Test Writer Agent (optional)
1. **Purpose.** Author tests that encode acceptance criteria, typically before/alongside implementation.
2. **When to invoke.** Large behavioral surface; safety-critical path; Implementer's coverage insufficient.
3. **When NOT.** Small changes where Implementer can own tests.
4. **Inputs.** `01-requirements.md`, protocol/interface definitions.
5. **Outputs.** `05-test-plan.md` + failing tests committed.
6. **Quality bar.** Tests map 1:1 to AC; fail for the right reason; no weakened assertions.
7. **Failure modes.** Tautological tests; modifying production code; over-mocking.
8. **Hand-off contract.** Implementer must make these tests green without weakening them.
9. **Metrics.** AC-to-test coverage; test-induced bug catches.
10. **Prompt principles.** Sandbox `workspace-write` (no real per-path restriction available — `writable_roots` is additive); diff guard in `bin/run-role.sh` enforces "writes only under `tests/**` and `artifacts/{id}/**`"; forbid editing `src/**`.

### 4.7 QA / Acceptance Agent (required)
1. **Purpose.** Black-box validation that the running system meets every acceptance criterion.
2. **When to invoke.** Every task, after implementation.
3. **When NOT.** Never skipped.
4. **Inputs.** `01-requirements.md` (or `00-brief.md` if no PM), running system/test fixtures.
5. **Outputs.** `07-qa-report.json` with per-AC `{id, status: pass|fail, evidence}`.
6. **Quality bar.** Every AC has an evidence entry; no code-style judgments.
7. **Failure modes.** Acting as code reviewer; running unit tests as if they were AC; skipping AC with "looks fine".
8. **Hand-off contract.** Any `fail` returns to Implementer (max 1 round) or escalates.
9. **Metrics.** AC pass rate; defects found post-merge (leakage).
10. **Prompt principles.** Sandbox `workspace-write` (read-only blocks command execution under `approval_policy = "never"`, so QA can't run pytest there); `src/**` is forbidden by prompt rule, not by sandbox — `writable_roots` is *additive*, not an allowlist, and does not restrict writes. Enforcement is the post-session diff guard in `bin/run-role.sh` (see Section 6); allowed to run test suite and exercise the app; forbid commenting on code structure.

### 4.8 CI/CD Agent (required)
1. **Purpose.** Verify pipeline readiness — build, lint, type, tests, coverage, security, migrations, artifact.
2. **When to invoke.** Every task, after QA.
3. **When NOT.** Never skipped.
4. **Inputs.** Repo at current commit.
5. **Outputs.** `08-cicd-report.json` with per-check `{name, status, duration, log_path}`.
6. **Quality bar.** Every check has a deterministic exit code; no AC judgment.
7. **Failure modes.** Acting as QA; skipping security/migration checks; treating flaky tests as green.
8. **Hand-off contract.** All-green gates merge; any red returns to Implementer (max 2 rounds) for deterministic fixes.
9. **Metrics.** First-pass CI green rate; flake rate; pipeline wall-clock.
10. **Prompt principles.** Prefer running existing scripts/Make targets over re-implementing checks; forbid "fix" edits outside declared failure scope.

### 4.9 Orchestrator Agent (required, human-played for solo dev)
1. **Purpose.** Sequence sessions, enforce gates, maintain state; coordinate, don't decide.
2. **When to invoke.** Every task.
3. **When NOT.** Never skipped — but at solo-dev scale it's you + a bash/Make driver, not another Codex session.
4. **Inputs.** Task queue, `artifacts/<task-id>/` tree.
5. **Outputs.** `09-orchestration-log.jsonl` (per-session event log), final PR.
6. **Quality bar.** All mandatory gates green; all caps respected; every transition logged.
7. **Failure modes.** Re-deciding technical questions; letting roles drift past caps; skipping mandatory gates.
8. **Hand-off contract.** Posts final results to tracker via SCM/Tracker adapters.
9. **Metrics.** Tasks/day, gate-violation count (must be 0), mean cost per task.
10. **Prompt principles.** If ever promoted from human to Codex session, sandbox is `workspace-write` (needed to invoke `codex exec`/`git`); diff guard restricts writes to `artifacts/{id}/09-orchestration-log.jsonl` only. No code edits, no role-output edits.

---

## Section 5 — Codex-ready role instructions

Each role has: **(A)** a short system prompt to paste as the first line of `codex exec`, **(B)** a fuller operating instruction kept as `prompts/agents/<role>.md`, **(C)** a compact self-check list. Keep A under ~400 tokens; rely on `AGENTS.md` for project-durable rules.

> **Maintenance contract.** This section is the self-contained recovery copy of the role prompts. The canonical, sync-required content is the **embedded prompt payload inside each `### 5.x` subsection** — specifically, the three fenced code blocks labelled "A. Short prompt", "B. Fuller instruction", and "C. Self-check". Those fenced payloads must stay content-equivalent to the matching `## A` / `## B` / `## C` fenced blocks in `prompts/agents/<role>.md`. The surrounding markdown chrome (Section-5 numbering, bold labels, narrative prose outside the fenced blocks) is allowed to differ and is **not** part of the sync contract — an automated check should compare fenced-block contents only, not whole-section bytes. `orchestrator-research.md` is the document a future operator would use to rebuild the system from scratch, so drift in the embedded payloads makes recovery lossy. When you change a prompt under `prompts/agents/`, mirror the edit into the matching fenced blocks in Section 5 in the same commit, and re-check the baseline principles in `AGENTS.md`, the operating rules in Section 11.3, and the anti-patterns in Section 11.4 for consistency. If you add or remove a role, Sections 4, 5, 6 (profiles + file layout), 11.1, and 11.2 must all move together.

### 5.1 Task PM

**A. Short prompt.**
```
ROLE: Task PM. TASK_ID: {id}.
GOAL: Convert 00-brief.md into testable Given/When/Then acceptance criteria + explicit scope.
READ: artifacts/{id}/00-brief.md, instration/project.md, instration/tasks/{file}.
WRITE: artifacts/{id}/01-requirements.md (schema: schemas/requirements.schema.json).
DO NOT: propose libraries, choose designs, write pseudocode, edit src/**.
ESCALATE: emit {status:"blocked", reason} in 01-status.json if intent unclear.
DONE WHEN: ≥1 Given/When/Then AC, scope in/out lists, open questions section exist and schema validates.
```

**B. Fuller instruction (`prompts/agents/task_pm.md`).**
```
# Role: Task PM
Identity: you are a product analyst, not an engineer.
Goal: produce a requirements artifact a Codex-based Implementer and QA can consume unambiguously.

Scope boundaries:
- In: user intent, acceptance criteria, scope fences, dependencies, open questions.
- Out: architecture, libraries, APIs, code.

Required inputs: 00-brief.md. Optional: linked tracker text, instration/project.md for domain terms.

Required output: artifacts/{id}/01-requirements.md with sections:
## Summary (≤3 sentences)
## Acceptance criteria
- AC-1 Given ... When ... Then ...
## In scope
- ...
## Out of scope
- ...
## Open questions
- Q-1: ...

Do-not rules:
- Do not mention frameworks, classes, or file paths.
- Do not weaken ACs into "should work".
- Do not invent user research.
- Do not bundle multiple behaviors into one AC. If an AC contains `and`/`also`/multiple Thens, split it so each AC verifies one behavior.

Escalation: if intent cannot be recovered, write {status:"blocked", reason} to 01-status.json and stop.

Completion: the artifact exists, schema validates, ≥1 AC present.
```

**C. Self-check.**
```
[ ] Every AC is Given/When/Then and binary.
[ ] Each AC is independently falsifiable (one behavior, one Then).
[ ] Scope in/out is non-empty.
[ ] No library or code mentioned.
[ ] Open questions listed (or "none").
[ ] schema validates.
```

### 5.2 Architect

**A. Short prompt.**
```
ROLE: Architect. TASK_ID: {id}.
GOAL: Decide architecturally significant points; produce an ADR. Do not implement.
READ: artifacts/{id}/00-brief.md, 01-requirements.md, src/backend/** (read-only).
WRITE: artifacts/{id}/03-architecture.md; 03-status.json.
DO NOT: edit src/**, write working code, expand scope beyond ACs.
SANDBOX: workspace-write (needed to run read-only commands like git/grep under approval=never). Diff guard restricts writes to artifacts/{id}/**. If you need to run a probe, write it as a `suggested_command` field; do not execute.
DONE WHEN: ADR sections Context/Assumptions/Decision/Consequences/Alternatives populated, files-to-touch list present, ≤1 page.
```

**B. Fuller instruction (`prompts/agents/architect.md`).**
```
# Role: Architect
Identity: senior engineer who decides and documents, not implements.
Goal: one ADR per architecturally significant decision.

Architecturally significant = hard-to-change later: protocol shape, data model, worker boundaries, concurrency model, public interface, irreversible choice.

Required output: 03-architecture.md (Nygard ADR, ≤1 page):
## Title
## Status (proposed)
## Context
## Assumptions (explicit list; mark each as verified or unverified. An unverified assumption must either cause `{status:"blocked"}` or be recorded here with enough detail for the orchestrator to route it — do not proceed with a silent guess.)
## Decision
## Consequences (positive + negative)
## Alternatives considered (≥2, with why rejected)
## Files to touch
## Interface sketch (types/function signatures only, no bodies)

Do-not:
- Do not write function bodies.
- Do not choose tooling that the AGENTS.md stack already specifies.
- Do not ADR-ify non-significant decisions.
- Do not include speculative extension points, configurability, parameters, or interface members that are not required by an existing AC. "Designed for future X" without an AC for X is out.

Escalation: if requirements are ambiguous on a load-bearing axis, emit {status:"blocked"} and stop.

Completion: ADR complete, alternatives non-trivial, files-to-touch concrete, ≤1 page.
```

**C. Self-check.**
```
[ ] Decision is specific and testable.
[ ] ≥2 alternatives with rejection rationale.
[ ] No function bodies written.
[ ] Files-to-touch list matches ACs.
[ ] Assumptions section present; every unverified assumption is either blocking or recorded explicitly in Assumptions with enough detail for the orchestrator to route.
[ ] Interface sketch contains no speculative methods, parameters, or extension points beyond ACs.
[ ] ≤1 page rendered.
```

### 5.3 Implementer

**A. Short prompt.**
```
ROLE: Implementer. TASK_ID: {id}.
GOAL: Produce minimal code + tests satisfying ACs and ADR. Stop at green tests.
READ: 00-brief.md, 01-requirements.md, 03-architecture.md (if present), AGENTS.md.
WRITE: code diff in repo, tests, 04-change-summary.md, 04-status.json (schema: schemas/implementer.schema.json).
SCOPE: declared = files in 03-architecture.md "Files to touch" ∪ 00-brief.md "Scope". May expand only via the controlled-expansion protocol (see fuller instruction). No silent additions.
INNER LOOP CAP: ≤3 edit→test cycles on the same failing test. After cap, emit {status:"blocked"}.
DO NOT: redesign, disable tests, weaken assertions, add TODOs without ticket refs, add speculative flexibility or opportunistic refactor inside touched files.
RUN: project test/lint commands from AGENTS.md.
DONE WHEN: all declared ACs have tests; tests green; lint/type clean; 04-status.json {status:"ready-for-review", tests_passed:true} with scope_expansions[] documenting any additions.
```

**B. Fuller instruction (`prompts/agents/implementer.md`).**
```
# Role: Implementer
Identity: a disciplined engineer who executes a plan.

Inputs:
- AC source of truth: 01-requirements.md (or 00-brief.md).
- Design binding: 03-architecture.md (Decision + Files to touch).
- Project rules: root AGENTS.md + nested.

Process:
1. Read inputs. If inputs missing or contradictory, emit {status:"blocked"} and stop.
2. Write or update failing tests for each uncovered AC.
3. Implement the smallest change that passes tests.
4. Run the project's test/lint/type commands (see AGENTS.md).
5. If all green, write 04-change-summary.md and 04-status.json.
6. If same test fails 3x in a row, stop and emit {status:"blocked", reason:"inner_loop_cap"}.

Hard rules:
- Edit only files inside declared scope (`Files to touch` of the ADR ∪ `Scope` of 00-brief.md), OR via the controlled-expansion protocol below.
- Never edit tests to make them pass by weakening assertions.
- Never add #ignore / @pytest.skip / # type: ignore without a TODO tag with ticket id.
- Never run destructive git commands (`push --force`, `reset --hard`).
- No single-use abstractions unless required by an AC, ADR, or an existing module boundary in `src/backend`. No configurability, parameters, flags, or extension points that are not required by an AC or ADR.
- Inside files listed in `Files to touch`, change only what the AC/ADR requires. No opportunistic cleanup, renaming, refactor, or reformatting. Match existing style.
- Unrelated dead code noticed in passing: record under `Observations` in 04-change-summary.md. Do not delete it.
- Do not add speculative defensive branches for inputs or states that are not required by an AC, an explicit contract, or a documented invariant. Validation at system boundaries (user input, external APIs, untrusted data) is explicitly allowed and is not covered by this rule.

Controlled scope expansion (when an unlisted file genuinely must change):
1. Allowed reasons only: missing test file the AC needs, contract/fixture file required by an existing test, AGENTS.md/config that the change provably depends on. Not for refactor, cleanup, or "while I'm here".
2. Append an entry to `04-status.json.scope_expansions[]`: `{path, reason, ac_id, evidence}`. Evidence is the failing test or import error that forced the addition.
3. Cap: ≤2 expansions per task. The 3rd would-be expansion → emit `{status:"blocked", reason:"scope_expansion_cap"}` and stop; the human re-scopes.
4. Reviewer treats every expansion entry as a blocker if reason is not in the allowed list.

Outputs:
- 04-change-summary.md: What/Why/How-tested/Risks/Rollback (≤1 page).
- 04-status.json: {status, files_changed[], tests_added[], commands_run[{cmd, exit_code}], tests_passed, iteration_count, scope_expansions[]}.

Done criteria:
- Tests green for all ACs.
- Lint/type clean.
- 04-status.json schema-valid with status = "ready-for-review".
```

**C. Self-check.**
```
[ ] Every AC has at least one test that fails without my change.
[ ] All tests green locally.
[ ] Lint + type-check clean.
[ ] Diff confined to declared scope OR every out-of-scope file is in `scope_expansions[]` with allowed reason + evidence.
[ ] ≤2 scope expansions used.
[ ] No speculative flexibility: every single-use abstraction traces to an AC, ADR, or existing module boundary in `src/backend`; no unused config; no unrequested extension points.
[ ] No opportunistic refactor, rename, or reformat inside touched files.
[ ] Every defensive branch maps to an AC, explicit contract, documented invariant, or system-boundary validation.
[ ] 04-change-summary.md has What/Why/How-tested/Risks/Rollback.
[ ] 04-status.json validates and says ready-for-review.
```

### 5.4 Researcher

**A. Short prompt.**
```
ROLE: Researcher. TASK_ID: {id}. QUESTION: "{one-sentence decision question}".
GOAL: produce a decision memo with ≥2 options and a recommendation.
READ: 00-brief.md. Use web_search/web_fetch sparingly; prefer canonical sources.
WRITE: artifacts/{id}/02-research.md; 02-status.json.
DO NOT: summarize without deciding; cite blog-spam; exceed 1 page.
DONE WHEN: Question / Interpretation chosen / Options (≥2) / Recommendation (exactly one) / Verification / Sources (URLs) sections exist.
```

**B. Fuller instruction (`prompts/agents/researcher.md`).**
```
# Role: Researcher
Identity: analyst answering exactly one decision question.

Input: one specific question + decision context from 00-brief.md.

Required output (02-research.md, ≤1 page):
## Question
## Interpretation chosen (name the reading being answered; write "none — question was unambiguous" if there is only one valid reading)
## Decision context (why we are asking, what depends on this)
## Options
- Option A: ... (pros/cons)
- Option B: ...
## Recommendation
- Chosen: ...
- Rationale in 2-3 bullets.
- Risks of recommendation.
## Verification
- 1-2 bullets: the observable signal that will tell us the recommendation was right (e.g. benchmark threshold, production metric, test outcome). Not "it works".
## Sources
- [title](url) — role (primary doc / vendor blog / etc.)

Do-not:
- Generic overviews.
- Recommendation-free memos.
- Unsourced claims.
- "It depends" with no recommendation.
- Silently choosing one reading of the question when it admits ≥2 incompatible valid readings. Either emit `{status:"blocked"}` for disambiguation, or record the picked reading in `## Interpretation chosen` (with a one-line justification) and answer against that reading only. Exactly one Recommendation in the memo, always.

Escalation: if the question is malformed or unanswerable without more context, emit {status:"blocked"}.
```

**C. Self-check.**
```
[ ] Exactly one question answered, with no silent disambiguation.
[ ] Interpretation chosen recorded (or "none — question was unambiguous").
[ ] Exactly one Recommendation in the memo.
[ ] ≥2 real options with trade-offs.
[ ] Verification criterion present and observable.
[ ] ≥2 sources with URLs.
[ ] ≤1 page.
```

### 5.5 Reviewer

**A. Short prompt.**
```
ROLE: Reviewer. TASK_ID: {id}.
GOAL: Independent diff review against code-health bar. Do NOT rewrite the solution.
READ: git diff, 04-change-summary.md, 01-requirements.md, 03-architecture.md, AGENTS.md.
WRITE: artifacts/{id}/06-review.md; 06-status.json.
SANDBOX: workspace-write (needed for `git diff`/grep under approval=never). Diff guard restricts writes to artifacts/{id}/**. No code edits.
DO NOT: redesign; add new requirements; request extension points/configurability beyond AC/ADR; nit-block (prefix stylistic nits with "Nit:"); run QA or CI.
DONE WHEN: {status: approve | request_changes} with findings list [{severity, file, line, issue, suggestion}].
CAP: this is round N of max 2 per task.
```

**B. Fuller instruction (`prompts/agents/reviewer.md`).**
```
# Role: Reviewer
Identity: code-health gatekeeper, not author of a replacement solution.

Focus (Google code-review guide):
- Design fit vs ADR.
- Correctness (inc. concurrency, error paths).
- Tests: exist and test the right thing.
- Readability, naming, complexity.
- Security (secrets, input validation, injection surfaces).
- Style guide conformance.
- Overcomplication: speculative flexibility, unused abstractions, excess configurability, or defensive branches without a concrete scenario backed by AC / explicit contract / documented invariant. Flag at least as `major`; if it also obscures correctness, `blocker`.

Do-not rules (hard):
- Do not rewrite the solution. You may propose one alternative in `suggestion`, but if the author's approach is valid, accept it.
- Do not introduce new requirements.
- Do not request new extension points, configurability, or abstractions that are not required by an existing AC or ADR.
- Do not edit code (enforced by post-session diff guard, since `read-only` sandbox would also block `git diff` under approval=never).
- Nits must be prefixed "Nit:" and are non-blocking.

Severity scale:
- blocker: correctness/security/ADR violation.
- major: readability or test gap that risks defects.
- minor: naming, local structure.
- nit: style preferences.

Output (06-review.md):
## Summary
## Findings
- [severity] file:line — issue — suggestion
## Decision: approve | request_changes
## Round: N of 2

If round 2 still has blockers: set status = "escalate".
```

**C. Self-check.**
```
[ ] I did not propose a new design.
[ ] I did not request extension points or configurability outside AC/ADR.
[ ] Overcomplication findings (speculative flexibility, unused abstractions, defensive branches without backing scenario) flagged at least `major`.
[ ] Every finding cites file:line.
[ ] Nits prefixed and non-blocking.
[ ] Decision field set.
[ ] Round N recorded.
```

### 5.6 Test Writer

**A. Short prompt.**
```
ROLE: Test Writer. TASK_ID: {id}.
GOAL: Author failing tests that encode every AC.
READ: 01-requirements.md, protocol/interface definitions in src/backend/**.
WRITE: tests/** (new files only under declared dirs), artifacts/{id}/05-test-plan.md, 05-status.json.
SANDBOX: workspace-write. The wrapper-script diff guard (Section 6) enforces "writes only under tests/** and artifacts/{id}/**"; sandbox-level restriction is not available (writable_roots is additive).
DO NOT: modify production code; weaken assertions; write tautological tests.
DONE WHEN: every AC has ≥1 test that fails for the right reason on current HEAD.
```

**B. Fuller instruction (`prompts/agents/test_writer.md`).**
```
# Role: Test Writer
Identity: QA engineer writing executable acceptance tests.

Output (05-test-plan.md):
## Scope
## Test levels (unit / integration / e2e)
## Test list
- T-1 covers AC-1: given/when/then, location, fixtures
## Risks / flakiness notes
## Entry/exit criteria

Hard rules:
- Tests must fail on current HEAD.
- Tests must reference the AC id in name or docstring.
- No changes under src/** (enforced by the diff-guard wrapper, not the sandbox).
- No `pytest.skip`/`xfail` without a ticket reference.
- Tests encode only AC, ADR contract, explicit interface contract, or recorded bug-context. No speculative edge cases. If a case feels important but is not backed by one of these sources, stop and escalate to Task PM instead of adding the test.
```

**C. Self-check.**
```
[ ] Every AC mapped to ≥1 test.
[ ] Every test traces to an AC, ADR contract, interface contract, or bug-context; no speculative cases.
[ ] Every test fails right now.
[ ] No src/** files modified.
[ ] Test plan lists levels and fixtures.
```

### 5.7 QA / Acceptance

**A. Short prompt.**
```
ROLE: QA / Acceptance. TASK_ID: {id}.
GOAL: Black-box validate every AC against the running system.
READ: 01-requirements.md; repo at current commit.
WRITE: artifacts/{id}/07-qa-report.json (schema: schemas/qa-report.schema.json). May write under tests/cache/coverage paths to run pytest. MUST NOT touch src/**, tests/** sources, AGENTS.md, prompts/, schemas/.
SANDBOX: workspace-write (required to execute pytest with approval_policy=never).
DO NOT: edit src/** or test sources; review code structure; propose code changes; skip ACs.
DONE WHEN: every AC has {id, status: pass|fail, evidence}. Overall = pass iff all ACs pass. Wrapper script verifies post-session diff is empty outside `artifacts/` + cache paths.
```

**B. Fuller instruction (`prompts/agents/qa.md`).**
```
# Role: QA / Acceptance
Identity: behavior validator, not code reviewer.

Process:
1. Load ACs from 01-requirements.md.
2. For each AC, plan a black-box verification (API call, CLI command, or running unit/integration test tied to that AC).
3. Execute. Record evidence (command, exit code, observed output).
4. Mark pass/fail. Stop at first blocker only if it invalidates all remaining ACs; otherwise continue.
5. Write 07-qa-report.json.

Hard rules:
- Never read or comment on implementation structure.
- Never propose fixes. If a fail, describe the observed behavior and the expected behavior only.
- If an AC cannot be mechanically verified, mark status="fail" with evidence="unverifiable".
- Do not edit any file under src/**, tests/**, AGENTS.md, prompts/, schemas/. Allowed writes: artifacts/{id}/**, .pytest_cache/**, htmlcov/**, .coverage. Enforcement is the wrapper-script diff guard (Section 6); a violation auto-blocks the role and reverts.

Output shape:
{
  "task_id": "...",
  "overall": "pass|fail",
  "results": [{"ac_id":"AC-1","status":"pass|fail","evidence":"..."}]
}
```

**C. Self-check.**
```
[ ] Every AC has a result entry.
[ ] Each result has evidence.
[ ] I did not comment on code.
[ ] Overall status matches per-AC statuses.
```

### 5.8 CI/CD

**A. Short prompt.**
```
ROLE: CI/CD. TASK_ID: {id}.
GOAL: Run the readiness checklist and report machine-readable results.
READ: repo at current commit; AGENTS.md for commands.
WRITE: artifacts/{id}/08-cicd-report.json (schema: schemas/cicd-report.schema.json).
SANDBOX: workspace-write for build artifacts; network_access=true only if AGENTS.md whitelists it.
DO NOT: judge feature correctness; edit source files to make checks pass; skip security/migration checks.
DONE WHEN: every mandatory check has a status and log path. Overall pass iff all mandatory green.
```

**B. Fuller instruction (`prompts/agents/cicd.md`).**
```
# Role: CI/CD
Identity: pipeline runner. Deterministic only.

Mandatory checks (adapt commands from AGENTS.md):
1. build: `uv sync` + `python -c "import backend"` smoke.
2. lint: `ruff check src tests`.
3. format: `ruff format --check src tests`.
4. type: `mypy src` (or configured equivalent).
5. unit: `pytest tests/unit`.
6. integration: `pytest tests/integration` (if exists).
7. coverage: `pytest --cov=src --cov-fail-under=<threshold>` on changed files.
8. security: dependency scan (`pip-audit` or project equivalent), secret scan.
9. migration check: dry-run forward + backward if alembic/migrations/** changed.
10. container build (if Dockerfile changed): `docker compose build`.

Hard rules:
- If a check is not applicable (e.g. no migrations touched), mark status="skipped" with reason.
- Never edit source to fix a failing check. Report only.
- Flaky retries allowed ×2 for integration; record all attempts.
- Do not introduce new mandatory checks opportunistically. The check list is fixed; additions or removals go through AGENTS.md, not through this role.

Output shape:
{
  "task_id": "...",
  "overall": "pass|fail",
  "checks": [{"name":"lint","status":"pass|fail|skipped","duration_s":..,"log":"logs/..","reason":".."}]
}
```

**C. Self-check.**
```
[ ] Every mandatory check present.
[ ] Every check has status + log path.
[ ] No source edits made.
[ ] Overall matches per-check statuses.
```

### 5.9 Orchestrator

**A. Short prompt (only if ever run as a Codex session rather than human+bash).**
```
ROLE: Orchestrator. TASK_ID: {id}.
GOAL: Sequence role sessions per pipeline.md; enforce gates; do not re-decide.
READ: artifacts/{id}/**, pipeline.md.
WRITE: artifacts/{id}/09-orchestration-log.jsonl (append only).
SANDBOX: workspace-write (needed to invoke `codex exec`, `git`, schema validators). Diff guard restricts writes to artifacts/{id}/09-orchestration-log.jsonl.
DO NOT: edit role outputs; change ACs; override gate failures.
ESCALATE: on any gate fail beyond cap, write {status:"human_required"} and stop.
```

**B. Fuller instruction (`prompts/agents/orchestrator.md`).**
```
# Role: Orchestrator
Identity: coordinator, not decider.

Responsibilities:
- Read task from instration/tasks/.
- Score risk via rubric in AGENTS.md → pick tier (minimal|standard|high-rigor).
- For each role in pipeline.md for that tier, shell out to `codex exec` with the right profile, prompt, and schema.
- Check exit code and schema validity.
- On red: re-run role once (append validation error); second failure = escalate.
- Track caps: inner loops, review rounds, wall-clock.
- Append one line per transition to 09-orchestration-log.jsonl.

Hard rules:
- Never modify any role's output file.
- Never re-decide an ADR or AC.
- Never bypass CI/CD red.
```

**C. Self-check.**
```
[ ] Tier decision logged.
[ ] All mandatory roles invoked.
[ ] All gates evaluated before proceeding.
[ ] All caps respected.
[ ] 09-orchestration-log.jsonl complete.
```

---

## Section 6 — Codex packaging recommendations

> **Status of this section.** What follows is *design + runbook*, not shipping automation. The configuration files (`AGENTS.md`, `.codex/agents/*.toml`, `.codex/config.toml`, `.agents/skills/*/SKILL.md`, `prompts/agents/*.md`, `prompts/agents/*.allowed-writes`, `schemas/*.json`) are concrete and copy-pasteable. The orchestration scripts (`bin/pipeline.sh`, `bin/run-role.sh`, `bin/sync-agents.sh`, `bin/score-risk.py`, `bin/validate-artifact.py`, `Makefile` targets) are *specified*, not *implemented* — every invariant they're supposed to enforce (diff guard, worktree isolation, schema validation, sync-check, cap tracking) needs to be coded and tested before this pipeline is safe to run on a real repo. Treat the script descriptions below as a TDD-ready spec, not a working tool.

**Root `AGENTS.md` contents (target ≤ 4 KB).**
- One-paragraph project overview ("Heavy Lifting: MVP backend orchestrator…").
- Stack: Python 3.12, `uv`, Flask, PostgreSQL, pytest, ruff, mypy, Docker Compose.
- Directory map (by capability, not tree): `src/backend` (app), `instration/` (specs/tasks), `artifacts/<task-id>/` (agent handoff), `prompts/agents/` (role prompts + per-role `.allowed-writes`), `prompts/` (shared skill guidelines), `schemas/` (JSON schemas), `tests/`.
- Canonical commands: `uv sync`, `uv run pytest path`, `uv run ruff check path`, `uv run mypy src`, `docker compose up -d`.
- Artifact protocol: prefix order `00-brief → 01-requirements → 02-research → 03-architecture → 04-change-summary / 04-status → 05-test-plan → 06-review → 07-qa-report → 08-cicd-report → 09-orchestration-log`.
- Universal hard rules: never commit secrets; never modify `instration/project.md` except by explicit Architect ADR; never disable tests; never run `git push --force`; respect the closest-AGENTS.md-wins rule.
- Iteration caps (authoritative): Implementer inner loop 3; Reviewer rounds 2; QA rounds 1; CI/CD rounds 2; wall-clock 20 min/role; ≤80 tool calls/session.
- Risk rubric (Section 9 summary).
- Pointer: "Your role prompt tells you which role you are and which artifacts to read/write. Do not deviate."

**Nested `AGENTS.md` placements.**
- `src/backend/AGENTS.md`: module layout (api/, workers/, adapters/, protocols/, models/), coding conventions, import rules, "never import from adapters.mock_* in production code paths outside tests".
- `src/backend/workers/AGENTS.md`: the three workers' responsibilities and non-overlap; concurrency/idempotency rules; tracker back-off policy.
- `src/backend/adapters/AGENTS.md`: Protocol adherence rules; MockTracker/MockScm must implement the full protocol; adapter tests must run against a shared contract-test suite.
- `tests/AGENTS.md`: test layout (unit/, integration/, contract/), fixtures, `pytest` markers, naming conventions.
- `instration/AGENTS.md`: read-only for all roles except Task PM and Architect (and only through adding, not overwriting).

**Three durable channels, one assignment.** Codex packaging in 2026 is not "AGENTS.md plus prompts"; it's three first-class channels, each carrying the kind of content it was designed for.

| Channel | What goes here | Why this channel |
|---|---|---|
| `AGENTS.md` (root + nested) | Stack, commands, directory map, forbidden actions, artifact protocol, caps, risk rubric, code style, module contracts. Closest-wins. | Always loaded, model is trained to follow. Best for project-wide invariants every role needs. |
| `.codex/agents/<role>.toml` (project-scoped custom agents) | The 9 role definitions, each with required fields `name`, `description`, `developer_instructions` (the role body — inlined as a TOML triple-quoted string, mirroring `prompts/agents/<role>.md`), plus optional `model`, `model_reasoning_effort`, `sandbox_mode`. | Codex's native subagent surface. A *parent* Codex session can spawn any registered custom agent as a subagent (parallel where it makes sense). Top-level invocation is still `codex exec --profile <role>` (there is **no** `--agent` flag on `codex exec` per the [CLI reference](https://developers.openai.com/codex/cli/reference)) — `.codex/agents/*.toml` matters because it makes the role available for in-session subagent spawning, not because it changes how the orchestrator drives top-level sessions. |
| `.agents/skills/<name>/SKILL.md` (project-scoped skills) | Reusable workflows the agent can invoke: risk scoring, schema validation, PR opening, scope-expansion validation, status-sidecar emission. Each skill = directory with `SKILL.md` (name + description + body) plus optional helper scripts. | Progressive disclosure — Codex sees only `name`/`description` until it decides to use the skill. Keeps AGENTS.md small while making the procedure available. |
| Per-invocation prompt (`prompts/agents/<role>.md` body, injected by `bin/run-role.sh`) | Task-specific values: task id, input/output paths, current round, escalation triggers, done criteria, output schema path. | Ephemeral per-task data that doesn't belong in any durable channel. |

**Channel assignment rule.** If a fact is true for the whole project → AGENTS.md. If it's true for a specific role across all tasks → `.codex/agents/<role>.toml`. If it's a procedure invoked by multiple roles → Skill. If it's only true for this one task instance → injected prompt. **One fact, one channel — duplication is the failure mode.**

**Profile vs custom agent — why both.** `[profiles.<role>]` in `.codex/config.toml` controls how the *top-level* session runs when the orchestrator shells out (`codex exec --profile <role>` — model, sandbox, approval, reasoning effort). `.codex/agents/<role>.toml` registers the same role as a *spawnable subagent* with required fields `name`/`description`/`developer_instructions` plus optional model/sandbox overrides, so a parent session (e.g. Architect, Reviewer) can dispatch it as a child. They overlap on `model`/`sandbox_mode`/`model_reasoning_effort` for that role — both must agree.

**Avoiding role-body drift.** The role body exists in two places by necessity: `prompts/agents/<role>.md` (passed as PROMPT arg to `codex exec` for top-level dispatch — see Section 10 examples) AND `developer_instructions = """…"""` inside `.codex/agents/<role>.toml` (for subagent spawning). Single source of truth: `prompts/agents/<role>.md` is canonical; `bin/sync-agents.sh` (run from the `Makefile` `sync` target and from the pre-commit hook) regenerates each `.codex/agents/<role>.toml` by inlining the matching `prompts/agents/<role>.md` into `developer_instructions`. CI runs the same script in `--check` mode and fails if the TOMLs are stale. The same script also enforces the Section-5 embedded-payload sync: each `### 5.x` fenced block must equal the matching fenced block in `prompts/agents/<role>.md`.

**Built-in subagents we lean on.** Codex ships `default` (general fallback), `worker` (execution-focused), and `explorer` (read-heavy codebase exploration). Architect uses `explorer` as a parallel subagent for module-mapping. Implementer uses `worker` as its base. Researcher and docs lookup are user-defined custom agents (`pr_explorer`/`reviewer`/`docs_researcher` patterns from the Codex docs are *example custom agents*, not built-ins — we adapt their patterns into our 9 roles).

**Workflows packaged as scripts the orchestrator invokes (under `bin/` or `Makefile`):**
- `bin/pipeline.sh <task-id> <tier>` — main driver.
- `bin/run-role.sh <role> <task-id>` — wraps `codex exec` with role profile, schema, logging. Critically, also enforces the **post-session write guard**: after the session ends, runs `git diff --name-only HEAD` and verifies every changed path matches the role's allowed-write glob (defined per-role in `prompts/agents/<role>.allowed-writes`). Any violation → role marked `blocked`, all changes outside the allowed set reverted via `git checkout HEAD -- <path>`. This is the actual enforcer for "QA must not edit src/" — Codex's `sandbox_workspace_write.writable_roots` is *additive*, not restrictive, so it cannot be relied on to fence off `src/`.

  **Mandatory workspace isolation.** The diff guard's revert step (`git checkout HEAD -- <path>`) is destructive: if the wrapper runs in the user's main checkout with unrelated dirty changes, those changes get clobbered. **Every task MUST run in an isolated git worktree.** `bin/pipeline.sh` creates one at start (`git worktree add ../wt-<task-id> <base-branch>`), runs the entire role chain inside it, and removes it on success/abort. `bin/run-role.sh` refuses to start if `pwd` is the main checkout (detected via `git worktree list --porcelain`). This also gives free isolation between concurrent tasks if you ever run more than one at a time.
- `bin/score-risk.py <task-file>` — computes rubric tier.
- `bin/validate-artifact.py <role> <task-id>` — JSON Schema validation.
- `bin/sync-agents.sh [--check]` — regenerates `.codex/agents/<role>.toml` from `prompts/agents/<role>.md` + `.codex/config.toml` profile fields, and verifies that each `### 5.x` fenced payload in `orchestrator-research.md` matches the matching fenced block of `prompts/agents/<role>.md`. `--check` mode (used by CI and pre-commit) fails if any TOML is out-of-sync or any Section-5 payload has drifted.
- `Makefile` targets: `pipeline`, `quality` (lint/type/test), `ci-local` (full readiness checklist), `sync` (runs `bin/sync-agents.sh`).

**Per-role write allowlists (enforced by the diff guard, not by sandbox).**
- task_pm, researcher, architect, reviewer: `artifacts/{id}/**` only.
- test_writer: `artifacts/{id}/**`, `tests/**`.
- implementer: `artifacts/{id}/**`, plus declared scope from `00-brief.md` ∪ `03-architecture.md`, plus any `scope_expansions[].path` in `04-status.json`.
- qa: `artifacts/{id}/**`, `.pytest_cache/**`, `htmlcov/**`, `.coverage`.
- cicd: `artifacts/{id}/**`, build/cache paths declared in AGENTS.md.
- orchestrator: `artifacts/{id}/09-orchestration-log.jsonl` only.

**Keeping Codex instructions small but strong.** Target token budgets: root AGENTS.md ≤ 1.5 K tokens; each nested AGENTS.md ≤ 0.5 K; per-role system prompt ≤ 400 tokens; fuller `prompts/agents/<role>.md` ≤ 1 K tokens (only loaded when role needs it — it's included by the wrapper script, not by default). Repeat done-criteria at the top AND bottom of each role prompt to counter lost-in-the-middle. Prefer concrete commands over persona prose. Audit for contradictions — GPT-5/Codex is literal.

**Preventing instruction sprawl.**
- **One rule, one place.** If a rule lives in root AGENTS.md, never restate it in a role prompt.
- **No rule without an enforcer.** Every "do not" should either be enforced by the post-session diff guard (per-role write allowlist in `bin/run-role.sh`), schema (shape mismatch), or a CI check. Sandbox alone can't enforce per-path writes — `sandbox_workspace_write.writable_roots` is additive, and `read-only` blocks command execution under `approval=never`. Rules no one can verify become folklore.
- **Expire rules.** Add a `last-reviewed: YYYY-MM` stamp to AGENTS.md; drop or update rules not reviewed in 90 days.
- **Closest-wins is the knife.** Push specifics down to the nearest nested AGENTS.md; keep root general.

**Concrete file layout for Heavy Lifting.**
```
/AGENTS.md                                # universal rules, caps, artifact protocol, commands
/.codex/
  config.toml                             # [profiles.*] for each of 9 roles (model, sandbox, approval)
  agents/                                 # project-scoped custom agents (Codex-native role surface)
    task_pm.toml
    architect.toml
    implementer.toml
    researcher.toml
    reviewer.toml
    test_writer.toml
    qa.toml
    cicd.toml
    orchestrator.toml
/.agents/
  skills/                                 # project-scoped Agent Skills (reusable workflows)
    score-risk/
      SKILL.md
      score.py
    validate-artifact/
      SKILL.md
      validate.py
    open-pr/
      SKILL.md
    emit-status/
      SKILL.md                            # canonical NN-status.json emitter
/instration/
  project.md                              # existing project spec
  instruction.md                          # existing task-handling instruction
  tasks/                                  # existing atomic tasks
  AGENTS.md                               # read-only guidance for roles
/prompts/
  SKILL.md                                # shared behavioral guidelines (project-level skill prompt)
  agents/                                 # canonical role bodies; bin/sync-agents.sh inlines each into .codex/agents/<role>.toml `developer_instructions` and verifies Section-5 parity
    task_pm.md
    architect.md
    implementer.md
    researcher.md
    reviewer.md
    test_writer.md
    qa.md
    cicd.md
    orchestrator.md
    task_pm.allowed-writes                # per-role write allowlist consumed by bin/run-role.sh diff guard
    architect.allowed-writes
    implementer.allowed-writes
    researcher.allowed-writes
    reviewer.allowed-writes
    test_writer.allowed-writes
    qa.allowed-writes
    cicd.allowed-writes
    orchestrator.allowed-writes
/schemas/
  requirements.schema.json
  architecture.schema.json
  research.schema.json
  implementer.schema.json
  review.schema.json
  test-plan.schema.json
  qa-report.schema.json
  cicd-report.schema.json
  status.schema.json
/artifacts/
  <task-id>/
    00-brief.md
    01-requirements.md
    01-status.json                          # PM sidecar (status.schema.json)
    02-research.md
    02-status.json                          # Researcher sidecar
    03-architecture.md
    03-status.json                          # Architect sidecar
    04-change-summary.md
    04-status.json                          # Implementer (rich schema)
    05-test-plan.md
    05-status.json                          # Test Writer sidecar
    06-review.md
    06-status.json                          # Reviewer sidecar
    07-qa-report.json                       # QA self-statused (overall field)
    08-cicd-report.json                     # CI/CD self-statused (overall field)
    09-orchestration-log.jsonl
/bin/
  pipeline.sh
  run-role.sh
  score-risk.py
  validate-artifact.py
  sync-agents.sh                          # regenerates .codex/agents/*.toml from prompts/agents/*.md and checks Section-5 parity in orchestrator-research.md (CI: --check)
/src/backend/
  AGENTS.md
  api/
  workers/       (AGENTS.md)
  adapters/      (AGENTS.md — MockTracker, MockScm)
  protocols/
  models/
/tests/
  AGENTS.md
  unit/
  integration/
  contract/
/Makefile
/docker-compose.yml
```

---

## Section 7 — Artifact contracts

All artifacts are short, schema-validated (JSON) or template-bound (markdown), committed to `artifacts/<task-id>/`.

**1. Task Brief (`00-brief.md`).**
- **Owner:** Orchestrator.
- **Required:** Title; Task ID; Source (tracker URL or `instration/tasks/...`); Problem statement (3–5 lines); Risk tier score (rubric); Initial scope sketch.
- **Optional:** Links to prior related artifacts; constraints.
- **Max:** 30 lines / 250 words.
- **Consumers:** every downstream role.
- **Acceptance bar:** task id + problem statement + tier score present.

**2. Clarified Requirements (`01-requirements.md`).**
- **Owner:** Task PM.
- **Required:** Summary; Acceptance criteria (Given/When/Then, numbered AC-1..n); In scope; Out of scope; Open questions.
- **Optional:** Non-functional requirements (perf, security).
- **Max:** 80 lines.
- **Consumers:** Architect, Test Writer, Implementer, QA.
- **Acceptance bar:** ≥1 Given/When/Then AC; scope explicit.

**3. Architecture Note (`03-architecture.md`).**
- **Owner:** Architect.
- **Required:** Title; Status; Context; Decision; Consequences (positive + negative); Alternatives considered (≥2); Files to touch; Interface sketch.
- **Optional:** Diagrams (ascii), cross-references.
- **Max:** 1 page / 80 lines.
- **Consumers:** Implementer, Reviewer.
- **Acceptance bar:** Decision testable; ≥2 alternatives with rejection rationale; files-to-touch concrete.

**4. Research Note (`02-research.md`).**
- **Owner:** Researcher.
- **Required:** Question; Decision context; Options (≥2) with pros/cons; Recommendation; Sources with URLs.
- **Optional:** Risks of recommendation; follow-up questions.
- **Max:** 1 page / 60 lines.
- **Consumers:** Architect, Implementer.
- **Acceptance bar:** explicit recommendation + ≥2 primary sources.

**5. Implementation Plan.** Folded into `03-architecture.md` "Files to touch" + Implementer's own pre-edit sketch. For high-rigor tier only, may be promoted to `03b-implementation-plan.md` (≤ 30 lines, ordered steps).

**6. Change Summary (`04-change-summary.md`).**
- **Owner:** Implementer.
- **Required:** What changed; Why; How tested (commands + results); Risks; Rollback plan.
- **Optional:** Screenshots / logs; follow-up tickets.
- **Max:** 1 page / 80 lines.
- **Consumers:** Reviewer, QA, humans reading the PR.
- **Acceptance bar:** all five required sections non-empty.

**6b. Implementer Status (`04-status.json`).**
- **Owner:** Implementer. Schema-validated against `schemas/implementer.schema.json` (extends `status.schema.json`).
- **Required:** `{task_id, role:"implementer", status, files_changed[], tests_added[], commands_run[{cmd, exit_code}], tests_passed, iteration_count, scope_expansions[{path, reason, ac_id, evidence}]}`.
- **Acceptance bar:** schema valid; `status ∈ {ready-for-review, blocked}`; every entry in `scope_expansions[]` uses an allowed reason.

**6c. Per-Role Status Sidecar (`01-status.json`, `02-status.json`, `03-status.json`, `05-status.json`, `06-status.json`).**
- **Owner:** PM, Researcher, Architect, Test Writer, Reviewer respectively. Schema-validated against `schemas/status.schema.json`.
- **Purpose:** machine-readable handoff signal for the orchestrator independent of the prose artifact. Lets `bin/run-role.sh` gate progression on a single JSON exit value rather than parsing markdown.
- **Required:** `{task_id, role, status, artifact_path, started_at, ended_at, notes?}`.
  - `role ∈ {task_pm, researcher, architect, test_writer, reviewer}`.
  - `status ∈ {done, blocked, escalate}`. Reviewer additionally allows `request_changes` (mirrors decision in `06-review.md`).
  - `artifact_path` points to the prose artifact (e.g. `artifacts/HL-007/03-architecture.md`).
- **Acceptance bar:** schema valid; `status` consistent with the prose artifact's stated decision (Reviewer's sidecar `status` must match `Decision:` line in `06-review.md`).
- **Why a sidecar at all (vs reading the prose):** the orchestrator must not LLM-parse markdown to decide gates — every gate-relevant signal goes through schema-validated JSON. QA and CI/CD don't need a sidecar because their report files are already JSON with an `overall` field that serves the same role.

**7. Review Findings (`06-review.md`).**
- **Owner:** Reviewer.
- **Required:** Summary; Findings list `[{severity, file, line, issue, suggestion}]`; Decision (`approve|request_changes|escalate`); Round `N of 2`.
- **Optional:** Commendations.
- **Max:** 80 lines.
- **Consumers:** Implementer (if request_changes), Orchestrator.
- **Acceptance bar:** every finding has file:line; decision field present.

**8. Test Plan (`05-test-plan.md`).**
- **Owner:** Test Writer (or Implementer if folded).
- **Required:** Scope; Test levels; Test list mapped to ACs; Fixtures; Entry/exit criteria.
- **Optional:** Flakiness notes; non-functional tests.
- **Max:** 60 lines.
- **Consumers:** Implementer, QA.
- **Acceptance bar:** every AC covered by ≥1 listed test.

**9. QA Acceptance Report (`07-qa-report.json`).**
- **Owner:** QA. Schema-validated.
- **Required:** `{task_id, overall, results:[{ac_id, status, evidence}]}`.
- **Acceptance bar:** one result per AC; overall = pass iff all results pass.

**10. CI/CD Readiness Report (`08-cicd-report.json`).**
- **Owner:** CI/CD. Schema-validated.
- **Required:** `{task_id, overall, checks:[{name, status, duration_s, log}]}`.
- **Checks (mandatory):** build, lint, format, type, unit, integration (if present), coverage, security, migration (if touched), container-build (if Dockerfile touched).
- **Acceptance bar:** every mandatory check has status + log; overall = pass iff all green or valid "skipped" with reason.

---

## Section 8 — Quality model

**System-level quality attributes** (what the pipeline must preserve on every merge):

1. **Correctness** — tests pass; ACs validated.
2. **Safety** — no secrets, destructive git ops, or sandbox escapes.
3. **Reversibility** — every change has a rollback path.
4. **Traceability** — every change has a full artifact trail with source AC.
5. **Scope discipline** — diff confined to declared files.
6. **Cost efficiency** — bounded tokens/wall-clock per role.
7. **Determinism** — CI/CD checks reproduce locally.
8. **Observability** — logs/metrics for new critical paths.
9. **Evolvability** — ADRs + schemas make future change cheap.
10. **Role discipline** — no overlaps, no rubber-stamps, no redesigns in review.

**Rubric (score each 1–5):**

| Attribute | 1 (failing) | 3 (acceptable) | 5 (exemplary) |
|---|---|---|---|
| Correctness | tests not run | all listed tests pass | failing tests pre-change prove coverage |
| Safety | secrets/force-push risk | sandbox respected | MCP + sandbox hardened, network opt-in |
| Reversibility | irreversible, no note | rollback documented | rehearsed rollback |
| Traceability | artifacts missing | all present, schema-valid | JSON logs archived with token usage |
| Scope discipline | diff sprawls | within declared files | ≤ planned LOC, no tangential edits |
| Cost efficiency | caps breached | within caps | < 50% of caps |
| Determinism | flaky tests | reproducible locally | reproducible across env matrix |
| Observability | none | logs added | metrics + alerts where needed |
| Evolvability | implicit design | ADR present | ADR + contract tests |
| Role discipline | 1+ role overlapped | roles respected | all self-checks pass |

**Gate interpretation.** Standard tier requires ≥ 3 on every mandatory attribute (Correctness, Safety, Traceability, Scope, Determinism). High-rigor requires ≥ 4 on Reversibility, Observability, Evolvability. Any score of 1 = hard block.

---

## Section 9 — Recommended default blueprint

**Risk rubric (score 1–3 per axis; sum):**

| Axis | 1 | 2 | 3 |
|---|---|---|---|
| Blast radius | one internal module | one service | cross-service / shared infra |
| Reversibility | pure revert | revert w/ data cleanup | irreversible migration/API |
| Complexity | <100 LOC, 1 concept | multi-file, 1 subsystem | large refactor / new dep |
| Dependency surface | no new deps | new internal contract | new external API/DB/vendor |
| Exposure | dev-only | internal users | paying users, auth, PII |

**Tiers.** 5–6 = minimal · 7–11 = standard · 12–15 = high-rigor.

**Minimal tier (solo dev, 5–6 score).** Mandatory roles only. Implementer + QA + CI/CD. Test Writer fused into Implementer. Orchestrator = you + Makefile. Artifacts produced: `00-brief.md`, `04-change-summary.md`, `04-status.json`, `07-qa-report.json`, `08-cicd-report.json`. No ADR, no Reviewer, no PM memo.

**Standard tier (7–11 score).** Add Task PM if AC missing, and Reviewer. Usual lineup: `Orchestrator → (PM?) → Implementer → Reviewer → QA → CI/CD`. Artifacts: add `01-requirements.md`, `06-review.md`.

**High-rigor tier (12–15 score).** Full lineup. `Orchestrator → PM → (Researcher?) → Architect → Test Writer → Implementer → Reviewer → QA → CI/CD`. All artifacts present. ADR is mandatory. Reviewer is not optional. Migration dry-runs forward and backward. Observability checklist enforced. Rollback rehearsed.

**Explicit switching criteria.**
- Any **irreversible** change (DB migration, public-API change, data deletion) → high-rigor regardless of LOC.
- Any **new dependency or vendor** → at minimum standard + Architect.
- Any **cross-worker contract** or **protocol change** (TrackerProtocol/ScmProtocol) → high-rigor.
- Any **security-sensitive** code (auth, secrets, PII) → high-rigor + mandatory security review step.
- Any **pure docs / typo fix** → minimal tier; QA still runs but its check collapses to "CI lint+format green and no behavioral surface touched". QA is never skipped — see [Section 9 skip rubric](#section-9--recommended-default-blueprint).

**Skipping optional roles — explicit rubric.**
- Skip **Task PM** if the tracker ticket already has Given/When/Then AC and scope is listed.
- Skip **Researcher** unless a named decision is blocked on a specific unknown.
- Skip **Architect** if no architecturally significant decision exists (no protocol change, no new module, no data-model change).
- Skip **Test Writer** at minimal tier if Implementer can own tests and the test surface is small.
- Skip **Reviewer** only at minimal tier when risk score ≤ 6.
- Never skip QA, CI/CD, or Implementer.

---

## Section 10 — End-to-end example

**Task.** `instration/tasks/07-mock-tracker-adapter.md`: "Implement `MockTracker` adapter with `fetch_open_tasks()` and `post_comment(task_id, body)` conforming to `TrackerProtocol`." Task ID: `HL-007`.

**Risk scoring.** Blast radius 1 (adapters module) · Reversibility 1 · Complexity 1 (<100 LOC) · Dependency 1 (no new deps) · Exposure 1 (dev-only, mock). Total = **5 → minimal tier**, but because this is the first adapter, the contract being set here will bind all future adapters, so we bump to **standard tier** manually (Orchestrator rule: "first implementation of any protocol is standard tier minimum").

**Pipeline.** `Orchestrator → Implementer → Reviewer → QA → CI/CD`. Task PM skipped (task file already has testable requirements). No Architect because `TrackerProtocol` already exists. Test Writer folded into Implementer.

**Workflow with exact files and commands.**

**Step 0 — Intake (Orchestrator, you).**
```
# Mandatory: every task runs in an isolated worktree so the diff guard's
# revert step can never clobber unrelated local changes in the main checkout.
git worktree add ../wt-HL-007 main
cd ../wt-HL-007
mkdir -p artifacts/HL-007
cat > artifacts/HL-007/00-brief.md <<'EOF'
# HL-007 — MockTracker adapter
Task ID: HL-007
Source: instration/tasks/07-mock-tracker-adapter.md
Problem: Provide a MockTracker implementing TrackerProtocol so Worker 1 can be exercised without a real tracker.
Risk tier: standard (first-of-kind protocol impl).
Scope: src/backend/adapters/mock_tracker.py, tests/unit/adapters/test_mock_tracker.py, tests/contract/test_tracker_contract.py.
EOF
git add artifacts/HL-007/00-brief.md && git commit -m "HL-007: intake"
```

**Step 1 — Implementer session.**
```
./bin/run-role.sh implementer HL-007
```
Under the hood:
```
codex exec \
  --profile implementer \
  --sandbox workspace-write --ask-for-approval never \
  --output-schema schemas/implementer.schema.json \
  -o artifacts/HL-007/04-status.json \
  --json \
  --skip-git-repo-check \
  "$(cat prompts/agents/implementer.md) TASK_ID=HL-007" \
  > logs/HL-007/implementer.jsonl
```
Implementer reads `00-brief.md`, `instration/tasks/07-mock-tracker-adapter.md`, `src/backend/protocols/tracker.py`. Writes:
- `src/backend/adapters/mock_tracker.py` (in-memory deterministic stub, seedable, conforms to Protocol).
- `tests/unit/adapters/test_mock_tracker.py` (fetch returns seeded tasks; post_comment appends; idempotent on same id).
- `tests/contract/test_tracker_contract.py` (parametrized fixture run against MockTracker).
- `artifacts/HL-007/04-change-summary.md` and `artifacts/HL-007/04-status.json` (`status: ready-for-review`, `tests_passed: true`, `files_changed: [...]`).

Orchestrator validates schema, checks exit code 0. Commits: `git commit -am "HL-007: MockTracker adapter + contract tests"`.

**Step 2 — Reviewer session.**
```
./bin/run-role.sh reviewer HL-007
```
```
codex exec \
  --profile reviewer \
  --sandbox workspace-write --ask-for-approval never \
  --output-schema schemas/review.schema.json \
  -o artifacts/HL-007/06-status.json \
  "$(cat prompts/agents/reviewer.md) TASK_ID=HL-007 ROUND=1" \
  > logs/HL-007/reviewer.jsonl
# After session: run-role.sh diff-guards Reviewer to artifacts/HL-007/** only.
```
Reviewer reads `git diff HEAD~1`, `04-change-summary.md`, `src/backend/protocols/tracker.py`, `AGENTS.md`. Writes `artifacts/HL-007/06-review.md`. Suppose findings:
- `major` — `post_comment` lacks retry / idempotency test beyond single call.
- `nit` — "Nit: docstring on `_store` attribute missing".
Decision: `request_changes` round 1.

Orchestrator re-invokes Implementer with `06-review.md` injected. Implementer adds idempotency test inside `tests/unit/adapters/test_mock_tracker.py` (already in declared scope, no expansion needed), ignores the nit (valid per author preference), writes new `04-status.json` round 2 with `scope_expansions: []`. Reviewer round 2 → `approve`.

**Step 3 — QA session.**
```
./bin/run-role.sh qa HL-007
```
```
codex exec \
  --profile qa \
  --sandbox workspace-write --ask-for-approval never \
  --output-schema schemas/qa-report.schema.json \
  -o artifacts/HL-007/07-qa-report.json \
  "$(cat prompts/agents/qa.md) TASK_ID=HL-007" \
  > logs/HL-007/qa.jsonl
# After session: run-role.sh checks `git diff --name-only HEAD` is empty outside
# artifacts/, .pytest_cache/, htmlcov/, .coverage. Anything else → revert + block.
```
QA derives ACs from the task file: "AC-1: `fetch_open_tasks()` returns seeded tasks in insertion order"; "AC-2: `post_comment(id, body)` appends to task and is visible on next fetch"; "AC-3: conforms to `TrackerProtocol` (isinstance check / runtime_checkable)". For each, runs the matching test invocation (`uv run pytest tests/unit/adapters/test_mock_tracker.py::test_fetch_returns_seeded_order -q`), records exit code + output as evidence. Writes `07-qa-report.json` with `overall: pass`.

**Step 4 — CI/CD session.**
```
./bin/run-role.sh cicd HL-007
```
```
codex exec \
  --profile cicd \
  --sandbox workspace-write --ask-for-approval never \
  --output-schema schemas/cicd-report.schema.json \
  -o artifacts/HL-007/08-cicd-report.json \
  "$(cat prompts/agents/cicd.md) TASK_ID=HL-007" \
  > logs/HL-007/cicd.jsonl
```
CI/CD runs: `uv sync`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`, `uv run pytest`, `uv run pytest --cov=src --cov-fail-under=80 src/backend/adapters`, `uv run pip-audit`, migration check skipped (reason: no `migrations/**` touched), container build skipped. Writes `08-cicd-report.json` with `overall: pass`.

**Step 5 — Finalize (Orchestrator).** Worktree is merged/PR-opened from inside `../wt-HL-007`; once the PR lands the worktree is removed (`git worktree remove ../wt-HL-007`). The user's main checkout was never touched.
```
./bin/run-role.sh orchestrator HL-007   # optional Codex session; usually just human+git
git tag hl-007-ready
# open PR via SCM adapter (MockScm stage 1 = noop; in later stages real SCM)
python -m backend.cli open-pr --task HL-007 --title "HL-007: MockTracker adapter" \
    --body "$(cat artifacts/HL-007/04-change-summary.md)"
# push results back to tracker
python -m backend.cli post-tracker-result --task HL-007 \
    --qa artifacts/HL-007/07-qa-report.json --cicd artifacts/HL-007/08-cicd-report.json
```

**Artifact tree at completion.**
```
artifacts/HL-007/
  00-brief.md
  04-change-summary.md
  04-status.json
  06-review.md
  06-status.json
  07-qa-report.json
  08-cicd-report.json
  09-orchestration-log.jsonl
logs/HL-007/
  implementer.jsonl
  reviewer.jsonl
  qa.jsonl
  cicd.jsonl
```

**Total sessions:** 4 (Implementer, Reviewer×1 round of rework, QA, CI/CD). **Total wall-clock (expected):** 10–20 min. **Caps status:** Reviewer rounds 1/2, Implementer inner loops per cycle ≤ 3, no escalation.

---

## Section 11 — Final deliverables

### 11.1 Consolidated role prompt pack

Package as `prompts/agents/` directory (role bodies plus per-role `.allowed-writes` globs). Each `<role>.md` file is the Section-5 "short prompt" prepended to the "fuller instruction" and ending with the "self-check". Keep total ≤ 1.5 KB per file. Pair each with a `[profiles.<role>]` block in `.codex/config.toml`:

```toml
# IMPORTANT (April 2026): default Codex model is `gpt-5.4`. `gpt-5.4-mini` is the
# cheaper/faster sibling explicitly recommended for subagents. `gpt-5.3-codex` and
# `gpt-5.3-codex-spark` (research preview) remain available. There is no
# `gpt-5.4-codex` variant — `gpt-5.4` rolled Codex capabilities into the flagship.
#
# Sandbox note: `read-only` blocks command execution under `approval_policy = "never"`,
# so ANY role that needs to run `git diff`, pytest, ruff, mypy, etc., must use
# `workspace-write`. Per-path write restriction is not enforceable via
# `sandbox_workspace_write.writable_roots` (it is *additive*, not an allowlist) —
# the post-session diff guard in `bin/run-role.sh` is the actual enforcer
# (see Section 6).

[profiles.implementer]
model = "gpt-5.4"
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "workspace-write"

[profiles.reviewer]
model = "gpt-5.4"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "workspace-write"   # needs `git diff`; diff guard enforces no source edits

[profiles.qa]
model = "gpt-5.4"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "workspace-write"   # needs to run pytest; diff guard enforces no source edits

[profiles.cicd]
model = "gpt-5.4-mini"
model_reasoning_effort = "low"
approval_policy = "never"
sandbox_mode = "workspace-write"
[profiles.cicd.sandbox_workspace_write]
network_access = true   # for dependency scan

[profiles.architect]
model = "gpt-5.4"
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "workspace-write"   # may need git/grep for context; diff guard enforces no code edits

[profiles.task_pm]
model = "gpt-5.4-mini"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "workspace-write"   # diff guard restricts writes to artifacts/

[profiles.researcher]
model = "gpt-5.4"
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "live"     # default is "cached"; Researcher needs fresh sources
[profiles.researcher.sandbox_workspace_write]
network_access = true   # web_search/web_fetch

[profiles.test_writer]
model = "gpt-5.4"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "workspace-write"   # diff guard restricts writes to tests/** + artifacts/

[profiles.orchestrator]
model = "gpt-5.4-mini"
model_reasoning_effort = "low"
approval_policy = "never"
sandbox_mode = "workspace-write"   # only orchestration log writes; diff guard enforces
```

### 11.2 Consolidated orchestration design

```
                  ┌─────────── risk score → tier ───────────┐
                  │   5–6 minimal   7–11 standard   12–15 high-rigor
                  ▼
   INTAKE ── 00-brief.md, risk tier
      │
      ▼
   [PM?]    01-requirements.md              (skip if AC present)
      │
      ▼
   [RESEARCH?] 02-research.md               (skip unless decision blocked)
      │
      ▼
   [ARCH?]  03-architecture.md              (skip if not architecturally sig.)
      │
      ▼
   [TEST-WRITER?] 05-test-plan.md + failing tests   (high-rigor / large surface)
      │
      ▼
   IMPLEMENTER  diff + 04-change-summary.md + 04-status.json
      │                                     (inner loop ≤3)
      ▼
   [REVIEWER?] 06-review.md                 (std+; ≤2 rounds)
      │  ↳ request_changes → back to IMPLEMENTER
      ▼
   QA          07-qa-report.json            (mandatory; ≤1 rework round)
      │  ↳ fail → back to IMPLEMENTER or escalate
      ▼
   CI/CD       08-cicd-report.json          (mandatory; ≤2 rework rounds)
      │  ↳ red → back to IMPLEMENTER
      ▼
   ORCHESTRATOR finalizes → PR + tracker update
                    09-orchestration-log.jsonl
```

Every box = a fresh `codex exec` with profile + schema + log. Every arrow = filesystem handoff. Every gate = schema-valid artifact + exit code. Any `status: "blocked"` or cap breach halts and asks the human.

### 11.3 Top operating rules

1. **One role, one session, one responsibility.** No role does another's job. Overlap is the #1 failure mode.
2. **Filesystem is the bus.** No cross-session memory is trusted; every handoff is a committed file.
3. **Every rule has an enforcer.** Sandbox, schema, or CI check — or it's folklore.
4. **Closest `AGENTS.md` wins.** Push specifics down; keep root terse.
5. **Schemas over prose for handoffs.** Use `--output-schema` for every machine-consumed artifact.
6. **Caps are hard, not aspirational.** Inner loops 3, Reviewer rounds 2, wall-clock 20 min, tool calls ≤ 80.
7. **Deterministic checks outrank self-report.** Trust `pytest` / `ruff` / `mypy` exit codes, not the agent's "done".
8. **Rigor tracks risk, not seniority.** A solo dev doing a migration runs the high-rigor pipeline.
9. **Network off by default.** `workspace-write` does not imply internet; enable per-role only when needed.
10. **Escalate, don't loop.** Any cap breach or ambiguity → emit `{status:"blocked"}` and stop. Humans resolve, agents don't grind.
11. **Surface assumptions; never disambiguate silently.** When inputs are ambiguous or multiple readings are valid, an autonomous role either emits `{status:"blocked"}` or records the picked interpretation/assumption explicitly in its artifact (ADR Assumptions, requirements Open questions, Researcher's `Interpretation chosen`, change summary). A silent guess is a pipeline defect even when the code is correct.
12. **Simplest solution that satisfies ACs.** No speculative flexibility, configurability, or extension points that are not required by an AC or ADR. Reviewer flags overcomplication at least as `major`.
13. **Surgical changes only.** Inside touched files, change only what the task requires. No opportunistic cleanup, rename, refactor, or reformat. Unrelated dead code is noted, not deleted.

### 11.4 Top anti-patterns to avoid

1. **Agent theater.** Trusting the model's "task complete" without running the tests it claims passed.
2. **Reviewer-as-author.** Reviewer rewriting the solution instead of evaluating the author's approach.
3. **Architect-as-Implementer.** Bottleneck; ADRs become after-the-fact archaeology.
4. **QA as code reviewer.** Misses behavior while duplicating style nits already enforced by lint.
5. **CI as QA.** Green pipeline treated as acceptance; ACs never actually validated.
6. **Unbounded review rounds.** Reviewer ↔ Implementer ping-pong on nits until context melts.
7. **Single mega-prompt.** One Codex session playing all roles; context contamination and early termination dominate.
8. **Rule sprawl in AGENTS.md.** File grows past 32 KiB, gets truncated, agents start ignoring sections silently.
9. **Preamble over-prompting in non-interactive runs.** Verbose plan-before-you-act instructions cause premature "done" in `codex exec` — explicitly warned against in the Codex prompting guide.
10. **Network-on YOLO mode.** `--dangerously-bypass-approvals-and-sandbox` on a dev laptop with real credentials; the lethal trifecta (private data + untrusted content + exfiltration path) materializes fast.
11. **Silent disambiguation.** A role picks one reading of an ambiguous AC/ADR without recording the choice. Downstream QA validates the wrong behavior; the drift is invisible until integration.
12. **Speculative flexibility.** Adding config knobs, extension points, or single-use abstractions "for the future" when no AC or ADR requires them. Bloats the diff, multiplies review surface, rarely used.
13. **Opportunistic cleanup.** Refactor, rename, or reformat adjacent code inside a touched file "while I'm here". Breaks blame, blows up the diff, hides the real change from the Reviewer.
14. **Defensive branches without a scenario.** `if x is None: raise` or generic try/except added for states not reachable by any AC, contract, or invariant. Masks real bugs and inflates test surface.

## Conclusion

The model above is deliberately boring: a fixed pipeline of fresh `codex exec` sessions, short markdown/JSON artifacts in git, schema-validated handoffs, and hard caps. The boringness is the point — Codex CLI gives you primitives (`AGENTS.md` auto-loading, `--output-schema`, fresh sessions, sandbox modes, exit codes) that make a deterministic, auditable pipeline cheaper than any graph framework or swarm. The upside you buy from multi-agent orchestration — independent contexts, narrower specialists, stronger boundaries — is real; the downside — token burn, drift, agent theater — is avoided only by hard caps and external verification, not by cleverer prompts. For Heavy Lifting specifically, start minimal-tier on the Mock adapters and plumbing, step up to standard-tier as soon as you touch the real Protocols, and reserve the full high-rigor pipeline for the inevitable day you replace MockTracker with a production adapter that talks to a real system. The rubric, not the team size, decides.