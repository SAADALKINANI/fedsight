"""Input and output checks that run around every model call.

Input:  PII redaction, prompt-injection screening, length limits.
Output: citation verification, citation coverage, numeric grounding, PII scan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- PII

PII_PATTERNS = {
    "ssn": re.compile(r"\b(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)"),
    "card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def _luhn_ok(digits: str) -> bool:
    nums = [int(d) for d in digits][::-1]
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(nums))
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, list[str]]:
    found = []

    def sub(kind):
        def repl(m):
            if kind == "card" and not _luhn_ok(re.sub(r"\D", "", m.group())):
                return m.group()
            found.append(kind)
            return f"[{kind.upper()} REDACTED]"
        return repl

    for kind in ("card", "ssn", "email", "phone"):
        text = PII_PATTERNS[kind].sub(sub(kind), text)
    return text, found


# ---------------------------------------------------------------- prompt injection

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|your) (instructions|rules)",
    r"(reveal|show|print|repeat|output) (me )?(your|the) (system prompt|instructions|hidden prompt)",
    r"\byou are now\b",
    r"\b(developer|dan|god) mode\b",
    r"\bjailbreak\b",
    r"pretend (you are|to be) (an? )?(unrestricted|different|evil)",
    r"act as (if you have no|an unrestricted)",
    r"new instructions?:",
    r"</?(system|instructions?)>",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def injection_score(text: str) -> tuple[float, list[str]]:
    hits = [p.pattern for p in _INJ if p.search(text)]
    return min(1.0, 0.6 * len(hits)), hits


# ---------------------------------------------------------------- output checks

NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _numbers(text: str) -> set[str]:
    out = set()
    for m in NUM_RE.findall(text):
        n = m.replace("$", "").replace(",", "").rstrip("%").rstrip(".")
        if n and not (len(n) == 1 and n.isdigit()):  # single digits ("3 recommendations") are too noisy to check
            out.add(n)
    return out


@dataclass
class OutputReport:
    citations_total: int = 0
    citations_invalid: int = 0
    coverage: float = 1.0
    unsupported_numbers: list[str] = field(default_factory=list)
    pii_found: list[str] = field(default_factory=list)
    declined: bool = False

    @property
    def status(self) -> str:
        if self.declined:
            return "declined"
        if self.citations_total == 0 or self.citations_invalid:
            return "unsupported"
        if self.unsupported_numbers or self.coverage < 0.6:
            return "partially_supported"
        return "verified"

    def as_dict(self) -> dict:
        return {"status": self.status, "citations_total": self.citations_total,
                "citations_invalid": self.citations_invalid, "coverage": round(self.coverage, 3),
                "unsupported_numbers": self.unsupported_numbers, "pii_found": self.pii_found, "declined": self.declined}


DECLINE_RE = re.compile(r"(couldn'?t|could not|can'?t|cannot|unable to) find|not (covered|available) in the (indexed )?sources"
                        r"|outside (the scope|what)|don'?t have (a source|information)", re.I)


def check_answer(segments: list[dict], source_texts: list[str]) -> OutputReport:
    """segments: [{"text": str, "citations": [{"cited_text": str, ...}]}]
    source_texts: every text block that was given to the model (passages and query results)."""
    rep = OutputReport()
    full = "".join(s["text"] for s in segments)
    rep.declined = bool(DECLINE_RE.search(full)) and sum(len(s.get("citations", [])) for s in segments) == 0
    corpus = _norm(" ".join(source_texts))
    corpus_nums = _numbers(corpus)

    cited_chars = total_chars = 0
    for seg in segments:
        text, cites = seg["text"], seg.get("citations", [])
        substantive = len(text.strip()) >= 25 and not text.strip().startswith("#")
        if substantive:
            total_chars += len(text)
            if cites:
                cited_chars += len(text)
        for c in cites:
            rep.citations_total += 1
            if _norm(c.get("cited_text", "")) not in corpus:
                rep.citations_invalid += 1
        if substantive:
            evidence = " ".join(c.get("cited_text", "") for c in cites) or ""
            ev_nums = _numbers(evidence)
            for n in _numbers(text):
                if n not in ev_nums and n not in corpus_nums:
                    rep.unsupported_numbers.append(n)
    rep.coverage = cited_chars / total_chars if total_chars else 1.0
    _, rep.pii_found = redact_pii(full)
    return rep
