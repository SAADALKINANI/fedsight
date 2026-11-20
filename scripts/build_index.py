"""Embed every passage and save data/corpus/embeddings.npy (row i belongs to passage i in chunks.jsonl.gz).

    python scripts/build_index.py

Embedding ~9,000 passages takes a while on a small CPU, so finished batches are saved under .cache/ and a
re-run picks up where it stopped.
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

BATCH = 500


def main() -> int:
    corpus = settings.data_dir / "corpus"
    chunks = load_chunks(settings.data_dir)
    texts = [embedding_text(c) for c in chunks]
    digest = hashlib.sha256((corpus / "chunks.jsonl.gz").read_bytes()).hexdigest()[:16]
    parts_dir = Path(__file__).resolve().parents[1] / ".cache" / f"emb_{digest}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    print(f"embedding {len(texts):,} passages with {settings.embed_model} ...", flush=True)

    embedder = FastEmbedder()
    started = time.time()
    for start in range(0, len(texts), BATCH):
        part = parts_dir / f"{start:06d}.npy"
        if not part.exists():
            np.save(part, embedder.embed_documents(texts[start:start + BATCH]))
        done = min(start + BATCH, len(texts))
        print(f"  {done:,}/{len(texts):,}  ({time.time() - started:.0f}s)", flush=True)

    emb = np.vstack([np.load(p) for p in sorted(parts_dir.glob("*.npy"))])
    assert len(emb) == len(chunks), "embedding count doesn't match passage count"
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)  # unit length so cosine == dot product

    np.save(corpus / "embeddings.npy", emb.astype(np.float16))
    (corpus / "index_info.json").write_text(json.dumps(
        {"embed_model": settings.embed_model, "passages": len(chunks), "dim": int(emb.shape[1]),
         "chunks_sha": digest}, indent=2))
    print(f"saved {emb.shape} to {corpus / 'embeddings.npy'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
