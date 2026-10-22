# -*- coding: utf-8 -*-
"""PreToolUse gate: a real email send requires the human's newest message to contain an
explicit send command (default word: "send"), not merely approval of a draft.

Incident classes:
  * a cold-email batch was quietly downgraded from "ask first" to "send and tell" by the
    agent's own reasoning ("the operator liked the draft, so sending is implied");
  * a pilot script with a retry bug sent 26 duplicate emails to the same recipients.
"Looks good" is approval of the text. Sending is a separate, irreversible, external action.

Gated (configurable with AGENT_OPS_EMAIL_SEND_TOOLS, a regex over tool names):
  mcp__*gmail*__send_message / reply / forward / send_draft, mcp__*__send_email
  and shell commands that run a script named like *send_mail* / *gmail_send* / *send_email*.
Never gated: creating or updating drafts, reading mail.

Approval = the newest human message in the transcript contains the send word and is not a
negation ("don't send", "do not send", "not yet", "hold off", "wait"). Override the word
with AGENT_OPS_SEND_WORD.

Mode: BLOCK by default. Set AGENT_OPS_EMAIL_GATE_MODE=warn to log and allow while you tune it.

    python email_send_gate.py --self-test
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, last_human_text, quiet_stderr, read_payload, write_audit  # noqa: E402

NAME = "email_send_gate"
SEND_WORD = os.environ.get("AGENT_OPS_SEND_WORD", "send")
MCP_SEND_RE = re.compile(
    os.environ.get("AGENT_OPS_EMAIL_SEND_TOOLS")
    or r"^mcp__.*gmail[^_]*__(send_message|reply|forward|send_draft)$|^mcp__.*__send_email$",
    re.IGNORECASE,
)
SCRIPT_SEND_RE = re.compile(r"\b(?:python[\w.]*|py|node)(?:\.exe)?\b[^|;&\n]*?\b\w*(send_?mail|gmail_send|send_email)\w*\.(py|js)\b",
                            re.IGNORECASE)
NEGATION_RE = re.compile(
    r"\b(don'?t|do not|never|not yet|no need to|hold off|wait|stop)\b[^.\n]{0,20}\b" + re.escape(SEND_WORD)
    + r"|\b" + re.escape(SEND_WORD) + r"\b[^.\n]{0,15}\b(later|tomorrow|after)\b",
    re.IGNORECASE,
)
SEND_WORD_RE = re.compile(r"\b" + re.escape(SEND_WORD) + r"\b", re.IGNORECASE)


def send_target(payload: dict) -> str | None:
    tool = str(payload.get("tool_name") or "")
    if MCP_SEND_RE.search(tool):
        return tool
    if tool in ("Bash", "PowerShell"):
        cmd = str((payload.get("tool_input") or {}).get("command") or "")
        m = SCRIPT_SEND_RE.search(cmd)
        if m and "--draft" not in cmd:
            return m.group(0)[:120]
    return None


def human_approved(text: str) -> bool:
    return bool(SEND_WORD_RE.search(text or "")) and not NEGATION_RE.search(text or "")


def check(payload: dict) -> int:
    target = send_target(payload)
    if not target:
        return 0
    if human_approved(last_human_text(payload.get("transcript_path"))):
        write_audit(NAME, {"target": target, "outcome": "allowed_send_word"})
        return 0
    warn_only = os.environ.get("AGENT_OPS_EMAIL_GATE_MODE", "block").lower() == "warn"
    write_audit(NAME, {"target": target, "outcome": "warned" if warn_only else "blocked"})
    sys.stderr.write(
        f"{'WARNING' if warn_only else 'BLOCKED'}: email send without an explicit '{SEND_WORD}' from the operator.\n"
        "Approving a draft is not a send command. Keep it as a draft and tell the operator:\n"
        f"'reply \"{SEND_WORD}\" and I will send it.'\n"
    )
    return 0 if warn_only else 2


def main() -> int:
    try:
        return check(read_payload())
    except Exception:
        return 0


def self_test() -> int:
    import json
    import tempfile
    t = SelfTest(NAME)

    def transcript(human: str) -> str:
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": human}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}) + "\n")
        f.close()
        return f.name

    t.ck("approve plain", human_approved("looks good, send it"))
    t.ck("approve bare word", human_approved("send"))
    t.ck("reject draft praise", not human_approved("the draft looks good"))
    t.ck("reject negation", not human_approved("don't send yet"))
    t.ck("reject not yet", not human_approved("not yet, I will send it myself later"))
    t.ck("reject later", not human_approved("send it tomorrow"))
    t.ck("mcp send gated", send_target({"tool_name": "mcp__claude_ai_Gmail__send_message"}))
    t.ck("draft not gated", send_target({"tool_name": "mcp__claude_ai_Gmail__create_draft"}) is None)
    t.ck("script send gated", send_target({"tool_name": "Bash", "tool_input": {"command": "python scripts/gmail_send.py --to a@example.com"}}))
    t.ck("grep script not gated", send_target({"tool_name": "Bash", "tool_input": {"command": "grep def scripts/gmail_send.py"}}) is None)
    os.environ.pop("AGENT_OPS_EMAIL_GATE_MODE", None)
    with quiet_stderr():
        t.ck("blocks without word", check({"tool_name": "mcp__x_gmail__send_message",
                                            "transcript_path": transcript("that draft looks great")}) == 2)
        t.ck("allows with word", check({"tool_name": "mcp__x_gmail__send_message",
                                         "transcript_path": transcript("ok send it")}) == 0)
        t.ck("blocks with no transcript", check({"tool_name": "mcp__x_gmail__send_message"}) == 2)
        t.ck("ignores other tools", check({"tool_name": "Read"}) == 0)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
