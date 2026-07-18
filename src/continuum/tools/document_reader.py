"""
Reads a gathered source (by URL) into plain text for the READ phase.

Local/demo implementation: since web_search.py returns synthetic URLs, this
generates deterministic synthetic body text keyed off the URL rather than
actually fetching anything - keeps the whole pipeline runnable offline. A
real deployment swaps this for an actual fetcher (requests + readability
extraction, or a fetch tool routed through Claude's built-in web tools).
"""
from __future__ import annotations

import hashlib


def read(url: str, title: str = "") -> str:
    seed = hashlib.sha256(url.encode()).hexdigest()
    paragraphs = [
        f"{title or url}: overview paragraph {seed[0:4]} covering context and background.",
        f"Key finding referenced in this source, id {seed[4:8]}, with supporting detail.",
        f"Caveat and limitation noted by the source author, ref {seed[8:12]}.",
    ]
    return "\n\n".join(paragraphs)
