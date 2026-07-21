"""
Continuum's AWS stack.

See docs/ARCHITECTURE.md for the full rationale behind each choice below;
this file is the implementation, that doc is the "why."
"""
from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_opensearchserverless as aoss,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as sfn_tasks,
)
from constructs import Construct

PHASES = ["plan", "gather", "read", "synthesize", "draft", "cite_check", "publish"]


@dataclass
class EnvConfig:
    name: str
    removal_policy_retain: bool
    point_in_time_recovery: bool


class ContinuumStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_config: EnvConfig, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        self.env_config = env_config
        removal_policy = RemovalPolicy.RETAIN if env_config.removal_policy_retain else RemovalPolicy.DESTROY
        suffix = env_config.name

        # --- Secrets -----------------------------------------------------
        anthropic_secret = secretsmanager.Secret(
            self,
            "AnthropicApiKey",
            secret_name=f"continuum/{suffix}/anthropic-api-key",
            description="Anthropic API key for the Claude research agent. Populate manually after deploy - "
            "CDK creates the secret shell, it does not (and should not) contain a real key in source.",
        )

        # --- Checkpoints + idempotency (shared table, see checkpoint_store.py) ---
        checkpoint_table = dynamodb.Table(
            self,
            "CheckpointTable",
            table_name=f"continuum-checkpoints-{suffix}",
            partition_key=dynamodb.Attribute(name="run_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=env_config.point_in_time_recovery,
            removal_policy=removal_policy,
        )

        # --- Cold storage for finished reports (compliance retention) ----
        reports_bucket = s3.Bucket(
            self,
            "ReportsBucket",
            bucket_name=f"continuum-reports-{suffix}-{self.account}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=removal_policy,
            auto_delete_objects=not env_config.removal_policy_retain,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="archive-after-90-days",
                    transitions=[
                        s3.Transition(storage_class=s3.StorageClass.GLACIER, transition_after=Duration.days(90))
                    ],
                )
            ],
        )

        # --- Semantic memory: OpenSearch Serverless (vector search) ------
        # L1 constructs only (no L2 for Serverless collections yet). Three
        # policies are required before the collection is usable:
        # encryption, network, and data-access - OpenSearch Serverless
        # authorizes via its own data-access policy layered on top of IAM,
        # not IAM alone.
        collection_name = f"continuum-memory-{suffix}"

        encryption_policy = aoss.CfnSecurityPolicy(
            self,
            "MemoryEncryptionPolicy",
            name=f"{collection_name}-enc",
            type="encryption",
            policy=cdk.Fn.sub(
                '{"Rules":[{"ResourceType":"collection","Resource":["collection/%s"]}],"AWSOwnedKey":true}',
                {"collectionName": collection_name},
            ).replace("%s", collection_name),
        )

        network_policy = aoss.CfnSecurityPolicy(
            self,
            "MemoryNetworkPolicy",
            name=f"{collection_name}-net",
            type="network",
            policy=f'[{{"Rules":[{{"ResourceType":"collection","Resource":["collection/{collection_name}"]}}],"AllowFromPublic":false,"SourceVPCEs":[]}}]',
        )

        memory_collection = aoss.CfnCollection(
            self,
            "MemoryCollection",
            name=collection_name,
            type="VECTORSEARCH",
            description="Semantic recall over past research reports",
        )
        memory_collection.add_dependency(encryption_policy)
        memory_collection.add_dependency(network_policy)

        # --- Ops alerting --------------------------------------------------
        ops_alerts_topic = sns.Topic(
            self, "OpsAlertsTopic", topic_name=f"continuum-ops-alerts-{suffix}",
            display_name="Continuum ops alerts (staleness conflicts, publish failures)",
        )

        # --- Lambda execution role (least privilege) ----------------------
        phase_runner_role = iam.Role(
            self,
            "PhaseRunnerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for the phase_runner Lambda - scoped to exactly what a phase needs.",
        )
        phase_runner_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        checkpoint_table.grant_read_write_data(phase_runner_role)
        reports_bucket.grant_read_write(phase_runner_role)
        anthropic_secret.grant_read(phase_runner_role)
        phase_runner_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=["arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0"],
            )
        )
        phase_runner_role.add_to_policy(
            iam.PolicyStatement(
                actions=["aoss:APIAccessAll"],
                resources=[memory_collection.attr_arn],
            )
        )
        phase_runner_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=["*"],  # SES sender-identity ARN scoping done via SES config, not IAM resource
                conditions={"StringEquals": {"ses:FromAddress": f"research-bot-{suffix}@example.com"}},
            )
        )

        # Data-access policy: OpenSearch Serverless's own authorization
        # layer, separate from the IAM policy above. Both are required.
        aoss.CfnAccessPolicy(
            self,
            "MemoryDataAccessPolicy",
            name=f"{collection_name}-access",
            type="data",
            policy=(
                f'[{{"Rules":[{{"ResourceType":"collection","Resource":["collection/{collection_name}"],'
                f'"Permission":["aoss:*"]}},{{"ResourceType":"index","Resource":["index/{collection_name}/*"],'
                f'"Permission":["aoss:*"]}}],"Principal":["{phase_runner_role.role_arn}"]}}]'
            ),
        )

        # --- phase_runner Lambda ------------------------------------------
        phase_runner_fn = lambda_.Function(
            self,
            "PhaseRunnerFunction",
            function_name=f"continuum-phase-runner-{suffix}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/phase_runner"),
            role=phase_runner_role,
            timeout=Duration.minutes(5),
            memory_size=512,
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "CHECKPOINT_TABLE_NAME": checkpoint_table.table_name,
                "OPENSEARCH_COLLECTION_ENDPOINT": memory_collection.attr_collection_endpoint,
                "REPORTS_BUCKET_NAME": reports_bucket.bucket_name,
                "SES_SENDER_ADDRESS": f"research-bot-{suffix}@example.com",
                "SES_RECIPIENT_ADDRESS": f"you-{suffix}@example.com",
                "ANTHROPIC_SECRET_ARN": anthropic_secret.secret_arn,
            },
        )

        # --- Step Functions state machine: one Task per phase -------------
        # Coarse, phase-boundary granularity by default (see
        # pipeline/checkpoint_store.py docstring) - each Task IS a
        # checkpoint boundary. Retries handle transient Lambda failures;
        # staleness conflicts are NOT retried, they're routed to ops review.
        def phase_task(phase: str) -> sfn.Chain:
            task = sfn_tasks.LambdaInvoke(
                self,
                f"Phase_{phase}",
                lambda_function=phase_runner_fn,
                payload=sfn.TaskInput.from_object(
                    {
                        "run_id.$": "$.run_id",
                        "phase": phase,
                        "state.$": "$.state",
                        "topic.$": "$.topic",
                    }
                ),
                result_path="$.state",
                retry_on_service_exceptions=True,
            )
            task.add_retry(
                errors=["Lambda.ServiceException", "Lambda.TooManyRequestsException"],
                interval=Duration.seconds(2),
                max_attempts=3,
                backoff_rate=2.0,
            )
            return task

        flag_for_review = sfn_tasks.SnsPublish(
            self,
            "FlagStalenessForReview",
            topic=ops_alerts_topic,
            message=sfn.TaskInput.from_text(
                "Continuum run flagged: environment changed while paused (staleness). "
                "See execution input for run_id/phase. Needs human review before resuming."
            ),
        ).next(sfn.Fail(self, "StopOnStaleness", cause="staleness detected on resume"))

        chain: sfn.IChainable = phase_task(PHASES[0])
        for phase in PHASES[1:]:
            chain = chain.next(phase_task(phase))

        for phase in PHASES:
            # StalenessError surfaces from the Lambda as a handled error
            # type (see phase_runner/handler.py -> orchestrator ->
            # state_versioning.StalenessError); route it to human review
            # instead of the default retry/fail behavior.
            self.node.find_child(f"Phase_{phase}").add_catch(
                flag_for_review, errors=["StalenessError"], result_path="$.error"
            )

        state_machine = sfn.StateMachine(
            self,
            "ResearchPipeline",
            state_machine_name=f"continuum-research-pipeline-{suffix}",
            definition_body=sfn.DefinitionBody.from_chainable(chain),
            timeout=Duration.hours(1),
            logs=sfn.LogOptions(
                destination=logs.LogGroup(self, "StateMachineLogs", retention=logs.RetentionDays.ONE_MONTH),
                level=sfn.LogLevel.ALL,
            ),
        )

        # --- API Gateway trigger -------------------------------------------
        # No auth in v1 - see docs/ARCHITECTURE.md "Cut corners." Put this
        # behind Cognito or an API key before it's anything but your own
        # testing endpoint.
        trigger_fn = lambda_.Function(
            self,
            "TriggerFunction",
            function_name=f"continuum-trigger-{suffix}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/trigger"),
            timeout=Duration.seconds(10),
            environment={"STATE_MACHINE_ARN": state_machine.state_machine_arn},
        )
        state_machine.grant_start_execution(trigger_fn)

        http_api = apigwv2.HttpApi(
            self,
            "ContinuumApi",
            api_name=f"continuum-api-{suffix}",
            create_default_stage=True,
        )
        http_api.add_routes(
            path="/research",
            methods=[apigwv2.HttpMethod.POST],
            integration=apigwv2_integrations.HttpLambdaIntegration("TriggerIntegration", trigger_fn),
        )

        cdk.CfnOutput(self, "ApiEndpoint", value=http_api.api_endpoint)
        cdk.CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
        cdk.CfnOutput(self, "CheckpointTableName", value=checkpoint_table.table_name)
        cdk.CfnOutput(self, "OpsAlertsTopicArn", value=ops_alerts_topic.topic_arn)
