# Resume updates — add Continuum project

Suggested edits to `Papan Das - Profile - v8.pdf`, written to match its existing tone/format. Drop these in as shown; nothing else needs to move.

## 1. KEY PROJECTS — new entry (#10)

Add after item 9 (CrossLedger Orchestration):

> **10. Continuum — Checkpoint-Safe Memory Architecture for a Long-Running Claude Agent**
> Production-pattern research agent (Claude Sonnet + AWS Step Functions/Lambda) built to survive interruption without losing progress or repeating irreversible actions. Phase-boundary checkpointing to DynamoDB, environment-hash staleness detection on resume, and checkpoint-before-action idempotency guarding around the pipeline's one external side effect (report delivery via SES). Semantic recall over prior research via OpenSearch Serverless vector search. Full CDK infra with dev/staging/prod separation, CI/CD with gated prod approval, 24-test suite (unit + moto-mocked AWS integration). Zero duplicate sends across interruption/resume testing.

## 2. PROFESSIONAL EXPERIENCE — Self-Employed bullet list

Add one line, matching the existing bullets under *Self-Employed – Full-Time Freelancer*:

> ● Designed and open-sourced Continuum, a reference architecture for interruption-safe Claude agents: phase-boundary checkpointing, staleness detection, and idempotency-guarded irreversible actions on AWS Step Functions/Lambda/DynamoDB.

## 3. ACCOMPLISHMENTS — new bullet

Matches the granular, technical-feat style of the existing list:

> ● Designed checkpoint-before-irreversible-action ordering with DynamoDB conditional-write idempotency guards, preventing duplicate execution of side-effecting steps (payments, sends) after a process interruption — validated via automated interruption/resume test suite.

## 4. TECHNICAL SKILLS table — two small additions

**AI → Claude row** — append: `checkpoint & recovery design, semantic memory architecture, state versioning`
(existing row already covers Bedrock/multi-agent orchestration/MCP; this adds the reliability-engineering angle Continuum demonstrates)

**AWS Ecosystem → Cloud & Infra (AWS) row** — append: `Step Functions, SNS`
(Step Functions isn't currently listed anywhere despite being a natural fit next to Lambda/ECS/EKS)

## Why these four and not more

Kept this additive rather than rewriting existing bullets — the CrossLedger and multi-agent entries already establish the blockchain-bridge and Bedrock multi-agent range; Continuum adds a distinct, resume-worthy capability (production reliability patterns for long-running agents) that nothing else on the resume currently claims explicitly.
