# -*- coding: utf-8 -*-
"""Commitment ledger guard. One file, two hook events:

PreToolUse (Edit / Write / NotebookEdit / Bash / PowerShell):
  block any direct write to the commitments ledger. Items are opened and closed only through
  tools/commitment_cli.py. Incident: a clean-up job rewrote the ledger and silently marked
  four real, unfinished commitments as done; nobody noticed for days.

Stop:
  if the agent is about to end its turn while commitments it made recently are still
  pending (and not waiting on a human), block the stop once and list them. Incident class:
  the agent said "I'll write a guard for this" in chat, ended the turn, and the guard was
  never written; the operator found out a day later by asking "did that ever get fixed?".

Guard rails so the Stop check can never trap a session:
  * stop_hook_active=true (we already blocked once this stop) -> allow;
  * only commitments added within RECENT_MIN minutes count (stale items belong in a review);
  * items with waiting_on set (blocked on a human decision) never block;
  * the ledger is read with "latest event per id wins", so a closed item stays closed.
    (An earlier version without that rule re-blocked forever on an item that was already done.)

    python commitment_ledger_guard.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, quiet_stderr, read_payload, state_dir, write_audit  # noqa: E402

NAME = "commitment_ledger_guard"
LEDGER_NAME = "commitments.jsonl"
RECENT_MIN = float(os.environ.get("AGENT_OPS_COMMITMENT_RECENT_MIN", 180))
RAW_WRITE_SHELL_RE = re.compile(
    r"(>>?|\b(?:Set-Content|Add-Content|Out-File|Clear-Content|sed\s+-i|perl\s+-pi|truncate|tee)\b)[^\n]*commitments\.jsonl"
    r"|commitments\.jsonl[^\n]*\|\s*(Set-Content|Out-File)", re.IGNORECASE)


def ledger_path() -> Path:
    return state_dir() / LEDGER_NAME


def pending_recent(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now().astimezone()
    p = ledger_path()
    if not p.is_file():
        return []
    state: dict[str, dict] = {}
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        cid = ev.get("id")
        if not cid:
            continue
        cur = state.setdefault(cid, {"id": cid})
        if ev.get("event") == "add":
            cur.update(summary=ev.get("summary"), added=ev.get("ts"), waiting_on=ev.get("waiting_on"),
                       eta=ev.get("eta"), status="pending")
        elif ev.get("event") in ("done", "drop"):
            cur["status"] = ev["event"]
    out = []
    for st in state.values():
        if st.get("status") != "pending" or st.get("waiting_on"):
            continue
        try:
            added = datetime.fromisoformat(st["added"])
        except Exception:
            continue
        if now - added <= timedelta(minutes=RECENT_MIN):
            out.append(st)
    return out


def check_pretool(payload: dict) -> int:
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}
    hit = False
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        hit = str(ti.get("file_path") or ti.get("notebook_path") or "").replace("\\", "/").endswith(LEDGER_NAME)
    elif tool in ("Bash", "PowerShell"):
        hit = bool(RAW_WRITE_SHELL_RE.search(str(ti.get("command") or "")))
    if not hit:
        return 0
    write_audit(NAME, {"outcome": "blocked_raw_write", "tool": tool})
    sys.stderr.write(
        "BLOCKED: the commitments ledger is never edited directly.\n"
        "Use: python tools/commitment_cli.py done <id> --note '<evidence>'  (or add / drop / list).\n"
    )
    return 2


def check_stop(payload: dict, now: datetime | None = None) -> tuple[int, str | None]:
    """Returns (exit_code, stdout_json). Stop hooks block via {"decision": "block"}."""
    if payload.get("stop_hook_active"):
        return 0, None
    items = pending_recent(now)
    if not items:
        return 0, None
    lines = "\n".join(f"  - {i['id']}: {i.get('summary', '')} (eta {i.get('eta') or 'none'})" for i in items[:10])
    reason = (
        f"You still have {len(items)} recent commitment(s) pending that do not wait on anyone:\n{lines}\n"
        "Either do the next one now, or close it honestly with commitment_cli.py done/drop --note, "
        "or mark it --waiting-on if a human must act first. Do not end the turn on an open promise."
    )
    write_audit(NAME, {"outcome": "blocked_stop", "pending": [i["id"] for i in items]})
    return 0, json.dumps({"decision": "block", "reason": reason})


def main() -> int:
    try:
        payload = read_payload()
        if payload.get("hook_event_name") == "Stop" or "stop_hook_active" in payload:
            code, out = check_stop(payload)
            if out:
                print(out)
            return code
        return check_pretool(payload)
    except Exception:
        return 0


def self_test() -> int:
    t = SelfTest(NAME)
    now = datetime.now().astimezone()
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    evs = [
        {"id": "a1", "event": "add", "ts": (now - timedelta(minutes=5)).isoformat(), "summary": "write the guard"},
        {"id": "b2", "event": "add", "ts": (now - timedelta(minutes=5)).isoformat(), "summary": "publish", "waiting_on": "operator"},
        {"id": "c3", "event": "add", "ts": (now - timedelta(minutes=5)).isoformat(), "summary": "closed one"},
        {"id": "c3", "event": "done", "ts": now.isoformat(), "note": "verified"},
        {"id": "d4", "event": "add", "ts": (now - timedelta(days=3)).isoformat(), "summary": "stale"},
    ]
    p.write_text("\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")
    ids = [i["id"] for i in pending_recent(now)]
    t.ck("only recent, unblocked, open items", ids == ["a1"])
    code, out = check_stop({"hook_event_name": "Stop", "stop_hook_active": False}, now)
    t.ck("stop blocked with pending", out is not None and json.loads(out)["decision"] == "block")
    t.ck("stop_hook_active never re-blocks", check_stop({"stop_hook_active": True}, now) == (0, None))
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "a1", "event": "done", "ts": now.isoformat(), "note": "done"}) + "\n")
    t.ck("stop allowed once closed", check_stop({"stop_hook_active": False}, now) == (0, None))
    with quiet_stderr():
        t.ck("Edit on ledger blocked", check_pretool({"tool_name": "Edit", "tool_input": {"file_path": "x/.agent-ops/commitments.jsonl"}}) == 2)
        t.ck("Write on ledger (backslash path) blocked", check_pretool({"tool_name": "Write", "tool_input": {"file_path": "x\\.agent-ops\\commitments.jsonl"}}) == 2)
        t.ck("shell append blocked", check_pretool({"tool_name": "Bash", "tool_input": {"command": "echo '{}' >> .agent-ops/commitments.jsonl"}}) == 2)
        t.ck("sed -i blocked", check_pretool({"tool_name": "Bash", "tool_input": {"command": "sed -i 's/pending/done/' commitments.jsonl"}}) == 2)
        t.ck("cli allowed", check_pretool({"tool_name": "Bash", "tool_input": {"command": "python tools/commitment_cli.py done a1 --note ok"}}) == 0)
        t.ck("read allowed", check_pretool({"tool_name": "Bash", "tool_input": {"command": "cat .agent-ops/commitments.jsonl"}}) == 0)
        t.ck("other file allowed", check_pretool({"tool_name": "Edit", "tool_input": {"file_path": "notes.md"}}) == 0)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
