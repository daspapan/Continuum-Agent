# Deployment runbook

Actual steps to get this running on real AWS infrastructure. Assumes you've
already run the local path in `docs/LEARNING_PATH.md`.

## Prerequisites

- AWS account with credentials configured (`aws configure` or equivalent env vars)
- Node.js 20+ and the AWS CDK CLI: `npm install -g aws-cdk`
- Python 3.12
- `cdk bootstrap` has been run once per account/region (see below)
- SES sender identity verified for your `env` (SES starts in sandbox mode -
  verify both sender and recipient addresses, or request production access,
  before `publish` will actually send anything)

## First-time setup (once per AWS account/region)

```bash
cd infra
pip install -r requirements.txt
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
```

## Deploy to dev

```bash
cd infra
cdk deploy -c env=dev -c account=<ACCOUNT_ID> -c region=ap-south-1
```

This provisions: DynamoDB table, OpenSearch Serverless collection + policies,
S3 reports bucket, the phase_runner and trigger Lambdas, the Step Functions
state machine, API Gateway, an SNS ops-alerts topic, and a Secrets Manager
secret shell for the Anthropic key.

**After deploy, before first use:**

1. Populate the Anthropic key: `aws secretsmanager put-secret-value --secret-id continuum/dev/anthropic-api-key --secret-string '{"key":"sk-ant-..."}'`
   (the phase_runner Lambda reads this via `ANTHROPIC_SECRET_ARN` - wire
   that read into `agent.py`'s client construction if you haven't already
   for your target environment, or set `ANTHROPIC_API_KEY` directly as a
   Lambda env var for a quicker/less secure first pass).
2. Verify SES identities for `research-bot-dev@...` and the recipient
   address you configured (SES console -> Verified identities).
3. Create the OpenSearch Serverless vector index (the collection is created
   by CDK; the index inside it - name, `knn_vector` field, dimension - is
   created via the OpenSearch API, not CloudFormation):
   ```bash
   python3 scripts/create_memory_index.py --endpoint <OPENSEARCH_COLLECTION_ENDPOINT from CDK output>
   ```
   (see `infra/continuum_stack.py` CfnOutput for the endpoint value)

## Verify the deploy

```bash
curl -X POST <ApiEndpoint from CDK output>/research -d '{"topic":"test topic"}'
# {"run_id": "...", "status": "started"}
```

Then check the Step Functions console for the execution, or run the smoke
test directly:

```bash
export SMOKE_TEST_STATE_MACHINE_ARN=<StateMachineArn from CDK output>
export SMOKE_TEST_TABLE_NAME=<CheckpointTableName from CDK output>
pytest tests/smoke -m smoke
```

## Deploy to staging / prod

Same commands with `-c env=staging` or `-c env=prod`, or trigger the
`Deploy` GitHub Actions workflow manually (`workflow_dispatch`) and pick the
target environment. Prod requires a reviewer approval configured on the
`prod` GitHub Environment (Settings -> Environments -> prod -> required
reviewers) before the deploy job runs.

## Rollback

CDK deploys are CloudFormation changesets - `cdk deploy` on a previous
commit re-applies the previous template, which CloudFormation reconciles
against current state. For a fast rollback under pressure, `aws cloudformation
rollback-stack --stack-name ContinuumStack-<env>` reverts to the last known
good state if the most recent update is still in a rollback-capable status.

## Teardown (dev/staging only - prod resources are retained by design)

```bash
cdk destroy -c env=dev
```

Won't touch prod's DynamoDB table, S3 bucket contents, or OpenSearch
collection - `EnvConfig.removal_policy_retain=True` for prod means those
survive stack deletion on purpose. Delete them by hand if you actually mean
to.
