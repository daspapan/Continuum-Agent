"""
Lambda handler backing every Step Functions Task state in the pipeline.

One Lambda, not seven. Each phase in the state machine invokes this same
function with a different `phase` in the event payload. The alternative
(one Lambda per phase) means seven near-identical deployment packages, seven
IAM roles to keep in sync, and seven places to patch when
orchestrator._run_phase's shared logic changes. Since every phase already
funnels through that one method, a single Lambda that dispatches on `phase`
mirrors the code structure instead of fighting it. The state machine still
shows each phase as a distinct step (see infra/continuum_stack.py) - this is
a deployment-unit decision, not a loss of visibility into what ran.

Event shape (see continuum_stack.py's Task state Parameters):
    {"run_id": "...", "phase": "plan", "state": {...}}
Returns the updated state dict, which Step Functions merges back via
ResultPath for the next Task.
"""
from __future__ import annotations

import json
import os

from continuum.agent import ClaudeResearchAgent
from continuum.memory.embeddings import get_embeddings_backend
from continuum.memory.vector_store import get_vector_store
from continuum.pipeline.checkpoint_store import DynamoDBCheckpointStore
from continuum.pipeline.idempotency import DynamoDBIdempotencyGuard
from continuum.pipeline.orchestrator import ResearchOrchestrator
from continuum.tools.publisher import get_publisher


def _build_orchestrator() -> ResearchOrchestrator:
    table_name = os.environ["CHECKPOINT_TABLE_NAME"]
    embeddings = get_embeddings_backend("aws")
    vector_store = get_vector_store("aws", embeddings, endpoint=os.environ["OPENSEARCH_COLLECTION_ENDPOINT"])
    checkpoint_store = DynamoDBCheckpointStore(table_name=table_name)
    idempotency_guard = DynamoDBIdempotencyGuard(table_name=table_name)
    publisher = get_publisher(
        "aws",
        sender=os.environ["SES_SENDER_ADDRESS"],
        recipient=os.environ["SES_RECIPIENT_ADDRESS"],
    )
    agent = ClaudeResearchAgent()
    return ResearchOrchestrator(agent, checkpoint_store, vector_store, idempotency_guard, publisher)


def handler(event: dict, context) -> dict:
    run_id = event["run_id"]
    phase = event["phase"]
    state = event.get("state") or {"topic": event.get("topic", "")}

    orchestrator = _build_orchestrator()
    updated_state = orchestrator._run_phase(run_id, phase, state)

    # Step Functions JSON-serializes the return value; make sure everything
    # in state is plain JSON (it should be - phases only ever put str/dict/
    # list into state - but fail loudly here rather than opaquely inside SFN
    # if that assumption is ever violated).
    json.dumps(updated_state)
    return updated_state
