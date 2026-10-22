# Known failure modes

Real incident classes from months of an agent operating a small business every day. Names
of people, clients, systems and dates are removed; the mechanics are kept, because the
mechanics are what repeat. Each entry lists what the guard or eval case is.

The pattern across almost all of them: **a written rule existed, and the incident happened
anyway.** Prose rules are necessary for the agent to know what you want, but they are not a
control. The fix that held was always structural: a hook, a ledger, or an eval case.

## Destructive actions

### 1. Bulk deletion from a vague instruction
"Clean these up" in a task manager became one command that deleted 258 items, including
many that should have stayed. Nothing was listed, nothing was confirmed, no backup existed.
- Guard: `hooks/batch_delete_guard.py` (more than 10 explicit targets or a mass-delete
  pattern needs a human confirmation token). Eval: AO04.
- Residual gap: deletions whose targets come from a query or a pipe cannot be counted
  statically. Those still rely on the list, ask, back up, delete-only-listed procedure.

### 2. Killing every process with a given name
A sub-agent stopping its own test server used a name-based kill and took down every
process of that runtime on the machine, breaking four unrelated tools. The follow-up "I'll
add a rule" was only said in chat and never implemented.
- Guard: `hooks/unscoped_process_kill_guard.py`. Lesson also feeds #11 below.

### 3. Deleting content to "remove" it
Asked to remove an outdated article, the right answer is unpublish plus redirect, never
delete: deletion loses links and search equity and cannot be undone. Eval: AO05.

## Leaks and external actions

### 4. A secret pasted into chat
While explaining a timeline, the agent pasted a full API token into a chat message. It was
visible for about a minute; the token was rotated. The rule "never paste secrets" was
already written down. Guard: `hooks/secret_output_guard.py`. Eval: AO03.

### 5. Sending email on implied approval
"The draft looks good" was treated as "send it". Separately, a pilot script with a retry
bug sent 26 duplicate emails. Approval of text is not a send command.
Guard: `hooks/email_send_gate.py`. Eval: AO07.

### 6. Client names in public copy
Case-study copy named the client. Public copy is depersonalised by default, and publishing
is ASK tier. Eval: AO06.

### 7. Invented claims in outreach
A first-contact draft claimed "our customers often ask about this". There was no such
record. It was removed once and silently re-added in the next revision. Every factual claim
in external copy needs a source. Eval: AO18.

## Delegation and verification

### 8. Re-dispatch loop (duplicate sub-agents)
A backlog notification listed 7 pending reviews. The agent spawned 7 new reviewers without
checking which already existed; a dedup hook warned each time but only warned. To "retrieve"
the old reviewers' verdicts it called the spawn tool again with their names, which creates
new agents rather than resuming old ones: 14 duplicates. One duplicate returned a confident
FAIL citing a source domain that does not resolve, contradicting the original reviewer's
correct, verified PASS. Duplicates are not just waste; they produce conflicting answers.
- Guard: `hooks/duplicate_dispatch_guard.py` (name reuse, repeated work unit, runaway rate).
  Eval: AO15.

### 9. "Dispatched" reported as "done"
A sub-agent said "deployed, done"; the agent relayed it as fact. The deploy had not taken
effect. Dispatch is not done; "applied" is not proof; check the live artifact.
Eval: AO11. Skill: `skills/verify-before-done`.

### 10. Asserting live state from memory
The agent told the operator a site "still runs on" a platform it had left weeks earlier,
and that a key "could not be found" while it sat in the secrets folder. Same root: a
conclusion about current state with zero checks.
Guard: `hooks/status_claim_verify_guard.py`. Eval: AO20.

## Promises and follow-through

### 11. Promises that evaporate
"I'll write a guard for this" in chat, turn ends, nothing happens. Discovered a day later
when the operator asked "did that ever get fixed?". Every promise now goes into a ledger
with an ETA, and the Stop hook blocks ending a turn on a fresh open promise.
Guard: `hooks/commitment_ledger_guard.py` + `tools/commitment_cli.py`.

### 12. Silent bookkeeping
An automatic clean-up rewrote the commitment ledger directly and marked four real,
unfinished items as done. Ledgers are append-only, closed only via CLI with a note, and
raw edits are blocked. Eval: AO16.

### 13. A guard that blocked forever
An early Stop guard read the ledger without "latest event wins" and kept blocking on an
item that had already been closed. Every guard needs a way to be satisfied, and a Stop
guard must never block twice in the same stop (`stop_hook_active`).

## Communication

### 14. Answering where the human cannot see
The operator reads chat only. Answers printed to the terminal were never seen. Eval: AO02.

### 15. The frozen session
An interactive multiple-choice dialog opened in the terminal; nobody was there to answer;
the session sat frozen for 13 minutes. Guard: `hooks/block_interactive_question.py`.
Closed-set questions go to chat as numbered options. Eval: AO01.

### 16. Stop-and-wait on reversible work
"I plan to do X, waiting for your confirmation" on a change the agent owned and could
revert. This was among the most frequent violations. The autonomy tiers say: do it, report
it. Eval: AO09.

### 17. Over-broad pause
"Pause the blog schedule" was treated as "stop everything". Scope the pause to what was
named and say that the rest continues. Eval: AO10.

### 18. Short replies attached to the wrong proposal
"OK, do it" was matched to the most recent topic instead of the message it replied to.
Resolve terse approvals against the reply reference. Eval: AO12.

### 19. Vague timing
"Later", "soon", "shortly": promises with no time cannot be tracked or chased. Always a
clock time plus what triggers it. Eval: AO14.

### 20. Paternalism
Unrequested remarks about the operator's sleep or working hours, after being asked to stop.
Eval: AO19.

## Tooling traps

### 21. Heredoc escapes corrupting code
Python written through shell heredocs lost its backslash escapes on the way to the shell
(`"\n"` became a real newline, `\s` became a space). Four times in one day; two broken
patches were committed. Guard: `hooks/heredoc_backslash_guard.py`.

### 22. Scheduled scripts go live on save
Editing a script that a scheduler runs is a production deploy. Risky edits ship behind an
off-by-default flag file and are switched on after review.

### 23. Rules that only exist in the model's head
Several incidents above recurred after a rule was written. The general lesson: when a rule
fails once, move it down a layer (prose, then lint, then hook); when the model changes,
re-run the evals to see which prose rules still hold.

## Meta: guard design failures

- **False positives cause loops.** A high-frequency reply lint that misfired made the agent
  rewrite and resend repeatedly, each rewrite tripping a neighbouring rule. Prefer a miss to
  a false block; collect false positives and narrow the pattern rather than widening it.
- **Warn-only guards are ignored under load.** The dedup warning in #8 fired every time and
  changed nothing. If a signal is reliable enough to warn on every time, it is usually
  reliable enough to block once.
- **Rule bloat.** The same rule restated in a prompt, a hook message and an index adds cost
  without adding reliability. One canonical home per rule, pointers everywhere else.
