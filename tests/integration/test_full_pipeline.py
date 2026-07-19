"""
What this validates: the pipeline end to end through the same code path the
CLI uses, with the Anthropic client mocked out (no network, no API key
needed to run this in CI) - and specifically, that publish is genuinely
idempotent: calling the publish phase's underlying claim logic twice for the
same run only results in one "send."
"""
from unittest.mock import MagicMock, patch

from continuum.agent import ClaudeResearchAgent
from continuum.memory.embeddings import LocalHashEmbeddings
from continuum.memory.vector_store import LocalVectorStore
from continuum.pipeline import phases
from continuum.pipeline.checkpoint_store import LocalCheckpointStore
from continuum.pipeline.idempotency import LocalIdempotencyGuard
from continuum.pipeline.orchestrator import ResearchOrchestrator
from continuum.tools.publisher import LocalPublisher


def _fake_anthropic_message(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def _mocked_agent():
    client = MagicMock()
    client.messages.create.side_effect = [
        _fake_anthropic_message('{"angle": "test angle", "subtopics": ["a", "b"]}'),
        _fake_anthropic_message("synthesized findings"),
        _fake_anthropic_message("# Draft report\n\nsynthesized findings"),
        _fake_anthropic_message("# Final report\n\nsynthesized findings (cite-checked)"),
    ]
    return ClaudeResearchAgent(client=client, model="claude-sonnet-5")


def test_full_pipeline_with_mocked_claude(tmp_workdir):
    orchestrator = ResearchOrchestrator(
        agent=_mocked_agent(),
        checkpoint_store=LocalCheckpointStore(db_path=str(tmp_workdir / "cp.sqlite3")),
        vector_store=LocalVectorStore(LocalHashEmbeddings(), db_path=str(tmp_workdir / "mem.sqlite3")),
        idempotency_guard=LocalIdempotencyGuard(db_path=str(tmp_workdir / "idem.sqlite3")),
        publisher=LocalPublisher(output_dir=str(tmp_workdir / "runs")),
    )

    result = orchestrator.run("battery recycling economics")

    assert result.final_phase == phases.PUBLISH
    report_file = tmp_workdir / "runs" / result.run_id / "report.md"
    assert report_file.exists()
    assert "Final report" in report_file.read_text()


def test_publish_is_not_repeated_on_a_second_call(tmp_workdir):
    publisher = MagicMock(wraps=LocalPublisher(output_dir=str(tmp_workdir / "runs")))
    orchestrator = ResearchOrchestrator(
        agent=_mocked_agent(),
        checkpoint_store=LocalCheckpointStore(db_path=str(tmp_workdir / "cp.sqlite3")),
        vector_store=LocalVectorStore(LocalHashEmbeddings(), db_path=str(tmp_workdir / "mem.sqlite3")),
        idempotency_guard=LocalIdempotencyGuard(db_path=str(tmp_workdir / "idem.sqlite3")),
        publisher=publisher,
    )

    state = {"topic": "t", "final_report": "report body", "_env_sources": []}
    run_id = "double-publish-run"

    orchestrator._run_publish(run_id, state)
    orchestrator._run_publish(run_id, state)  # simulates a naive retry after a crash

    assert publisher.publish.call_count == 1
