# Architecture overview

This describes the system the parts in this repository were extracted from: a Claude Code
agent that operates a one-person business day to day (content sites, publishing, health
checks, reporting, ad optimisation loops, client operations). Only the generic, reusable
pieces are published here; the business-specific parts stay private.

## The shape in one picture

```
            operator (reads chat only, often on a phone)
                         |
                   chat bridge (MCP)
                         |
   +---------------- main agent session -----------------+
   |  instructions layer   short CLAUDE.md: identity, red  |
   |                       lines, pointers. Nothing else.  |
   |  rules layer          one canonical file per rule +   |
   |                       an index; path-scoped rules     |
   |                       load only when matching files   |
   |                       are touched                     |
   |  skills               SOPs loaded on demand           |
   |  autonomy tiers       AUTO / NOTIFY / ASK seating     |
   +--------+-------------------+--------------------------+
            |                   |
     PreToolUse / Stop     sub-agents (dispatch, then verify the
     hooks = structural    artifact, never the claim)
     controls outside            |
     the model's judgment   schedules (approved jobs run unattended)
            |
     ledgers: commitments, decisions, violations (append-only)
            |
     behaviour eval suite (re-run on every model change)
```

## Layers and why each exists

**1. Instructions layer (small on purpose).** The always-loaded instruction file holds only
identity, the red lines and pointers. Every always-loaded line is a tax on every turn, and
emphasis inflation ("CRITICAL", "HIGHEST PRIORITY" everywhere) makes all of it weaker. An
earlier version said the same rule in three places (prompt, hook message, index); cutting
that redundancy made the remaining lines more reliable, not less.

**2. Rules layer.** Each rule has exactly one canonical file with the why and the how, plus
a one-line entry in an index. Path-scoped rules (frontmatter `paths:` globs) load only when
the agent is about to touch matching files, for example CMS safety rules only when editing
CMS scripts.

**3. Skills.** Multi-step procedures (root-cause loop, dispatch, publishing pipelines) live
in skills that load on demand. See `skills/` for three generic templates.

**4. Autonomy tiers.** The act-or-ask decision is a lookup, not a judgment call. See
[`autonomy-tiers.md`](autonomy-tiers.md) and `classifier/`.

**5. Hooks.** Anything that must hold even when the model forgets goes into a hook:
deterministic, no model calls, fail-open, with a human-supplied confirmation token as the
only bypass for safety guards. Hooks are where incident lessons go once a prose rule has
failed at least once. See `hooks/`.

**6. Ledgers.** Append-only JSONL files:
- *commitments*: every promise has an id and an ETA and is closed only via a CLI with a note;
- *decisions*: what the human decided, so "you told me before" can be traced to a source;
- *violations*: each incident with trigger, root cause, fix, prevention and re-test.

**7. Sub-agents.** The main session dispatches parallelisable work, supervises and verifies.
Two hard-won rules: dispatch is not done (check the artifact, not the report), and ask
existing agents before spawning new ones (see the duplicate-dispatch guard).

**8. The operator only reads chat.** Every message for the human goes through the chat
tool. Terminal output is invisible to them. Interactive terminal dialogs are blocked
because nobody is at the terminal to answer them.

**9. Schedules.** Approved recurring jobs (health patrols, backups, reports) run
unattended. Edits to a scheduled script go live on the next run, so risky changes ship
behind an off-by-default flag file until reviewed.

**10. Behaviour evals.** Real incidents become deterministic test cases, run through the
Claude Code CLI on every model change. A case that flips from PASS to FAIL means that
lesson needs a stronger mechanism before switching models.

## Design rules that recur everywhere

- **Fail open in guards, fail closed in red lines.** A hook that crashes must not block the
  agent; a red-line guard that detects its signal must block until a human confirms.
- **Prefer a miss over a false block in high-frequency hooks.** A guard that misfires
  produces block-resend loops and teaches the agent to route around guards.
- **Block once, then trust** for judgment-adjacent checks (status claims): the first block
  forces a look, the identical resend passes.
- **Every proactive message closes its loop.** A detector that only posts "X looks wrong"
  creates work for the human; it should propose or apply the fix.
- **Numbers need a source, URLs need a 200, "done" needs evidence.**
