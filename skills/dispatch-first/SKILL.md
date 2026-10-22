---
name: dispatch-first
description: Use when the main agent receives a high-priority task, a task with 3 or more steps, or work that can run in parallel (multi-site audits, batch outreach, multi-file refactors, long drafts, N keyword lookups, fact-checking several sources, dashboard clean-ups). Also use when the operator says "why didn't you hand that off", "you don't have to do everything yourself", "split it up", or at the "it's faster if I just type it" reflex.
---

# Dispatch first

The main session is a commander: **dispatch, supervise, verify.** Typing everything by hand
feels diligent and is usually the slower path: two minutes spent writing a good brief buys
thirty minutes of parallel work.

## Rule 1: three questions before starting any task

1. **Can it be split?** 3+ steps with at least one independent step -> dispatch that part.
2. **Is it repeated?** The same action N times (5 site audits, 10 keyword lookups) -> one
   dispatch, not N manual runs.
3. **Can it be supervised instead of typed?** Long drafts, search sweeps, audits, 5+ web
   searches, dashboard tidy-ups -> dispatch; you write the spec and do acceptance.

Any "yes" -> dispatch.

## Rule 2: what the main session always does itself

- talking to the operator (sub-agents never message the operator directly);
- the root-cause analysis and meta reflection for incidents (keeps one audit trail);
- shipping structural guards (hooks, lints);
- decisions that change the rules or the architecture (and those go to the operator);
- closed-set questions to the operator.

## Rule 3: doing it yourself is fine when you have capacity

Do it by hand only when none of these "overloaded" signals is present:

- an overload or backlog alert is showing;
- the operator has waited more than 5 minutes for a reply;
- you are stuck, near your context budget, or hitting repeated lint blocks;
- 5+ actions are stacked in this turn and not cleared.

Any signal -> stop pushing through alone and dispatch.

## Rule 4: before you dispatch, check who already exists

List the existing agents first. If one already owns this work unit, **message it** and ask
what it found. Spawning a new agent with an old agent's name does not resume it; it creates a
duplicate, and duplicates produce conflicting answers. (The duplicate-dispatch guard in
`hooks/` enforces this.)

## Rule 5: a complete brief

Every dispatch carries six things, or the worker improvises in the wrong direction:

1. the goal and why (one sentence of what the operator actually wants);
2. the tools, APIs and credential *paths* it may use (never the values);
3. the steps in order, and the SOP or skill to follow;
4. the output format and where to write it;
5. what to do on failure (fallback, when to stop and report);
6. priority, and what to do if it conflicts with other work.

Add the facts it must read first, so it does not invent them.

## Rule 6: dispatch is not done

When a worker reports "done", check the artifact yourself (open the file, curl the URL,
look at the rendered page) before telling the operator. Relay evidence, not claims. See
`skills/verify-before-done`.

## Example: the wrong path and the right one

Wrong: the main session stacked five actions by hand (compare files, flag issues, ship a
hook, edit settings, rewrite a reply twice after lint blocks), 18 minutes, while the
operator waited and finally asked "why didn't you hand this off?".

Right: at minute 1, dispatch a research worker for the fact check and a writing worker for
the corrected page; the main session ships the hook (its own job) and keeps the operator
updated. Same result in 6 to 8 minutes, and the operator is never left waiting.
