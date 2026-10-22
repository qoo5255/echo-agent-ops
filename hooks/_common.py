# -*- coding: utf-8 -*-
"""Shared helpers for the guard hooks in this directory.

Every hook here follows the Claude Code hook contract:
  * the hook receives one JSON object on stdin (tool_name, tool_input, transcript_path, ...)
  * exit code 0 = allow, exit code 2 = block (stderr is shown to the model)
  * Stop hooks may instead print {"decision": "block", "reason": "..."} on stdout

Design rules shared by all guards:
  * fail open: a malformed payload or an internal exception never blocks the agent.
    A guard that crashes and blocks every call is worse than a guard that misses one.
  * deterministic: no model calls, no network. A guard is a structural control that
    sits outside the model's judgment.
  * an explicit, human-supplied confirmation token is the only bypass. The token is a
    timestamp of when the human approved, e.g. `--operator-confirmed=2026-10-22-1530`.
    There is deliberately no "resend to pass" bypass on the safety guards.

Configuration (environment variables, all optional):
  AGENT_OPS_STATE_DIR      where audit logs / ledgers live
                           (default: $CLAUDE_PROJECT_DIR/.agent-ops, else ./.agent-ops)
  AGENT_OPS_CONFIRM_FLAG   name of the confirmation flag (default: operator-confirmed)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # best effort; some hosts give non-reconfigurable streams
        pass

CONFIRM_FLAG = os.environ.get("AGENT_OPS_CONFIRM_FLAG", "operator-confirmed")
CONFIRMATION_RE = re.compile(r"--" + re.escape(CONFIRM_FLAG) + r"=20\d{2}-\d{2}-\d{2}-\d{4}")

QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")

READONLY_PREFIX_RE = re.compile(
    r"^\s*(grep|rg|egrep|fgrep|findstr|cat|less|more|head|tail|ls|dir"
    r"|Get-Content|Select-String|Get-ChildItem|type|wc|sort|uniq)\b",
    re.IGNORECASE,
)


def state_dir() -> Path:
    explicit = os.environ.get("AGENT_OPS_STATE_DIR")
    if explicit:
        return Path(explicit)
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(root) / ".agent-ops"


def read_payload() -> dict:
    """Read the hook payload from stdin. Empty / broken / non-object input -> {}."""
    try:
        raw = sys.stdin.read()
        obj = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def is_confirmed(text: str) -> bool:
    return bool(CONFIRMATION_RE.search(text or ""))


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def scannable(command: str, exec_wrap_re: re.Pattern | None = None) -> str:
    """Text worth scanning: the command with top-level quoted literals blanked out
    (so a commit message that *mentions* `rm -rf` is not treated as running it), plus the
    inner command of `ssh host '...'` / `bash -c '...'` wrappers, which really execute."""
    command = command or ""
    inners = [m.group(2) for m in exec_wrap_re.finditer(command)] if exec_wrap_re else []
    return QUOTED_RE.sub(" ", command) + "\n" + "\n".join(inners)


def write_audit(name: str, record: dict) -> None:
    """Append one JSON line to <state_dir>/<name>_audit.jsonl. Never raises."""
    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now_iso(), **record}
        with (d / f"{name}_audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _transcript_entries(transcript_path: str | None, tail_lines: int = 800) -> list[dict]:
    """Last `tail_lines` JSONL entries of a Claude Code session transcript (best effort)."""
    if not transcript_path:
        return []
    try:
        p = Path(transcript_path)
        if not p.is_file():
            return []
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_lines:]
    except Exception:
        return []
    out = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _content_blocks(entry: dict) -> list:
    msg = entry.get("message") if isinstance(entry.get("message"), dict) else {}
    content = msg.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def last_human_text(transcript_path: str | None) -> str:
    """Text of the newest human-authored message (tool results are skipped)."""
    for entry in reversed(_transcript_entries(transcript_path)):
        if entry.get("type") != "user":
            continue
        blocks = _content_blocks(entry)
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
            continue
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def recent_tool_uses(transcript_path: str | None, tail_lines: int = 500) -> list[dict]:
    """[{name, input}] for assistant tool_use blocks near the end of the transcript."""
    uses = []
    for entry in _transcript_entries(transcript_path, tail_lines):
        if entry.get("type") != "assistant":
            continue
        for b in _content_blocks(entry):
            if isinstance(b, dict) and b.get("type") == "tool_use":
                uses.append({"name": b.get("name", ""), "input": b.get("input") or {}})
    return uses


def command_of(payload: dict) -> str:
    return str((payload.get("tool_input") or {}).get("command") or "")


class SelfTest:
    """Tiny assertion collector used by every hook's --self-test."""

    def __init__(self, name: str):
        import tempfile
        # self-tests must never write audit logs / ledgers into a real project
        os.environ["AGENT_OPS_STATE_DIR"] = tempfile.mkdtemp(prefix="agent_ops_selftest_")
        self.name = name
        self.results: list[tuple[str, bool]] = []

    def ck(self, label: str, cond) -> None:
        self.results.append((label, bool(cond)))

    def finish(self) -> int:
        passed = sum(ok for _, ok in self.results)
        for label, ok in self.results:
            if not ok:
                sys.stderr.write(f"  FAIL: {label}\n")
        sys.stdout.write(f"{self.name} self-test: {passed}/{len(self.results)} PASS\n")
        return 0 if passed == len(self.results) else 1


class quiet_stderr:
    """Context manager: swallow stderr while a self-test exercises the block path."""

    def __enter__(self):
        import io
        self._real = sys.stderr
        sys.stderr = io.StringIO()
        return self

    def __exit__(self, *exc):
        sys.stderr = self._real
        return False
