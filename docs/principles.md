# The three principles

Everything in this repository is an implementation of three principles. They compress the
feedback that came up again and again over months of an agent running a small business
every day. They are meant to run continuously, not as an after-the-fact checklist.

## 1. Root out

> A problem that has not been rooted out has not been solved; it has been papered over.

- Ask "why" until you reach the cause, not the symptom (five whys is a guide, not a quota).
- Then ask the meta question: **why did the last fix for this class of problem not catch
  this one?** If something similar happened in the last 30 days, the earlier fix was a
  surface patch, and the real fix is at a different layer.
- Cap your attempts: **3 tries or 15 minutes** on one approach, then switch approach (plan
  A / B / C) instead of grinding on a dead end.
- A fix is only done when it is verified (a self-test, a re-run, the live URL) and the
  incident is written down where the next session will find it.

Skill template: [`skills/root-cause-loop`](../skills/root-cause-loop/SKILL.md).

## 2. Evolve

> Every correction is codified on the spot, as a rule, a hook or an eval case.

- When the human corrects the agent, the correction becomes an artifact in the same turn.
  Pick the strongest mechanism that is worth its cost:
  1. a **hook** if the action can be detected deterministically (see `hooks/`);
  2. an **eval case** if it is a behaviour that a model upgrade could lose (see `evals/`);
  3. a **rule line** only when neither of the above can express it.
- Prefer an eval case over another prose rule file. Prose rules pile up, contradict each
  other and quietly stop being read when the model changes. A test either passes or fails.
- Check prior art before building anything new: your own scripts first (`git log -- <path>`,
  grep the repo), then existing tools. Most "new" guards turned out to duplicate an old one.
- Retire rules too. The eval harness's `--compare` mode shows which rules the raw model
  already follows without being told; those lines are paying context rent for nothing.

## 3. Never stop

> When the goal is clear and the action is reversible, run to the end without waiting
> for a "go".

- Three conditions: the goal is clear, the direction is agreed, and the agent may decide
  on its own. "May decide on its own" means the action sits in the AUTO or NOTIFY tier of
  [`autonomy-tiers.md`](autonomy-tiers.md). If any condition is missing, stop.
- Only the ASK tier stops the run: bulk deletes, external publishing, money, client-facing
  changes, the rules themselves. Those stay human-approved, always.
- "Never stop" also means **never end a turn on an open promise**. If the agent said it
  would do something, it either does it, closes it honestly, or records what it is waiting
  on (see `tools/commitment_cli.py` and `hooks/commitment_ledger_guard.py`).
- Uncertainty is not a reason to stop. Below 70% confidence, take the conservative default,
  log it, and say so afterwards.

## How the three fit together

- *Never stop* without *root out* produces an agent that confidently runs in circles.
- *Root out* without *evolve* fixes today's incident and loses the lesson by next week.
- *Evolve* without *never stop* produces a rulebook so cautious that the human does the work.

The autonomy tiers decide where *never stop* ends. The hooks are where *evolve* puts the
lessons that must not depend on the model remembering them. The eval suite is how you find
out, on model upgrade day, which lessons survived.
