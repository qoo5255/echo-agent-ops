# Contributing

Thanks for looking. This project grows the same way the private system did: from real
incidents. The most useful contributions are failure modes you have actually seen.

## Good contributions

- **A new eval case** for a failure you observed in your own agent. Follow the steps in
  `evals/README.md`; `python evals/run_evals.py --dry-run` must show `selftest OK` for it.
- **A new guard hook** for an action that can be detected deterministically. Keep the shape
  of the existing hooks: pure scan function, fail open, audit line, `--self-test` with both
  hits and near-misses. Explain the incident class in the docstring and list known gaps.
- **False-positive fixes.** If a guard blocked something legitimate, open an issue with the
  exact command (redact anything private) and add it to the self-test as a near-miss.
- **Patterns for other languages** in the status-claim guard, the email gate and the lint.

## Rules for every change

1. `python tests/run_all.py` passes.
2. No real names, client names, domains, chat IDs, tokens or personal paths anywhere,
   including test fixtures. Build token-shaped fixtures at runtime (see
   `hooks/secret_output_guard.py`) so secret scanners stay quiet.
3. No third-party dependencies in hooks. Hooks run on every tool call; they must start fast
   and never fail because a package is missing.
4. Guards fail open on errors. Safety guards block only on a high-confidence signal.
5. Prefer narrowing a pattern over widening it. A guard that misfires gets routed around.

## Reporting a security issue

If you find a way to bypass a safety guard (bulk delete, secret output, email send), please
open an issue describing the class of bypass without a working exploit, or contact the
maintainer through the profile on the repository host.
