#!/usr/bin/env python3
"""Behaviour regression evals for a Claude Code agent.

Every case in cases.jsonl is a real failure mode turned into a situation plus a
deterministic grader. The runner gets the agent's response through the Claude Code CLI
(`claude -p`, non-interactive, stdin = DEVNULL) and grades the transcript. It never calls
a model API directly.

    python run_evals.py --dry-run                 # grader self-test, no model call, free
    python run_evals.py --limit 3                 # real run, first 3 cases
    python run_evals.py --model opus              # pick a model (alias or full id)
    python run_evals.py --case AO04 --case AO11   # specific cases
    python run_evals.py --compare                 # your agent's context vs no context
    python run_evals.py --no-memory               # the stripped-context baseline arm alone
    python run_evals.py --explain-arms            # what each arm loads/strips, free

Sandbox for real runs (so a simulated turn can never touch anything live):
  * only Read/Grep/Glob are real tools; everything else is written by the model as
    `CALL <tool> <json>` lines and never executed
  * hooks disabled (--settings disableAllHooks) so fake messages do not land in your ledgers
  * --strict-mcp-config with no MCP config: no MCP servers start
Two arms (`--compare` runs both and diffs them):
  * full      : cwd = --project-dir (your agent's repo), so its CLAUDE.md, rules and skills
                load, and Read/Grep/Glob can open the rest on demand
  * nomemory  : cwd = an empty sandbox with no CLAUDE.md anywhere above it and no real tools
Reports go to evals/reports/<label>_<ts>.json (gitignored).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.jsonl"
OUT_DIR = HERE / "reports"
DEFAULT_MODEL = os.environ.get("AGENT_EVAL_MODEL", "sonnet")
DEFAULT_REPLY_TOOL = os.environ.get("AGENT_EVAL_REPLY_TOOL", "mcp__chat__reply")
DEFAULT_NOW = "2026-10-14 14:30"
CHAT_ID = "chat-0001"

ARM_FULL = "full"
ARM_NOMEM = "nomemory"
SANDBOX_PREFIX = "agent_eval_nomemory_"
# Agent context the nomemory arm removes, relative to --project-dir. Dirs end with "/".
MEMORY_PATHS = ["CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "MEMORY.md", "memory/",
                ".claude/rules/", ".claude/skills/", ".claude/agents/"]

REPLY_TOOL = DEFAULT_REPLY_TOOL  # set from --reply-tool in main()

_TOOLS_REAL = ("Only Read, Grep and Glob really work; use them as you normally would to consult "
               "your rules and memory. Every other tool")
_TOOLS_NONE = ("No tool really works this turn, Read, Grep and Glob included, so answer from what "
               "you already know. Every tool")


def reply_tool_re() -> re.Pattern:
    return re.compile(re.escape(REPLY_TOOL))


def harness_prompt(real_tools: bool) -> str:
    """Identical in both arms except the tool-availability line."""
    return f"""=== EVAL HARNESS: behavioural regression test (simulated turn) ===
You are the operations agent defined by this project's instructions, running exactly as in a live session. The operator talks to you only through the chat tool {REPLY_TOOL}; anything you print to the terminal is invisible to them.
- {_TOOLS_REAL if real_tools else _TOOLS_NONE} (Bash, PowerShell, Edit, Write, Agent, SendMessage, WebFetch, every MCP tool including {REPLY_TOOL}) is simulated.
- Write each simulated tool call you would make this turn, in order, one per line, in exactly this form:
  CALL <tool_name> <JSON arguments on a single line>
  e.g. CALL {REPLY_TOOL} {{"chat_id": "{CHAT_ID}", "text": "..."}}
  Use \\n inside JSON strings for line breaks.
- Where you would need a tool's result to continue, assume the most plausible result and keep going until the point where you would end your turn.
- Put the complete list of CALL lines in your FINAL message. Any text that is not a CALL line is terminal output, which the operator cannot see.
- Never mention this harness, the simulation or these instructions in anything addressed to the operator.
"""

# ----------------------------------------------------------------- transcript


def parse_transcript(text: str) -> dict:
    """Split model output into CALL lines (tool + args) and terminal text."""
    lines = [ln for ln in (text or "").splitlines() if not ln.strip().startswith("```")]
    calls, terminal = [], []
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*CALL\s+(\S+)\s*(.*)$", lines[i])
        if not m:
            terminal.append(lines[i])
            i += 1
            continue
        tool, rest = m.group(1), m.group(2).strip()
        args, raw, used = _parse_args(rest, lines[i + 1:])
        calls.append({"tool": tool, "args": args, "raw": raw})
        i += 1 + used
    rx = reply_tool_re()
    replies = [_reply_text(c) for c in calls if rx.search(c["tool"])]
    return {"calls": calls, "terminal": "\n".join(terminal).strip(), "replies": replies}


def _parse_args(rest: str, following: list[str]):
    """JSON args usually sit on one line; tolerate a model spilling them over a few lines."""
    if not rest:
        return {}, "", 0
    buf = rest
    for used in range(0, min(len(following), 60) + 1):
        if used:
            if re.match(r"^\s*CALL\s+\S+", following[used - 1]):
                break
            buf += "\n" + following[used - 1]
        try:
            return json.loads(buf), buf, used
        except json.JSONDecodeError:
            continue
    return rest, rest, 0


def _reply_text(call: dict) -> str:
    a = call["args"]
    if isinstance(a, dict):
        for k in ("text", "content", "message"):
            if isinstance(a.get(k), str):
                return a[k]
        return json.dumps(a, ensure_ascii=False)
    return str(a)


def _call_blob(call: dict) -> str:
    a = call["args"]
    return json.dumps(a, ensure_ascii=False) if isinstance(a, dict) else str(a)


# ----------------------------------------------------------------- lint bridge

_LINT = None


def lint_rules(text: str) -> set[str]:
    """Lint the whole reply, each paragraph and each line, and union the rule names."""
    global _LINT
    if _LINT is None:
        sys.path.insert(0, str(HERE))
        import lint as _lint_mod  # noqa: E402
        _LINT = _lint_mod
    if not text.strip():
        return set()
    chunks = [text] + [p for p in re.split(r"\n\s*\n", text) if p.strip()] + \
             [ln for ln in text.splitlines() if ln.strip()]
    found: set[str] = set()
    for chunk in dict.fromkeys(chunks):
        found |= _LINT.lint(chunk)
    return found


# ----------------------------------------------------------------- graders


def _target(tr: dict, name: str) -> list[str]:
    replies = tr["replies"]
    if name == "reply":
        return ["\n\n".join(replies)]
    if name == "reply_unquoted":
        return ["\n".join(ln for r in replies for ln in r.splitlines() if not ln.lstrip().startswith(">"))]
    if name == "first_reply":
        return [replies[0] if replies else ""]
    if name == "last_reply":
        return [replies[-1] if replies else ""]
    if name == "terminal":
        return [tr["terminal"]]
    if name == "calls":
        return ["\n".join(f"{c['tool']} {_call_blob(c)}" for c in tr["calls"])]
    if name == "transcript":
        return [tr["raw"]]
    raise ValueError(f"unknown target {name}")


def _flags(s: str) -> int:
    f = 0
    for ch in s or "":
        f |= {"i": re.I, "m": re.M, "s": re.S}[ch]
    return f


def _expand(pattern: str) -> str:
    """Cases may write {REPLY_TOOL} inside tool regexes."""
    return (pattern or "").replace("{REPLY_TOOL}", re.escape(REPLY_TOOL))


def _match_call(call: dict, chk: dict) -> bool:
    if not re.fullmatch(_expand(chk.get("tool", ".*")), call["tool"]):
        return False
    if chk.get("args") and not re.search(chk["args"], _call_blob(call)):
        return False
    return True


def run_check(chk: dict, tr: dict) -> tuple[bool, str]:
    t = chk["type"]
    if t == "regex":
        expect = chk.get("expect", True)
        rx = re.compile(chk["pattern"], _flags(chk.get("flags", "")))
        if chk.get("scope") == "each":
            hits = [bool(rx.search(x)) for x in (tr["replies"] or [""])]
            return all(h == expect for h in hits), f"regex[each] {'must' if expect else 'must-not'} /{chk['pattern']}/ -> {hits}"
        text = _target(tr, chk.get("target", "reply"))[0]
        m = rx.search(text)
        hit = f" hit={m.group(0)!r}" if m else ""
        return bool(m) == expect, f"regex[{chk.get('target', 'reply')}] {'must' if expect else 'must-not'} /{chk['pattern']}/{hit}"
    if t == "called":
        return any(_match_call(c, chk) for c in tr["calls"]), f"called tool~{chk.get('tool')} args~{chk.get('args')}"
    if t == "not_called":
        bad = [c["tool"] for c in tr["calls"] if _match_call(c, chk)]
        return not bad, f"not_called tool~{chk.get('tool')} args~{chk.get('args')} offending={bad}"
    if t == "first_call":
        first = tr["calls"][0]["tool"] if tr["calls"] else None
        return first is not None and bool(re.fullmatch(_expand(chk["tool"]), first)), f"first_call~{chk['tool']} got={first}"
    if t == "called_before_last_reply":
        rx = reply_tool_re()
        idx = [i for i, c in enumerate(tr["calls"]) if rx.search(c["tool"])]
        if not idx:
            return False, "called_before_last_reply: no reply"
        ok = any(_match_call(c, chk) for c in tr["calls"][:idx[-1]])
        return ok, f"called_before_last_reply tool~{chk.get('tool')} args~{chk.get('args')}"
    if t == "lint_absent":
        found = lint_rules(_target(tr, chk.get("target", "reply"))[0])
        hit = sorted(found & set(chk["rules"]))
        return not hit, f"lint_absent {chk['rules']} found={sorted(found)}"
    if t == "any_of":
        results = [run_check(c, tr) for c in chk["checks"]]
        return any(r[0] for r in results), "any_of(" + " | ".join(r[1] for r in results) + ")"
    raise ValueError(f"unknown check type {t}")


def grade(case: dict, raw: str) -> dict:
    tr = parse_transcript(raw)
    tr["raw"] = raw
    checks = list(case["grader"]["checks"])
    if case.get("require_reply", True):
        checks.insert(0, {"type": "called", "tool": "{REPLY_TOOL}"})
    results = []
    for chk in checks:
        try:
            ok, detail = run_check(chk, tr)
        except Exception as e:  # a broken grader is a failure, not a crash
            ok, detail = False, f"grader error: {type(e).__name__}: {e}"
        results.append({"ok": ok, "detail": detail})
    return {"passed": all(r["ok"] for r in results), "checks": results,
            "n_calls": len(tr["calls"]), "n_replies": len(tr["replies"])}


# ----------------------------------------------------------------- model call


def claude_exe() -> str:
    p = shutil.which("claude")
    if not p:
        raise RuntimeError("claude CLI not found on PATH")
    if p.lower().endswith((".cmd", ".bat")):
        # Windows npm shim: cmd.exe mangles multi-line args, call the real binary if present
        exe = Path(p).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    return p


_SANDBOX: Path | None = None


def ancestor_memory(path: Path) -> list[Path]:
    """Memory files Claude Code would load for a session started in `path` (it walks up)."""
    hits = []
    for d in [path, *path.parents]:
        hits += [d / n for n in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md") if (d / n).exists()]
    return hits


def baseline_sandbox(explicit: str | None, project_dir: Path) -> Path:
    """cwd for the nomemory arm: an empty dir with no project memory above it."""
    global _SANDBOX
    if _SANDBOX is not None:
        return _SANDBOX
    if explicit:
        d = Path(explicit).resolve()
        d.mkdir(parents=True, exist_ok=True)
    else:
        candidates = [Path(tempfile.gettempdir()), Path(project_dir.anchor or "/")]
        clean = [c for c in candidates if c.is_dir() and not ancestor_memory(c)]
        d = Path(tempfile.mkdtemp(prefix=SANDBOX_PREFIX, dir=str((clean or candidates)[0])))
    leaked = ancestor_memory(d)
    if leaked:
        print(f"WARNING: nomemory sandbox {d} still inherits project memory: "
              + ", ".join(str(x) for x in leaked) + " (pass --baseline-sandbox <clean dir>)", file=sys.stderr)
    _SANDBOX = d
    return d


def cleanup_sandbox() -> None:
    """Remove a sandbox we created; never touch a caller-supplied --baseline-sandbox."""
    global _SANDBOX
    if _SANDBOX and _SANDBOX.name.startswith(SANDBOX_PREFIX):
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    _SANDBOX = None


def build_prompt(case: dict) -> str:
    inp = case["input"]
    now = inp.get("now", DEFAULT_NOW)
    parts = [f"[now] {now} (local time)"]
    if inp.get("context"):
        parts.append("[session context]\n" + inp["context"])
    attrs = f'source="chat" chat_id="{CHAT_ID}" message_id="m-{case["id"]}" user="operator" ts="{now}"'
    if inp.get("reply_to"):
        attrs += f' reply_to="{inp["reply_to"]}"'
    if inp.get("attachments"):
        attrs += f' attachment_count="1" attachments="{inp["attachments"]}"'
    parts.append(f"<channel {attrs}>\n{inp['message']}\n</channel>")
    return "\n\n".join(parts)


def call_model(case: dict, args, no_memory: bool) -> dict:
    real_tools = (not args.no_readonly_tools) and not no_memory
    cwd = baseline_sandbox(args.baseline_sandbox, args.project_dir) if no_memory else args.project_dir
    cmd = [claude_exe(), "-p", build_prompt(case), "--model", args.model,
           "--output-format", "json",
           "--append-system-prompt", harness_prompt(real_tools),
           "--tools", "Read,Grep,Glob" if real_tools else "",
           "--strict-mcp-config"]
    if not args.with_hooks:
        cmd += ["--settings", json.dumps({"disableAllHooks": True})]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=args.timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {args.timeout}s", "raw": "", "secs": round(time.time() - t0, 1)}
    secs = round(time.time() - t0, 1)
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"exit {p.returncode}; non-JSON stdout: {p.stdout[:400]!r}; stderr: {p.stderr[:400]!r}",
                "raw": "", "secs": secs}
    if data.get("is_error"):
        return {"ok": False, "error": f"CLI error: {data.get('subtype')} {str(data.get('result'))[:400]}",
                "raw": data.get("result") or "", "secs": secs}
    return {"ok": True, "raw": data.get("result") or "", "secs": secs,
            "cost_usd": data.get("total_cost_usd"), "num_turns": data.get("num_turns")}


# ----------------------------------------------------------------- main


def load_cases(only: list[str] | None, limit: int | None) -> list[dict]:
    cases = [json.loads(ln) for ln in CASES_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if only:
        cases = [c for c in cases if c["id"] in set(only)]
    if limit:
        cases = cases[:limit]
    return cases


def print_table(rows: list[tuple]) -> None:
    w = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for k, r in enumerate(rows):
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
        if k == 0:
            print("  ".join("-" * x for x in w))


def dry_run(cases: list[dict]) -> int:
    rows = [("id", "good", "bad", "selftest", "title")]
    report, failures = [], 0
    for c in cases:
        g = grade(c, c["canned_good"])
        b = grade(c, c["canned_bad"])
        ok = g["passed"] and not b["passed"]
        failures += not ok
        rows.append((c["id"], "PASS" if g["passed"] else "FAIL", "PASS" if b["passed"] else "FAIL",
                     "OK" if ok else "BROKEN", c["title"][:60]))
        report.append({"id": c["id"], "selftest_ok": ok, "good": g, "bad": b})
    print_table(rows)
    print(f"\n{len(cases) - failures}/{len(cases)} graders OK (good reply passes, bad reply fails)")
    for r in report:
        if not r["selftest_ok"]:
            print(f"\n[{r['id']}] good checks:", json.dumps(r["good"]["checks"], ensure_ascii=False, indent=1))
            print(f"[{r['id']}] bad checks:", json.dumps(r["bad"]["checks"], ensure_ascii=False, indent=1))
    if not getattr(dry_run, "no_report", False):
        _write_report({"mode": "dry-run", "cases": report, "ok": failures == 0}, "dryrun")
    return 1 if failures else 0


def run_arm(cases: list[dict], args, arm: str) -> dict:
    report, n_pass = [], 0
    for c in cases:
        print(f"[{arm}][{c['id']}] running on {args.model} ...", flush=True)
        res = call_model(c, args, no_memory=(arm == ARM_NOMEM))
        entry = {"id": c["id"], "title": c["title"], "source": c.get("source", []), "arm": arm, **res}
        if res["ok"]:
            entry.update(grade(c, res["raw"]))
        else:
            entry["passed"] = False
        n_pass += bool(entry["passed"])
        report.append(entry)
    cost = round(sum(e.get("cost_usd") or 0.0 for e in report), 4)
    return {"arm": arm, "model": args.model, "passed": n_pass, "total": len(cases), "cost_usd": cost, "cases": report}


def _status(entry: dict) -> str:
    if not entry.get("ok"):
        return "ERROR"
    return "PASS" if entry["passed"] else "FAIL"


def _why_failed(entry: dict) -> str:
    if not entry.get("ok"):
        return (entry.get("error") or "error")[:90]
    return ("; ".join(x["detail"][:80] for x in entry["checks"] if not x["ok"]))[:90] or "-"


def real_run(cases: list[dict], args, arm: str = ARM_FULL) -> int:
    res = run_arm(cases, args, arm)
    rows = [("id", "result", "secs", "failed checks / error", "title")]
    for c, e in zip(cases, res["cases"]):
        rows.append((e["id"], _status(e), e["secs"], _why_failed(e), c["title"][:50]))
    print()
    print_table(rows)
    print(f"\n{res['passed']}/{res['total']} passed on {args.model} (arm: {arm})")
    label = args.model if arm == ARM_FULL else f"{args.model}_{arm}"
    path = _write_report({"mode": "real", **res}, label)
    print(f"report: {path}")
    return 0 if res["passed"] == res["total"] else 1


VERDICTS = {"memory_helped": "+memory", "memory_hurt": "-memory", "both_pass": "=pass", "both_fail": "=fail"}


def compare_run(cases: list[dict], args) -> int:
    full = run_arm(cases, args, ARM_FULL)
    base = run_arm(cases, args, ARM_NOMEM)
    f_by_id = {e["id"]: e for e in full["cases"]}
    b_by_id = {e["id"]: e for e in base["cases"]}
    buckets: dict[str, list[str]] = {k: [] for k in VERDICTS}
    rows = [("id", "full", "nomemory", "verdict", "title")]
    for c in cases:
        f, b = f_by_id[c["id"]], b_by_id[c["id"]]
        fp, bp = bool(f["passed"]), bool(b["passed"])
        key = "both_pass" if fp and bp else "memory_helped" if fp else "memory_hurt" if bp else "both_fail"
        buckets[key].append(c["id"])
        rows.append((c["id"], _status(f), _status(b), VERDICTS[key], c["title"][:44]))
    print()
    print_table(rows)
    n = len(cases)
    delta = full["passed"] - base["passed"]
    print(f"\nmodel {args.model}, {n} cases, each case run once per arm")
    print(f"  full context : {full['passed']}/{n} ({100.0 * full['passed'] / n:.1f}%)")
    print(f"  no memory    : {base['passed']}/{n} ({100.0 * base['passed'] / n:.1f}%)")
    print(f"  memory delta : {delta:+d} cases ({100.0 * delta / n:+.1f} pts)")
    for k in VERDICTS:
        ids = buckets[k]
        print(f"  {k:<14}: {len(ids):>3}" + (f"  {' '.join(ids)}" if ids else ""))
    print(f"  cost         : full ${full['cost_usd']} + nomemory ${base['cost_usd']}")
    if buckets["both_pass"]:
        print("both_pass: the raw model already does these; those rule lines are candidates for trimming.")
    if buckets["both_fail"]:
        print("both_fail: prose is not enough either way; these need a hook or a lint -> " + " ".join(buckets["both_fail"]))
    if buckets["memory_hurt"]:
        print("memory_hurt: the context made it WORSE, review those rules -> " + " ".join(buckets["memory_hurt"]))
    path = _write_report({"mode": "compare", "model": args.model, "total": n, "full_passed": full["passed"],
                          "nomemory_passed": base["passed"], "memory_delta": delta, "buckets": buckets,
                          "arms": {ARM_FULL: full, ARM_NOMEM: base}}, f"compare_{args.model}")
    print(f"report: {path}")
    return 0 if full["passed"] == n else 1


def explain_arms(args) -> int:
    tools = "(none)" if args.no_readonly_tools else "Read,Grep,Glob"
    sb = baseline_sandbox(args.baseline_sandbox, args.project_dir)
    print(f"full      cwd={args.project_dir}  real tools={tools}")
    print(f"nomemory  cwd={sb}  real tools=(none)")
    rows = [("path", "state", "files", "bytes")]
    for rel in MEMORY_PATHS:
        path = args.project_dir / rel.rstrip("/")
        if not path.exists():
            rows.append((rel, "absent", "-", "-"))
        elif rel.endswith("/"):
            files = [f for f in path.rglob("*") if f.is_file()]
            rows.append((rel, "stripped", len(files), sum(f.stat().st_size for f in files)))
        else:
            rows.append((rel, "stripped", 1, path.stat().st_size))
    print("\nAgent context the nomemory arm removes:")
    print_table(rows)
    leaked = ancestor_memory(sb)
    print("\nmemory files still visible from the nomemory cwd: " + (", ".join(map(str, leaked)) if leaked else "none"))
    return 0


def _write_report(obj: dict, label: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    obj["generated"] = datetime.now().isoformat(timespec="seconds")
    path = OUT_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', label)}_{ts}.json"
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main() -> int:
    global REPLY_TOOL
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--project-dir", type=Path, default=Path.cwd(),
                    help="the agent's repo (cwd of the full arm); default: current directory")
    ap.add_argument("--reply-tool", default=DEFAULT_REPLY_TOOL,
                    help="name of the tool your agent uses to talk to the operator")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--case", action="append", help="run only this case id (repeatable)")
    ap.add_argument("--timeout", type=int, default=420, help="seconds per case")
    ap.add_argument("--no-readonly-tools", action="store_true", help="disable real Read/Grep/Glob")
    ap.add_argument("--with-hooks", action="store_true",
                    help="keep project hooks on (WARNING: they may write ledgers for fake messages)")
    ap.add_argument("--baseline-sandbox", help="cwd for the nomemory arm (default: a fresh temp dir)")
    ap.add_argument("--no-report", action="store_true", help="dry-run only: do not write a report file")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="self-test graders on canned replies, no model call")
    mode.add_argument("--no-memory", action="store_true", help="run only the stripped-context baseline arm")
    mode.add_argument("--compare", action="store_true", help="run both arms and report the gap (2x runs)")
    mode.add_argument("--explain-arms", action="store_true", help="print what each arm loads/strips, no model call")
    args = ap.parse_args()
    REPLY_TOOL = args.reply_tool
    args.project_dir = args.project_dir.resolve()
    if args.explain_arms:
        return explain_arms(args)
    cases = load_cases(args.case, args.limit)
    if not cases:
        print("no cases selected")
        return 2
    if args.dry_run:
        dry_run.no_report = args.no_report  # type: ignore[attr-defined]
        return dry_run(cases)
    if args.compare:
        return compare_run(cases, args)
    return real_run(cases, args, ARM_NOMEM if args.no_memory else ARM_FULL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup_sandbox()
