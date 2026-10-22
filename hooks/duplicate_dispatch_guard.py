# -*- coding: utf-8 -*-
"""PreToolUse guard (Agent / Task tool): stop unsupervised re-dispatch loops.

Incident class: a background notification listed 7 pending review jobs. The agent spawned
7 fresh reviewer sub-agents without checking which reviewers already existed. A dedup
hook warned on every one, but only warned. Then, trying to "retrieve" the earlier
reviewers' verdicts, it called the spawn tool again with the old agents' names, assuming
that resumes them. It does not: it spawns 7 more duplicates. 14 duplicate agents in total,
and one duplicate returned a confident FAIL that cited a source domain which does not even
resolve, contradicting the original reviewer's correct, verified PASS.

Three checks, in order:
  1. name reuse: spawning with a `name` that was already used in this project. A spawn
     never resumes an agent; message the existing one instead (SendMessage-style tool).
  2. duplicate work unit: the same normalised description + prompt prefix was dispatched
     within DUP_WINDOW_HOURS. Ask the earlier agent what it found before re-running it.
  3. runaway rate: more than MAX_DISPATCHES dispatches inside RATE_WINDOW_MIN minutes.

Bypass:
  * checks 1-2: include `fresh-dispatch: <reason>` in the prompt (the reason is audited).
    Re-dispatch is cheap to undo, so the agent may decide, but it has to say why.
  * check 3: `--operator-confirmed=YYYY-MM-DD-HHMM` in the prompt (a human must look at a
    possible loop).

Env: AGENT_OPS_DUP_WINDOW_HOURS (12), AGENT_OPS_MAX_DISPATCHES (8), AGENT_OPS_RATE_WINDOW_MIN (10).

    python duplicate_dispatch_guard.py --self-test
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, is_confirmed, quiet_stderr, read_payload, state_dir, write_audit  # noqa: E402

NAME = "duplicate_dispatch_guard"
DISPATCH_TOOLS = {"Agent", "Task"}
FRESH_RE = re.compile(r"fresh-dispatch:\s*(\S.{3,})", re.IGNORECASE)


def _cfg(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except ValueError:
        return default


def ledger_path() -> Path:
    return state_dir() / "dispatch_ledger.jsonl"


def work_key(tool_input: dict) -> str:
    desc = str(tool_input.get("description") or "")
    prompt = str(tool_input.get("prompt") or "")
    norm = re.sub(r"\s+", " ", (desc + " | " + prompt[:400]).lower()).strip()
    norm = FRESH_RE.sub("", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def load_ledger() -> list[dict]:
    p = ledger_path()
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def record(entry: dict) -> None:
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def evaluate(tool_input: dict, now: float | None = None) -> tuple[str, str] | None:
    """(check, message) if the dispatch should be blocked, else None."""
    now = now or time.time()
    prompt = str(tool_input.get("prompt") or "")
    name = str(tool_input.get("name") or "").strip()
    ledger = load_ledger()
    fresh = FRESH_RE.search(prompt)

    rate_window = _cfg("AGENT_OPS_RATE_WINDOW_MIN", 10) * 60
    recent = [e for e in ledger if now - e.get("t", 0) <= rate_window]
    if len(recent) >= int(_cfg("AGENT_OPS_MAX_DISPATCHES", 8)) and not is_confirmed(prompt):
        return "runaway_rate", (
            f"{len(recent)} sub-agents were dispatched in the last {int(rate_window // 60)} minutes. "
            "That is the shape of a re-dispatch loop. Stop, list the agents that already exist, "
            "and ask the operator before spawning more (bypass: --operator-confirmed=YYYY-MM-DD-HHMM).")

    if fresh:
        return None
    if name and any(e.get("name") == name for e in ledger):
        return "name_reuse", (
            f"An agent named '{name}' was already dispatched. Spawning with the same name creates a "
            "NEW agent, it does not resume the old one. Message the existing agent instead "
            "(SendMessage to that name) and ask what it found. If you truly need a fresh one, add "
            "'fresh-dispatch: <reason>' to the prompt.")
    key = work_key(tool_input)
    window = _cfg("AGENT_OPS_DUP_WINDOW_HOURS", 12) * 3600
    prior = [e for e in ledger if e.get("key") == key and now - e.get("t", 0) <= window]
    if prior:
        last = prior[-1]
        return "duplicate_work", (
            f"The same work unit was dispatched {int((now - last['t']) // 60)} min ago"
            + (f" (agent '{last['name']}')" if last.get("name") else "")
            + ". Ask that agent for its result before re-running it; a fresh duplicate can contradict "
            "a verified earlier answer. If a re-run is really needed, add 'fresh-dispatch: <reason>'.")
    return None


def check(payload: dict, now: float | None = None) -> int:
    if payload.get("tool_name") not in DISPATCH_TOOLS:
        return 0
    ti = payload.get("tool_input") or {}
    verdict = evaluate(ti, now)
    if verdict:
        write_audit(NAME, {"check": verdict[0], "outcome": "blocked", "description": str(ti.get("description", ""))[:120]})
        sys.stderr.write("BLOCKED: " + verdict[1] + "\n")
        return 2
    fresh = FRESH_RE.search(str(ti.get("prompt") or ""))
    record({"t": now or time.time(), "key": work_key(ti), "name": str(ti.get("name") or ""),
            "description": str(ti.get("description") or "")[:120],
            "fresh_reason": fresh.group(1)[:200] if fresh else None})
    return 0


def main() -> int:
    try:
        return check(read_payload())
    except Exception:
        return 0


def self_test() -> int:
    t = SelfTest(NAME)  # isolates the ledger in a temp state dir
    os.environ["AGENT_OPS_MAX_DISPATCHES"] = "5"
    base = 1_800_000_000.0

    def disp(desc, prompt="review the page", name=None, at=0.0):
        ti = {"description": desc, "prompt": prompt}
        if name:
            ti["name"] = name
        return check({"tool_name": "Agent", "tool_input": ti}, now=base + at)

    with quiet_stderr():
        t.ck("first dispatch allowed", disp("review site A", name="review-a") == 0)
        t.ck("same work unit blocked", disp("review site A", at=60) == 2)
        t.ck("name reuse blocked", disp("something else", name="review-a", at=90) == 2)
        t.ck("fresh-dispatch reason allows", disp("review site A", prompt="review the page fresh-dispatch: first run crashed", at=120) == 0)
        t.ck("different work allowed", disp("review site B", at=130) == 0)
        t.ck("same unit after window allowed", disp("review site B", at=13 * 3600) == 0)
        t.ck("non-dispatch tool ignored", check({"tool_name": "Bash", "tool_input": {}}) == 0)
        for i in range(5):
            disp(f"batch job {i}", at=14 * 3600 + i)
        t.ck("runaway rate blocked", disp("batch job 99", at=14 * 3600 + 10) == 2)
        t.ck("runaway rate operator bypass",
             disp("batch job 100", prompt="go --operator-confirmed=2026-10-22-1200", at=14 * 3600 + 11) == 0)
    os.environ.pop("AGENT_OPS_MAX_DISPATCHES", None)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
