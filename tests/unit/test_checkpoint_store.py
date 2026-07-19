"""
What this validates: the sqlite checkpoint store round-trips state correctly
and `latest()` actually returns the most recent write, not just the first
row - that's the exact bug class that would make resume silently pick up
from the wrong phase.
"""
from continuum.pipeline.checkpoint_store import LocalCheckpointStore


def test_write_and_latest_roundtrip(tmp_workdir):
    store = LocalCheckpointStore(db_path=str(tmp_workdir / "cp.sqlite3"))
    store.write("run-1", "plan", "completed", {"topic": "x"}, env_hash="h1")
    store.write("run-1", "gather", "completed", {"topic": "x", "sources": [1, 2]}, env_hash="h2")

    latest = store.latest("run-1")
    assert latest.phase == "gather"
    assert latest.env_hash == "h2"
    assert latest.state["sources"] == [1, 2]


def test_latest_is_none_for_unknown_run(tmp_workdir):
    store = LocalCheckpointStore(db_path=str(tmp_workdir / "cp.sqlite3"))
    assert store.latest("no-such-run") is None


def test_history_is_chronological(tmp_workdir):
    store = LocalCheckpointStore(db_path=str(tmp_workdir / "cp.sqlite3"))
    for phase in ["plan", "gather", "read"]:
        store.write("run-1", phase, "completed", {}, env_hash=phase)
    history = store.history("run-1")
    assert [c.phase for c in history] == ["plan", "gather", "read"]


def test_history_scoped_to_run_id(tmp_workdir):
    store = LocalCheckpointStore(db_path=str(tmp_workdir / "cp.sqlite3"))
    store.write("run-1", "plan", "completed", {}, env_hash="h")
    store.write("run-2", "plan", "completed", {}, env_hash="h")
    assert len(store.history("run-1")) == 1
    assert len(store.history("run-2")) == 1
