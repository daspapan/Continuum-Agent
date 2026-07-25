# LinkedIn — Announcement post

I keep seeing the same failure mode in agent projects: they work great in a
demo, then fall over the first time something interrupts them mid-task. A
Lambda times out, a laptop closes, a process crashes — and the agent either
loses everything and starts over, or worse, repeats an action it already
took.

So I built Continuum: a Claude-powered research agent designed to be killed
at any point and resume correctly. Not "restart from zero" — actually
resume from wherever it was, without redoing finished work or double-firing
the one step that can't be undone (sending the final report).

What it does:
→ Runs a 7-phase research pipeline (plan → gather → read → synthesize →
  draft → cite-check → publish)
→ Checkpoints at phase boundaries in DynamoDB — coarse enough to be cheap,
  fine enough to never redo more than a few idempotent seconds of work
→ Detects staleness on resume: if a source changed while the run was
  paused, it flags the conflict instead of confidently continuing on data
  it can no longer vouch for
→ Guards the one irreversible action (publish) with checkpoint-before-action
  ordering + a conditional-write idempotency claim, so a crash mid-send
  can't cause a duplicate

Built it local-first — the whole pipeline runs on a laptop with just an
Anthropic API key before it ever touches AWS — then layered on the
production side: Step Functions + Lambda, OpenSearch Serverless for semantic
recall, DynamoDB, SES, all wired through CDK with dev/staging/prod
separation and a CI/CD pipeline that gates prod behind manual approval.

24 tests, full architecture writeup, deployment runbook, the works. Repo and
technical breakdown coming in the next post.

If you're building anything that runs longer than a single request-response
cycle, this pattern (or some version of it) is worth having before you need
it, not after the first duplicate charge / duplicate email / silently stale
report.

#AgenticAI #ClaudeAI #AWS #SoftwareArchitecture
