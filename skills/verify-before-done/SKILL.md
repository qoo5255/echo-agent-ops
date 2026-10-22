---
name: verify-before-done
description: Use before telling the operator that anything is done, live, fixed, deployed, sent, valid or running; when a sub-agent reports completion; and before stating the current state of any external system (a site's stack, a key's validity, whether a job ran). Turns claims into evidence.
---

# Verify before "done"

"Dispatched" is not done. "Applied" is not proof. A verifier's FAIL can itself be a false
positive. Check the artifact, not the claim about it.

## The rule

Before a status sentence reaches the operator, one of these must exist **in this session**:

| Claim | Minimum evidence |
|---|---|
| a page is live / fixed | fetch the live URL (status 200) and look at the rendered page |
| a deploy took effect | the live response shows the change (not the deploy log) |
| a file was written | read it back |
| a key / token is valid | an authenticated test call succeeded |
| a key "doesn't exist" | you searched the secrets location and the tool index |
| a job / schedule ran | its log or output has a fresh timestamp |
| a site runs on X | a live check (headers, generator tag, admin endpoint) |
| an email / post went out | the sent item or the live post URL |
| a number | its source (API, report, query), named in the message |

If you cannot verify, say exactly that: "the worker reports X; I have not verified it yet,
checking at 15:10".

## Sub-agent reports

1. Read what the worker claims.
2. Check the deliverable yourself (open, fetch, diff, screenshot).
3. If a second agent disagrees, do not average them: check the contested facts directly
   (does the cited source resolve? does it contain the claim?).
4. Report what you saw, with the evidence.

## Review like a human would

For anything visual, look at the rendered output (a screenshot), not just the HTML. A page
that returns 200 can still be broken.

## Why this is a skill and a hook

The agent knows this rule and still breaks it under load, so the most common form (an
assertion about live state with no check in the session) is also caught by
`hooks/status_claim_verify_guard.py`. The skill covers the judgment the hook cannot.
