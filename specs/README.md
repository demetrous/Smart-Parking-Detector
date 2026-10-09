# Specs

This repo is developed spec-first, following the workflow from DeepLearning.AI's
"Spec-Driven Development with Coding Agents" course (JetBrains): write a short
Markdown spec, let a coding agent implement it, validate with a human in the
loop, then replan.

## Layout

```
specs/
  mission.md        why the project exists, who it is for, what matters now
  tech-stack.md     services, hard constraints, verification gate
  roadmap.md        small phases, each one branch and one PR
  YYYY-MM-DD-<feature>/
    requirements.md scope, decisions, context
    plan.md         numbered task groups, each independently implementable
    validation.md   automated + manual checks and the definition of done
.claude/skills/feature-spec/SKILL.md   the skill that writes a phase spec
```

`mission.md`, `tech-stack.md` and `roadmap.md` together are the project
**constitution**. Agents read them before drafting or implementing anything.
`AGENTS.md` remains the authoritative guide for guardrails and process.

## The loop

1. **Spec.** Run the `feature-spec` skill. It finds the next open phase in
   `roadmap.md`, makes a branch, asks three questions (scope, decisions,
   context), and writes the dated spec directory. Review and edit the spec
   before any code is written.
2. **Route.** Check `docs/MODEL-ROUTING.md` for the phase's task class and
   switch to the recommended model and effort before implementing.
3. **Implement.** "Implement the task groups in `specs/<dir>/plan.md`." One
   group at a time is fine; commit per group.
4. **Validate.** Run everything in `validation.md`, including the verification
   gate. A separate session on a different model reviews the diff against
   `validation.md` before merge.
5. **Close out.** Tick the phase's boxes in `roadmap.md` and the matching
   Progress boxes in `todo.md` in the same PR.
6. **Replan.** After each merge, adjust `roadmap.md` if what you learned
   changes the order or scope. Ideas that are not yet phases go in
   `specs/backlog/`.

One phase per conversation thread keeps each one reviewable on its own. Run
phases in parallel only when they touch different files.

## Relationship to `todo.md`

`todo.md` holds the detailed July 2026 specs (goal, likely files, required
implementation, acceptance criteria). It stays the source those phases draw
from; a phase's `requirements.md` and `validation.md` restate the relevant
section in this format and add the decisions made in the interview.
