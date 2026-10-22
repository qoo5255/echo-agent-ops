# -*- coding: utf-8 -*-
"""Minimal commitment ledger: every promise the agent makes gets an id, an ETA, and is
closed only through this CLI.

Why a CLI and not "just edit the file": an automatic clean-up job once rewrote the ledger
directly and silently marked four real, unfinished items as done. Since then the ledger is
append-only events, closing an item is an explicit `done <id>` with a note, and the
commitment_ledger_guard hook blocks raw edits of the file.

The ledger is JSONL of events; the latest event per id wins:
  {"id": "3f87a2c1", "ts": "...", "event": "add",  "summary": "...", "eta": "2026-10-22 18:00", "waiting_on": null}
  {"id": "3f87a2c1", "ts": "...", "event": "done", "note": "verified live"}

    python commitment_cli.py add "ship the sitemap fix" --eta "2026-10-22 18:00"
    python commitment_cli.py add "publish post" --waiting-on operator     # blocked on a human
    python commitment_cli.py list
    python commitment_cli.py done 3f87a2c1 --note "verified the live URL returns 200"
    python commitment_cli.py drop 3f87a2c1 --note "operator cancelled"

State dir: $AGENT_OPS_STATE_DIR, else $CLAUDE_PROJECT_DIR/.agent-ops, else ./.agent-ops
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path


def state_dir() -> Path:
    if os.environ.get("AGENT_OPS_STATE_DIR"):
        return Path(os.environ["AGENT_OPS_STATE_DIR"])
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()) / ".agent-ops"


def ledger() -> Path:
    return state_dir() / "commitments.jsonl"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def events() -> list[dict]:
    p = ledger()
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def current() -> dict[str, dict]:
    """id -> merged state, latest event wins (an id closed once stays closed)."""
    state: dict[str, dict] = {}
    for ev in events():
        cid = ev.get("id")
        if not cid:
            continue
        merged = {**state.get(cid, {}), **ev}
        merged["status"] = {"add": "pending", "done": "done", "drop": "dropped"}.get(ev.get("event"), merged.get("status"))
        state[cid] = merged
    return state


def append(ev: dict) -> None:
    p = ledger()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now(), **ev}, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("summary")
    a.add_argument("--eta", help="concrete time, e.g. '2026-10-22 18:00' (never 'later')")
    a.add_argument("--waiting-on", help="who/what must act first, e.g. 'operator'")
    sub.add_parser("list")
    for name in ("done", "drop"):
        s = sub.add_parser(name)
        s.add_argument("id")
        s.add_argument("--note", required=True, help="evidence for done / reason for drop")
    args = ap.parse_args(argv)

    if args.cmd == "add":
        cid = uuid.uuid4().hex[:8]
        append({"id": cid, "event": "add", "summary": args.summary, "eta": args.eta, "waiting_on": args.waiting_on})
        print(cid)
        return 0
    if args.cmd == "list":
        for cid, st in current().items():
            if st.get("status") == "pending":
                extra = f" waiting_on={st['waiting_on']}" if st.get("waiting_on") else ""
                print(f"{cid}  eta={st.get('eta') or '-'}{extra}  {st.get('summary', '')}")
        return 0
    st = current().get(args.id)
    if not st:
        print(f"unknown id {args.id}", file=sys.stderr)
        return 1
    if st.get("status") != "pending":
        print(f"{args.id} is already {st.get('status')}", file=sys.stderr)
        return 1
    append({"id": args.id, "event": args.cmd, "note": args.note})
    print(f"{args.id} -> {'done' if args.cmd == 'done' else 'dropped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
