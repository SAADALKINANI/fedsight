import gzip
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fedsight.search import Passage, tokenize  # noqa: E402


class FakeEmbedder:
    """Hashes words into a small vector. Good enough to make similar texts land near each other."""

    dim = 64

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in tokenize(text):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts, batch_size=64):
        return np.vstack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def chunks():
    rows = [
        ("GAO-1-001", "GAO-1", "gao", "GAO-1: FEMA Disaster Workforce", "Staffing",
         "FEMA struggled to deploy enough qualified disaster workforce staff after the 2017 hurricanes. "
         "GAO found that 40 percent of positions were unfilled."),
        ("GAO-1-002", "GAO-1", "gao", "GAO-1: FEMA Disaster Workforce", "Recommendations",
         "GAO recommended that FEMA develop a workforce strategy for its disaster cadre."),
        ("GAO-2-001", "GAO-2", "gao", "GAO-2: Federal Cybersecurity", "Findings",
         "Agencies have not fully implemented risk management programs for cybersecurity."),
        ("CDC-1-001", "CDC-1", "cdc", "CDC: Overdose Data", "Overview",
         "CDC tracks fatal overdose data using state surveillance systems."),
        ("CFR-1-001", "CFR-1", "fema", "44 CFR 206", "Individuals and Households",
         "Individuals and households may receive financial assistance for home repair after a major disaster."),
    ]
    return [{"id": i, "doc_id": d, "source": s, "title": t, "url": f"https://example.gov/{d}", "page": None,
             "section": sec, "text": txt} for i, d, s, t, sec, txt in rows]


@pytest.fixture
def tables_dir(tmp_path):
    d = tmp_path / "tables"
    d.mkdir()
    pd.DataFrame({"disaster_number": [1, 2, 3, 3], "state": ["FL", "FL", "TX", "TX"],
                  "declaration_type": ["DR", "DR", "DR", "DR"],
                  "declaration_date": ["2017-09-10", "2018-10-11", "2017-08-25", "2017-08-25"]}
                 ).to_csv(d / "fema_declarations.csv.gz", index=False)
    return d


def make_passage(chunk: dict, score: float = 1.0) -> Passage:
    return Passage(chunk["id"], chunk["doc_id"], chunk["source"], chunk["title"], chunk["url"], chunk["page"],
                   chunk["text"], score, section=chunk["section"])


@pytest.fixture
def write_corpus_files(tmp_path, chunks):
    def _write():
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        with gzip.open(corpus / "chunks.jsonl.gz", "wt") as f:
            import json
            for c in chunks:
                f.write(json.dumps(c) + "\n")
        return tmp_path
    return _write
