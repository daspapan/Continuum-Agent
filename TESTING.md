# Testing

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

No AWS account, Anthropic API key, or network access is required for the
default test run. `pytest` (no args) runs everything except the `smoke`
marker.

## What's covered, and why

**`tests/unit/test_checkpoint_store.py`** — the sqlite checkpoint store
round-trips state correctly and `latest()` returns the most recent write,
not just any row. If this breaks, resume silently picks up from the wrong
phase.

**`tests/unit/test_idempotency.py`** — a second claim on the same
idempotency key raises. This is the mechanism that actually stops a
double-send; everything else (checkpoint-before-action ordering) just makes
sure recovery *checks* this before acting.

**`tests/unit/test_state_versioning.py`** — environment-hash staleness
detection catches changed source content, and does *not* false-positive on
reordering the same sources.

**`tests/unit/test_vector_store.py`** — semantic recall ranks a topically
related record above an unrelated one, using the local hash-embedding
backend (no Bedrock access needed to run this in CI). Confirms "find by
meaning" actually works, not just "doesn't crash."

**`tests/unit/test_orchestrator_resume.py`** — the core guarantee: a run
interrupted mid-pipeline and resumed by a fresh orchestrator instance
(simulating a process restart) picks up at the right phase, doesn't redo
completed work, and correctly refuses to resume when the environment hash
no longer matches.

**`tests/integration/test_full_pipeline.py`** — full pipeline, Anthropic
client mocked, no network. Also confirms calling the publish step twice
(simulating a naive retry after a crash) only sends once.

**`tests/integration/test_dynamodb_backends.py`** — the production
DynamoDB-backed checkpoint store and idempotency guard, exercised against a
moto-mocked DynamoDB. Confirms the `env=aws` code path is actually
exercised, not just written.

**Known gap:** `OpenSearchServerlessVectorStore` and `SESPublisher` aren't
covered by the automated suite. moto doesn't mock OpenSearch Serverless's
data-plane API or SES sending well enough to be worth faking. These are
validated against real (dev-account) infrastructure after deploy — see
`tests/smoke/` and `docs/DEPLOYMENT_RUNBOOK.md`. Flagging this rather than
pretending it's covered.

## Smoke tests

`tests/smoke/test_deployed_endpoint.py` starts a real Step Functions
execution against deployed infra and confirms a checkpoint lands in
DynamoDB. Skipped unless `SMOKE_TEST_STATE_MACHINE_ARN` and
`SMOKE_TEST_TABLE_NAME` are set. Run explicitly after a deploy:

```bash
SMOKE_TEST_STATE_MACHINE_ARN=... SMOKE_TEST_TABLE_NAME=... pytest tests/smoke -m smoke
```

## CI

`.github/workflows/ci.yml` runs the default suite (unit + integration, no
smoke) on every PR and on push to `main`. See `.github/workflows/deploy.yml`
for where the smoke test runs post-deploy.
