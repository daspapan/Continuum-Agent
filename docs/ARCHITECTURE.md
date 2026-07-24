# Architecture

Continuum is a research agent you can interrupt at any point (laptop closes,
Lambda times out, the process just dies) and resume without redoing finished
work or double-sending the final report. This document is the "why" behind
every non-obvious choice below. For "what the code does," read the modules
directly - they're commented at the decision points, not line by line.

## System overview

```
POST /research {topic}
        |
        v
  API Gateway (HTTP API) --auth: none in v1, see "Cut corners"--
        |
        v
   Trigger Lambda --starts--> Step Functions state machine
                                    |
              +---------------------+---------------------+
              |    plan -> gather -> read -> synthesize -> draft -> cite_check -> publish
              |    each state = one Task invoking the SAME phase_runner Lambda
              |    with a different `phase` parameter
              v
   phase_runner Lambda (one function, dispatches on event.phase)
        |                    |                      |
        v                    v                      v
  DynamoDB               OpenSearch            SES (publish only)
  (checkpoints +         Serverless            + S3 (report archive)
   idempotency claims)   (semantic memory)
```

Local dev mode swaps every AWS-backed piece for a same-interface local one
(sqlite, mock search/read tools, a file-based "publisher") so the whole
pipeline runs on a laptop with just an Anthropic API key. See
`docs/LEARNING_PATH.md` for that path; this document covers the AWS side.

## Compute: Step Functions + Lambda, not ECS/Fargate or EC2

The pipeline is a short-lived (minutes, not hours), bursty (triggered
per-request, not constantly running), multi-phase job that needs exactly two
things a compute layer doesn't usually give you for free: a durable record
of "which phase did we get to" and the ability to pause between phases
without paying for idle compute.

Step Functions gives phase-boundary checkpointing almost as a side effect of
its own execution model - each state transition is already a durable,
inspectable record. Lambda gives pay-per-invocation billing that matches the
bursty load pattern (a request every few minutes, not a steady stream) and
zero idle cost between runs.

ECS/Fargate would be the right call if phases needed to share warm state
in-memory across a long-running process, or if a single phase routinely ran
past Lambda's 15-minute cap. Neither is true here - LLM calls dominate phase
latency (seconds), not the surrounding logic, and phases don't share
in-memory state (that's the whole point of the checkpoint store: state lives
in DynamoDB, not in a process). EC2 would only make sense if this needed to
run outside AWS's managed compute entirely (it doesn't) or needed
always-on background processing (it doesn't - it's request-triggered).

**Trade-off accepted:** cold starts. The phase_runner Lambda's first
invocation in a while pays a cold-start penalty (dependency imports: boto3,
anthropic, numpy). At one invocation per phase per run, and runs happening
minutes apart at most, this adds low-single-digit seconds to a pipeline
whose LLM calls already take longer than that. Not worth provisioned
concurrency for v1's traffic.

## One Lambda, not seven

Every phase funnels through the same `orchestrator._run_phase` dispatch
logic (see `src/continuum/pipeline/orchestrator.py`). Packaging that as
seven near-identical Lambda functions - one per phase - means seven
deployment artifacts, seven IAM roles to keep in sync when a permission
changes, and seven places to patch a shared bug. A single Lambda that reads
`event["phase"]` and dispatches mirrors the code's actual structure. The
state machine still shows each phase as its own step in the execution
history and console - this is a deployment-unit decision, not a loss of
per-phase visibility.

## Storage

**DynamoDB for checkpoints + idempotency claims, one table.** Partition key
`run_id`, sort key `sk`. Checkpoint items use
`sk = "{written_at_iso}#{phase}"`; idempotency claims use `sk = "IDEM#{action}"`.
Same table because both are keyed by `run_id` and both need the same
read/write access pattern from the same Lambda role - splitting them into
two tables would double the IAM surface for no isolation benefit, since
nothing else reads either table. `latest()`/`history()` filter to items with
a `phase` attribute so a claim item is never mistaken for a checkpoint (this
was a real bug caught by `tests/integration/test_dynamodb_backends.py` - see
git history).

**OpenSearch Serverless for semantic memory.** The recall problem ("what did
we find about X before") is fundamentally similarity search, not exact-key
lookup - see `src/continuum/memory/vector_store.py` docstring. OpenSearch
Serverless was picked over standing up a self-managed OpenSearch cluster or
using pgvector on RDS because there's no cluster to size or patch, and the
access pattern (occasional writes on publish, occasional reads on plan) is
exactly what "serverless" billing is for - a fixed-capacity cluster would
mostly sit idle.

**S3 for finished report archive**, lifecycle-transitioned to Glacier after
90 days. This is cold storage in the "rarely touched but must survive"
sense - see the memory module's hot/cold split. It's not the retrieval path
(that's the vector store); it's the durable copy for compliance/audit
retrieval, which doesn't need sub-second access.

## IAM

One role (`PhaseRunnerRole`) for the phase_runner Lambda, scoped to: R/W on
the checkpoint table, R/W on the reports bucket, `bedrock:InvokeModel` on
the Titan embeddings model ARN specifically (not `*`), `aoss:APIAccessAll`
scoped to the memory collection ARN, and `ses:SendEmail` conditioned on the
`FromAddress` matching this environment's sender identity. No admin
policies, no `Resource: "*"` outside the two places (SES, Bedrock model
selection) where the service doesn't support tighter ARN scoping.

OpenSearch Serverless additionally requires its own data-access policy
(`MemoryDataAccessPolicy`) naming the Lambda role's ARN as principal - IAM
alone doesn't authorize collection access on Serverless, both layers have to
agree.

## Environment separation

Three independent stacks (`ContinuumStack-dev`, `-staging`, `-prod`), not
one stack with conditionals. Each environment gets its own DynamoDB table,
OpenSearch collection, and state machine - a mistake in dev can't touch
prod's resources because they're not the same resources. `EnvConfig`
controls the two things that should actually differ by environment:
`removal_policy_retain` (dev resources can be destroyed freely; prod data
is retained even if the stack is deleted) and `point_in_time_recovery`
(off in dev to avoid the extra cost on throwaway data, on everywhere state
matters).

Deploys to `dev` happen automatically on merge to `main`
(`.github/workflows/deploy.yml`). Staging and prod are manual
`workflow_dispatch` runs, and prod is additionally gated by a GitHub
Environment protection rule requiring a reviewer approval - configured in
repo settings, not in the workflow file itself.

## Cost

Every AWS-backed piece here is pay-per-use: Lambda (per invocation +
duration), DynamoDB on-demand (per request), OpenSearch Serverless (per OCU-hour,
scales to near-zero on light traffic), S3 (per GB + Glacier for cold
archive), Step Functions (per state transition). At the traffic this is
designed for (occasional research requests, not a constant stream), the
whole stack should run in AWS free-tier-adjacent territory per environment.
The one line item worth watching if usage grows is OpenSearch Serverless's
minimum OCU floor - it doesn't scale to literally zero the way Lambda/DynamoDB
do. Not a concern at v1 scale; worth a look before assuming this stays cheap
at 100x the traffic.

## Cut corners

Stated explicitly rather than silently shipped as if it were a complete
answer:

- **No auth on the `/research` API endpoint.** Fine for personal use/demo;
  put it behind Cognito or at minimum an API key before exposing it beyond
  your own testing.
- **No multi-tenant isolation.** Checkpoints, memory, and reports aren't
  partitioned by user - this is a single-user design (see
  `notes/project-brief.md` non-goals).
- **`OpenSearchServerlessVectorStore` and `SESPublisher` aren't covered by
  automated tests** - moto doesn't mock either well enough to be worth
  faking. They're validated post-deploy via `tests/smoke/`. See
  `TESTING.md`'s "known gap" note.
- **No dead-letter queue on the state machine.** A run that exhausts its
  Lambda retries currently just fails the execution; nothing captures it
  for later inspection beyond CloudWatch Logs. Worth adding before this
  handles anything you can't afford to silently lose.
