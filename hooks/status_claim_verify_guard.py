# -*- coding: utf-8 -*-
"""PreToolUse guard on outbound replies: a claim about the CURRENT state of an external
system must be backed by a check made in this session.

Incident classes (same day, same root):
  * the agent told the operator a site "still runs on WordPress"; it had been migrated to a
    static build weeks earlier;
  * the agent said an API key "could not be found"; it was sitting in the secrets folder;
  * a sub-agent reported "deployed, done"; the agent relayed it as fact without opening the
    live page (the deploy had not taken effect).
Common root: a conclusion about live state, drawn from memory or from someone else's
claim, with zero checks. The fix is structural: assert-without-evidence gets stopped once.

Detected assertion families (English; extend STATE_CLAIM_PATTERNS for your language):
  deployment / page live, credential valid / expired / missing, service or schedule
  running / down, site technology stack.
Not treated as assertions: questions, hedged statements ("might", "probably", "not sure",
"checking", "let me verify").

Evidence = a tool call in the recent transcript that actually observes state: a shell
command using curl / wget / Invoke-WebRequest / ssh / systemctl / Get-Service / schtasks /
gh / git ls-remote, a web fetch, a browser navigate/screenshot/snapshot, or a file read.

Behaviour: block ONCE per distinct message text. If the agent did check (or decides the
claim is safe), sending the identical text again passes. This keeps false positives cheap.

    python status_claim_verify_guard.py --self-test
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, quiet_stderr, read_payload, recent_tool_uses, state_dir, write_audit  # noqa: E402

NAME = "status_claim_verify_guard"
REPLY_TOOL_RE = re.compile(os.environ.get("AGENT_OPS_REPLY_TOOLS") or r"^mcp__.*__(reply|send_message|post_message)$",
                           re.IGNORECASE)

STATE_CLAIM_PATTERNS = [
    ("deploy_live", re.compile(r"\b(is|are|went|now)\s+live\b|\b(deployed|shipped)\s+(to|on)\s+(prod|production|the live)"
                               r"|\b(is|are)\s+(up|down)\s+(now|again)\b|\breturns?\s+(HTTP\s+)?[2-5]\d\d\b", re.I)),
    ("credential_state", re.compile(r"\b(key|token|credential|password|cert(ificate)?)s?\s+(is|are)\s+(still\s+)?"
                                    r"(valid|working|active|expired|revoked|invalid|missing|gone)\b"
                                    r"|\b(can'?t|cannot|couldn'?t)\s+find\s+(the\s+)?(api\s+)?(key|token|credential)", re.I)),
    ("service_state", re.compile(r"\b(service|daemon|job|cron|schedule|scheduled task|worker|server|pipeline)s?\s+"
                                 r"(is|are|has|have)\s+(still\s+)?(running|down|stopped|dead|crashed|not running|failing)\b", re.I)),
    ("tech_stack", re.compile(r"\b(site|website|blog|store)\s+(is\s+)?(still\s+)?(runs?|running|built|hosted)\s+on\s+\w+", re.I)),
]
HEDGE_RE = re.compile(r"\?|\b(might|may|maybe|probably|possibly|not sure|unsure|i think|checking|let me (check|verify)"
                      r"|i'?ll (check|verify)|to be confirmed|unverified)\b", re.I)
EVIDENCE_SHELL_RE = re.compile(r"\b(curl|wget|Invoke-WebRequest|iwr|Invoke-RestMethod|ssh|systemctl|Get-Service"
                               r"|schtasks|Get-ScheduledTask|gh\s|git\s+ls-remote|ping|nslookup|dig|Test-Path)\b", re.I)
EVIDENCE_TOOL_RE = re.compile(r"^(WebFetch|Read|Grep|Glob)$|navigate|screenshot|snapshot|pagespeed|health", re.I)


def find_claim(text: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?\n])\s+", text or ""):
        if HEDGE_RE.search(sentence):
            continue
        for kind, rx in STATE_CLAIM_PATTERNS:
            if rx.search(sentence):
                return kind
    return None


def has_evidence(uses: list[dict]) -> bool:
    for u in uses:
        name = str(u.get("name") or "")
        if REPLY_TOOL_RE.search(name):
            continue
        if EVIDENCE_TOOL_RE.search(name):
            return True
        if name in ("Bash", "PowerShell") and EVIDENCE_SHELL_RE.search(str((u.get("input") or {}).get("command") or "")):
            return True
    return False


def _seen_path() -> Path:
    return state_dir() / "status_claim_seen.json"


def _seen_once(text: str) -> bool:
    """True if this exact text was already blocked once (then let it through)."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    p = _seen_path()
    try:
        seen = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    except Exception:
        seen = []
    if h in seen:
        return True
    seen = (seen + [h])[-200:]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(seen), encoding="utf-8")
    except Exception:
        pass
    return False


def check(payload: dict) -> int:
    if not REPLY_TOOL_RE.search(str(payload.get("tool_name") or "")):
        return 0
    ti = payload.get("tool_input") or {}
    text = str(ti.get("text") or ti.get("content") or ti.get("message") or "")
    kind = find_claim(text)
    if not kind or has_evidence(recent_tool_uses(payload.get("transcript_path"))):
        return 0
    if _seen_once(text):
        write_audit(NAME, {"kind": kind, "outcome": "allowed_second_send"})
        return 0
    write_audit(NAME, {"kind": kind, "outcome": "blocked_once"})
    sys.stderr.write(
        f"BLOCKED ONCE: this reply asserts the current state of an external system ({kind}),\n"
        "but no check of that system appears in this session. Look first (curl the URL, open the\n"
        "page, query the service, read the file), then send. If the claim is already verified or\n"
        "you rephrase it as unverified, sending the same text again will pass.\n"
    )
    return 2


def main() -> int:
    try:
        return check(read_payload())
    except Exception:
        return 0


def self_test() -> int:
    import tempfile
    t = SelfTest(NAME)

    def transcript(tool_uses: list[dict]) -> str:
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": u["name"], "input": u.get("input", {})} for u in tool_uses]}}) + "\n")
        f.close()
        return f.name

    t.ck("claim live", find_claim("The pricing page is live now.") == "deploy_live")
    t.ck("claim key expired", find_claim("The ads token is expired.") == "credential_state")
    t.ck("claim cant find key", find_claim("I can't find the API key anywhere.") == "credential_state")
    t.ck("claim service down", find_claim("The backup job is not running.") == "service_state")
    t.ck("claim stack", find_claim("The site still runs on WordPress.") == "tech_stack")
    t.ck("question clean", find_claim("Is the pricing page live now?") is None)
    t.ck("hedge clean", find_claim("The page might be live, let me check.") is None)
    t.ck("plain clean", find_claim("I drafted three headline options.") is None)
    t.ck("curl is evidence", has_evidence([{"name": "Bash", "input": {"command": "curl -sI https://example.com/"}}]))
    t.ck("webfetch is evidence", has_evidence([{"name": "WebFetch"}]))
    t.ck("echo is not evidence", not has_evidence([{"name": "Bash", "input": {"command": "echo hi"}}]))
    reply = {"tool_name": "mcp__chat__reply", "tool_input": {"text": "Deployed to production, the page is live now."}}
    with quiet_stderr():
        t.ck("blocks unverified claim", check({**reply, "transcript_path": transcript([])}) == 2)
        t.ck("second identical send passes", check({**reply, "transcript_path": transcript([])}) == 0)
        t.ck("verified claim passes", check({"tool_name": "mcp__chat__reply",
                                             "tool_input": {"text": "Checked: the service is running."},
                                             "transcript_path": transcript([{"name": "Bash", "input": {"command": "systemctl status app"}}])}) == 0)
        t.ck("non-reply ignored", check({"tool_name": "Bash", "tool_input": {"command": "ls"}}) == 0)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
