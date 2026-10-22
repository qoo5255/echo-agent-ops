# echo-agent-ops

Guardrails, autonomy tiers and a behaviour eval harness for running a business with a
Claude Code agent, extracted from a system that has operated a one-person company every day
since May 2026.

Most agent frameworks show what an agent can do. This repository is about what goes wrong
when one does real work unattended for months, and the structural fixes that held:

- **Autonomy tiers** (`docs/autonomy-tiers.md`, `classifier/`): a fixed AUTO / NOTIFY / ASK
  seating chart for actions, enforced by a hook, so the agent never has to judge
  "is this reversible?" in the middle of a task.
- **Guard hooks** (`hooks/`): nine deterministic Claude Code hooks, each born from a real
  incident: bulk deletes, name-based process kills, secrets in chat, heredoc escape
  corruption, frozen terminal dialogs, implied email sends, duplicate sub-agent dispatch,
  unverified status claims, evaporating promises.
- **Behaviour evals** (`evals/`): 20 deterministic regression cases run through the Claude
  Code CLI, plus a `--compare` mode that measures how much of the behaviour your rule layer
  is actually buying.
- **Skill templates** (`skills/`): root-cause loop, dispatch-first, verify-before-done.
- **Docs for solo operators** (`docs/`): the three principles, architecture, a step-by-step
  adoption guide, and a write-up of 23 failure modes.

No third-party dependencies. Written for Python 3.9+ and to be cross-platform; tested so
far on Python 3.12 on Windows.

## The three principles

1. **Root out.** Every failure gets traced to its root cause plus a meta question: why did
   the last fix not catch this one? Three tries or fifteen minutes on one approach, then
   switch. No surface patches.
2. **Evolve.** Every correction is codified on the spot, as a hook, an eval case, or (only
   if neither fits) a rule line. Check prior art before building anything.
3. **Never stop.** When the goal is clear and the action is reversible, run to completion
   without waiting for a "go". Stop only at a defined set of irreversible or high-impact
   actions, which stay human-approved.

More in [`docs/principles.md`](docs/principles.md).

## Quick start

```bash
git clone <this repo>
cd echo-agent-ops
python tests/run_all.py                 # every hook self-test + classifier + eval grader dry-run
```

Use it in your own agent project:

```bash
cp -r hooks classifier tools <your-project>/
# merge examples/settings.example.json into <your-project>/.claude/settings.json
echo ".agent-ops/" >> <your-project>/.gitignore
```

Run the evals against your agent (needs the `claude` CLI, costs a few cents per case):

```bash
python evals/run_evals.py --project-dir <your-project> --reply-tool <your chat tool> --limit 3
```

Then read [`docs/adapting-for-solo-operators.md`](docs/adapting-for-solo-operators.md).

## Layout

```
classifier/   autonomy-tier classifier (table + hook + CLI)
docs/         principles, architecture, autonomy tiers, adoption guide, failure modes
evals/        behaviour regression harness, 20 cases, deterministic lint
examples/     settings.json hook wiring
hooks/        guard hooks with self-tests
skills/       SKILL.md templates
tests/        run_all.py
tools/        commitment ledger CLI
```

## What this is not

- Not a framework or an agent. It is a set of controls you add to a Claude Code agent.
- Not a claim of adoption. This is a one-person project and the public version is new.
- Not complete. The guards document their known gaps in their docstrings. Read them.

## License

MIT, see [LICENSE](LICENSE).
