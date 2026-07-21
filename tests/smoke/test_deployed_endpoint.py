"""
Post-deploy smoke test - NOT part of the default `pytest` run (see
TESTING.md). Exercises the actually-deployed AWS stack: starts a real Step
Functions execution and confirms it reaches a phase checkpoint in DynamoDB.

Requires:
  - infra already deployed to the target env (`cdk deploy`, see
    docs/DEPLOYMENT_RUNBOOK.md)
  - AWS credentials for that account in the environment
  - SMOKE_TEST_STATE_MACHINE_ARN and SMOKE_TEST_TABLE_NAME set

Run explicitly with:
    pytest tests/smoke -m smoke
"""
import os
import time

import boto3
import pytest

pytestmark = pytest.mark.smoke

STATE_MACHINE_ARN = os.environ.get("SMOKE_TEST_STATE_MACHINE_ARN")
TABLE_NAME = os.environ.get("SMOKE_TEST_TABLE_NAME")

requires_deployed_stack = pytest.mark.skipif(
    not STATE_MACHINE_ARN or not TABLE_NAME,
    reason="SMOKE_TEST_STATE_MACHINE_ARN / SMOKE_TEST_TABLE_NAME not set - "
    "skip unless running against a deployed stack",
)


@requires_deployed_stack
def test_pipeline_execution_reaches_first_checkpoint():
    sfn = boto3.client("stepfunctions")
    dynamodb = boto3.resource("dynamodb").Table(TABLE_NAME)

    run_id = f"smoke-{int(time.time())}"
    sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        input=f'{{"run_id": "{run_id}", "topic": "smoke test topic"}}',
    )

    # Poll for up to 60s for a checkpoint to show up - the PLAN phase alone
    # (an LLM call) usually completes well inside that window.
    deadline = time.time() + 60
    found = False
    while time.time() < deadline:
        resp = dynamodb.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("run_id").eq(run_id)
        )
        if resp.get("Items"):
            found = True
            break
        time.sleep(3)

    assert found, f"no checkpoint written for run_id={run_id} within 60s"
