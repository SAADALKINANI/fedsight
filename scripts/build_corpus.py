"""Build the document corpus: data/corpus/chunks.jsonl.gz and data/corpus/documents.jsonl.

    python scripts/build_corpus.py

Sources (all U.S. government publications, free to reuse):
  * GAO reports       - the GovReport dataset on Hugging Face (GAO reports from 2017-2020)
  * FEMA rules        - 44 CFR parts 201, 204 and 206 from the eCFR API (current text)
  * OpenFEMA catalog  - dataset descriptions and field definitions from the OpenFEMA API
  * CDC pages         - overdose prevention and public health readiness pages on cdc.gov

gao.gov itself blocks scripted downloads, so GAO text comes from GovReport instead. That's why the
GAO documents are older than the FEMA and CDC ones; the README explains this.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fedsight.ingest import clean, gao_document, web_document, write_corpus  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / ".cache" / "raw"
UA = "fedsight/0.1 (portfolio project; github.com/SAADALKINANI/fedsight)"
HF = "https://huggingface.co/datasets/launch/gov_report/resolve/main/data"

CDC_PAGES = [
    "overdose-prevention/index.html",
    "overdose-prevention/about/index.html",
    "overdose-prevention/about/what-you-should-know-about-xylazine.html",
    "overdose-prevention/data-research/facts-stats/index.html",
    "overdose-prevention/data-research/facts-stats/sudors-dashboard-fatal-overdose-data.html",
    "overdose-prevention/data-channel/index.html",
    "overdose-prevention/situation-summary/index.html",
    "overdose-prevention/prevention/index.html",
    "overdose-prevention/treatment/index.html",
    "overdose-prevention/php/public-health-strategy/index.html",
    "overdose-prevention/php/od2a/index.html",
    "overdose-prevention/php/interventions/index.html",
    "overdose-prevention/php/drug-free-communities/index.html",
    "overdose-prevention/hcp/clinical-guidance/index.html",
    "overdose-prevention/hcp/clinical-care/index.html",
    "orr/index.html",
    "orr/about/index.html",
    "orr/budget-funding/index.html",
    "orr/deo/index.html",
    "orr/responses/index.html",
    "orr/divisions-offices/about-division-of-emergency-operations.html",
    "orr/divisions-offices/about-division-of-state-and-local-readiness.html",
    "han/php/about/index.html",
    "prepare-your-health/index.html",
]
CFR_PARTS = {
    201: "Mitigation Planning; Hazard Mitigation Planning and Mitigation Grants",
    204: "Fire Management Assistance Grant Program",
    206: "Federal Disaster Assistance",
}
CFR_DATE = "2026-11-18"


def get(client: httpx.Client, url: str, cache: Path | None = None, **kw) -> str:
    if cache is not None and cache.exists():
        return cache.read_text(encoding="utf-8")
    r = client.get(url, **kw)
    r.raise_for_status()
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(r.text, encoding="utf-8")
    return r.text


# ---------------------------------------------------------------- GAO

def build_gao(client: httpx.Client):
    ids = [ln.strip() for ln in (ROOT / "scripts" / "gao_reports.txt").read_text().splitlines()
           if ln.startswith("GAO-")]
    wanted = set(ids)
    found = {}
    for split in ("valid", "test"):
        text = get(client, f"{HF}/gao_{split}.jsonl", RAW / f"gao_{split}.jsonl", follow_redirects=True, timeout=300)
        for line in text.splitlines():
            row = json.loads(line)
            if row["id"] in wanted:
                found[row["id"]] = row
    missing = wanted - set(found)
    if missing:
        raise SystemExit(f"not found in GovReport: {sorted(missing)}")
    docs, passages = [], []
    for gid in ids:
        d, p = gao_document(found[gid])
        docs.append(d)
        passages += p
    print(f"GAO: {len(docs)} reports, {len(passages)} passages")
    return docs, passages


# ---------------------------------------------------------------- eCFR

def build_cfr(client: httpx.Client):
    docs, passages = [], []
    for part, name in CFR_PARTS.items():
        xml = get(client, f"https://www.ecfr.gov/api/versioner/v1/full/{CFR_DATE}/title-44.xml?part={part}",
                  RAW / f"cfr44_{part}.xml")
        soup = BeautifulSoup(xml, "xml")
        sections = []
        for sub in soup.find_all("DIV6"):
            sub_name = clean(sub.find("HEAD").get_text(" ")) if sub.find("HEAD") else ""
            for sec in sub.find_all("DIV8"):
                head = clean(sec.find("HEAD").get_text(" "))
                paras = [clean(p.get_text(" ")) for p in sec.find_all(["P", "FP"]) if p.get_text(strip=True)]
                if not paras or "[Reserved]" in head:
                    continue
                number = sec.get("N", "")
                link = f"https://www.ecfr.gov/current/title-44/section-{number}"
                sections.append((f"{sub_name} > {head}", paras, link))
        d, p = web_document(
            f"44CFR{part}", "fema", f"44 CFR Part {part}: {name}",
            f"https://www.ecfr.gov/current/title-44/part-{part}", CFR_DATE, "Federal regulation (eCFR)", sections)
        docs.append(d)
        passages += p
    print(f"eCFR: {len(docs)} parts, {len(passages)} passages")
    return docs, passages


# ---------------------------------------------------------------- OpenFEMA catalog

_BOILERPLATE = re.compile(r"\s*(FEMA's terms and conditions|For answers to Frequently Asked Questions|"
                          r"If you have media inquiries).*", re.S)


def build_openfema(client: httpx.Client):
    base = "https://www.fema.gov/api/open/v1"
    sets = client.get(f"{base}/OpenFemaDataSets", params={"$top": 200}).json()["OpenFemaDataSets"]
    fields: dict[str, list[dict]] = {}
    skip = 0
    while True:
        batch = client.get(f"{base}/OpenFemaDataSetFields", params={"$top": 1000, "$skip": skip}).json()
        rows = batch["OpenFemaDataSetFields"]
        for r in rows:
            fields.setdefault(r["openFemaDataSet"], []).append(r)
        if len(rows) < 1000:
            break
        skip += 1000
    docs, passages = [], []
    for ds in sorted(sets, key=lambda d: d["name"]):
        desc = _BOILERPLATE.sub("", ds.get("description") or "").strip()
        if not desc:
            continue
        sections = [("Description", [desc])]
        cols = sorted(fields.get(ds["name"], []), key=lambda f: f.get("sortOrder") or 0)
        if cols:
            lines = [f"{c['name']} ({c['type']}): {clean(c.get('description') or c['title'])}" for c in cols]
            sections.append(("Field definitions", lines))
        url = ds.get("dataDictionary") or ds.get("landingPage") or ds["webService"]
        title = f"OpenFEMA dataset: {ds['title']}"
        d, p = web_document(f"OPENFEMA-{ds['name']}", "fema", title, url,
                            (ds.get("modified") or "")[:10], "OpenFEMA data catalog", sections)
        d["records"] = ds.get("recordCount")
        docs.append(d)
        passages += p
    print(f"OpenFEMA: {len(docs)} datasets, {len(passages)} passages")
    return docs, passages


# ---------------------------------------------------------------- CDC

_DROP_LINES = {"share", "print", "feedback", "email", "facebook", "twitter", "linkedin", "syndicate",
               "on this page", "related pages", "more information", "view all"}


def parse_cdc(html: str):
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text()) if soup.title else ""
    title = re.sub(r"\s*\|\s*(CDC|Overdose Prevention.*)$", "", title).strip()
    main = soup.find("main") or soup
    for tag in main.find_all(["script", "style", "nav", "form", "button", "svg", "figure"]):
        tag.decompose()
    text = main.get_text(" ")
    m = re.search(r"(?:Last Reviewed|Reviewed)\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    date = m.group(1) if m else ""
    sections, heading, buf = [], title or "Overview", []
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        t = clean(el.get_text(" "))
        if not t or t.lower() in _DROP_LINES:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            if buf:
                sections.append((heading, buf))
            heading, buf = t, []
        elif el.name == "li" and el.find_parent(["li"]) is not None:
            continue  # nested list items are already part of their parent's text
        elif len(t) > 25:
            buf.append(t)
    if buf:
        sections.append((heading, buf))
    return title, date, sections


def build_cdc(client: httpx.Client):
    docs, passages = [], []
    for path in CDC_PAGES:
        url = f"https://www.cdc.gov/{path}"
        try:
            html = get(client, url, RAW / "cdc" / path.replace("/", "_"), follow_redirects=True)
        except httpx.HTTPError as err:
            print(f"  skipped {path}: {err}")
            continue
        title, date, sections = parse_cdc(html)
        if sum(len(" ".join(p)) for _, p in sections) < 1200:
            print(f"  skipped {path}: too little text")
            continue
        doc_id = "CDC-" + re.sub(r"[^a-z0-9]+", "-", path.replace(".html", "").replace("/index", "")).strip("-")
        d, p = web_document(doc_id, "cdc", f"CDC: {title}", url, date, "CDC web page", sections)
        docs.append(d)
        passages += p
    print(f"CDC: {len(docs)} pages, {len(passages)} passages")
    return docs, passages


def main() -> int:
    with httpx.Client(headers={"User-Agent": UA}, timeout=60) as client:
        all_docs, all_passages = [], []
        for builder in (build_gao, build_cfr, build_openfema, build_cdc):
            d, p = builder(client)
            all_docs += d
            all_passages += p
    write_corpus(ROOT / "data" / "corpus", all_docs, all_passages)
    print(f"total: {len(all_docs)} documents, {len(all_passages)} passages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
