# Guard hooks

Deterministic Claude Code hooks distilled from real incidents. Each file is standalone
apart from `_common.py`, has no third-party dependencies (written for Python 3.9+,
tested on 3.12), and carries a `--self-test`.

| Hook | Event / matcher | Blocks | Bypass |
|---|---|---|---|
| `batch_delete_guard.py` | PreToolUse `Bash\|PowerShell` | deleting more than 10 explicit targets, or mass-delete patterns | `--operator-confirmed=YYYY-MM-DD-HHMM` |
| `unscoped_process_kill_guard.py` | PreToolUse `Bash\|PowerShell` | name-based kills (`taskkill /IM`, `pkill`, `killall`, `Stop-Process -Name`) | PID-scoped kill, or the token |
| `secret_output_guard.py` | PreToolUse `mcp__.*` | outbound messages containing credential-shaped strings | none, by design |
| `heredoc_backslash_guard.py` | PreToolUse `Bash\|PowerShell` | heredocs / here-strings that write Python source with backslash escapes | use the Write tool |
| `block_interactive_question.py` | PreToolUse `AskUserQuestion` | terminal dialogs in remotely operated sessions | `AGENT_OPS_ALLOW_INTERACTIVE=1` |
| `email_send_gate.py` | PreToolUse `mcp__.*\|Bash\|PowerShell` | email sends without an explicit "send" in the newest human message | the human says "send" |
| `duplicate_dispatch_guard.py` | PreToolUse `Agent\|Task` | spawning with a used name, re-dispatching the same work unit, runaway spawn rate | `fresh-dispatch: <reason>` / the token |
| `status_claim_verify_guard.py` | PreToolUse `mcp__.*` | replies asserting live system state with no check in the session (once) | resend the same text |
| `commitment_ledger_guard.py` | PreToolUse `Edit\|Write\|Bash\|PowerShell` and Stop | raw edits of the commitment ledger; ending a turn on a fresh open promise (once) | `tools/commitment_cli.py` |

The autonomy-tier classifier (`../classifier/autonomy_tier.py`) is also a PreToolUse hook;
see `docs/autonomy-tiers.md`.

## Install

1. Copy `hooks/` (and `classifier/`, `tools/` if you want them) into your project.
2. Merge `../examples/settings.example.json` into `.claude/settings.json`. Paths use
   `$CLAUDE_PROJECT_DIR`, which Claude Code sets for hook commands.
3. Run the self-tests: `python tests/run_all.py` from the repo root.
4. Add `.agent-ops/` to your `.gitignore` (audit logs and ledgers live there).

## Contract

- stdin: the hook payload JSON (`tool_name`, `tool_input`, `transcript_path`, ...).
- exit 0 = allow; exit 2 = block, stderr is shown to the model; Stop hooks print
  `{"decision": "block", "reason": ...}` instead.
- Every hook **fails open**: bad input or an internal error allows the call.
- Audit records go to `<state dir>/<hook>_audit.jsonl`; secret values are never logged.

## Writing your own

Copy the smallest one (`unscoped_process_kill_guard.py`) and keep its shape:
a pure `scan_*` function, a `handle` that decides and writes the audit line, a `main` that
fails open, and a `--self-test` with both hits and near-misses. Near-misses matter more:
a guard that fires on a commit message which merely *mentions* `rm -rf` will be routed
around within a day.
