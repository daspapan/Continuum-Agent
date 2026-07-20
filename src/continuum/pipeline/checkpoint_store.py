"""
Checkpoint storage for a running pipeline.

Granularity rule this module enforces by convention (see orchestrator.py for
where it's actually applied): checkpoint at phase boundaries by default, not
after every step inside a phase. The pipeline's per-phase steps are fast and
idempotent, so re-running a phase from scratch after an interruption costs
almost nothing - there's no safety benefit to finer-grained checkpoints, only
extra writes and more recovery-state to reason about. The one exception is
anything that calls an external system with a real side effect (the publish
phase's email send); that gets its own checkpoint write immediately before
the side-effecting call, independent of phase boundaries. See idempotency.py.

Two backends:
  - LocalCheckpointStore: sqlite, single file, no setup.
  - DynamoDBCheckpointStore: production backend. One item per (run_id, phase),
    partition key run_id so a full run's checkpoint history is one query.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass


@dataclass
class Checkpoint:
    run_id: str
    phase: str
    status: str  # "started" | "completed"
    state: dict
    env_hash: str
    written_at: float


class CheckpointStore:
    def write(self, run_id: str, phase: str, status: str, state: dict, env_hash: str) -> None:
        raise NotImplementedError

    def latest(self, run_id: str) -> Checkpoint | None:
        raise NotImplementedError

    def history(self, run_id: str) -> list[Checkpoint]:
        raise NotImplementedError


class LocalCheckpointStore(CheckpointStore):
    def __init__(self, db_path: str = "continuum_checkpoints.sqlite3"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                run_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                state TEXT NOT NULL,
                env_hash TEXT NOT NULL,
                written_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def write(self, run_id: str, phase: str, status: str, state: dict, env_hash: str) -> None:
        self._conn.execute(
            "INSERT INTO checkpoints (run_id, phase, status, state, env_hash, written_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, phase, status, json.dumps(state), env_hash, time.time()),
        )
        self._conn.commit()

    def latest(self, run_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT run_id, phase, status, state, env_hash, written_at FROM checkpoints "
            "WHERE run_id = ? ORDER BY written_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_checkpoint(row)

    def history(self, run_id: str) -> list[Checkpoint]:
        rows = self._conn.execute(
            "SELECT run_id, phase, status, state, env_hash, written_at FROM checkpoints "
            "WHERE run_id = ? ORDER BY written_at ASC",
            (run_id,),
        ).fetchall()
        return [_row_to_checkpoint(r) for r in rows]

    def close(self) -> None:
        self._conn.close()


def _row_to_checkpoint(row) -> Checkpoint:
    run_id, phase, status, state_json, env_hash, written_at = row
    return Checkpoint(
        run_id=run_id,
        phase=phase,
        status=status,
        state=json.loads(state_json),
        env_hash=env_hash,
        written_at=written_at,
    )


class DynamoDBCheckpointStore(CheckpointStore):
    """
    Production backend. Table schema (see infra/continuum_stack.py):
      partition key: run_id (S)
      sort key: sk (S)  -> "{written_at_iso}#{phase}" for checkpoint items,
                            "IDEM#{action}" for idempotency claims (see
                            DynamoDBIdempotencyGuard, which shares this
                            table). `latest`/`history` filter to items with a
                            `phase` attribute so claim items never get read
                            back as checkpoints.
    """

    def __init__(self, table_name: str, region: str | None = None):
        import boto3

        self.table_name = table_name
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def write(self, run_id: str, phase: str, status: str, state: dict, env_hash: str) -> None:
        import datetime

        written_at = time.time()
        sk = f"{datetime.datetime.fromtimestamp(written_at, tz=datetime.timezone.utc).isoformat()}#{phase}"
        self._table.put_item(
            Item={
                "run_id": run_id,
                "sk": sk,
                "phase": phase,
                "status": status,
                "state": json.dumps(state),
                "env_hash": env_hash,
                "written_at": str(written_at),
            }
        )

    def latest(self, run_id: str) -> Checkpoint | None:
        # The run_id partition also holds idempotency-claim items (sk =
        # "IDEM#...", written by DynamoDBIdempotencyGuard against the same
        # table). Filter to items that are actually checkpoints - anything
        # with a `phase` attribute - so a claim item never gets mistaken for
        # the latest checkpoint. Filtering client-side would be wrong too;
        # this uses a server-side FilterExpression so Limit=1 still means
        # "one checkpoint," not "one item that might be a claim."
        from boto3.dynamodb.conditions import Attr, Key

        resp = self._table.query(
            KeyConditionExpression=Key("run_id").eq(run_id),
            FilterExpression=Attr("phase").exists(),
            ScanIndexForward=False,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        # FilterExpression is applied after Limit in DynamoDB, so we can't
        # combine Limit=1 with the filter and trust the result - sort here
        # instead, which is cheap since a single run's checkpoint history is
        # small (one item per phase, ~7 phases).
        items.sort(key=lambda i: i["written_at"], reverse=True)
        return _item_to_checkpoint(items[0])

    def history(self, run_id: str) -> list[Checkpoint]:
        from boto3.dynamodb.conditions import Attr, Key

        resp = self._table.query(
            KeyConditionExpression=Key("run_id").eq(run_id),
            FilterExpression=Attr("phase").exists(),
            ScanIndexForward=True,
        )
        return [_item_to_checkpoint(i) for i in resp.get("Items", [])]


def _item_to_checkpoint(item: dict) -> Checkpoint:
    return Checkpoint(
        run_id=item["run_id"],
        phase=item["phase"],
        status=item["status"],
        state=json.loads(item["state"]),
        env_hash=item["env_hash"],
        written_at=float(item["written_at"]),
    )


def get_checkpoint_store(env: str, **kwargs) -> CheckpointStore:
    if env == "aws":
        return DynamoDBCheckpointStore(table_name=kwargs["table_name"])
    return LocalCheckpointStore(db_path=kwargs.get("db_path", "continuum_checkpoints.sqlite3"))
