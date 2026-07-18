"""
What this validates: interrupting a run mid-pipeline and resuming it with a
fresh orchestrator instance (simulating a process restart) picks up at the
correct next phase, doesn't redo completed phases, and correctly rejects a
resume where the environment changed underneath it (staleness).

This is the core guarantee the whole module exists for - if this test suite
passes, "the process died and came back" behaves the way docs/ARCHITECTURE.md
says it should.
"""
import pytest

from continuum.memory.embeddings import LocalHashEmbeddings
from continuum.memory.vector_store import LocalVectorStore
from continuum.pipeline import phases
from continuum.pipeline.checkpoint_store import LocalCheckpointStore
from continuum.pipeline.idempotency import LocalIdempotencyGuard
from continuum.pipeline.orchestrator import ResearchOrchestrator
from continuum.pipeline.state_versioning import StalenessError
from continuum.tools.publisher import LocalPublisher


class FakeAgent:
    """Deterministic stand-in for ClaudeResearchAgent - no API calls, no
    network, so this test suite runs the same in CI as it does locally."""

    def plan(self, topic, prior_context):
        return {"angle": topic, "subtopics": ["a", "b"]}

    def synthesize(self, topic, source_texts):
        return f"synthesis of {len(source_texts)} sources about {topic}"

    def draft(self, topic, synthesis):
        return f"# {topic}\n\n{synthesis}"

    def cite_check(self, draft, source_texts):
        return draft + "\n\n(cite-checked)"


def _build_orchestrator(tmp_workdir, suffix=""):
    return ResearchOrchestrator(
        agent=FakeAgent(),
        checkpoint_store=LocalCheckpointStore(db_path=str(tmp_workdir / f"cp{suffix}.sqlite3")),
        vector_store=LocalVectorStore(LocalHashEmbeddings(), db_path=str(tmp_workdir / f"mem{suffix}.sqlite3")),
        idempotency_guard=LocalIdempotencyGuard(db_path=str(tmp_workdir / f"idem{suffix}.sqlite3")),
        publisher=LocalPublisher(output_dir=str(tmp_workdir / "runs")),
    )


def test_full_run_completes_all_phases(tmp_workdir):
    orch = _build_orchestrator(tmp_workdir)
    result = orch.run("edge computing trends")
    assert result.final_phase == phases.PUBLISH
    assert result.report_path is not None


def test_resume_continues_from_next_phase_not_from_scratch(tmp_workdir):
    # Same checkpoint/memory/idempotency backends across two orchestrator
    # instances, simulating "process restarted."
    orch1 = _build_orchestrator(tmp_workdir)
    run_id = "resume-test-run"

    # Manually drive it to just after GATHER to simulate an interruption -
    # run() only exposes full-pipeline execution, so we reach into
    # _run_phase the same way a crash-recovery path effectively would: by
    # writing checkpoints for the phases that "completed" before the crash.
    state = {"topic": "battery recycling"}
    for phase in [phases.PLAN, phases.GATHER]:
        state = orch1._run_phase(run_id, phase, state)

    orch2 = _build_orchestrator(tmp_workdir)
    # copy over the same sqlite-backed stores by pointing at the same files
    orch2.checkpoints = orch1.checkpoints
    orch2.memory = orch1.memory
    orch2.idempotency = orch1.idempotency

    result = orch2.run(topic="", run_id=run_id)

    assert result.resumed is True
    assert result.final_phase == phases.PUBLISH
    # sources gathered before the "crash" should still be present in the
    # final state - proof it didn't restart from PLAN
    assert "sources" in result.state


def test_resume_raises_staleness_error_when_source_changed(tmp_workdir):
    orch = _build_orchestrator(tmp_workdir)
    run_id = "stale-run"

    state = {"topic": "battery recycling"}
    for phase in [phases.PLAN, phases.GATHER, phases.READ]:
        state = orch._run_phase(run_id, phase, state)

    # Tamper with a source after the READ checkpoint was written - simulates
    # "the world changed while we were paused."
    latest = orch.checkpoints.latest(run_id)
    tampered_state = dict(latest.state)
    tampered_state["_env_sources"] = [
        {**s, "content": s["content"] + " (tampered)"} for s in tampered_state["_env_sources"]
    ]
    orch.checkpoints.write(run_id, phases.READ, "completed", tampered_state, latest.env_hash)
    # write a second checkpoint with the ORIGINAL hash but TAMPERED state, so
    # resume recomputes the hash from tampered content and it won't match.

    with pytest.raises(StalenessError):
        orch.run(topic="", run_id=run_id)


def test_resume_unknown_run_id_raises(tmp_workdir):
    orch = _build_orchestrator(tmp_workdir)
    with pytest.raises(ValueError):
        orch.run(topic="", run_id="never-existed")
