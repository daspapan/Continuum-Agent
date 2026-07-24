#!/usr/bin/env python3
"""
Creates the vector index inside an already-deployed OpenSearch Serverless
collection. CloudFormation/CDK provisions the *collection*
(`aoss.CfnCollection` in infra/continuum_stack.py); the index that actually
holds vectors lives inside it and is created via the OpenSearch API, which
CloudFormation has no resource type for. Run this once per environment,
after `cdk deploy` and before the first research run.

Usage:
    python3 scripts/create_memory_index.py --endpoint https://xyz.ap-south-1.aoss.amazonaws.com
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from continuum.memory.embeddings import EMBEDDING_DIM


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True, help="OpenSearch Serverless collection endpoint")
    parser.add_argument("--index-name", default="continuum-memory")
    parser.add_argument("--region", default=None)
    args = parser.parse_args()

    import boto3
    from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

    session = boto3.Session()
    region = args.region or session.region_name
    auth = AWSV4SignerAuth(session.get_credentials(), region, "aoss")

    client = OpenSearch(
        hosts=[{"host": args.endpoint.replace("https://", ""), "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )

    if client.indices.exists(index=args.index_name):
        print(f"index '{args.index_name}' already exists, nothing to do")
        return 0

    client.indices.create(
        index=args.index_name,
        body={
            "settings": {"index": {"knn": True}},
            "mappings": {
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": EMBEDDING_DIM,
                        "method": {"name": "hnsw", "engine": "faiss", "space_type": "cosinesimil"},
                    },
                    "text": {"type": "text"},
                    "metadata": {"type": "object"},
                    "created_at": {"type": "double"},
                }
            },
        },
    )
    print(f"created index '{args.index_name}' with dimension {EMBEDDING_DIM}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
