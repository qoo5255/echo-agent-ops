# -*- coding: utf-8 -*-
"""PreToolUse guard: deny the interactive multiple-choice question tool in a session that
is operated remotely (the human talks to the agent through chat, not the terminal).

Incident class: the agent opened an interactive question dialog in the terminal. The human
was only reading the chat channel, could not see or answer the dialog, and the whole
session sat frozen for 13 minutes. The rule "ask in chat instead" existed but lived only
in prose; moving it to the tool layer removed the failure entirely.

Replace with: a chat message that lists numbered options and says "reply with the number",
or chat-side buttons if your chat integration supports them.

Answers in both hook conventions: JSON permissionDecision=deny on stdout, plus exit 2 and
stderr, so it works whichever one the harness honours.

Set AGENT_OPS_ALLOW_INTERACTIVE=1 to disable (e.g. when you are sitting at the terminal).

    python block_interactive_question.py --self-test
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, read_payload  # noqa: E402

NAME = "block_interactive_question"
BLOCKED_TOOLS = {"AskUserQuestion", "AskQuestion"}
DENY_REASON = (
    "Interactive question dialogs are disabled: the operator reads chat, not this terminal, "
    "so the dialog would freeze the session. Ask in chat instead: list numbered options "
    "(1. ... 2. ...) and end with 'reply with the number', or use chat buttons if available."
)


def check(payload: dict) -> tuple[int, dict]:
    if os.environ.get("AGENT_OPS_ALLOW_INTERACTIVE") == "1":
        return 0, {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    if payload.get("tool_name", "") in BLOCKED_TOOLS:
        return 2, {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                   "permissionDecisionReason": DENY_REASON}
    return 0, {"hookEventName": "PreToolUse", "permissionDecision": "allow"}


def main() -> int:
    try:
        code, out = check(read_payload())
    except Exception:
        return 0
    if code == 2:
        print(json.dumps({"hookSpecificOutput": out}))
        print(DENY_REASON, file=sys.stderr)
    return code


def self_test() -> int:
    t = SelfTest(NAME)
    for tool in sorted(BLOCKED_TOOLS):
        code, out = check({"tool_name": tool})
        t.ck(f"deny {tool}", code == 2 and out["permissionDecision"] == "deny")
    for tool in ("Bash", "Read", "Edit", "mcp__chat__reply"):
        t.ck(f"allow {tool}", check({"tool_name": tool})[0] == 0)
    t.ck("empty payload allowed", check({})[0] == 0)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
