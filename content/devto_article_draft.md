# dev.to / Medium — article draft

## Title
Checkpoint-Safe Memory for a Long-Running Claude Agent: A Worked Example

## Subtitle
What actually changes when an agent has to survive being interrupted —
walked through with a real, small, MIT-licensed research agent.

---

### The failure mode this solves

Most agent tutorials stop at "call the model, get a response, maybe use a
tool." That's enough for a request/response demo. It's not enough the
moment your agent's work spans more than one LLM call with real state in
between — a multi-phase pipeline, a background job, anything that can
outlive a single process.

The moment it can outlive a process, it can also be *interrupted* by that
process dying. And once interruption is possible, four questions stop being
optional:

1. **What does the agent remember**, and how does it find the right memory
   without an exact key?
2. **How often does it commit that memory to durable storage** — too rarely
   and you lose work, too often and recovery becomes its own source of bugs?
3. **How does it know when its memory has gone stale** after a pause — is
   the data it's about to act on still accurate?
4. **In what order does it commit memory relative to actions it can't take
   back?**

I built a small project, Continuum, specifically to answer all four in one
place, sized so you can read the whole thing in an afternoon instead of
reverse-engineering the pattern from a much larger production codebase.

### What it does

Continuum is a Claude-backed research agent. Give it a topic, it runs a
7-phase pipeline (plan, gather sources, read them, synthesize findings,
draft a report, cite-check it, publish/email it). You can kill the process
at any point and resume it later; it picks up from the last completed
phase, and if the world changed while it was paused, it tells you instead
of guessing.

### 1. Semantic recall, not exact-key lookup

The PLAN phase asks: "have we researched something related to this topic
before?" There's no ticket number or session ID to look up with — the only
thing available is the meaning of the current topic. That's a vector search
problem, not a database lookup:

```python
memory_hits = self.memory.search(state["topic"], top_k=3)
plan = self.agent.plan(state["topic"], [m.text for m in memory_hits])
```

Locally this runs against a sqlite-backed brute-force cosine similarity
store (`LocalVectorStore`) so you can try it without any cloud account. In
production it's OpenSearch Serverless. Same interface, swappable backend —
see `src/continuum/memory/vector_store.py`.

### 2. Checkpoint granularity: coarse by default, justified when fine

Every phase writes exactly one checkpoint, after it completes:

```python
self.checkpoints.write(run_id, phase, status="completed", state=state, env_hash=env_hash)
```

Not after every tool call inside the phase. I actually built the per-call
version first — more frequent saves feels strictly safer — and reverted it
the same day. The steps within a phase are fast and idempotent; if a phase
crashes partway through, re-running the whole phase from scratch costs
almost nothing. Checkpointing every sub-step bought extra writes and extra
recovery-state complexity for a safety margin that doesn't actually
materialize unless a step is slow or has an external side effect.

Exactly one phase in this pipeline meets that bar: publish.

### 3. Staleness detection via content hashing

Every checkpoint records a hash of the source content the phase depended
on:

```python
def compute_environment_hash(sources: list[dict]) -> str:
    normalized = sorted(sources, key=lambda s: s["id"])
    canonical = json.dumps([{"id": s["id"], "content": s["content"]} for s in normalized], sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
```

On resume, recompute the hash from current state and compare:

```python
if current_hash != latest.env_hash:
    raise StalenessError(run_id, latest.phase, latest.env_hash, current_hash)
```

Content-hashed rather than timestamp- or ETag-based on purpose: it catches
"this actually changed" regardless of what touched the modification time,
and it works the same whether the source lives on local disk or in S3. A
mismatch doesn't retry-and-hope; it stops and flags for review (in the AWS
version, via an SNS alert routed from a Step Functions Catch clause).

### 4. Checkpoint-before-irreversible-action

This is the one that actually prevents a duplicate send, and the ordering
is the whole trick:

```python
def _run_publish(self, run_id, state):
    env_hash = compute_environment_hash(state.get("_env_sources", []))

    # Written BEFORE the send call, not after.
    self.checkpoints.write(run_id, phases.PUBLISH, "started", state, env_hash)

    try:
        self.idempotency.claim(f"{run_id}:publish")
    except AlreadyClaimedError:
        # Already sent (or a previous attempt crashed after claiming) -
        # do NOT resend either way.
        report_path = state.get("report_path")
    else:
        report_path = self.publisher.publish(run_id=run_id, subject=..., body_markdown=state["final_report"])

    ...
    self.checkpoints.write(run_id, phases.PUBLISH, "completed", state, env_hash)
```

If the process dies between the claim succeeding and the send call
returning, recovery sees "publish was about to happen," tries to claim
again, fails (already claimed), and skips the send. Worst case, a human
checks the provider's own send log to confirm delivery — the system never
blindly replays the one action that can't be undone.

### What this cost, and what it didn't

Locally: nothing extra — sqlite, no external services, runs on a laptop.
In production: one shared DynamoDB table for checkpoints and idempotency
claims (partitioned by `run_id`, differentiated by sort key), one
OpenSearch Serverless collection, both billed per-use. The full
architecture writeup, including the Lambda/Step Functions vs ECS/Fargate
decision and what's explicitly cut for v1, is in the repo's
`ARCHITECTURE.md`.

### Try it

Repo: [link] — MIT licensed, `README.md` has a five-minute local quickstart
that needs nothing but an Anthropic API key.

---

*If you're building an agent that does anything longer-lived than a single
request/response cycle, some version of these four questions is worth
answering before you need to — not after the first duplicate charge, lost
run, or confidently-wrong report on stale data.*
