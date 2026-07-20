#!/usr/bin/env python3
"""
CDK entrypoint. Deploys one environment per invocation, selected via
context: `cdk deploy -c env=dev` (default), `-c env=staging`, `-c env=prod`.

Separate stacks per env rather than one stack with conditionals - each
environment gets its own independent set of resources (own DynamoDB table,
own OpenSearch collection, own state machine), so a mistake in dev can't
touch prod resources, and each env's stack can be deployed independently.
"""
import aws_cdk as cdk

from continuum_stack import ContinuumStack, EnvConfig

app = cdk.App()

env_name = app.node.try_get_context("env") or "dev"

ENV_CONFIGS = {
    "dev": EnvConfig(name="dev", removal_policy_retain=False, point_in_time_recovery=False),
    "staging": EnvConfig(name="staging", removal_policy_retain=False, point_in_time_recovery=True),
    "prod": EnvConfig(name="prod", removal_policy_retain=True, point_in_time_recovery=True),
}

if env_name not in ENV_CONFIGS:
    raise SystemExit(f"unknown env '{env_name}', expected one of {list(ENV_CONFIGS)}")

ContinuumStack(
    app,
    f"ContinuumStack-{env_name}",
    env_config=ENV_CONFIGS[env_name],
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "ap-south-1",
    ),
)

app.synth()
