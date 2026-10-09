---
name: feature-spec
description: Starts the next feature by finding the first open phase in specs/roadmap.md, creating a branch, interviewing the user about scope, decisions and context, and writing a dated spec directory under specs/ with requirements.md, plan.md and validation.md. Use when the user says "feature spec", "next phase", "start the next feature", or invokes /feature-spec.
---

# Feature Spec

Adapted from the DeepLearning.AI SDD course skill for ParkingSpotter.

## Workflow

### 1. Find the next phase

Read `specs/roadmap.md`. The next phase is the first `## Phase N` section with
any unticked `[ ]` item, unless the user names a different phase. Note its
number, name and the `todo.md` item id(s) it cites (for example `R0.1`).

### 2. Create the branch

```
git checkout -b phase-N-<kebab-name>
```

If the session already has a designated branch, use that instead.

### 3. Read the guidance

Before asking anything, read:

- `specs/mission.md` and `specs/tech-stack.md`
- `AGENTS.md` (guardrails, security invariants, verification gate)
- The cited section(s) of `todo.md`: goal, likely files, required
  implementation, acceptance criteria, progress
- The files those sections list as likely to change

### 4. Interview the user BEFORE writing any files

Ask exactly three questions in one message (use a structured question tool if
the agent has one). Pre-fill each with what `todo.md` already decides, so the
user only confirms or overrides:

| Header | Question focus |
|--------|----------------|
| **Scope** | What is in and out for this phase; anything from `todo.md` to defer or add |
| **Decisions** | Open implementation choices: defaults, env var names, thresholds, new dependencies |
| **Context** | Constraints shaping the work: footage or hardware available, deadlines, what to test manually |

Do not write files until all three are answered.

### 5. Write the spec directory

Name: `specs/YYYY-MM-DD-<feature-name>/` with today's date.

#### `requirements.md`
- **Scope**: in and out of scope; data, endpoint or CLI tables where useful
- **Decisions**: choices made and why (from the interview and `todo.md`)
- **Context**: guardrails that apply (cite `AGENTS.md`), files and patterns to
  follow, source `todo.md` section

#### `plan.md`
- Numbered task groups (for example: Core logic → API/CLI → Frontend → Tests → Docs)
- Each group has numbered sub-tasks and is independently implementable and
  committable

#### `validation.md`
- Automated: `python -m pytest`, `cd frontend && npm run lint && npm run build`,
  plus the specific test assertions this phase requires (from the `todo.md`
  acceptance criteria)
- Manual: walkthrough steps, edge cases, benchmark runs where relevant
- Definition of done: gate green, acceptance criteria met, docs updated,
  boxes ticked in `specs/roadmap.md` and `todo.md`

### 6. Stop for review and routing

Show the user the three files and wait for approval. Before implementing,
look up the phase's task class in `docs/MODEL-ROUTING.md`, tell the user the
recommended model and effort level, and ask them to confirm they have
switched. Do not write code until they confirm.

## Constraints

- Respect `specs/tech-stack.md` and every guardrail in `AGENTS.md`; no new
  dependencies without the user's approval.
- Never weaken `POST /spots` HMAC; new write endpoints get auth and size limits
  in the same phase.
- Keep each phase focused and independently shippable. If a phase is too big
  for one PR, propose splitting it in `roadmap.md` instead.
