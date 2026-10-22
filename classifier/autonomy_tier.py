# -*- coding: utf-8 -*-
"""Autonomy-tier classifier: maps a tool call to AUTO / NOTIFY / ASK from a fixed table.

The core idea (see docs/autonomy-tiers.md): classification happens when you write the
table, not when the agent is mid-task. An agent that judges "is this reversible?" at run
time is exactly the failure mode: it sometimes judges wrong, and it judges wrong most
confidently when it is usually right. So the run-time job is only to look up a seat.

  AUTO    read-only or trivially undoable    -> just do it
  NOTIFY  reversible write, sane default     -> do it, list it in the end-of-task report
  ASK     irreversible / external / money / client-facing / the rules themselves
          -> stop, bring options + a recommendation, wait for the human

Use it three ways:
  1. as a PreToolUse hook: ASK blocks unless the call carries
     --operator-confirmed=YYYY-MM-DD-HHMM; NOTIFY is appended to a ledger that
     `--report` prints for the end-of-task summary; AUTO passes silently.
  2. from the CLI, to see where an action sits:
       python autonomy_tier.py classify Bash '{"command": "git push --force"}'
  3. as a library: classify(tool_name, tool_input) -> Decision

Unknown actions get `unknown_tier` from tiers.json (default NOTIFY) and are logged as
`unclassified`, so the table can be extended deliberately instead of guessed at run time.

    python autonomy_tier.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIERS_PATH = Path(os.environ.get("AGENT_OPS_TIERS") or HERE / "tiers.json")
CONFIRM_FLAG = os.environ.get("AGENT_OPS_CONFIRM_FLAG", "operator-confirmed")
CONFIRMATION_RE = re.compile(r"--" + re.escape(CONFIRM_FLAG) + r"=20\d{2}-\d{2}-\d{2}-\d{4}")
ORDER = ("ASK", "NOTIFY", "AUTO")


@dataclass
class Decision:
    tier: str
    rule_id: str
    why: str


def state_dir() -> Path:
    if os.environ.get("AGENT_OPS_STATE_DIR"):
        return Path(os.environ["AGENT_OPS_STATE_DIR"])
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()) / ".agent-ops"


def load_table(path: Path = TIERS_PATH) -> dict:
    table = json.loads(path.read_text(encoding="utf-8"))
    for r in table["rules"]:
        r["_tool"] = re.compile(r["tool"])
        r["_input"] = re.compile(r["input"]) if r.get("input") else None
    return table


def input_text(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Bash", "PowerShell"):
        return str((tool_input or {}).get("command") or "")
    return json.dumps(tool_input or {}, ensure_ascii=False)


def classify(tool_name: str, tool_input: dict | None, table: dict | None = None) -> Decision:
    table = table or load_table()
    text = input_text(tool_name, tool_input or {})
    for tier in ORDER:
        for r in table["rules"]:
            if r["tier"] != tier or not r["_tool"].fullmatch(tool_name or ""):
                continue
            if r["_input"] is not None and not r["_input"].search(text):
                continue
            return Decision(tier, r["id"], r.get("why", ""))
    return Decision(table.get("unknown_tier", "NOTIFY"), "unclassified", "no rule matched; extend tiers.json")


def _append(name: str, rec: dict) -> None:
    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **rec},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass


def hook(payload: dict, table: dict | None = None) -> int:
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    d = classify(tool, ti, table)
    summary = input_text(tool, ti)[:200]
    if d.tier == "ASK":
        if CONFIRMATION_RE.search(json.dumps(ti, ensure_ascii=False)):
            _append("notify_ledger.jsonl", {"tier": "ASK-confirmed", "rule": d.rule_id, "tool": tool, "what": summary})
            return 0
        sys.stderr.write(
            f"ASK-tier action ({d.rule_id}: {d.why}). Stop and ask the human in ONE message:\n"
            "  what you want to do, options A/B, and which one you recommend and why.\n"
            f"After an explicit yes, retry with --{CONFIRM_FLAG}=YYYY-MM-DD-HHMM in the command/input.\n"
        )
        return 2
    if d.tier == "NOTIFY" or d.rule_id == "unclassified":
        _append("notify_ledger.jsonl", {"tier": d.tier, "rule": d.rule_id, "tool": tool, "what": summary})
    return 0


def report() -> int:
    p = state_dir() / "notify_ledger.jsonl"
    if not p.is_file():
        print("nothing to report")
        return 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        print(f"{r['ts']}  {r['tier']:<13} {r['rule']:<16} {r['tool']}  {r['what'][:90]}")
    return 0


def self_test() -> int:
    import io
    import tempfile
    os.environ["AGENT_OPS_STATE_DIR"] = tempfile.mkdtemp(prefix="agent_ops_selftest_")
    table = load_table()
    cases = [
        ("Read", {"file_path": "README.md"}, "AUTO"),
        ("Grep", {"pattern": "x"}, "AUTO"),
        ("Bash", {"command": "git status"}, "AUTO"),
        ("Bash", {"command": "curl -sI https://example.com/"}, "AUTO"),
        ("mcp__search__list_items", {}, "AUTO"),
        ("Edit", {"file_path": "src/app.py", "old_string": "a", "new_string": "b"}, "NOTIFY"),
        ("Bash", {"command": "git commit -m 'fix: x'"}, "NOTIFY"),
        ("Bash", {"command": "python scripts/report.py"}, "NOTIFY"),
        ("mcp__chat__reply", {"text": "progress"}, "NOTIFY"),
        ("Agent", {"description": "review"}, "NOTIFY"),
        ("Bash", {"command": "git push --force origin main"}, "ASK"),
        ("Bash", {"command": "pip install leftpad"}, "ASK"),
        ("Bash", {"command": "ssh host 'wp post delete 12'"}, "ASK"),
        ("mcp__social__post_thread", {"text": "hello"}, "ASK"),
        ("mcp__mail__send_message", {"to": "a@example.com"}, "ASK"),
        ("Edit", {"file_path": "CLAUDE.md"}, "ASK"),
        ("Bash", {"command": "python ads.py --daily_budget=50"}, "ASK"),
        ("SomeNewTool", {}, "NOTIFY"),
    ]
    fails = 0
    for tool, ti, want in cases:
        got = classify(tool, ti, table).tier
        if got != want:
            fails += 1
            sys.stderr.write(f"  FAIL: {tool} {ti} -> {got}, want {want}\n")
    real_err, sys.stderr = sys.stderr, io.StringIO()
    try:
        checks = [
            hook({"tool_name": "Bash", "tool_input": {"command": "git push --force"}}, table) == 2,
            hook({"tool_name": "Bash", "tool_input": {"command": f"git push --force --{CONFIRM_FLAG}=2026-10-22-1200"}}, table) == 0,
            hook({"tool_name": "Read", "tool_input": {"file_path": "x"}}, table) == 0,
            hook({"tool_name": "Edit", "tool_input": {"file_path": "x.py"}}, table) == 0,
        ]
    finally:
        sys.stderr = real_err
    fails += checks.count(False)
    ledger = (state_dir() / "notify_ledger.jsonl").read_text(encoding="utf-8")
    if "edit_files" not in ledger or "ASK-confirmed" not in ledger:
        fails += 1
        sys.stderr.write("  FAIL: notify ledger missing entries\n")
    total = len(cases) + len(checks) + 1
    print(f"autonomy_tier self-test: {total - fails}/{total} PASS")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if "--report" in argv:
        return report()
    if len(argv) >= 2 and argv[0] == "classify":
        ti = json.loads(argv[2]) if len(argv) > 2 else {}
        d = classify(argv[1], ti)
        print(f"{d.tier}  ({d.rule_id}: {d.why})")
        return 0
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        return hook(payload) if isinstance(payload, dict) else 0
    except Exception:
        return 0  # fail open


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
