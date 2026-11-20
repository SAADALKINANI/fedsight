"""Turn raw documents (GAO reports, CDC web pages, OpenFEMA catalog entries) into search passages.

Every passage is a small dict:
    id, doc_id, source ("gao" | "fema" | "cdc"), title, url, page, section, text

GovReport has no page numbers, so GAO passages carry the section path instead
("Background > Public Assistance") and `page` stays None.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

MAX_CHARS = 1000      # target upper size of one passage
MIN_CHARS = 180       # smaller leftovers get merged into the previous passage

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_SKIP_SECTIONS = re.compile(r"contacts? and staff|staff acknowledg|related gao products|gao contact", re.I)
# Most GAO appendices are tables and program sheets that flatten into noise. Methodology and agency
# comments are the exceptions: they say how the work was done and how the agency responded.
_KEEP_APPENDIX = re.compile(r"methodology|comments", re.I)


def clean(text: str) -> str:
    return " ".join(text.split())


def split_long(paragraph: str, limit: int = MAX_CHARS) -> list[str]:
    """Split one long paragraph on sentence boundaries so each piece fits in `limit` characters."""
    if len(paragraph) <= limit:
        return [paragraph]
    pieces, current = [], ""
    for sentence in _SENTENCE_END.split(paragraph):
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    # a single "sentence" can still be huge (tables flattened into text), hard-wrap those
    out = []
    for piece in pieces:
        while len(piece) > limit * 1.5:
            cut = piece.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(piece[:cut])
            piece = piece[cut:].strip()
        out.append(piece)
    return out


def pack(paragraphs: list[str], limit: int = MAX_CHARS) -> list[str]:
    """Group paragraphs into passages of at most ~`limit` characters, never splitting mid-sentence."""
    units = [u for p in paragraphs for u in split_long(clean(p), limit) if u]
    passages, current = [], ""
    for unit in units:
        if current and len(current) + len(unit) + 1 > limit:
            passages.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    if current:
        if passages and len(current) < MIN_CHARS:
            passages[-1] = f"{passages[-1]} {current}"
        else:
            passages.append(current)
    return passages


def walk_sections(sections: list[dict], trail: tuple[str, ...] = ()):
    """Yield (section path, paragraphs) for a GovReport section tree."""
    for sec in sections:
        title = clean(sec.get("section_title") or "")
        here = trail + ((title,) if title else ())
        if _SKIP_SECTIONS.search(title):
            continue
        if not trail and title.lower().startswith("appendix") and not _KEEP_APPENDIX.search(title):
            continue
        paragraphs = [p for p in sec.get("paragraphs", []) if p.strip()]
        if paragraphs:
            yield " > ".join(here), paragraphs
        yield from walk_sections(sec.get("subsections") or [], here)


def gao_document(report: dict) -> tuple[dict, list[dict]]:
    doc_id = report["id"]
    title = clean(report["title"])
    url = report["url"]
    date = (report.get("published_date") or "")[:10]
    passages: list[dict] = []

    def add(section: str, paragraphs: list[str]):
        for text in pack(paragraphs):
            passages.append({
                "id": f"{doc_id}-{len(passages) + 1:03d}", "doc_id": doc_id, "source": "gao",
                "title": f"{doc_id}: {title}", "url": url, "page": None, "section": section, "text": text,
            })

    for sec in report.get("highlight") or []:
        add(f"Highlights > {clean(sec['section_title'])}", sec.get("paragraphs", []))
    for section, paragraphs in walk_sections(report.get("report") or []):
        add(section, paragraphs)

    doc = {"doc_id": doc_id, "source": "gao", "title": f"{doc_id}: {title}", "url": url, "date": date,
           "kind": "GAO report", "n_passages": len(passages)}
    return doc, passages


def web_document(doc_id: str, source: str, title: str, url: str, date: str, kind: str,
                 sections: list[tuple]) -> tuple[dict, list[dict]]:
    """Build passages from (section, paragraphs[, url]) tuples. A section can carry its own deep link."""
    passages = []
    for item in sections:
        section, paragraphs = item[0], item[1]
        link = item[2] if len(item) > 2 and item[2] else url
        for text in pack(paragraphs):
            passages.append({
                "id": f"{doc_id}-{len(passages) + 1:03d}", "doc_id": doc_id, "source": source,
                "title": title, "url": link, "page": None, "section": section, "text": text,
            })
    doc = {"doc_id": doc_id, "source": source, "title": title, "url": url, "date": date,
           "kind": kind, "n_passages": len(passages)}
    return doc, passages


def write_corpus(out_dir: Path, docs: list[dict], passages: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / "chunks.jsonl.gz", "wt", encoding="utf-8") as f:
        for p in passages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(out_dir / "documents.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
