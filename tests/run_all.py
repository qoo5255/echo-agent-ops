#!/usr/bin/env python3
"""Run every self-test in the repo: each hook, the classifier, the commitment CLI, the lint
and the eval graders (dry run, no model call). Exit 0 only if everything passes.

    python tests/run_all.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, args: list[str], env: dict | None = None) -> bool:
    p = subprocess.run([sys.executable, *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env={**os.environ, **(env or {})})
    ok = p.returncode == 0
    tail = (p.stdout.strip().splitlines() or [""])[-1]
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {tail}")
    if not ok:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:])
    return ok


def commitment_cli_roundtrip() -> bool:
    state = tempfile.mkdtemp(prefix="agent_ops_cli_")
    env = {"AGENT_OPS_STATE_DIR": state}
    cli = "tools/commitment_cli.py"
    p = subprocess.run([sys.executable, cli, "add", "roundtrip item", "--eta", "2026-10-22 18:00"], cwd=str(ROOT),
                       capture_output=True, text=True, env={**os.environ, **env})
    cid = p.stdout.strip()
    ok = p.returncode == 0 and len(cid) == 8
    ok = ok and run("commitment_cli done", [cli, "done", cid, "--note", "verified"], env)
    p2 = subprocess.run([sys.executable, cli, "done", cid, "--note", "again"], cwd=str(ROOT),
                        capture_output=True, text=True, env={**os.environ, **env})
    ok = ok and p2.returncode == 1  # closing twice is refused
    print(f"[{'PASS' if ok else 'FAIL'}] commitment_cli roundtrip (add -> done -> refuse second done)")
    return ok


def main() -> int:
    results = []
    for hook in sorted((ROOT / "hooks").glob("*.py")):
        if hook.name.startswith("_"):
            continue
        results.append(run(f"hooks/{hook.name}", [str(hook.relative_to(ROOT)), "--self-test"]))
    results.append(run("classifier/autonomy_tier.py", ["classifier/autonomy_tier.py", "--self-test"]))
    results.append(commitment_cli_roundtrip())
    results.append(run("evals/lint.py", ["evals/lint.py", "--self-test"]))
    results.append(run("evals/run_evals.py --dry-run", ["evals/run_evals.py", "--dry-run", "--no-report"]))
    passed = sum(results)
    print(f"\n{passed}/{len(results)} suites passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
