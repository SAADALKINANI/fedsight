from types import SimpleNamespace

import pytest
from conftest import FakeEmbedder

from fedsight.search import HybridIndex, embedding_text, tokenize


@pytest.fixture
def index(chunks):
    emb = FakeEmbedder()
    return HybridIndex(chunks, emb.embed_documents([embedding_text(c) for c in chunks]), emb, reranker=None)


def test_tokenize_drops_stopwords_and_keeps_ids():
    assert tokenize("What did GAO-19-164 say about the FEMA workforce?") == ["gao-19-164", "say", "fema", "workforce"]


def test_finds_the_relevant_passage(index):
    hits = index.search("FEMA disaster workforce staffing")
    assert hits[0].doc_id == "GAO-1"


def test_source_filter_is_respected(index):
    for query in ("overdose data surveillance", "workforce staffing"):
        hits = index.search(query, sources=["cdc"])
        assert hits and {h.source for h in hits} == {"cdc"}


def test_exact_keyword_still_wins_via_bm25(index):
    hits = index.search("cybersecurity risk management programs")
    assert hits[0].doc_id == "GAO-2"


def test_citation_id_is_unique_per_passage(index):
    hits = index.search("FEMA workforce recommended strategy")
    ids = [h.cite_source for h in hits]
    assert len(ids) == len(set(ids))


def test_cite_title_includes_section(index):
    h = index.search("workforce strategy recommended")[0]
    assert h.cite_title.endswith(h.section)


def test_per_document_cap(index, monkeypatch):
    import fedsight.search as search_module
    capped = SimpleNamespace(candidates=40, top_k=6, max_chunks_per_doc=1, min_rerank_score=-4.0)
    monkeypatch.setattr(search_module, "settings", capped)
    docs = [h.doc_id for h in index.search("FEMA workforce")]
    assert len(docs) == len(set(docs)) > 1


def test_out_of_sync_embeddings_are_rejected(chunks):
    emb = FakeEmbedder()
    with pytest.raises(AssertionError):
        HybridIndex(chunks, emb.embed_documents(["a"]), emb)
