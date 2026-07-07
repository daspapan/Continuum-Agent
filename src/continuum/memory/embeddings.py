"""
Text -> vector embeddings.

Two backends:
  - BedrockTitanEmbeddings: production backend, calls Amazon Bedrock's Titan
    Text Embeddings model. Requires AWS creds + Bedrock model access.
  - LocalHashEmbeddings: deterministic, dependency-free "embedding" backend used for
    local dev and tests so the whole pipeline can run without any AWS or
    Anthropic calls in CI. It's not semantically meaningful in the way a real
    embedding model is - it's a bag-of-tokens hash projected into a fixed
    dimension - but cosine similarity over it still rewards shared vocabulary,
    which is enough to exercise recall logic in tests.

Don't ship LocalHashEmbeddings as your production recall quality. It exists
so `pytest` doesn't need a Bedrock model access grant to pass.
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod

import numpy as np

EMBEDDING_DIM = 256


class Embeddings(ABC):
    @abstractmethod
    def embed(self, text: str) -> np.ndarray:
        ...

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        # Default: no batching support in the backend, just loop.
        # BedrockTitanEmbeddings overrides this if/when we move to a
        # batch-capable model.
        return [self.embed(t) for t in texts]


class LocalHashEmbeddings(Embeddings):
    """Offline fallback. Deterministic, no network calls."""

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        tokens = text.lower().split()
        if not tokens:
            return vec
        for tok in tokens:
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % EMBEDDING_DIM
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


class BedrockTitanEmbeddings(Embeddings):
    """Production backend: Amazon Bedrock Titan Text Embeddings V2."""

    def __init__(self, model_id: str = "amazon.titan-embed-text-v2:0", region: str | None = None):
        import boto3  # local import: keeps boto3 optional for local-only usage

        self.model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))

    def embed(self, text: str) -> np.ndarray:
        import json

        body = json.dumps({"inputText": text})
        resp = self._client.invoke_model(
            modelId=self.model_id,
            body=body,
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(resp["body"].read())
        return np.array(payload["embedding"], dtype=np.float32)


def get_embeddings_backend(env: str = "local") -> Embeddings:
    if env == "aws":
        return BedrockTitanEmbeddings()
    return LocalHashEmbeddings()
