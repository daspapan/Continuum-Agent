# Continuum

A Claude-powered research agent that survives being interrupted. It runs a
multi-phase deep-research pipeline (plan, gather sources, read, synthesize,
draft, cite-check, publish) and can be killed at any point - laptop closes,
a Lambda times out, whatever - then resumed without redoing finished work or
double-sending the final report.

Built as an end-to-end learning project and portfolio piece: same
checkpoint/recovery, semantic-memory, and idempotency patterns you'd need
for a production long-running agent, applied to a scope you can actually
run and understand in an afternoon. See `docs/LEARNING_PATH.md` if that's
what you're here for.

## Why this exists

Long-running agents lose track of "what already happened" across a
restart in a few specific, recurring ways: they can't recall relevant prior
work without an exact ID, they either checkpoint too often (slow, complex
recovery) or not at all, they resume into a world that changed underneath
them without noticing, and worst case, they repeat an action that can't be
undone. Continuum is a small, complete example of handling all four in one
pipeline. `docs/ARCHITECTURE.md` has the full reasoning.

## Quickstart (no AWS required)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # set ANTHROPIC_API_KEY

python -m continuum.cli research "impact of grid-scale battery storage on renewable adoption"
```

Interrupt it (Ctrl+C) partway through, then:

```bash
python -m continuum.cli resume <run_id>
```

It picks up from the next phase after the last checkpoint, not from
scratch. See `docs/LEARNING_PATH.md` for a guided walkthrough.

## Architecture, at a glance

```
API Gateway -> Trigger Lambda -> Step Functions
                                    |
   plan -> gather -> read -> synthesize -> draft -> cite_check -> publish
   (each phase checkpoints to DynamoDB; publish is idempotency-guarded)
                                    |
              DynamoDB (checkpoints)   OpenSearch Serverless (semantic memory)
              S3 (report archive)      SES (report delivery)
```

Full rationale (compute choice, storage choice, IAM, cost, what's cut for
v1) in `docs/ARCHITECTURE.md`.

## Repo layout

```
src/continuum/
  memory/          semantic recall - vector store + embeddings (local + AWS backends)
  pipeline/        phases, orchestrator, checkpoint store, idempotency, staleness detection
  tools/           mock search, doc reader, publisher (local file + SES)
  agent.py         Claude-backed plan/synthesize/draft/cite-check
  cli.py           local run entrypoint
infra/             AWS CDK app (Step Functions, DynamoDB, OpenSearch Serverless, S3, SES, API Gateway)
tests/             unit, integration (mocked Claude + moto-mocked AWS), smoke (real deployed stack)
docs/              architecture rationale, learning path, deployment runbook
content/           launch content drafts (LinkedIn, YouTube, dev.to)
```

## Testing

```bash
pytest
```

No AWS or Anthropic credentials required for the default run. See
`TESTING.md` for what's covered and the one known coverage gap.

## Deploying

```bash
cd infra && pip install -r requirements.txt
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>   # once per account/region
cdk deploy -c env=dev -c account=<ACCOUNT_ID>
```

Full runbook, including SES verification and post-deploy setup, in
`docs/DEPLOYMENT_RUNBOOK.md`.

## Status / changelog

- **2026-07-25** - v1.0: full pipeline, local + AWS backends, CDK infra,
  CI/CD with dev auto-deploy and gated staging/prod, test suite (24 tests),
  docs, launch content.
- **2026-07-05** - project started.

## License

MIT - see `LICENSE`.
