---
name: root-cause-loop
description: Use when the agent hits a bug, a system anomaly, a behaviour deviation or a stuck process, when the same lint or hook fires 10+ times in a day, when 3 attempts at one approach have failed, when a violation repeats within 3 sessions, or when the operator says things like "why did this happen again", "root it out", "that wasn't caught". Also use at the moment of the "just patch the surface" reflex. Runs the root-cause loop to completion before anything is marked done.
---

# Root-cause loop

A problem that has not been rooted out has not been solved; it has been papered over. The
cheapest surface patch brings the same bug back a week later and grows the incident log.
The loop below must be walked before a fix is marked done.

## Step 0: start it yourself (do not wait to be told)

Start the loop when any of these holds:

- the same lint rule or hook blocks 10 or more times in a day (a spike);
- 3 attempts or 15 minutes on one approach without success;
- the same violation recurs within 3 sessions;
- a daily self-audit reports a warning or a critical;
- the operator corrects you, however small the correction;
- you notice something improvable during a patrol that nobody mentioned.

## The loop

```
trigger
  |
  +- 1. Same class before?  search the incident log and learning log (30 seconds)
  |       found -> handle the whole class together; not found -> continue
  |
  +- 2. Reproduce.  Can you trigger it reliably?
  |       no -> collect logs / more samples. Do not fix a guessed bug.
  |
  +- 3. Root cause.  Dig to the cause, not the symptom.
  |
  +- 4. Known answer?  Check your own incident log before searching the web.
  |
  +- 5. Prior art.  Search "<keywords> best practice", issue trackers, SRE writing.
  |
  +- 6. ROI gate.  (occurrences per month x minutes each) > (build hours x 60)?
  |       no -> record it, do not build a guard (avoid over-engineering).
  |
  +- 7. Blast radius + structural guard.
  |       blast radius: 0-1 files edit directly / 2-5 list first / 6+ plan first /
  |       critical infrastructure -> propose to the operator (ASK)
  |       guard type:
  |         action violation   -> hook (PreToolUse / PostToolUse / Stop)
  |         reply quality      -> lint rule
  |         periodic drift     -> scheduled check
  |         process violation  -> SOP or rule file
  |         behaviour a model upgrade could lose -> eval case
  |
  +- 8. Self-test.  Unit + integration; if it fails, back to step 3.
  |
  +- 9. Write it down, in three places:
          incident log   trigger / root cause / fix / prevention / re-test
          rule file      the extracted rule, loaded next session
          learning log   one line of what changed
```

## Meta root cause (mandatory before "done")

Ask one level up, at most three levels:

1. Did the same class of problem happen in the last 30 days? (search the incident log)
2. Why did that fix not catch this one?
3. Does this fix close that meta cause, or is it another lowest-cost surface patch?

If your task tracker supports metadata, require `root_cause` and `guard_file` on any
bug-fix task before it can be completed.

## Triage cheat sheet

| Symptom | Check in this order |
|---|---|
| State file / dashboard not updating | file mtime -> hook chain -> hook stderr -> concurrent writers -> render write-back |
| Reply format wrong | lint stderr -> the rule file -> run the lint self-test |
| API call failing | 403 user agent / 401 token / permission / 429 rate -> endpoint typo -> payload schema |
| Misclassification | compare samples -> classifier logic -> metadata overrides -> fallback marker |
| Sync drift | source of truth -> sync function -> missing fields -> reconciliation script |

## Counts as a violation

- claiming done without a self-test;
- fixing the symptom only, so the same bug returns;
- changing critical infrastructure without proposing it first;
- building a structural guard the ROI gate rejected.

## Exempt from self-test

Pure wording or typo changes, comments or frontmatter, pure rule-file edits: re-reading is
enough.
