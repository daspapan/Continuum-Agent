"""
The research pipeline's phases, in order.

Kept as a plain enum-like list rather than a graph/DAG library because the
pipeline is strictly sequential for v1 - no branching, no fan-out. If that
changes (e.g. parallel GATHER across multiple sub-topics), this is the file
that grows into something heavier; not worth the abstraction until then.
"""
from __future__ import annotations

PLAN = "plan"
GATHER = "gather"
READ = "read"
SYNTHESIZE = "synthesize"
DRAFT = "draft"
CITE_CHECK = "cite_check"
PUBLISH = "publish"

PHASE_ORDER = [PLAN, GATHER, READ, SYNTHESIZE, DRAFT, CITE_CHECK, PUBLISH]

# The only phase with a real external side effect. Everything else can be
# safely rerun from scratch after an interruption; this one gets the
# idempotency guard (see idempotency.py) instead of relying on rerun-safety.
IRREVERSIBLE_PHASES = {PUBLISH}


def next_phase(current: str | None) -> str | None:
    if current is None:
        return PHASE_ORDER[0]
    idx = PHASE_ORDER.index(current)
    if idx + 1 >= len(PHASE_ORDER):
        return None
    return PHASE_ORDER[idx + 1]
