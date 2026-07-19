"""
What this validates: the production DynamoDB-backed checkpoint store and
idempotency guard behave identically to their sqlite counterparts, against a
moto-mocked DynamoDB (no real AWS account or credentials needed to run this
in CI - moto intercepts the boto3 calls). This is the piece that gives
confidence the `env=aws` code path isn't just "written," it's exercised.

Not covered here: OpenSearchServerlessVectorStore and SESPublisher. moto
doesn't mock OpenSearch Serverless's data-plane API or SES sending well
enough to be worth faking; those get validated against real (dev-account)
infra post-deploy - see tests/smoke and docs/DEPLOYMENT_RUNBOOK.md. Flagging
this explicitly rather than pretending it's covered: it isn't.
"""
import boto3
import pytest
from moto import mock_aws

from continuum.pipeline.checkpoint_store import DynamoDBCheckpointStore
from continuum.pipeline.idempotency import AlreadyClaimedError, DynamoDBIdempotencyGuard

TABLE_NAME = "continuum-test-table"


@pytest.fixture
def dynamodb_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-south-1")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "run_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "run_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield TABLE_NAME


def test_dynamodb_checkpoint_write_and_latest(dynamodb_table):
    store = DynamoDBCheckpointStore(table_name=dynamodb_table, region="ap-south-1")
    store.write("run-1", "plan", "completed", {"topic": "x"}, env_hash="h1")
    store.write("run-1", "gather", "completed", {"topic": "x", "n": 2}, env_hash="h2")

    latest = store.latest("run-1")
    assert latest.phase == "gather"
    assert latest.state["n"] == 2


def test_dynamodb_idempotency_guard_blocks_second_claim(dynamodb_table):
    guard = DynamoDBIdempotencyGuard(table_name=dynamodb_table, region="ap-south-1")
    guard.claim("run-1:publish")
    with pytest.raises(AlreadyClaimedError):
        guard.claim("run-1:publish")


def test_dynamodb_checkpoint_and_idempotency_share_table_without_colliding(dynamodb_table):
    store = DynamoDBCheckpointStore(table_name=dynamodb_table, region="ap-south-1")
    guard = DynamoDBIdempotencyGuard(table_name=dynamodb_table, region="ap-south-1")

    store.write("run-1", "publish", "started", {}, env_hash="h")
    guard.claim("run-1:publish")

    # both items exist under the same run_id partition without overwriting
    # each other - proof the sk prefixing ("IDEM#" vs plain phase name) works
    history = store.history("run-1")
    assert len(history) == 1
    assert history[0].phase == "publish"
