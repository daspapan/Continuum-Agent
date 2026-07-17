"""
What this validates: semantic recall actually ranks a topically-related
record above an unrelated one using only the local hash-embedding backend
(no network, no Bedrock access needed for this to run in CI). This is
exercising "find by meaning, not by exact key" - the whole reason the memory
module is a vector index and not a dict.
"""
from continuum.memory.embeddings import LocalHashEmbeddings
from continuum.memory.vector_store import LocalVectorStore


def test_search_ranks_related_record_higher(tmp_workdir):
    store = LocalVectorStore(LocalHashEmbeddings(), db_path=str(tmp_workdir / "mem.sqlite3"))
    store.add("quarterly cloud infrastructure cost report for the platform team")
    store.add("recipe for sourdough bread with a rye starter")

    results = store.search("cloud infrastructure costs", top_k=2)

    assert results[0].text.startswith("quarterly cloud")


def test_search_on_empty_store_returns_empty(tmp_workdir):
    store = LocalVectorStore(LocalHashEmbeddings(), db_path=str(tmp_workdir / "mem.sqlite3"))
    assert store.search("anything", top_k=3) == []


def test_add_returns_stable_retrievable_id(tmp_workdir):
    store = LocalVectorStore(LocalHashEmbeddings(), db_path=str(tmp_workdir / "mem.sqlite3"))
    record_id = store.add("distinctive record about migrating to kubernetes")
    results = store.search("migrating to kubernetes", top_k=1)
    assert results[0].id == record_id
