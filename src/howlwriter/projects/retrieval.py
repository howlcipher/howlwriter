"""Task-specific evidence retrieval: the few items a section needs, and why.

A small in-process BM25 index over the evidence library (excerpt, location,
file name, structured observation fields). Nothing is embedded remotely and
nothing leaves the machine. Results can be filtered by category, source
type, and evidence status, and are ranked with a purpose-aware prior:

* ``facts``        observations and references first, instructions last;
* ``observations`` only what was actually observed (captures, screenshots,
                   data, lab observations);
* ``requirements`` instructions and rubrics only.

Every hit carries its explanation: the matched terms, its score, and the
prior applied. Instruction text is never returned for ``facts`` unless asked
for, so "the lab says to do X" cannot be retrieved as "X happened".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re

from howlwriter.projects import models as m

_TOKEN = re.compile(r"[a-z0-9][a-z0-9._:-]*[a-z0-9]|[a-z0-9]", re.I)
_STOP = set("""
a an and are as at be by for from has have in is it its of on or that the this to was were will with you your
not no can should must may might also into than then there these those their they them which who what when
where how why all any each other some such only own same so too very just over under about after before
""".split())

PURPOSE_PRIORS = {
    "facts": {
        m.EXPERIMENTAL: 1.3,
        m.SCREENSHOT: 1.3,
        m.PACKET_CAPTURE: 1.4,
        m.REFERENCE: 1.1,
        m.MULTIMEDIA: 1.0,
        m.USER_DRAFT: 0.5,
        m.OUTPUT_DOCUMENT: 0.4,
        m.INSTRUCTIONS: 0.0,
        m.RUBRIC: 0.0,
    },
    "observations": {m.EXPERIMENTAL: 1.0, m.SCREENSHOT: 1.0, m.PACKET_CAPTURE: 1.0},
    "requirements": {m.INSTRUCTIONS: 1.0, m.RUBRIC: 1.0},
}


def terms(text: str) -> list[str]:
    out = []
    for token in _TOKEN.findall(text.lower()):
        token = token.strip("._:-")
        if len(token) < 2 or token in _STOP:
            continue
        out.append(token)
        # "tls1.3" style tokens also match their parts.
        if any(c in token for c in "._:-") and len(token) > 3:
            out += [p for p in re.split(r"[._:-]", token) if len(p) >= 2 and p not in _STOP]
    return out


def _document(item: m.EvidenceItem) -> list[str]:
    observation = {k: v for k, v in item.observation.items() if k not in ("lines", "segments", "box")}
    body = item.observation.get("text") or item.excerpt
    return terms(" ".join([body, item.location, item.source_path, item.kind, str(observation)]))


@dataclass
class Hit:
    item: m.EvidenceItem
    score: float
    matched: list[str]
    prior: float

    def explain(self) -> str:
        return (
            f"matched {', '.join(self.matched[:8])}; BM25 {self.score / max(self.prior, 1e-9):.2f}"
            f" × {self.prior:g} ({self.item.category} prior)"
        )

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.item.evidence_id,
            "citation": self.item.citation,
            "status": self.item.status,
            "category": self.item.category,
            "kind": self.item.kind,
            "excerpt": self.item.excerpt[:400],
            "score": round(self.score, 3),
            "why": self.explain(),
        }


class EvidenceIndex:
    def __init__(self, evidence: dict[str, m.EvidenceItem], k1: float = 1.4, b: float = 0.75) -> None:
        self.items = list(evidence.values())
        self.docs = [Counter(_document(item)) for item in self.items]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.df: Counter = Counter()
        for doc in self.docs:
            self.df.update(doc.keys())
        self.k1, self.b = k1, b

    def search(
        self,
        query: str,
        *,
        purpose: str = "facts",
        limit: int = 8,
        categories=None,
        source_types=None,
        statuses=None,
        include_instructions: bool = False,
    ) -> list[Hit]:
        wanted = list(dict.fromkeys(terms(query)))
        priors = PURPOSE_PRIORS.get(purpose, {})
        n = len(self.items)
        hits: list[Hit] = []
        for item, doc, length in zip(self.items, self.docs, self.lengths):
            if categories and item.category not in categories:
                continue
            if source_types and item.source_type not in source_types:
                continue
            if statuses and item.status not in statuses:
                continue
            if purpose == "observations":
                from howlwriter.projects.requirements import is_observation

                if not is_observation(item):
                    continue
            prior = priors.get(item.category, 1.0 if purpose != "requirements" else 0.0)
            if item.source_type == "browser":
                prior = 1.2 if purpose != "requirements" else 0.0
            if item.category in m.REQUIREMENT_CATEGORIES and purpose == "facts" and include_instructions:
                prior = 0.6
            if prior <= 0:
                continue
            score = 0.0
            matched = []
            for term in wanted:
                tf = doc.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                score += (
                    idf
                    * tf
                    * (self.k1 + 1)
                    / (tf + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
                )
                matched.append(term)
            if score > 0:
                hits.append(Hit(item, score * prior, matched, prior))
        hits.sort(key=lambda h: (-h.score, h.item.evidence_id))
        # One source should not crowd out the rest: at most 3 hits per source.
        per_source: Counter = Counter()
        out = []
        for hit in hits:
            if per_source[hit.item.source_id] >= 3:
                continue
            per_source[hit.item.source_id] += 1
            out.append(hit)
            if len(out) >= limit:
                break
        return out
