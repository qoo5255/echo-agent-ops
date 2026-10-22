# -*- coding: utf-8 -*-
"""PreToolUse guard: block any outbound message (chat reply, email, social post, comment)
whose text contains something that looks like a live credential.

Incident class: while explaining a timeline in chat, an agent pasted a complete API token
into a message the human (and anyone else in the channel) could see. It was visible for
about a minute before being deleted and rotated. "Never paste secrets" was already a
written rule; this guard makes it structural.

What counts as outbound: any tool whose name matches OUTBOUND_TOOL_RE (override with the
env var AGENT_OPS_OUTBOUND_TOOLS, a regex). The default covers common MCP naming:
`*__reply`, `*__send*`, `*__post*`, `*__publish*`, `*__comment*`, `*draft*`.

What counts as a credential: well-known prefixed formats (cloud / payment / code-host /
chat-bot / OAuth tokens, PEM private keys, JWT bearer tokens). Generic high-entropy
strings are NOT blocked here (too many false positives on hashes and IDs); add your own
patterns to EXTRA_PATTERNS if you have an in-house token format.

No bypass token: there is no legitimate reason to send a secret through a chat tool.
Point the human at the local secrets file path instead.

Self-test fixtures are assembled at runtime so this file never contains a token-shaped
literal (keeps secret scanners and push protection quiet).

    python secret_output_guard.py --self-test
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, quiet_stderr, read_payload, write_audit  # noqa: E402

NAME = "secret_output_guard"

OUTBOUND_TOOL_RE = re.compile(
    os.environ.get("AGENT_OPS_OUTBOUND_TOOLS")
    or r"^mcp__.*__(reply|send\w*|post\w*|publish\w*|\w*comment\w*|create_draft|update_draft|edit_message)$",
    re.IGNORECASE,
)

SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai_or_anthropic_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("stripe_key", re.compile(r"\b[sr]k_(live|test)_[A-Za-z0-9]{20,}")),
    ("aws_access_key_id", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}")),
    ("google_oauth_client_secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}")),
    ("google_oauth_access_token", re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}")),
    ("cloudflare_token", re.compile(r"\bcf[au]t_[A-Za-z0-9]{20,}", re.IGNORECASE)),
    ("discord_bot_token", re.compile(r"\b[MN][A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}")),
    ("jwt_bearer", re.compile(r"Bearer\s+eyJ[A-Za-z0-9_-]{20,}\.eyJ")),
    ("pem_private_key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
]
EXTRA_PATTERNS: list[tuple[str, re.Pattern]] = []  # add in-house formats here


def find_secret(text: str) -> str | None:
    for name, rx in SECRET_PATTERNS + EXTRA_PATTERNS:
        if rx.search(text or ""):
            return name
    return None


def outbound_text(tool_input: dict) -> str:
    """Every string in the tool input, flattened (text, body, subject, attachments...)."""
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(tool_input or {})
    return "\n".join(out)


def check(payload: dict) -> int:
    tool = str(payload.get("tool_name") or "")
    if not OUTBOUND_TOOL_RE.search(tool):
        return 0
    kind = find_secret(outbound_text(payload.get("tool_input") or {}))
    if not kind:
        return 0
    write_audit(NAME, {"tool": tool, "kind": kind, "outcome": "blocked"})  # never log the value itself
    sys.stderr.write(
        f"BLOCKED: this outbound message contains what looks like a credential ({kind}).\n"
        "Secrets never go into chat, email or posts. Remove the value and point to the local\n"
        "secrets file path instead (e.g. 'it is in .secrets/<name>.txt on the host').\n"
        "If the value was already sent somewhere, rotate it now and say so.\n"
    )
    return 2


def main() -> int:
    try:
        return check(read_payload())
    except Exception:
        return 0


def self_test() -> int:
    t = SelfTest(NAME)
    body = "Ab3" * 10  # 30 chars, mixed case + digits
    fake = {
        "openai_or_anthropic_key": "sk-" + body,
        "github_token": "gh" + "p_" + body,
        "aws_access_key_id": "AKIA" + "ABCDEFGHIJKLMNOP",
        "google_api_key": "AIza" + ("x1Y2" * 9)[:35],
        "pem_private_key": "-----BEGIN " + "PRIVATE KEY-----",
        "jwt_bearer": "Bearer " + "eyJ" + "a" * 24 + ".eyJ" + "b" * 10,
    }
    for kind, value in fake.items():
        t.ck(f"detects {kind}", find_secret(f"here you go: {value}") == kind)
    t.ck("plain text clean", find_secret("the token lives in .secrets/ads_token.txt") is None)
    t.ck("git sha clean", find_secret("commit 9f2c1e7a4b3d5f6a7b8c9d0e1f2a3b4c5d6e7f80") is None)
    t.ck("sk- prose clean", find_secret("use the sk- prefix check") is None)
    reply = {"tool_name": "mcp__chat__reply", "tool_input": {"chat_id": "1", "text": "key: " + fake["github_token"]}}
    email = {"tool_name": "mcp__mail__send_message", "tool_input": {"to": "a@example.com", "body": fake["openai_or_anthropic_key"]}}
    with quiet_stderr():
        t.ck("blocks reply with secret", check(reply) == 2)
        t.ck("blocks email with secret", check(email) == 2)
        t.ck("allows clean reply", check({"tool_name": "mcp__chat__reply", "tool_input": {"text": "done"}}) == 0)
        t.ck("ignores non-outbound tool", check({"tool_name": "Read", "tool_input": {"file_path": fake["github_token"]}}) == 0)
        t.ck("empty payload allowed", check({}) == 0)
    t.ck("nested list scanned", "deep" in outbound_text({"a": [{"b": "deep"}]}))
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
