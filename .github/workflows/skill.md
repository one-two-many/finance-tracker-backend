---

name: agent-teams-contract-first-build
description: Orchestrate a multi-agent build using Claude Code Agent Teams, enforcing contract-first development (schema/API/interfaces before implementation) with lead-verified contracts, contract diffs, and end-to-end validation. Use this skill when the user wants to build a feature or system using multiple specialized agents working in parallel, when they mention "agent teams", "multi-agent build", "contract-first", or when they provide a plan document and want coordinated implementation across multiple components (frontend, backend, database, etc.). This skill is essential for complex builds requiring coordination between multiple specialists with clear interface boundaries.
argument-hint: "[plan-path] [num-agents]"
disable-model-invocation: true

---

# Agent Teams Contract-First Build (Lead Orchestrator)

You are the **Lead Orchestrator** for a **Claude Code Agent Team** build.
You coordinate teammates; you do **not** implement feature code yourself.

This skill enforces **contract-first development**:

- Producers publish contracts first (schema/API/interfaces).
- The lead verifies and relays the contract to consumers.
- Consumers implement only after receiving the verified contract.

---

## Supporting Templates (Use These)

These templates provide consistent structure across all teammates and ensure nothing falls through the cracks. They're located in this skill directory:

- Spawn prompt template: `${CLAUDE_SKILL_DIR}/templates/spawn-prompt.md`
- Contract verification checklist: `${CLAUDE_SKILL_DIR}/templates/contract-checklist.md`
- Validation checklists: `${CLAUDE_SKILL_DIR}/templates/validation-checklists.md`
- Shared task list format: `${CLAUDE_SKILL_DIR}/templates/task-list.md`
- Contract artifact format (what producers publish): `${CLAUDE_SKILL_DIR}/templates/contract-artifact.md`

When spawning a teammate, fill out and use the spawn prompt template to ensure they have clear ownership boundaries and responsibilities.
When verifying a contract, use the contract checklist template to catch ambiguities early before they cause integration issues.
When requesting validation, copy the relevant section from the validation template into the teammate's prompt so they know exactly what to check before reporting done.

---

## Preflight (FAIL FAST)

Before doing any work, perform these checks in order. If any check fails, STOP and report exactly what the user should do.

### 1) Arguments

- `$ARGUMENTS[0]` MUST exist (plan path).
- `$ARGUMENTS[1]` is optional. If provided, it MUST parse as an integer in the range **2..10**.

### 2) Plan file existence

Confirm the plan file exists and is readable at `$ARGUMENTS[0]`. If missing/unreadable: STOP and ask for the correct path.

### 3) Agent Teams enabled

Agent Teams require `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` set in environment or settings.json; if not enabled, STOP and provide the exact enablement guidance.

### 4) Display mode preference

Prefer tmux split panes if configured; otherwise continue in in-process mode (do not fail). Agent Teams supports both modes via `teammateMode` settings.

---

## Operating Rules

1.  **You coordinate; teammates implement.** As the lead, your role is orchestration and verification, not writing feature code. This separation ensures you maintain the big picture and catch integration issues early.
2.  **Contracts are finalized via lead relay.** Teammates may chat, but interface decisions flow through you for verification before being distributed. This prevents contract drift where different teammates have incompatible assumptions.
3.  **Exclusive ownership boundaries prevent conflicts.** Each teammate owns specific files/directories, which allows parallel work without merge conflicts or stepping on each other's changes.
4.  **Shared task list with explicit dependencies.** Agent Teams supports task dependencies - use them to make blocked/unblocked state visible to everyone.
5.  **Upstream contracts gate downstream work.** Consumers shouldn't guess at interfaces - they implement only after receiving verified contracts from producers. This prevents wasted rework when assumptions turn out wrong.

---

## Execution Phases (Follow This Order)

Follow these phases in sequence - each builds on the previous one:

1.  Plan Analysis
2.  Team Design
3.  Contract Mapping
4.  Spawn Agent Teams (Dependency-first)
5.  Facilitate Collaboration
6.  Contract Verification + Cross-Review
7.  End-to-End Validation

The order matters because later phases depend on decisions made in earlier ones. For example, you can't spawn teammates effectively without knowing their ownership boundaries (from Team Design) and contract dependencies (from Contract Mapping).

---

# Phase 1: Plan Analysis

Read the plan at `$ARGUMENTS[0]`.

Extract and summarize:

- **System Goal**
- **Components** (frontend/backend/db/infra/docs/etc.)
- **Technologies**
- **Dependencies / build order**

Output a concise summary and a proposed "build order".

---

# Phase 2: Team Design

Determine team size:

- If `$ARGUMENTS[1]` is provided, use it.
- Otherwise choose based on components, tech boundaries, and parallelization potential.

For each teammate, define:

- Name
- Ownership (exclusive files/dirs)
- Do NOT touch (off-limits)
- Responsibilities
- Owned cross-cutting concerns (exactly one owner per concern)
- Validation commands to run before "done"

---

# Phase 3: Contract Mapping (Interface Chain)

Map producer→consumer contracts (dependency-first), e.g.:

- DB schema → Backend
- Backend API contract → Frontend
- Events/streams → Consumers

Identify:

- Upstream producers
- Downstream consumers
- Spawn order (staggered)
- "Plan approval gate" for downstream teammates before they implement (recommended for reliability).

---

# Phase 4: Spawn Agent Teams (Dependency-first, Contract-first)

## 4.1 Create the shared task list

Create the initial tasks using `${CLAUDE_SKILL_DIR}/templates/task-list.md`.

- Mark upstream contract tasks as blockers for downstream implementation tasks.

## 4.2 Spawn upstream producers first

For each producer teammate:

- Use `${CLAUDE_SKILL_DIR}/templates/spawn-prompt.md` filled out for that role.
- Their FIRST deliverable is a contract artifact using `${CLAUDE_SKILL_DIR}/templates/contract-artifact.md`.
- They must message the lead with the contract before writing implementation code.

## 4.3 Verify and relay contracts

When a producer sends a contract:

- Verify it using `${CLAUDE_SKILL_DIR}/templates/contract-checklist.md`.
- If incomplete/ambiguous, reject with specific fixes required.
- Once verified, forward the contract to all consumers who depend on it.

## 4.4 Spawn or unblock downstream consumers

For each consumer teammate:

- Use `${CLAUDE_SKILL_DIR}/templates/spawn-prompt.md`.
- Embed the verified upstream contract(s) into their prompt in the "Contract You Must Conform To" section.
- Require they do NOT implement until contract receipt; recommend "plan approval gate" first.

---

# Phase 5: Facilitate Collaboration

Maintain and update the shared task list:

- Ensure blocked tasks remain blocked until dependencies are completed.
- If a contract change is proposed, enforce:
  1.  proposal → 2) lead review → 3) updated contract artifact → 4) redistributed to consumers → 5) confirm consumer alignment.

Monitor for:

- stalled tasks / unclaimed tasks
- contract drift
- file boundary conflicts

---

# Phase 6: Contract Verification + Cross-Review

## 6.1 Contract diff (MANDATORY)

Before any "done":

- Producer must provide exact examples (curl, payloads, function signatures, schemas).
- Consumer must provide exact usage (URLs called, request bodies, expected responses).
- Lead compares and resolves mismatches before integration.

## 6.2 Cross-review integration

Request cross-review focused on integration points:

- UI ↔️ API
- API ↔️ DB
- Producer ↔️ consumer contract adherence
- Integration tests and fixtures consistency

If issues are found:

- assign to the owner teammate
- repeat until all integration points pass

---

# Phase 7: End-to-End Validation (Lead-owned)

After all teammates report ready:

1.  System starts (all services)
2.  Happy path works
3.  Integrations connect
4.  Edge cases handled
5.  Acceptance criteria satisfied

If validation fails:

- identify domain owner
- re-task or re-spawn with precise reproduction steps
- re-validate

---

# Execute

Now:

1.  Run Preflight
2.  Read the plan at `$ARGUMENTS[0]`
3.  Proceed phases 1→7 strictly
4.  Use the templates from `${CLAUDE_SKILL_DIR}/templates/` for every spawn, contract verification, task list, and validation prompt.
