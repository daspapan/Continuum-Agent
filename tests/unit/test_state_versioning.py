"""
What this validates: environment-hash staleness detection actually catches a
changed source, and does NOT false-positive on cosmetic differences (e.g.
source list reordering) that don't represent real staleness.
"""
import pytest

from continuum.pipeline.state_versioning import (
    StalenessError,
    check_for_staleness,
    compute_environment_hash,
)


def test_same_sources_same_hash():
    sources = [{"id": "a", "content": "hello"}, {"id": "b", "content": "world"}]
    assert compute_environment_hash(sources) == compute_environment_hash(sources)


def test_reordered_sources_same_hash():
    a = [{"id": "a", "content": "hello"}, {"id": "b", "content": "world"}]
    b = [{"id": "b", "content": "world"}, {"id": "a", "content": "hello"}]
    assert compute_environment_hash(a) == compute_environment_hash(b)


def test_changed_content_changes_hash():
    a = [{"id": "a", "content": "hello"}]
    b = [{"id": "a", "content": "hello, edited"}]
    assert compute_environment_hash(a) != compute_environment_hash(b)


def test_check_for_staleness_raises_on_mismatch():
    original = [{"id": "a", "content": "hello"}]
    changed = [{"id": "a", "content": "hello, but different now"}]
    checkpoint_hash = compute_environment_hash(original)
    with pytest.raises(StalenessError):
        check_for_staleness("run-1", "read", checkpoint_hash, changed)


def test_check_for_staleness_passes_when_unchanged():
    sources = [{"id": "a", "content": "hello"}]
    checkpoint_hash = compute_environment_hash(sources)
    check_for_staleness("run-1", "read", checkpoint_hash, sources)  # should not raise
