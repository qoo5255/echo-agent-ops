# -*- coding: utf-8 -*-
"""PreToolUse guard (Bash / PowerShell): block "kill every process with this name".

Incident class: a sub-agent shutting down its own test server ran `taskkill /IM node.exe /F`.
That killed every node.exe on the machine, not just its own, and took four unrelated tools
offline (browser automation, a notes app bridge, a test runner, a docs server). The
follow-up "I'll add a rule for this" was only said in chat and never implemented; the
guard below is the real fix.

Blocked (name-based, no PID):
  taskkill /IM <name>  |  Stop-Process -Name <name>  |  pkill / pkill -f / killall
  wmic process where "name='x'" delete|call terminate  |  Get-Process x | Stop-Process
Allowed:
  anything PID-scoped (/PID, -Id <n>, kill <pid>), read-only commands, quoted literals.
Bypass: append `--operator-confirmed=YYYY-MM-DD-HHMM` when a human asked for it.

    python unscoped_process_kill_guard.py --self-test
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (SelfTest, command_of, is_confirmed, quiet_stderr, read_payload,  # noqa: E402
                     scannable, write_audit, CONFIRM_FLAG)

NAME = "unscoped_process_kill_guard"

READONLY_RE = re.compile(
    r"^\s*(grep|rg|findstr|cat|less|head|tail|ls|dir|Get-Content|Select-String|Get-ChildItem|type"
    r"|Get-Process\s*$)\b", re.IGNORECASE)
PID_SCOPED_RE = re.compile(r"/PID\b|-Id\s+\d|Stop-Process\s+(-Id|-InputObject)\b", re.IGNORECASE)
UNSCOPED_KILL_RE = re.compile(
    r"taskkill[^\n]*?/IM\b"
    r"|Stop-Process\b[^\n]*-Name\b"
    r"|\bpkill\b|\bkillall\b"
    r"|wmic\s+process\s+where[^\n]*?(delete|call\s+terminate)"
    r"|Get-Process\b[^\n]*?\|\s*Stop-Process\b",
    re.IGNORECASE,
)

BLOCK_MSG = (
    "BLOCKED: name-based process kill (kills every process with that name, not just yours).\n"
    "Use the exact PID of the process you started instead:\n"
    "  taskkill /PID <pid> /F   |   Stop-Process -Id <pid>   |   kill <pid>\n"
    f"If a human explicitly asked for a name-based kill, append --{CONFIRM_FLAG}=YYYY-MM-DD-HHMM.\n"
)


def scan_command(command: str) -> bool:
    if not command or READONLY_RE.search(command):
        return False
    text = scannable(command)
    return bool(UNSCOPED_KILL_RE.search(text)) and not PID_SCOPED_RE.search(text)


def handle(command: str) -> int:
    if not scan_command(command):
        return 0
    if is_confirmed(command):
        write_audit(NAME, {"outcome": "allowed_with_token", "cmd": command[:400]})
        return 0
    write_audit(NAME, {"outcome": "blocked", "cmd": command[:400]})
    sys.stderr.write(BLOCK_MSG)
    return 2


def main() -> int:
    try:
        payload = read_payload()
        if payload.get("tool_name") not in ("Bash", "PowerShell"):
            return 0
        return handle(command_of(payload))
    except Exception:
        return 0


def self_test() -> int:
    t = SelfTest(NAME)
    for cmd in ("taskkill /IM node.exe /F", "taskkill /F /IM python.exe", "Stop-Process -Name chrome -Force",
                "Stop-Process -Force -Name chrome", "pkill node", "pkill -f uvicorn", "killall node",
                "wmic process where \"name='node.exe'\" delete", "Get-Process node | Stop-Process -Force"):
        t.ck(f"hit: {cmd}", scan_command(cmd) is True)
    for cmd in ("taskkill /PID 12345 /F", "Stop-Process -Id 12345", "kill 12345", "kill -9 12345",
                "grep -r taskkill scripts/", "Get-Process", "git status", "",
                'git commit -m "block taskkill /IM node.exe"'):
        t.ck(f"clean: {cmd!r}", scan_command(cmd) is False)
    with quiet_stderr():
        t.ck("handle blocks", handle("taskkill /IM node.exe /F") == 2)
        t.ck("handle token", handle(f"taskkill /IM node.exe /F --{CONFIRM_FLAG}=2026-10-22-0900") == 0)
        t.ck("handle pid", handle("taskkill /PID 999 /F") == 0)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
