# LinkedIn — Lessons-learned post

Three things I got wrong on the first pass building Continuum, and what
they taught me.

**1. I over-checkpointed at first.**
My first instinct was: checkpoint after every tool call, everywhere. Feels
safer — more frequent saves, smaller blast radius if something fails. I
shipped it, then reverted it a day later. The pipeline's steps are fast and
idempotent; re-running a whole phase from scratch costs almost nothing. All
that extra checkpointing bought was more writes and more recovery-state to
reason about, for a safety margin that doesn't materialize unless a step is
genuinely expensive or has an external side effect. Coarse by default,
fine-grained only where it's actually justified (one phase out of seven)
turned out to be the right call — but I had to build the wrong version
first to see why.

**2. My tests caught two real bugs the "it runs on my machine" pass missed.**
A `NameError` in the mock document reader (leftover loop variable from a
refactor) that only surfaced once tests exercised more than a single
source. And a DynamoDB query bug: checkpoints and idempotency claims share
one table, and a plain query on `run_id` was pulling back claim records and
crashing when the code tried to read them as checkpoints. Both would've
been "works in the demo, breaks on the second real run" bugs if I'd shipped
on manual testing alone. Writing the resume/interruption tests first — not
after — is what surfaced them before a user would.

**3. "Local-first" saved more time than I expected.**
I built the entire pipeline runnable on a laptop with mock search/read
tools and sqlite-backed everything, before writing a line of CDK. It meant
every checkpoint/resume/idempotency bug got found and fixed against a fast
local loop, not a `cdk deploy` cycle. By the time I wired up the real AWS
backends, the logic was already correct — infra was just infra.

None of these are novel lessons. They're the same lessons you learn on any
project that touches production concerns. Writing them down here mostly for
future-me, and in case they save someone else a day.

#AgenticAI #SoftwareEngineering #BuildInPublic
