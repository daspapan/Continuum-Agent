"""
Local CLI entrypoint.

    python -m continuum.cli research "topic here"
    python -m continuum.cli resume <run_id>

Wires up the local (sqlite + mock tools) backends by default. This is the
"learn it on your laptop before you touch AWS" path - see docs/LEARNING_PATH.md.
"""
from __future__ import annotations

import argparse
import logging
import sys

from continuum.agent import ClaudeResearchAgent
from continuum.config import get_settings
from continuum.memory.embeddings import get_embeddings_backend
from continuum.memory.vector_store import get_vector_store
from continuum.pipeline.checkpoint_store import get_checkpoint_store
from continuum.pipeline.idempotency import get_idempotency_guard
from continuum.pipeline.orchestrator import ResearchOrchestrator
from continuum.tools.publisher import get_publisher


def build_orchestrator(env: str) -> ResearchOrchestrator:
    settings = get_settings()
    embeddings = get_embeddings_backend(env)
    vector_store = get_vector_store(env, embeddings, endpoint=settings.opensearch_endpoint)
    checkpoint_store = get_checkpoint_store(env, table_name=settings.checkpoint_table_name)
    idempotency_guard = get_idempotency_guard(env, table_name=settings.checkpoint_table_name)
    publisher = get_publisher(env, sender=settings.ses_sender, recipient=settings.ses_recipient)
    agent = ClaudeResearchAgent()
    return ResearchOrchestrator(agent, checkpoint_store, vector_store, idempotency_guard, publisher)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="continuum")
    sub = parser.add_subparsers(dest="command", required=True)

    research_p = sub.add_parser("research", help="start a new research run")
    research_p.add_argument("topic")

    resume_p = sub.add_parser("resume", help="resume an interrupted run")
    resume_p.add_argument("run_id")

    args = parser.parse_args(argv)
    settings = get_settings()
    orchestrator = build_orchestrator(settings.env)

    if args.command == "research":
        result = orchestrator.run(args.topic)
    else:
        result = orchestrator.run(topic="", run_id=args.run_id)

    print(f"run_id={result.run_id} final_phase={result.final_phase} report={result.report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
