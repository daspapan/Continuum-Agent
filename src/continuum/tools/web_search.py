"""
Mock web search tool.

Real web search is out of scope for v1 (see notes/project-brief.md) so this
project doesn't depend on a paid search API to run or demo. It returns
canned-but-topic-shaped results deterministically from the query string, which
is enough to exercise the gather -> read -> synthesize phases end to end.

Swap this for a real provider (Brave Search API, Tavily, etc.) by implementing
the same `search(query, num_results)` signature and passing it into
ResearchAgent instead of this one - nothing else in the pipeline needs to
change, since phases only depend on the tool interface, not this
implementation.
"""
from __future__ import annotations

import hashlib


def search(query: str, num_results: int = 5) -> list[dict]:
    results = []
    for i in range(num_results):
        seed = hashlib.sha256(f"{query}:{i}".encode()).hexdigest()[:8]
        results.append(
            {
                "title": f"{query.title()} — source {i + 1}",
                "url": f"https://example-sources.test/{seed}",
                "snippet": f"Background and analysis relevant to '{query}', reference {i + 1}.",
            }
        )
    return results
