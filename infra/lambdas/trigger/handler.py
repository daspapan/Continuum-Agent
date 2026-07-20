"""
API Gateway entrypoint: POST /research {"topic": "..."} starts a new Step
Functions execution and returns the run_id immediately (fire-and-forget;
the pipeline runs async). No auth on this route in v1 - see ARCHITECTURE.md
"Cut corners" section. Put this behind Cognito or an API key before pointing
it at anything but your own testing.
"""
from __future__ import annotations

import json
import os
import uuid

import boto3

sfn = boto3.client("stepfunctions")
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]


def handler(event: dict, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    topic = body.get("topic")
    if not topic:
        return {"statusCode": 400, "body": json.dumps({"error": "missing 'topic'"})}

    run_id = str(uuid.uuid4())
    sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=run_id,
        input=json.dumps({"run_id": run_id, "phase": "plan", "topic": topic}),
    )
    return {"statusCode": 202, "body": json.dumps({"run_id": run_id, "status": "started"})}
