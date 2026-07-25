"""
Semantic recall over past research: "what did we find about X" without an
exact document ID or session key.

Why a vector index instead of a key-value/relational lookup: the retrieval
problem here is "find what's semantically relevant," not "look up a known
ID." A customer/user referencing prior work by meaning, not by ID, can't be
served by an exact-match store - there's no key to look up with. That's the
whole reason this module exists instead of just a dict keyed by report_id.

Two backends, same interface:
  - LocalVectorStore: sqlite-backed, brute-force cosine similarity in numpy.
    Fine up to a few thousand vectors, which covers local dev and a single
    user's report history. Zero external services.
  - OpenSearchServerlessVectorStore: production backend, k-NN search against
    an OpenSearch Serverless collection. This is the one that actually
    scales past "fits in memory."
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from continuum.memory.embeddings import Embeddings


@dataclass
class MemoryRecord:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    score: float | None = None  # populated on search results only


class VectorStore:
    def add(self, text: str, metadata: dict | None = None) -> str:
        raise NotImplementedError

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        raise NotImplementedError


class LocalVectorStore(VectorStore):
    """sqlite + numpy brute-force cosine similarity. Local dev / small scale."""

    def __init__(self, embeddings: Embeddings, db_path: str | Path = "continuum_memory.sqlite3"):
        self.embeddings = embeddings
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def add(self, text: str, metadata: dict | None = None) -> str:
        record_id = str(uuid.uuid4())
        vec = self.embeddings.embed(text)
        self._conn.execute(
            "INSERT INTO memory (id, text, metadata, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
            (record_id, text, json.dumps(metadata or {}), json.dumps(vec.tolist()), time.time()),
        )
        self._conn.commit()
        return record_id

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        query_vec = self.embeddings.embed(query)
        rows = self._conn.execute("SELECT id, text, metadata, embedding, created_at FROM memory").fetchall()
        if not rows:
            return []

        scored: list[MemoryRecord] = []
        for row_id, text, metadata_json, embedding_json, created_at in rows:
            vec = np.array(json.loads(embedding_json), dtype=np.float32)
            score = _cosine_similarity(query_vec, vec)
            scored.append(
                MemoryRecord(
                    id=row_id,
                    text=text,
                    metadata=json.loads(metadata_json),
                    created_at=created_at,
                    score=score,
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def close(self) -> None:
        self._conn.close()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class OpenSearchServerlessVectorStore(VectorStore):
    """
    Production backend: k-NN search against an OpenSearch Serverless
    collection (vector search engine). Index is expected to already exist
    (see infra/continuum_stack.py) with a `knn_vector` field named
    `embedding` and dimension continuum.memory.embeddings.EMBEDDING_DIM.

    NOTE: this class is written against the OpenSearch Serverless data-plane
    API but is not exercised by the local test suite (no AWS creds in CI by
    default) - see tests/integration for the moto-backed coverage we do have,
    and docs/DEPLOYMENT_RUNBOOK.md for how to validate this against a real
    collection after `cdk deploy`.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        endpoint: str,
        index_name: str = "continuum-memory",
        region: str | None = None,
    ):
        import boto3
        from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

        self.embeddings = embeddings
        self.index_name = index_name

        session = boto3.Session()
        region = region or session.region_name
        credentials = session.get_credentials()
        auth = AWSV4SignerAuth(credentials, region, "aoss")

        self._client = OpenSearch(
            hosts=[{"host": endpoint.replace("https://", ""), "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )

    def add(self, text: str, metadata: dict | None = None) -> str:
        record_id = str(uuid.uuid4())
        vec = self.embeddings.embed(text)
        self._client.index(
            index=self.index_name,
            id=record_id,
            body={
                "text": text,
                "metadata": metadata or {},
                "embedding": vec.tolist(),
                "created_at": time.time(),
            },
        )
        return record_id

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        vec = self.embeddings.embed(query)
        resp = self._client.search(
            index=self.index_name,
            body={
                "size": top_k,
                "query": {"knn": {"embedding": {"vector": vec.tolist(), "k": top_k}}},
            },
        )
        results = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            results.append(
                MemoryRecord(
                    id=hit["_id"],
                    text=src["text"],
                    metadata=src.get("metadata", {}),
                    created_at=src.get("created_at", 0.0),
                    score=hit["_score"],
                )
            )
        return results


def get_vector_store(env: str, embeddings: Embeddings, **kwargs) -> VectorStore:
    if env == "aws":
        endpoint = kwargs["endpoint"]
        return OpenSearchServerlessVectorStore(embeddings, endpoint=endpoint)
    return LocalVectorStore(embeddings, db_path=kwargs.get("db_path", "continuum_memory.sqlite3"))
