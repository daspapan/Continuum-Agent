"""
Runs the research pipeline phase by phase, checkpointing at phase
boundaries, verifying environment freshness on resume, and guarding the one
irreversible step (publish) with checkpoint-before-action ordering plus an
idempotency claim.

This is the piece that ties memory/, tools/, and the checkpoint/recovery
primitives together. See docs/ARCHITECTURE.md for the full design rationale;
the short version is in each phase's checkpoint call below.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from continuum.memory.vector_store import VectorStore
from continuum.pipeline import phases
from continuum.pipeline.checkpoint_store import CheckpointStore
from continuum.pipeline.idempotency import AlreadyClaimedError, IdempotencyGuard
from continuum.pipeline.state_versioning import StalenessError, compute_environment_hash
from continuum.tools import document_reader, web_search
from continuum.tools.publisher import Publisher

logger = logging.getLogger("continuum.orchestrator")


class ResearchAgent(Protocol):
    """What the orchestrator needs from the LLM-backed agent. Kept as a
    narrow protocol so tests can pass a fake without touching the Anthropic
    client at all."""

    def plan(self, topic: str, prior_context: list[str]) -> dict: ...
    def synthesize(self, topic: str, source_texts: list[str]) -> str: ...
    def draft(self, topic: str, synthesis: str) -> str: ...
    def cite_check(self, draft: str, source_texts: list[str]) -> str: ...


@dataclass
class RunResult:
    run_id: str
    final_phase: str
    report_path: str | None = None
    resumed: bool = False
    state: dict = field(default_factory=dict)


class ResearchOrchestrator:
    def __init__(
        self,
        agent: ResearchAgent,
        checkpoint_store: CheckpointStore,
        vector_store: VectorStore,
        idempotency_guard: IdempotencyGuard,
        publisher: Publisher,
    ):
        self.agent = agent
        self.checkpoints = checkpoint_store
        self.memory = vector_store
        self.idempotency = idempotency_guard
        self.publisher = publisher

    def run(self, topic: str, run_id: str | None = None) -> RunResult:
        resumed = run_id is not None
        run_id = run_id or str(uuid.uuid4())

        state: dict = {"topic": topic}
        start_phase = phases.PHASE_ORDER[0]

        if resumed:
            latest = self.checkpoints.latest(run_id)
            if latest is None:
                raise ValueError(f"no checkpoint found for run_id={run_id}; can't resume")
            state = latest.state
            current_sources = state.get("_env_sources", [])
            current_hash = compute_environment_hash(current_sources)
            if current_hash != latest.env_hash:
                # Staleness on resume: something the last completed phase
                # depended on changed while we were paused. Don't proceed on
                # data we can no longer vouch for.
                raise StalenessError(run_id, latest.phase, latest.env_hash, current_hash)
            next_ = phases.next_phase(latest.phase)
            if next_ is None:
                return RunResult(run_id=run_id, final_phase=latest.phase, resumed=True, state=state)
            start_phase = next_
            logger.info("resuming run=%s from phase=%s", run_id, start_phase)

        phase = start_phase
        while phase is not None:
            state = self._run_phase(run_id, phase, state)
            phase = phases.next_phase(phase)

        return RunResult(
            run_id=run_id,
            final_phase=phases.PHASE_ORDER[-1],
            report_path=state.get("report_path"),
            resumed=resumed,
            state=state,
        )

    def _run_phase(self, run_id: str, phase: str, state: dict) -> dict:
        logger.info("run=%s phase=%s starting", run_id, phase)

        if phase == phases.PLAN:
            memory_hits = self.memory.search(state["topic"], top_k=3)
            plan = self.agent.plan(state["topic"], [m.text for m in memory_hits])
            state = {**state, "plan": plan, "_env_sources": []}

        elif phase == phases.GATHER:
            results = web_search.search(state["topic"], num_results=5)
            state = {**state, "sources": results}

        elif phase == phases.READ:
            texts = [document_reader.read(s["url"], s["title"]) for s in state["sources"]]
            env_sources = [{"id": s["url"], "content": t} for s, t in zip(state["sources"], texts)]
            state = {**state, "source_texts": texts, "_env_sources": env_sources}

        elif phase == phases.SYNTHESIZE:
            synthesis = self.agent.synthesize(state["topic"], state["source_texts"])
            state = {**state, "synthesis": synthesis}

        elif phase == phases.DRAFT:
            draft = self.agent.draft(state["topic"], state["synthesis"])
            state = {**state, "draft": draft}

        elif phase == phases.CITE_CHECK:
            checked = self.agent.cite_check(state["draft"], state["source_texts"])
            state = {**state, "final_report": checked}

        elif phase == phases.PUBLISH:
            state = self._run_publish(run_id, state)

        else:
            raise ValueError(f"unknown phase: {phase}")

        env_hash = compute_environment_hash(state.get("_env_sources", []))

        if phase not in phases.IRREVERSIBLE_PHASES:
            # Default: checkpoint at the phase boundary, after the phase
            # completes. Steps within a phase are fast/idempotent, so a
            # rerun-from-here costs almost nothing - no need for finer
            # granularity.
            self.checkpoints.write(run_id, phase, status="completed", state=state, env_hash=env_hash)

        # Remember this report for future semantic recall, once it's done.
        if phase == phases.PUBLISH and "final_report" in state:
            self.memory.add(state["final_report"], metadata={"run_id": run_id, "topic": state["topic"]})

        logger.info("run=%s phase=%s complete", run_id, phase)
        return state

    def _run_publish(self, run_id: str, state: dict) -> dict:
        env_hash = compute_environment_hash(state.get("_env_sources", []))

        # Checkpoint BEFORE the irreversible call, not after. If the process
        # dies mid-send, recovery sees "publish was about to happen" and
        # checks the idempotency guard below before deciding to retry.
        self.checkpoints.write(run_id, phases.PUBLISH, status="started", state=state, env_hash=env_hash)

        idem_key = f"{run_id}:publish"
        try:
            self.idempotency.claim(idem_key)
        except AlreadyClaimedError:
            # Either this already sent successfully, or a previous attempt
            # crashed after claiming but we can't tell which from here - and
            # that's fine: we do NOT re-send. Re-sending is the failure mode
            # this whole module exists to prevent. A human can check the
            # publisher's own send log if they need to confirm delivery.
            logger.warning("run=%s publish already claimed, skipping send", run_id)
            report_path = state.get("report_path")
        else:
            report_path = self.publisher.publish(
                run_id=run_id,
                subject=f"Research report: {state['topic']}",
                body_markdown=state["final_report"],
            )

        state = {**state, "report_path": report_path}
        self.checkpoints.write(run_id, phases.PUBLISH, status="completed", state=state, env_hash=env_hash)
        return state
