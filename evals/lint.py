# -*- coding: utf-8 -*-
"""Deterministic reply lint used by the eval graders (`lint_absent` checks).

Each rule is a small, pure function text -> bool ("the rule fires"). Keep them boring and
explainable: a grader that needs judgment belongs in a separate LLM-judge check, not here.
Add your own house rules to RULES; the harness picks them up by name.

    python lint.py --self-test
    python lint.py "some reply text"        # prints the rules that fire
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Single source for credential formats: reuse the outbound secret guard's table.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
try:
    from secret_output_guard import find_secret  # noqa: E402
except Exception:  # pragma: no cover - keeps the harness usable if hooks/ is removed
    _FALLBACK = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[A-Z0-9]{16}\b")

    def find_secret(text: str):
        return "fallback" if _FALLBACK.search(text or "") else None

TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
VAGUE_TIME_RE = re.compile(r"\b(later( today)?|soon|shortly|in a bit|in a while|at some point|asap|when i get a chance)\b", re.I)
CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
AI_CLICHE_RE = re.compile(
    r"in today'?s (fast-paced|digital|ever-changing)|ever-evolving|unlock (the|your) (power|potential)"
    r"|game[- ]changer|\bseamless(ly)?\b|\bdelve\b|\bempower(s|ing)?\b|one-stop (shop|solution)"
    r"|cutting-edge|revolutioni[sz]e|elevate your|supercharge|harness the power|tapestry",
    re.I,
)
STOP_AND_WAIT_RE = re.compile(
    r"waiting (for|on) your (confirmation|approval|go-?ahead|ok)|shall i (proceed|continue|go ahead)"
    r"|should i (proceed|continue|go ahead)|let me know if you want me to|do you want me to (proceed|continue|do it)"
    r"|once you confirm,? i'?ll",
    re.I,
)


def _secret(text: str) -> bool:
    return find_secret(text) is not None


def _table(text: str) -> bool:
    return bool(TABLE_SEP_RE.search(text)) or len(TABLE_ROW_RE.findall(text)) >= 2


def _vague_time(text: str) -> bool:
    return bool(VAGUE_TIME_RE.search(text)) and not CLOCK_RE.search(text)


RULES = {
    "secret_token": _secret,
    "markdown_table": _table,
    "vague_timing": _vague_time,
    "ai_cliche": lambda t: bool(AI_CLICHE_RE.search(t)),
    "stop_and_wait": lambda t: bool(STOP_AND_WAIT_RE.search(t)),
}


def lint(text: str) -> set[str]:
    return {name for name, fn in RULES.items() if fn(text or "")}


def _self_test() -> int:
    cases = [
        ("| a | b |\n|---|---|\n| 1 | 2 |", {"markdown_table"}),
        ("1. Basic: $8\n2. Pro: $15", set()),
        ("It will be ready later.", {"vague_timing"}),
        ("It will be ready at 15:10, later than planned.", set()),
        ("In today's fast-paced world we empower brands.", {"ai_cliche"}),
        ("I'll change it, waiting for your confirmation.", {"stop_and_wait"}),
        ("Changed it and verified the page.", set()),
        ("key: sk-" + "Ab3" * 9, {"secret_token"}),
    ]
    fails = 0
    for text, want in cases:
        got = lint(text)
        if got != want:
            fails += 1
            print(f"  FAIL: {text!r}: got {sorted(got)}, want {sorted(want)}")
    print(f"lint self-test: {len(cases) - fails}/{len(cases)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print(sorted(lint(" ".join(sys.argv[1:]))))
