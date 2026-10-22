# Adapting this for your own one-person operation

You run a business alone (or nearly), and you want a Claude Code agent to do real
operational work while you are away from the keyboard. This is the order that worked.

## Week 1: red lines and the chat bridge

1. **Write your red lines first, and keep them few.** Five or six things the agent may never
   do without you, for example: bulk deletes over 10 items, publishing anything external,
   spending money, touching client systems, leaking secrets, changing its own rules. Put them
   at the top of your `CLAUDE.md`. Everything else in that file should be short pointers.
2. **Decide where you will read the agent.** If you will be on your phone, connect a chat
   MCP server and make "every message to me goes through the chat tool" a red line. Then
   install `hooks/block_interactive_question.py` so a terminal dialog can never freeze an
   unattended session.
3. **Install the destructive-action guards** (copy `hooks/` into your repo, merge
   `examples/settings.example.json` into `.claude/settings.json`):
   `batch_delete_guard`, `unscoped_process_kill_guard`, `secret_output_guard`.
   Run `python tests/run_all.py` to confirm they work on your machine.

## Week 2: autonomy tiers

4. Copy [`autonomy-tiers.md`](autonomy-tiers.md) into `.claude/rules/` and edit the tables
   for your tools. Mirror the edits in `classifier/tiers.json`.
5. Start the classifier hook in observation mode: let it log for a week, then run
   `python classifier/autonomy_tier.py --report` and look at what ended up `unclassified`.
   Seat those deliberately.
6. Watch your own approval rate. If you approve more than 90% of what the agent asks, it is
   asking too much; move actions from ASK to NOTIFY.

## Week 3: ledgers and follow-through

7. Use `tools/commitment_cli.py` for every promise the agent makes ("I'll do X by 18:00").
   Add the Stop half of `commitment_ledger_guard.py` so it cannot end a turn on a fresh,
   open promise. Mark items `--waiting-on you` when they are blocked on you, so they do not
   nag.
8. Keep a decision log (one JSON line per decision you made, with where you said it), so
   the agent can follow precedent instead of asking again.
9. Keep an incident log: trigger, root cause, fix, prevention, re-test. Five lines each.

## Week 4 onwards: evals, then evolve

10. Run `python evals/run_evals.py --dry-run`, then a real run against your agent:
    `python evals/run_evals.py --project-dir <your agent repo> --reply-tool <your chat tool>`.
11. Every time you correct the agent, turn the correction into the strongest mechanism that
    is worth it: a hook if it is detectable, an eval case if it is behaviour, a rule line
    only if neither works. Add the eval case the same day (see `evals/README.md`).
12. On every model change, run the suite on the old and the new model and compare case by
    case before switching. Use `--compare` occasionally to find rules the model no longer
    needs.

## What to change for your setup

- **Confirmation token name.** Guards accept `--operator-confirmed=YYYY-MM-DD-HHMM`. Rename
  with `AGENT_OPS_CONFIRM_FLAG` if you prefer another word. The token is a record that a
  human said yes at that time; the agent should only add it after you did.
- **Tool names.** Your chat, email and social tools have their own MCP names. Set
  `AGENT_OPS_OUTBOUND_TOOLS`, `AGENT_OPS_REPLY_TOOLS`, `AGENT_OPS_EMAIL_SEND_TOOLS`
  (regexes) and the eval harness `--reply-tool`.
- **Language.** The status-claim, email-negation and lint patterns are English. If you
  work in another language, add patterns for it; keep them narrow.
- **State location.** Audit logs and ledgers go to `$CLAUDE_PROJECT_DIR/.agent-ops/`
  unless `AGENT_OPS_STATE_DIR` is set. Keep that directory out of git.

## What not to copy

- Do not copy a big rulebook. Start with red lines, tiers and guards; add rules only when
  an incident proves you need one.
- Do not let the agent judge reversibility at run time for anything on your red-line list.
  That judgment belongs in the table you wrote while calm.
- Do not make every guard a hard block. Safety red lines block; judgment-adjacent checks
  block once; style checks warn. A guard that blocks wrongly teaches the agent to route
  around guards.
