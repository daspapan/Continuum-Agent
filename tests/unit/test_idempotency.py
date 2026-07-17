"""
What this validates: the idempotency guard actually blocks a second claim on
the same key. This is the mechanism that stops a double-send if the publish
phase runs twice (e.g. a naive retry after a crash) - if this test doesn't
hold, the whole checkpoint-before-publish design doesn't actually prevent
the double charge/double email it's meant to prevent.
"""
import pytest

from continuum.pipeline.idempotency import AlreadyClaimedError, LocalIdempotencyGuard


def test_first_claim_succeeds(tmp_workdir):
    guard = LocalIdempotencyGuard(db_path=str(tmp_workdir / "idem.sqlite3"))
    guard.claim("run-1:publish")  # should not raise


def test_second_claim_on_same_key_raises(tmp_workdir):
    guard = LocalIdempotencyGuard(db_path=str(tmp_workdir / "idem.sqlite3"))
    guard.claim("run-1:publish")
    with pytest.raises(AlreadyClaimedError):
        guard.claim("run-1:publish")


def test_different_keys_are_independent(tmp_workdir):
    guard = LocalIdempotencyGuard(db_path=str(tmp_workdir / "idem.sqlite3"))
    guard.claim("run-1:publish")
    guard.claim("run-2:publish")  # different run, should not raise
