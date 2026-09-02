"""The guard that keeps corpus text out of the profile.

A model asked to describe someone's style will, if left alone, reach for
evidence: "they often open with 'I've spent the last decade...'". That single
habit would turn a distribution into a stencil -- every generated post would
start the same way -- and it would put the user's actual sentences into a file
that gets loaded into prompts.

So every string a model returns is checked against the text it analyzed
before anything is stored. Shared word sequences above a threshold mean the
model quoted rather than described, and the field is dropped.

The threshold has to tolerate the unavoidable. "production system", "incident
response", and "the results suggest" will appear in both the source and any
honest description of it; rejecting those would reject every useful trait. So
the test is a run of consecutive words long enough that its appearance is not
coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

_WORD = re.compile(r"[a-z0-9']+")

#: A shared run this long is a quotation, not shared vocabulary. Six words
#: comfortably clears stock technical phrasing while catching a copied clause.
MAX_SHARED_RUN = 6

#: Warning recorded when a field is dropped. Surfaced in the build record so
#: a user can see that a model misbehaved, without the passage itself being
#: written anywhere.
MODEL_TRAIT_LITERAL_LEAKAGE = "MODEL_TRAIT_LITERAL_LEAKAGE"

#: Trait values are short labels. Anything much longer is prose, which is
#: itself a signal the model ignored the schema.
MAX_TRAIT_VALUE_WORDS = 12


@dataclass
class LeakageFinding:
    field_name: str
    shared_words: int
    reason: str


@dataclass
class LeakageReport:
    findings: list[LeakageFinding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    def warnings(self) -> list[str]:
        """Warnings safe to persist: field names and lengths, never the text."""
        return [
            f"{MODEL_TRAIT_LITERAL_LEAKAGE}: dropped '{f.field_name}' ({f.reason})"
            for f in self.findings
        ]


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def longest_shared_run(candidate: str, source: str) -> int:
    """Length of the longest run of consecutive words shared with the source.

    Implemented as a rolling set membership test rather than a full LCS: the
    question is only "did this appear verbatim", and the corpus side can be
    large enough that an O(n*m) table is not worth building.
    """
    candidate_words = _tokens(candidate)
    if not candidate_words:
        return 0
    source_words = _tokens(source)
    if not source_words:
        return 0

    limit = min(len(candidate_words), MAX_SHARED_RUN + 4)
    source_runs: dict[int, set[str]] = {}
    for length in range(2, limit + 1):
        source_runs[length] = {
            " ".join(source_words[i:i + length])
            for i in range(len(source_words) - length + 1)
        }

    best = 0
    for length in range(2, limit + 1):
        window = source_runs.get(length) or set()
        if not window:
            break
        found = any(
            " ".join(candidate_words[i:i + length]) in window
            for i in range(len(candidate_words) - length + 1)
        )
        if found:
            best = length
        else:
            break
    return best


def check_field(name: str, value: str, source: str) -> LeakageFinding | None:
    """Return a finding when a model-returned field must not be persisted."""
    if not isinstance(value, str) or not value.strip():
        return None

    words = _tokens(value)
    if len(words) > MAX_TRAIT_VALUE_WORDS:
        return LeakageFinding(
            field_name=name,
            shared_words=0,
            reason=(
                f"value is {len(words)} words; trait values must be short labels, "
                f"not prose (max {MAX_TRAIT_VALUE_WORDS})"
            ),
        )

    run = longest_shared_run(value, source)
    if run >= MAX_SHARED_RUN:
        return LeakageFinding(
            field_name=name,
            shared_words=run,
            reason=f"shares a {run}-word run with the analyzed text",
        )
    return None


def scrub(traits: dict[str, str], source: str) -> tuple[dict[str, str], LeakageReport]:
    """Drop every model-returned field that quotes the source.

    Returns the surviving traits and a report. The dropped values are not
    included in the report and are not returned anywhere -- a leaked passage
    must not travel further just because it was detected.
    """
    report = LeakageReport()
    kept: dict[str, str] = {}
    for name, value in traits.items():
        finding = check_field(name, str(value), source)
        if finding is not None:
            report.findings.append(finding)
            continue
        kept[name] = value
    return kept, report
