# -*- coding: utf-8 -*-
"""PreToolUse guard (Bash / PowerShell): block heredocs / here-strings that write Python
source containing backslash escapes.

Incident class: on one day an agent wrote Python patches through shell heredocs four times.
Somewhere between the model's tool call and the shell, backslash sequences in the heredoc
body (`\\n`, `\\s`, `\\d`, `\\1` ...) were turned into real characters, so Python received
different source than intended: `"\\n"` became a literal newline (SyntaxError), and
`re.compile(r"\\s+")` silently became `re.compile(r" +")` (a broken regex that raises no
error). Two of those broken patches were committed. Reminders did not stop it; a guard did.

Blocks only when ALL three hold (kept narrow on purpose, this runs on every shell command):
  1. the command contains a heredoc start (`<<EOF`, `<<'EOF'`, `<<"EOF"`, `<<-EOF`; not `<<<`)
     or a PowerShell here-string (`@' ... '@`, `@" ... "@`);
  2. the opening line shows the body IS Python source:
       - redirected into a .py file (`cat > x.py <<EOF`, `cat >> x.py`, `tee -a x.py`), or
       - fed to the interpreter as the program (`python - <<PY`, `python3 <<PY`);
     `python script.py <<EOF` feeds DATA to a script and is not blocked;
     for PowerShell: Set-Content / Out-File / Add-Content / `>` into a .py, or piped to python;
  3. the body contains a backslash followed by one of [nrtsdw0-9].

Judging by the destination on the opening line (not by guessing the body's language) is
what keeps false positives near zero: a markdown note that happens to quote a Windows path
or a Python code fence is never blocked, and neither is a .js file that uses `import`.

Fix suggested to the agent: write the file with the editor tool, or avoid the escapes
(chr(10) instead of "\\n", [0-9] instead of \\d).

Known misses (all fail toward allowing): targets without a .py suffix, targets held in shell
variables or command substitutions, process substitution.

    python heredoc_backslash_guard.py --self-test
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SelfTest, command_of, quiet_stderr, read_payload, write_audit  # noqa: E402

NAME = "heredoc_backslash_guard"

BACKSLASH_SEQ_RE = re.compile(r"\\[nrtsdw0-9]")
HEREDOC_START_RE = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2(?!<)")
PY_EXE_RE = re.compile(r"^(?:.*[/\\])?(?:python\d?(?:\.\d+)?|py)(?:\.exe)?$", re.IGNORECASE)
PS_HERESTRING_RE = re.compile(r"@(['\"])\r?\n(.*?)\r?\n\1@", re.DOTALL)
PS_WRITES_PY_RE = re.compile(
    r"(Set-Content|Out-File|Add-Content|Tee-Object|New-Item)\b[^\n]*?\.py\b"
    r"|>>?\s*['\"]?[^\s'\"|;]+\.py\b"
    r"|\|\s*(?:python\d?|py)(?:\.exe)?\b",
    re.IGNORECASE,
)


def extract_heredocs(command: str) -> list[tuple[str, str]]:
    """[(opening_line, body)] for each bash heredoc in the command."""
    lines = command.splitlines()
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        starts = list(HEREDOC_START_RE.finditer(line))
        if not starts:
            i += 1
            continue
        j = i + 1
        for m in starts:  # consecutive heredocs on one line are read in order
            dash, delim = m.group(1) == "-", m.group(3)
            body: list[str] = []
            while j < len(lines):
                cand = lines[j].lstrip("\t") if dash else lines[j]
                if cand.rstrip("\r") == delim:
                    break
                body.append(lines[j])
                j += 1
            out.append((line, "\n".join(body)))
            j += 1
        i = j
    return out


def _stage_writes_python(stage: str) -> bool:
    stage = HEREDOC_START_RE.sub(" ", stage)
    # redirect into a .py file
    if re.search(r">>?\s*['\"]?[^\s'\"|;&]+\.py['\"]?(\s|$)", stage):
        return True
    try:
        toks = shlex.split(stage, posix=True)
    except ValueError:
        return False  # unbalanced quotes: unsure, so allow
    if not toks:
        return False
    word = toks[0]
    if word == "tee":
        return any(t.endswith(".py") for t in toks[1:] if not t.startswith("-"))
    if PY_EXE_RE.match(word):
        rest = toks[1:]
        k = 0
        while k < len(rest):
            tok = rest[k]
            if tok == "-":
                return True  # explicit "read program from stdin"
            if tok in ("-m", "-c"):
                return False  # module / inline program: the heredoc is data
            if tok == "-X" or tok == "-W":
                k += 2
                continue
            if tok.startswith("-"):
                k += 1
                continue
            return False  # a script path: the heredoc is data for that script
        return True  # bare `python <<EOF` runs stdin as the program
    return False


def writes_python_source(opening_line: str) -> bool:
    return any(_stage_writes_python(stage) for stage in re.split(r"\|\||&&|;|\|", opening_line))


def analyze(command: str) -> dict | None:
    for opening, body in extract_heredocs(command):
        if writes_python_source(opening) and BACKSLASH_SEQ_RE.search(body):
            return {"kind": "bash_heredoc", "opening": opening.strip()[:200],
                    "seq": BACKSLASH_SEQ_RE.search(body).group(0)}
    for m in PS_HERESTRING_RE.finditer(command):
        body = m.group(2)
        if BACKSLASH_SEQ_RE.search(body) and PS_WRITES_PY_RE.search(command[m.end():] + "\n" + command[:m.start()]):
            return {"kind": "powershell_herestring", "opening": "@" + m.group(1),
                    "seq": BACKSLASH_SEQ_RE.search(body).group(0)}
    return None


def handle(command: str) -> int:
    hit = analyze(command or "")
    if not hit:
        return 0
    write_audit(NAME, {"outcome": "blocked", **hit})
    sys.stderr.write(
        f"BLOCKED: a {hit['kind']} writes Python source containing the escape {hit['seq']!r}.\n"
        "Backslash sequences in heredoc bodies can be altered before the shell sees them, so the\n"
        "Python you get is not the Python you wrote (\\n -> real newline, \\s -> space).\n"
        "Instead: write the file with the editor/Write tool and run it, or avoid the escape\n"
        "(chr(10) for a newline, [0-9] for \\d, a character class for \\s).\n"
    )
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
    bs = "\\"
    py_body = f'import re{chr(10)}print(re.sub(r"{bs}s+", " ", "a  b")){chr(10)}'
    t.ck("cat > x.py with \\s blocks", analyze(f"cat > fix.py <<'EOF'\n{py_body}EOF") is not None)
    t.ck("cat >> x.py blocks", analyze(f"cat >> fix.py <<EOF\nx = '{bs}n'\nEOF") is not None)
    t.ck("tee -a x.py blocks", analyze(f"tee -a fix.py <<EOF\nx = '{bs}t'\nEOF") is not None)
    t.ck("python - blocks", analyze(f"python - <<'PY'\nprint('a{bs}nb')\nPY") is not None)
    t.ck("bare python3 blocks", analyze(f"python3 <<PY\nprint('{bs}d')\nPY") is not None)
    t.ck("py -X utf8 - blocks", analyze(f"py -X utf8 - <<PY\nprint('{bs}1')\nPY") is not None)
    t.ck("markdown note clean", analyze(f"cat >> NOTES.md <<'EOF'\nsee C:{bs}scripts{bs}data_import.py\nEOF") is None)
    t.ck("js file clean", analyze(f"cat > a.js <<'EOF'\nconst s = '{bs}n'\nEOF") is None)
    t.ck("data into script clean", analyze(f"python tool.py <<'EOF'\nline{bs}none\nEOF") is None)
    t.ck("python -m json.tool clean", analyze("python -m json.tool <<'EOF'\n{\"a\": \"" + bs + "n\"}\nEOF") is None)
    t.ck("py heredoc without escapes clean", analyze("python - <<'PY'\nprint(chr(10).join(['a','b']))\nPY") is None)
    t.ck("herestring <<< clean", analyze(f"python <<< 'print(1{bs}n)'") is None)
    t.ck("echo clean", analyze(f"echo 'a{bs}nb'") is None)
    t.ck("ps herestring to .py blocks",
         analyze(f"@'\nimport re; re.compile(r'{bs}d+')\n'@ | Set-Content fix.py") is not None)
    t.ck("ps herestring to .md clean",
         analyze(f"@'\npath C:{bs}new{bs}data\n'@ | Set-Content notes.md") is None)
    with quiet_stderr():
        t.ck("handle blocks", handle(f"cat > fix.py <<'EOF'\n{py_body}EOF") == 2)
        t.ck("handle allows", handle("ls -la") == 0)
    return t.finish()


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
