# Autonomy tiers: AUTO / NOTIFY / ASK

This is the decision layer for "do I act, or do I ask?". It is written as a seating chart
for actions, not as advice, and it ships with a machine-readable version
(`classifier/tiers.json`) and a hook that enforces it (`classifier/autonomy_tier.py`).

## Core principle: classify when you write the table, not when the agent is mid-task

The dangerous way to grant an agent more autonomy is to let it judge, at run time, whether
an action is reversible. Sooner or later it judges wrong, and it is most confidently wrong
in exactly the situations where it is usually right. Publicly reported incidents of coding
agents deleting production data or backups have this shape.

So the control point sits outside the agent's judgment. The run-time job is to **look up a
seat**, not to reconsider "should I ask?" every time. The three tables below are the seats.

---

## AUTO: reversible and tiny blast radius, so just do it

**Criteria:** read-only, or the effect can be undone cheaply (overwrite, revert, append-only),
and a mistake costs almost nothing.

| Action type | Example | Why |
|---|---|---|
| Read any file, git log, notes | Read, Glob, Grep | read-only |
| Web search, fetch a URL | WebSearch, WebFetch | read-only, repeatable |
| Search your own reference library | local search tools | read-only |
| Local draft that is not sent | write to a scratch or drafts folder | not external, overwritable |
| Analysis, benchmarks, reports | research notes | not external |
| Create a git commit (no force push) | `git commit` | revertable |
| Backups | copy to `backups/` | append-only |
| Read chat history | fetch messages | read-only |
| Read-only diagnostic scripts | `check_*.py` that change no state | no state change |

In one line: **read, search, draft, read-only local scripts, backups = AUTO.**

---

## NOTIFY: has a sensible default, so do it and say so afterwards

**Criteria:** a reversible write or a low-impact internal action with a clear conservative
default. The human does not need to approve it first, but should be able to see it and roll
it back. Do it, then mention it in one line in the end-of-task report. Do not interrupt
mid-task to announce it.

| Action type | Example | How it is reported |
|---|---|---|
| Edit an existing rule or memory file | append to a learning log | "appended a learning entry" |
| Create a new outbox or draft file | worker output | "output is at [path]" |
| Run an approved scheduled task | cron, scheduler | "job X finished" |
| Run an approved local script | `scripts/*.py` | "ran Y, result Z" |
| Progress message in an internal channel | status update | "posted a progress update" |
| Record a decision in the decision log | decision ledger | listed in the final report |
| Register or update a commitment | commitment ledger | listed in the final report |

In one line: **write existing files, send progress, run approved schedules = NOTIFY.**

Rewrite the habit, not just the rule: the old "shall I send this update?" becomes "sent a
progress update, tell me if it needs changing". For low-impact actions that do touch the
outside world, a short objection window (for example 15 minutes) works well: if no
objection arrives, it is final.

---

## ASK: irreversible, high-impact, client-facing or over budget, so stop and ask

**Criteria (any one is enough; if none apply, do not ask):** the effect cannot be undone at
an acceptable cost, the blast radius is large, it is directly visible to a client or the
public, it exceeds an approved budget, or it touches a red line or the rules themselves.

| Trigger | Example | How to ask |
|---|---|---|
| Bulk delete of more than 10 items (red line) | any platform | list them + "delete these N items?" |
| Direct CMS changes (red line) | posts, plugins, passwords, core config | "this change needs your OK: [exact change]" |
| External sending | cold email, social post, client deliverable | "ready to send, reply 1 to confirm" |
| Spending beyond the approved budget | any new charge | "this costs X, OK?" |
| Installing an unreviewed plugin or tool | new package, CMS plugin | list it + reason + ask |
| Changing the agent's instructions or adding a rule | any rule content | show a diff, "is this change OK?" |
| Changing a client's site | any client website change | impact description + ask |
| Writing into the reviewed knowledge base | promoting a draft | "the draft is at [path], can it go in?" |
| Changing a red line or the autonomy boundary itself | red lines, the core principles | always ASK, never self-modified |
| Irreversible and high impact | production deploys, database deletion, payments | options A/B + a recommendation |

In one line: **delete more than 10, install plugins, publish externally, change client sites,
change red lines = ASK.**

When you ask, act like a chief of staff: **bring options, not just the problem.** "I recommend
A because ..., the alternative is B." One message asks only the single most blocking
question; everything else proceeds on conservative defaults.

---

## Downgrade list: things agents wrongly ask about

These were asked again and again in practice. They should not be asked any more.

| What the agent used to ask | Correct handling |
|---|---|
| "Should I continue?" (direction is clear) | continue (AUTO / NOTIFY) |
| "Is it OK to do it this way?" (an AUTO or NOTIFY action) | do it, report it at the end |
| "Which direction do you want?" (a precedent exists) | check the decision log, follow precedent |
| "Should I ...?" (uncertain) | confidence > 70%: do it. Below 70%: do the conservative default and say so afterwards. **Uncertain is not a reason to ask**: uncertainty is a confidence problem, not an escalation condition |
| "Is this right?" (you can check it yourself) | check it yourself (curl, read, git log) |
| Several questions in one message | ask only the most blocking one, default the rest |

Key mindset: in areas where the human's values are already clear, ask yourself once "how
would they choose?" and, at 70% or more confidence, apply their framework and decide,
rather than bouncing the question back.

---

## When an action is not in any table

```
1. In the AUTO table?    -> do it, no notification.
2. In the NOTIFY table?  -> do it, one line in the final report.
3. Hits an ASK trigger?  -> stop, bring options A/B + a recommendation, ask one question.
4. A brand-new kind of action:
   ask "what is the worst outcome, and can it be rolled back?"
   -> rollback-able and low impact: treat as NOTIFY, do it, say so afterwards.
   -> irreversible or high impact: treat as ASK, stop and ask.
   -> report the classification so the human can add it to the table
      (changing the table is itself ASK).
```

The classifier implements step 4 conservatively: unknown actions get `unknown_tier`
(NOTIFY by default) and are logged as `unclassified`, so the table grows deliberately.

---

## Self-calibration: a healthy approval rate is 70 to 90 percent

- **Approval rate above 90%**: the bar is too low, the human is rubber-stamping and no real
  oversight is happening. Downgrade some ASK actions to NOTIFY.
- **Approval rate below 70%**: the bar is too high, the agent's ability is wasted and the
  human drowns in decisions. Loosen some NOTIFY or ASK actions.
- Review the real approval rate once a quarter and adjust the table (that adjustment is
  ASK: show a diff).
- **Hard trigger on unusual volume, regardless of confidence:** if action volume suddenly
  explodes (normally 5 emails, suddenly 400), escalate to ASK. The duplicate-dispatch guard
  applies the same idea to sub-agent spawning.
- The goal is to move the agent from "collaborator who checks in constantly" towards
  "approver who stops only at predefined conditions", with ASK below roughly 20% of actions.

These thresholds are working heuristics from one operator's practice, not measured
constants. Tune them to your own tolerance.
