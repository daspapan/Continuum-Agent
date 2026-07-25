#!/usr/bin/env python3
"""
Standalone synth check for CI (.github/workflows/ci.yml).

A plain `python3 -c "<multiline>"` embedded directly in a YAML `run:` step
doesn't survive YAML's scalar folding (newlines get collapsed to spaces,
which breaks indentation-sensitive Python) unless it's written as a `|`
block AND still avoids quoting headaches - simplest fix is just: don't
inline it, put it in a file. This synths the dev stack against a throwaway
account/region purely to catch construct-level errors before a real deploy.
"""
import aws_cdk as cdk

from continuum_stack import ContinuumStack, EnvConfig

app = cdk.App()
ContinuumStack(
    app,
    "ContinuumStack-dev",
    env_config=EnvConfig(name="dev", removal_policy_retain=False, point_in_time_recovery=False),
    env=cdk.Environment(account="123456789012", region="ap-south-1"),
)
app.synth()
print("synth ok")
