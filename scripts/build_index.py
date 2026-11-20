"""Embed every passage and save data/corpus/embeddings.npy (row i belongs to passage i in chunks.jsonl.gz).

    python scripts/build_index.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fedsight.config import settings  # noqa: E402
from fedsight.search import FastEmbedder, embedding_text, load_chunks  # noqa: E402


def main() -> int:
    corpus = settings.data_dir / "corpus"
    chunks = load_chunks(settings.data_dir)
    texts = [embedding_text(c) for c in chunks]
    print(f"embedding {len(texts):,} passages with {settings.embed_model} ...", flush=True)

    embedder = FastEmbedder()
    started = time.time()
    parts = []
    for i in range(0, len(texts), 1000):
        parts.append(embedder.embed_documents(texts[i:i + 1000]))
        done = min(i + 1000, len(texts))
        print(f"  {done:,}/{len(texts):,}  ({time.time() - started:.0f}s)", flush=True)
    emb = np.vstack(parts)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)  # unit length so cosine == dot product

    np.save(corpus / "embeddings.npy", emb.astype(np.float16))
    digest = hashlib.sha256((corpus / "chunks.jsonl.gz").read_bytes()).hexdigest()[:16]
    (corpus / "index_info.json").write_text(json.dumps(
        {"embed_model": settings.embed_model, "passages": len(chunks), "dim": int(emb.shape[1]),
         "chunks_sha": digest}, indent=2))
    print(f"saved {emb.shape} to {corpus / 'embeddings.npy'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
