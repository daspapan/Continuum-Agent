"""
Checkpoint-before-irreversible-action, and a conditional-write idempotency
guard for the action itself.

Two layers, and both matter:

1. Ordering: the checkpoint for the publish phase is written *before* the
   email send call, not after. If the process dies mid-send, recovery sees
   "checkpoint says publish was about to happen" and checks the idempotency
   guard (layer 2) before deciding whether to retry - it never blindly
   replays a send that may have already gone out.

2. The guard itself: a conditional write keyed by an idempotency key (here,
   `f"{run_id}:publish"`) that only succeeds once. The send path always
   attempts the guard write first; if it's already claimed, we skip the send
   and treat the phase as already complete. This is what actually prevents
   the double-send - the checkpoint ordering just makes sure recovery *checks*
   before it *acts*.

Local backend uses sqlite's UNIQUE constraint for the same guarantee
DynamoDB's `attribute_not_exists` conditional put gives in production.
"""
from __future__ import annotations

import sqlite3


class AlreadyClaimedError(Exception):
    """Raised when an idempotency key has already been claimed - i.e. the
    action it guards has already happened (or is in flight). Callers should
    treat this as "skip the action," not as a failure."""


class IdempotencyGuard:
    def claim(self, key: str) -> None:
        """Raises AlreadyClaimedError if `key` was already claimed."""
        raise NotImplementedError


class LocalIdempotencyGuard(IdempotencyGuard):
    def __init__(self, db_path: str = "continuum_idempotency.sqlite3"):
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS claims (idem_key TEXT PRIMARY KEY, claimed_at REAL NOT NULL)"
        )
        self._conn.commit()

    def claim(self, key: str) -> None:
        import time

        try:
            self._conn.execute(
                "INSERT INTO claims (idem_key, claimed_at) VALUES (?, ?)", (key, time.time())
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise AlreadyClaimedError(key) from exc


class DynamoDBIdempotencyGuard(IdempotencyGuard):
    """
    Uses the same DynamoDB table as DynamoDBCheckpointStore
    (partition key run_id, sort key sk), with sk = "IDEM#{key}" so claims and
    checkpoints share a table without colliding, and a conditional put on
    attribute_not_exists(sk) does the actual guarding.
    """

    def __init__(self, table_name: str, region: str | None = None):
        import boto3

        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def claim(self, key: str) -> None:
        import time
        from botocore.exceptions import ClientError

        run_id, _, action = key.partition(":")
        try:
            self._table.put_item(
                Item={"run_id": run_id, "sk": f"IDEM#{action}", "claimed_at": str(time.time())},
                ConditionExpression="attribute_not_exists(sk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AlreadyClaimedError(key) from exc
            raise


def get_idempotency_guard(env: str, **kwargs) -> IdempotencyGuard:
    if env == "aws":
        return DynamoDBIdempotencyGuard(table_name=kwargs["table_name"])
    return LocalIdempotencyGuard(db_path=kwargs.get("db_path", "continuum_idempotency.sqlite3"))
