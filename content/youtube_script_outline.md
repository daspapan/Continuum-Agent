# YouTube — script outline

**Working title:** "I built a Claude agent that survives being killed
mid-task (checkpoint/resume, from scratch)"

**Target length:** 14–18 minutes

**Audience:** developers who've built a basic Claude/LLM agent demo and want
to understand what changes when it has to run in production.

---

## Hook (0:00–0:45)

Cold open: screen recording of the pipeline running, then hard-cut a
`kill -9` on the process mid-run. Cut to: running `continuum resume
<run_id>` and it picks up exactly where it left off, no duplicate email at
the end.

Line: "Most agent demos fall apart the second something interrupts them.
This one doesn't. Here's how, and here's the four bugs that showed me why
it matters."

## 1. The problem, with a concrete failure (0:45–3:00)

Screen: walk through the four scenes this project is built around, without
jargon first:
- Agent can't recall a prior conversation without an exact ID
- Team argues about checkpoint frequency
- Resume happens into a world that quietly changed
- A payment (or email, in this project's case) gets sent twice

Say explicitly: these aren't four unrelated bugs, they're one missing
capability — a deliberate design for what gets remembered, how often, how
staleness gets caught, and in what order relative to actions you can't take
back.

## 2. The pipeline, live (3:00–6:00)

Screen: run `continuum research "<topic>"` locally. Narrate each phase as it
logs. Show the sqlite checkpoint file filling in row by row.

## 3. The core fix: checkpoint-before-action (6:00–9:30)

Screen: pull up `idempotency.py` and `orchestrator._run_publish`. Diagram
(reuse from the technical LinkedIn post) showing action→checkpoint (bug) vs
checkpoint→action (fix). Live demo: kill the process right after the
"claimed" log line, before send, resume, show it does NOT resend.

## 4. Why phase-boundary, not per-call (9:30–11:30)

Show the git history: the "try per-tool-call checkpointing everywhere"
commit immediately followed by "revert." Explain the reasoning out loud —
this is more interesting on camera than a clean history would be, because
it shows the actual thought process, not just the answer.

## 5. Staleness detection (11:30–13:00)

Live demo: tamper with a checkpointed source file, try to resume, show the
`StalenessError`. Explain content-hashing vs timestamp-based, briefly.

## 6. From laptop to production (13:00–16:00)

Screen: `docs/ARCHITECTURE.md`, then a fast walkthrough of the CDK stack
diagram — Step Functions, one shared Lambda instead of seven, DynamoDB
sharing checkpoints and idempotency claims in one table, OpenSearch
Serverless for recall. Explicitly call out the "cut corners" section — no
auth on the API yet, no DLQ — because pretending a v1 is finished is worse
than saying what's next.

## Close (16:00–end)

"Repo's linked below, MIT-licensed, README has the quickstart if you want
to run this yourself in the next five minutes. If you build agents that run
longer than a single request/response, this pattern — or your own version
of it — is worth having before you need it."

CTA: repo link, connect on LinkedIn for the technical breakdown post.

---

**B-roll / cutaway shot list:**
- Terminal running the CLI end to end
- Git log --graph showing the branch/merge/revert history
- ARCHITECTURE.md scrolling past the "Compute" section
- The double-send prevention diagram
