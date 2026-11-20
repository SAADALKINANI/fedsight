"""Hybrid retrieval: Chroma (dense) + BM25 (keyword), fused with RRF, then a cross-encoder rerank."""
from __future__ import annotations

import gzip
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from .config import settings

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the this to was were
what when where which who will with how does did do not no than then there their they them can could would should
about into over under after before between during any all also may must""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class Passage:
    chunk_id: str
    doc_id: str
    source: str          # gao | fema | cdc
    title: str
    url: str
    page: int | None
    text: str
    score: float = 0.0
    rerank_score: float | None = None
    section: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def cite_source(self) -> str:
        # Must be unique per passage: several passages from one report share a URL, and the
        # citation numbering in the answer is keyed on this value.
        return self.chunk_id

    @property
    def cite_title(self) -> str:
        title = f"{self.title} (p. {self.page})" if self.page else self.title
        return f"{title} \u2014 {self.section}" if self.section else title


def embedding_text(chunk: dict) -> str:
    """What gets embedded and keyword-indexed for a passage: the text plus where it came from."""
    where = f"{chunk['title']}. {chunk['section']}. " if chunk.get("section") else f"{chunk['title']}. "
    return where + chunk["text"]


def load_chunks(data_dir: Path) -> list[dict]:
    with gzip.open(data_dir / "corpus" / "chunks.jsonl.gz", "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class FastEmbedder:
    def __init__(self, model_name: str = settings.embed_model):
        from fastembed import TextEmbedding
        self.model = TextEmbedding(model_name)

    def embed_documents(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        return np.array(list(self.model.embed(texts, batch_size=batch_size)), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vec = next(iter(self.model.embed([settings.embed_query_prefix + text])))
        return np.array(vec, dtype=np.float32)


class CrossEncoderReranker:
    def __init__(self, model_name: str = settings.rerank_model):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.model = TextCrossEncoder(model_name)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self.model.rerank(query, texts)]


class HybridIndex:
    def __init__(self, chunks: list[dict], embeddings: np.ndarray, embedder, reranker=None,
                 persist_dir: Path | None = None):
        assert len(chunks) == len(embeddings), "chunks and embeddings are out of sync - rebuild the index"
        self.chunks = chunks
        self.by_id = {c["id"]: i for i, c in enumerate(chunks)}
        self.embedder = embedder
        self.reranker = reranker
        self.sources = np.array([c["source"] for c in chunks])
        self.bm25 = BM25Okapi([tokenize(embedding_text(c)) for c in chunks])
        self.collection = self._load_collection(embeddings, persist_dir)

    def _load_collection(self, embeddings: np.ndarray, persist_dir: Path | None):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        if persist_dir:
            client = chromadb.PersistentClient(path=str(persist_dir), settings=chroma_settings)
        else:
            client = chromadb.EphemeralClient(settings=chroma_settings)
        col = client.get_or_create_collection("fedsight", embedding_function=None,
                                              metadata={"hnsw:space": "cosine"})
        if col.count() == len(self.chunks):
            return col
        if col.count():
            client.delete_collection("fedsight")
            col = client.create_collection("fedsight", embedding_function=None, metadata={"hnsw:space": "cosine"})
        log.info("building chroma collection with %d vectors", len(self.chunks))
        step = 4000
        for i in range(0, len(self.chunks), step):
            batch = self.chunks[i:i + step]
            col.add(ids=[c["id"] for c in batch],
                    embeddings=embeddings[i:i + step].astype(np.float32).tolist(),
                    metadatas=[{"source": c["source"], "doc_id": c["doc_id"]} for c in batch])
        return col

    def search(self, query: str, k: int = settings.top_k, sources: list[str] | None = None) -> list[Passage]:
        n = settings.candidates
        where = {"source": {"$in": list(sources)}} if sources else None

        qv = self.embedder.embed_query(query)
        dense = self.collection.query(query_embeddings=[qv.tolist()], n_results=n, where=where)
        dense_ids = [self.by_id[i] for i in dense["ids"][0]]

        bm = self.bm25.get_scores(tokenize(query))
        if sources:
            bm = np.where(np.isin(self.sources, list(sources)), bm, -np.inf)
        bm_ids = [int(i) for i in np.argsort(-bm)[:n] if np.isfinite(bm[i]) and bm[i] > 0]

        fused: dict[int, float] = {}
        for ranked in (dense_ids, bm_ids):
            for rank, idx in enumerate(ranked):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (60 + rank + 1)
        cand = sorted(fused, key=fused.get, reverse=True)[:n]
        passages = [self._passage(i, fused[i]) for i in cand]

        if self.reranker and passages:
            scores = self.reranker.score(query, [f"{p.title}. {p.section}. {p.text}" for p in passages])
            for p, s in zip(passages, scores, strict=True):
                p.rerank_score = s
            passages.sort(key=lambda p: p.rerank_score, reverse=True)
            passages = [p for p in passages if p.rerank_score >= settings.min_rerank_score]

        out, per_doc = [], {}
        for p in passages:
            if per_doc.get(p.doc_id, 0) >= settings.max_chunks_per_doc:
                continue
            per_doc[p.doc_id] = per_doc.get(p.doc_id, 0) + 1
            out.append(p)
            if len(out) == k:
                break
        return out

    def _passage(self, i: int, score: float) -> Passage:
        c = self.chunks[i]
        return Passage(c["id"], c["doc_id"], c["source"], c["title"], c["url"], c.get("page"), c["text"], score,
                       section=c.get("section", ""))


def load_index(data_dir: Path = settings.data_dir, embedder=None, reranker=None, persist_dir=settings.index_dir):
    chunks = load_chunks(data_dir)
    emb = np.load(data_dir / "corpus" / "embeddings.npy")
    return HybridIndex(chunks, emb, embedder or FastEmbedder(), reranker if reranker is not None else CrossEncoderReranker(),
                       persist_dir)
