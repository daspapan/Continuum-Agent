"""
Environment-hash state versioning: catches staleness on resume.

Every checkpoint records a hash of the source material a phase depended on
(the topic brief, gathered source documents/URLs, prior report drafts it's
building on) at the moment the checkpoint was written. On resume, we
recompute that hash from current state and compare. A mismatch means the
world changed while the run was paused - a source document was edited, a
gathered link now points somewhere else, the prior draft was hand-edited -
and we flag the conflict instead of silently continuing to synthesize from
data we can no longer vouch for.

This deliberately hashes *content*, not timestamps or ETags: content hashing
catches "the file changed" regardless of what changed the mtime, and it's the
same hash whether the source lives on local disk or in S3.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_environment_hash(sources: list[dict[str, Any]]) -> str:
    """
    `sources` is a list of {"id": ..., "content": ...} dicts describing
    everything the current phase read to do its work. Order-independent:
    sorted by id before hashing so reordering the same sources doesn't count
    as a change.
    """
    normalized = sorted(sources, key=lambda s: s["id"])
    canonical = json.dumps(
        [{"id": s["id"], "content": s["content"]} for s in normalized],
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class StalenessError(Exception):
    """Raised when a resumed run's environment hash no longer matches the
    hash recorded at the last checkpoint. Callers should treat this as
    "needs human review," not retry-and-ignore."""

    def __init__(self, run_id: str, phase: str, checkpoint_hash: str, current_hash: str):
        self.run_id = run_id
        self.phase = phase
        self.checkpoint_hash = checkpoint_hash
        self.current_hash = current_hash
        super().__init__(
            f"staleness detected resuming run={run_id} phase={phase}: "
            f"checkpoint env_hash={checkpoint_hash[:12]}... != current env_hash={current_hash[:12]}..."
        )


def check_for_staleness(run_id: str, phase: str, checkpoint_hash: str, sources: list[dict[str, Any]]) -> None:
    current_hash = compute_environment_hash(sources)
    if current_hash != checkpoint_hash:
        raise StalenessError(run_id, phase, checkpoint_hash, current_hash)
