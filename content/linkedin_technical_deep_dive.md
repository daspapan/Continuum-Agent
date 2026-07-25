# LinkedIn — Technical deep-dive post

The design decision in Continuum I'd defend hardest: checkpoint-before-
irreversible-action, not checkpoint-after.

Here's the failure mode it prevents. Pipeline sends an email, then crashes
before recording that the send happened. Process restarts, sees no record
of "email sent," replays the send. Customer/user gets a duplicate. This is
the exact shape of the classic "agent double-charges a customer" bug — same
root cause, whatever the irreversible action is.

The fix isn't "add more retries" or "check more carefully before retrying."
It's ordering: write the checkpoint immediately BEFORE the side-effecting
call, not after.

    checkpoint("publish", status="started")   # <- happens first
    claim_idempotency_key(run_id)              # <- conditional write, fails if already claimed
    send_email(...)                            # <- only reached if claim succeeded
    checkpoint("publish", status="completed")

If the process dies between claim and send, recovery sees "publish was
about to happen," checks the idempotency guard, sees it's already claimed,
and does NOT resend — worst case, a human checks the provider's own send
log to confirm delivery. The system never blindly replays.

Two other decisions worth calling out:

**Phase-boundary checkpointing, not per-step.** I initially tried
checkpointing after every tool call inside a phase — more frequent saves
feel strictly safer. Reverted it. The steps inside each phase are fast and
idempotent, so re-running a whole phase from scratch after an interruption
costs almost nothing. 12x the writes (metaphorically — Continuum has 7
phases) for no real safety margin isn't a trade I'd make in production
either.

**Environment-hash staleness detection.** Every checkpoint hashes the
source content the phase depended on. On resume, recompute the hash,
compare. Mismatch means the world changed while paused — a source got
edited, a draft got hand-modified — and the run flags it for review instead
of confidently synthesizing a report from data it can no longer vouch for.
Content-hashed, not timestamp-based, so it catches the actual change
regardless of what touched the mtime.

None of this is exotic. It's the same handful of patterns you'd reach for
in a payments system, applied to an agent pipeline instead — because the
failure modes (double-send, stale-data continuation, lost progress) are the
same failure modes.

Full writeup with the actual code: [link]

#AgenticAI #ClaudeAI #DistributedSystems #AWS
