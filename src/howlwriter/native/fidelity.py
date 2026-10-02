"""Deterministic factual fidelity: numbers stay bound to what they count.

A rewrite can keep every digit and still change the claim. "25 of 28
repositories" and "25/28 deployment paths" share both numbers, so a
bare-number comparison passes them, yet they count different things.
This module extracts each quantity together with the noun it counts and
the qualifiers around it, then compares a proposed rewrite against the
canonical source text it was written from.

Statuses, from least to most severe:

* ``FACTUALLY_PRESERVED``: every quantity in the proposal is present in
  the source with the same unit, and no scope qualifier or unsupported
  upgrade was found.
* ``FACTUAL_REVIEW_REQUIRED``: the proposal may be accurate, but a human
  has to confirm it (a dropped scope qualifier, a derived percentage, a
  number whose unit could not be determined, an ownership verb the
  source does not use).
* ``FACTUAL_UNIT_DRIFT``: a number in the proposal also appears in the
  source but counts something else.
* ``FACTUAL_CONFLICT``: the proposal asserts a number, version, technology,
  scope or outcome the source does not support.

The checker never decides a claim is true. It only reports whether the
proposal says more than, or something other than, its source.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Iterable, Literal

FactualStatus = Literal[
    "FACTUALLY_PRESERVED",
    "FACTUAL_REVIEW_REQUIRED",
    "FACTUAL_UNIT_DRIFT",
    "FACTUAL_CONFLICT",
]

STATUS_ORDER: tuple[FactualStatus, ...] = (
    "FACTUALLY_PRESERVED",
    "FACTUAL_REVIEW_REQUIRED",
    "FACTUAL_UNIT_DRIFT",
    "FACTUAL_CONFLICT",
)

QuantityKind = Literal["count", "ratio", "percent", "range", "version", "year"]

# Words that end a noun phrase after a number. The head noun is the last
# word before one of these.
_PHRASE_STOP = frozenset({
    "across", "for", "in", "into", "with", "and", "or", "of", "on", "to",
    "from", "by", "at", "per", "within", "over", "under", "that", "which",
    "were", "was", "are", "is", "be", "been", "being", "had", "has", "have",
    "while", "where", "when", "using", "via", "after", "before", "during",
    "including", "covering", "spanning", "remaining", "than", "as",
    # Verbs that follow a bare count ("27 passed") name an outcome, not a unit.
    "passed", "failed", "succeeded", "completed", "validated", "executed",
    "remained", "ran", "blocked", "identified", "processed", "scanned",
    "without", "between", "among", "against", "through", "toward", "towards",
    "because", "so", "but", "if", "then", "while", "whereas", "since", "until",
})
# Words that never name what a number counts.
_NOT_A_UNIT = frozenset({
    "the", "a", "an", "all", "each", "every", "total", "approximately",
    "about", "roughly", "nearly", "over", "more", "less", "than", "distinct",
    "standardized", "representative", "measured", "internal", "unique",
    "separate", "individual", "additional", "other", "new", "existing",
})
_MAX_PHRASE_WORDS = 5

# Technologies whose trailing number is a version, not a metric.
_VERSIONED_TECH = (
    r"\.net(?:\s+core)?", r"net", r"python", r"go", r"golang", r"java",
    r"node(?:\.js)?", r"c#", r"php", r"ruby", r"rails", r"angular", r"vue",
    r"react", r"django", r"windows", r"windows\s+server", r"sql\s+server",
    r"ubuntu", r"debian", r"rhel", r"fedora", r"postgres(?:ql)?", r"mysql",
    r"kotlin", r"swift", r"scala", r"perl", r"typescript", r"ecmascript",
    r"es", r"html", r"css", r"http", r"tls", r"oauth", r"iis", r"version",
    r"v",
)
_VERSION_RE = re.compile(
    r"(?<![\w.])(?P<tech>" + "|".join(_VERSIONED_TECH) + r")\s?(?P<ver>\d+(?:\.\d+)*)\b",
    re.IGNORECASE,
)
_DOTTED_VERSION_RE = re.compile(r"(?<![\w.])v?\d+\.\d+\.\d+(?:[-+.\w]*)?\b")

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_RATIO_RE = re.compile(
    rf"(?<![\w.])(?P<a>{_NUM})\s*(?:/|\bof\b|\bout\s+of\b)\s*(?P<b>{_NUM})(?!\w|\.\d)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(rf"(?<![\w.])(?P<a>{_NUM})\s*(?:%|percent\b)", re.IGNORECASE)
_RANGE_RE = re.compile(
    rf"(?<![\w.])(?P<a>{_NUM})\s*(?:-|\u2013|\u2014|\bto\b)\s*(?P<b>{_NUM})(?!\w|\.\d)",
    re.IGNORECASE,
)
_HYPHEN_UNIT_RE = re.compile(rf"(?<![\w.])(?P<a>{_NUM})-(?P<unit>[a-z][a-z/]+)", re.IGNORECASE)
_COUNT_RE = re.compile(rf"(?<![\w.]){_NUM}(?!\w|\.\d)")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z/\-']*|[,.;:()]")

# Scope qualifiers. Dropping one turns a narrower claim into a broader one.
SCOPE_QUALIFIERS: dict[str, tuple[str, ...]] = {
    "dry-run": (r"dry[- ]?runs?",),
    "representative": (r"representative",),
    "proof of concept": (r"proofs? of concept", r"\bpocs?\b", r"prototype[sd]?"),
    "investigation": (r"investigat\w*", r"evaluat\w*", r"explor\w*"),
    "pilot": (r"pilot(?:ed|s)?",),
    "approximately": (r"approximately", r"\babout\b", r"\broughly\b", r"~\s?\d"),
    "partial": (r"partial(?:ly)?", r"in progress", r"ongoing"),
    "shared": (r"\bteam\b", r"\bshared\b", r"\bco-\w+", r"collaborat\w*", r"contributed"),
    "independent": (r"independent", r"personal", r"open[- ]source", r"side project"),
}
_QUALIFIER_RES = {
    name: re.compile("|".join(patterns), re.IGNORECASE)
    for name, patterns in SCOPE_QUALIFIERS.items()
}
# Qualifiers whose loss can silently upgrade the claim's scope.
_CRITICAL_QUALIFIERS = frozenset({
    "dry-run", "representative", "proof of concept", "investigation", "pilot", "partial",
    "shared", "independent",
})

# Upgrades: a term in the proposal that the source must support. Each entry
# is (finding code, proposal pattern, source patterns that license it,
# severity when unlicensed).
_UPGRADES: tuple[tuple[str, str, tuple[str, ...], FactualStatus], ...] = (
    ("production_claim", r"\bproduction\b", (r"\bproduction\b",), "FACTUAL_CONFLICT"),
    ("completed_migration", r"\bmigrat(?:ed|ion|ions)\b", (r"\bmigrat\w*",), "FACTUAL_CONFLICT"),
    ("sole_ownership", r"\b(?:sole(?:ly)?|single-handedly|alone|personally owned)\b",
     (r"\bsole(?:ly)?\b", r"single-handedly"), "FACTUAL_CONFLICT"),
    ("leadership_claim", r"\b(?:led|lead|leading|headed|managed a team|spearheaded|directed)\b",
     (r"\b(?:led|lead|leading|headed|spearheaded|directed|managed)\b",),
     "FACTUAL_REVIEW_REQUIRED"),
    ("ownership_claim", r"\b(?:owned|owner|ownership|architected)\b",
     (r"\b(?:own(?:ed|er|ership)?|architect\w*)\b",), "FACTUAL_REVIEW_REQUIRED"),
    ("adoption_claim",
     r"\b(?:users?|adopt(?:ed|ion)|customers?|engineers use|teams use|used by)\b",
     (r"\b(?:users?|adopt\w*|customers?|used by|teams use|engineers use)\b",),
     "FACTUAL_CONFLICT"),
    ("financial_claim", r"(?:\$\s?\d|\brevenue\b|\broi\b|\bcost savings?\b|\bsaved\b)",
     (r"\$\s?\d", r"\brevenue\b", r"\broi\b", r"\bcost savings?\b", r"\bsaved\b"),
     "FACTUAL_CONFLICT"),
    ("technology_kubernetes", r"\b(?:kubernetes|k8s|aks|eks|gke|helm)\b",
     (r"\b(?:kubernetes|k8s|aks|eks|gke|helm)\b",), "FACTUAL_CONFLICT"),
    ("technology_terraform", r"\b(?:terraform|bicep|pulumi|cloudformation)\b",
     (r"\b(?:terraform|bicep|pulumi|cloudformation)\b",), "FACTUAL_CONFLICT"),
    ("technology_aws", r"\b(?:aws|amazon web services)\b", (r"\b(?:aws|amazon web services)\b",),
     "FACTUAL_CONFLICT"),
    ("technology_gcp", r"\b(?:gcp|google cloud)\b", (r"\b(?:gcp|google cloud)\b",),
     "FACTUAL_CONFLICT"),
)
# A dropped scope qualifier plus completion language is a scope upgrade, not
# a compression: "dry-run validated" becoming "deployed to production".
_SCOPE_UPGRADES: dict[str, str] = {
    "dry-run": r"\b(?:production|live|released|shipped|deployed)\b",
    "proof of concept": r"\b(?:production|shipped|launched|released|in use)\b",
    "investigation": r"\b(?:migrated|completed|implemented|delivered|rolled out|replaced)\b",
    "pilot": r"\b(?:organization-wide|company-wide|across all|rolled out)\b",
    "shared": r"\b(?:sole(?:ly)?|single-handedly|independently|alone)\b",
    "partial": r"\b(?:completed|finished|fully)\b",
}
# "Azure" on its own reads as Azure cloud ownership. It is supported only by
# a source that mentions Azure other than as part of "Azure DevOps".
_AZURE_CLOUD_RE = re.compile(r"\bazure\b(?!\s+devops)", re.IGNORECASE)


@dataclass(frozen=True)
class Quantity:
    """A number together with what it counts."""

    kind: QuantityKind
    value: str
    unit: str | None
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FidelityFinding:
    code: str
    status: FactualStatus
    message: str
    proposal_fragment: str = ""
    source_fragment: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FidelityResult:
    status: FactualStatus
    findings: list[FidelityFinding] = field(default_factory=list)
    proposal_quantities: list[Quantity] = field(default_factory=list)
    source_quantities: list[Quantity] = field(default_factory=list)
    omitted_quantities: list[Quantity] = field(default_factory=list)

    @property
    def factual_change(self) -> bool:
        return self.status != "FACTUALLY_PRESERVED"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "factual_change": self.factual_change,
            "findings": [finding.to_dict() for finding in self.findings],
            "proposal_quantities": [q.to_dict() for q in self.proposal_quantities],
            "omitted_quantities": [q.to_dict() for q in self.omitted_quantities],
        }


def worst_status(statuses: Iterable[FactualStatus]) -> FactualStatus:
    worst: FactualStatus = "FACTUALLY_PRESERVED"
    for status in statuses:
        if STATUS_ORDER.index(status) > STATUS_ORDER.index(worst):
            worst = status
    return worst


def _normalize_number(value: str) -> str:
    return value.replace(",", "")


def _lemma(word: str) -> str:
    word = word.lower().strip("'")
    if "/" in word:
        return "/".join(_lemma(part) for part in word.split("/"))
    for suffix, replacement in (("ies", "y"), ("ses", "s"), ("xes", "x")):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)] + replacement
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _is_plural(word: str) -> bool:
    last = word.split("/")[-1]
    return (
        len(last) > 3 and last.endswith("s")
        and not last.endswith(("ss", "us", "is", "ics"))
    )


def _phrase_after(text: str, end: int) -> str | None:
    """Head noun of the phrase that follows a number, if any."""
    words: list[str] = []
    for match in _WORD_RE.finditer(text[end:end + 120]):
        token = match.group(0)
        lower = token.lower()
        if token in ",.;:()" or lower in _PHRASE_STOP:
            break
        words.append(lower)
        if len(words) >= _MAX_PHRASE_WORDS:
            break
    candidates = [word for word in words if word not in _NOT_A_UNIT]
    if not candidates:
        return None
    # The counted noun is normally the first plural in the phrase ("legacy
    # server racks"), which keeps trailing words from being read as the unit.
    for word in candidates:
        if _is_plural(word):
            return _lemma(word)
    return _lemma(candidates[-1])


def _phrase_before(text: str, start: int) -> str | None:
    """Head noun of the phrase a trailing number qualifies ("paths for 25 of 28")."""
    tokens = [m.group(0).lower() for m in _WORD_RE.finditer(text[max(0, start - 120):start])]
    # Allow a single preposition between the noun phrase and the number.
    if tokens and tokens[-1] in {"for", "across", "in", "on", "of"}:
        tokens = tokens[:-1]
    else:
        return None
    if not tokens or tokens[-1] in ",.;:()" or tokens[-1] in _PHRASE_STOP:
        return None
    head = tokens[-1]
    return None if head in _NOT_A_UNIT else _lemma(head)


def extract_quantities(text: str) -> list[Quantity]:
    """Every quantity in ``text`` with the noun it counts, left to right."""
    found: list[tuple[int, int, Quantity]] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in taken)

    def add(start: int, end: int, quantity: Quantity) -> None:
        taken.append((start, end))
        found.append((start, end, quantity))

    for match in _DOTTED_VERSION_RE.finditer(text):
        add(match.start(), match.end(), Quantity("version", match.group(0).lower(), None, match.group(0)))
    for match in _VERSION_RE.finditer(text):
        start, end = match.start("ver"), match.end("ver")
        if free(start, end):
            tech = re.sub(r"\s+", " ", match.group("tech").lower())
            add(start, end, Quantity("version", f"{tech} {match.group('ver')}", None, match.group(0)))
    for match in _PERCENT_RE.finditer(text):
        if free(match.start(), match.end()):
            value = _normalize_number(match.group("a"))
            add(match.start(), match.end(), Quantity("percent", value, "percent", match.group(0)))
    for match in _RATIO_RE.finditer(text):
        if free(match.start(), match.end()):
            value = f"{_normalize_number(match.group('a'))}/{_normalize_number(match.group('b'))}"
            unit = _phrase_after(text, match.end()) or _phrase_before(text, match.start())
            add(match.start(), match.end(), Quantity("ratio", value, unit, match.group(0)))
    for match in _RANGE_RE.finditer(text):
        if free(match.start(), match.end()):
            value = f"{_normalize_number(match.group('a'))}-{_normalize_number(match.group('b'))}"
            unit = _phrase_after(text, match.end())
            add(match.start(), match.end(), Quantity("range", value, unit, match.group(0)))
    for match in _HYPHEN_UNIT_RE.finditer(text):
        if free(match.start(), match.end()):
            value = _normalize_number(match.group("a"))
            add(match.start(), match.end(),
                Quantity("count", value, _lemma(match.group("unit")), match.group(0)))
    for match in _COUNT_RE.finditer(text):
        if free(match.start(), match.end()):
            value = _normalize_number(match.group(0))
            if _YEAR_RE.match(value):
                add(match.start(), match.end(), Quantity("year", value, None, match.group(0)))
                continue
            unit = _phrase_after(text, match.end()) or _phrase_before(text, match.start())
            add(match.start(), match.end(), Quantity("count", value, unit, match.group(0)))
    found.sort(key=lambda item: item[0])
    return [quantity for _, _, quantity in found]


def qualifiers_in(text: str) -> set[str]:
    return {name for name, pattern in _QUALIFIER_RES.items() if pattern.search(text)}


def _same_unit(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    if left == right:
        return True
    left_parts, right_parts = set(left.split("/")), set(right.split("/"))
    return bool(left_parts & right_parts)


def _ratio_percent(value: str) -> float | None:
    numerator, denominator = (float(part) for part in value.split("/"))
    return None if denominator == 0 else numerator / denominator * 100


def compare(source: str, proposal: str, *, evidence: Iterable[str] = ()) -> FidelityResult:
    """Compare a proposal against its source copy and canonical evidence.

    ``source`` is the copy being rewritten. ``evidence`` is additional
    canonical text that may license a quantity or term the source copy did
    not state. Qualifier loss is judged against ``source`` only, because a
    rewrite is answerable for the scope of the copy it replaced.
    """
    evidence_text = "\n".join(evidence)
    licensed_text = f"{source}\n{evidence_text}"
    source_quantities = extract_quantities(licensed_text)
    proposal_quantities = extract_quantities(proposal)
    findings: list[FidelityFinding] = []

    for quantity in proposal_quantities:
        same_value = [q for q in source_quantities if q.kind == quantity.kind and q.value == quantity.value]
        if quantity.kind == "version":
            if not same_value:
                findings.append(FidelityFinding(
                    "version_unsupported", "FACTUAL_CONFLICT",
                    f'Version "{quantity.text}" is not in the source.', quantity.text,
                ))
            continue
        if quantity.kind == "year":
            if not same_value:
                findings.append(FidelityFinding(
                    "date_unsupported", "FACTUAL_CONFLICT",
                    f'Year "{quantity.value}" is not in the source.', quantity.text,
                ))
            continue
        if quantity.kind == "percent" and not same_value:
            derived = [
                q for q in source_quantities
                if q.kind == "ratio" and _ratio_percent(q.value) is not None
                and abs(_ratio_percent(q.value) - float(quantity.value)) < 1.0
            ]
            if derived:
                findings.append(FidelityFinding(
                    "derived_percentage", "FACTUAL_REVIEW_REQUIRED",
                    f'"{quantity.text}" is derived from "{derived[0].text}"; '
                    "confirm the percentage keeps the ratio's meaning.",
                    quantity.text, derived[0].text,
                ))
                continue
        if not same_value:
            if quantity.kind == "ratio":
                parts = quantity.value.split("/")
                counts = {q.value for q in source_quantities if q.kind == "count"}
                if parts[0] in counts and parts[1] in counts:
                    findings.append(FidelityFinding(
                        "derived_ratio", "FACTUAL_REVIEW_REQUIRED",
                        f'"{quantity.text}" combines two source counts into a ratio; '
                        "confirm both numbers count the same population.", quantity.text,
                    ))
                    continue
                numerator = quantity.value.split("/")[0]
                denominator = quantity.value.split("/")[1]
                changed = [
                    q for q in source_quantities
                    if q.kind == "ratio" and q.value.split("/")[0] == numerator
                ]
                if changed and all(q.value.split("/")[1] != denominator for q in changed):
                    findings.append(FidelityFinding(
                        "denominator_changed", "FACTUAL_CONFLICT",
                        f'"{quantity.text}" changes the denominator of "{changed[0].text}".',
                        quantity.text, changed[0].text,
                    ))
                    continue
            findings.append(FidelityFinding(
                "number_unsupported", "FACTUAL_CONFLICT",
                f'"{quantity.text}" does not appear in the source.', quantity.text,
            ))
            continue
        if quantity.unit is None:
            if any(q.unit for q in same_value):
                findings.append(FidelityFinding(
                    "unit_dropped", "FACTUAL_REVIEW_REQUIRED",
                    f'"{quantity.text}" no longer says what it counts '
                    f'(source: {same_value[0].unit}).',
                    quantity.text, same_value[0].text,
                ))
            continue
        if any(_same_unit(quantity.unit, q.unit) for q in same_value):
            continue
        source_units = sorted({q.unit for q in same_value if q.unit})
        if source_units:
            findings.append(FidelityFinding(
                "FACTUAL_UNIT_DRIFT", "FACTUAL_UNIT_DRIFT",
                f'"{quantity.text}" counts {quantity.unit}, but the source counts '
                f"{' / '.join(source_units)} for that number.",
                quantity.text, same_value[0].text,
            ))
        else:
            findings.append(FidelityFinding(
                "unit_unverifiable", "FACTUAL_REVIEW_REQUIRED",
                f'"{quantity.text}" counts {quantity.unit}; the source does not say what '
                "that number counts.", quantity.text, same_value[0].text,
            ))

    source_qualifiers = qualifiers_in(source)
    proposal_qualifiers = qualifiers_in(proposal)
    licensed_qualifiers = qualifiers_in(licensed_text)
    for name in sorted(source_qualifiers - proposal_qualifiers):
        if name not in _CRITICAL_QUALIFIERS:
            continue
        upgrade = _SCOPE_UPGRADES.get(name)
        hit = re.search(upgrade, proposal, re.IGNORECASE) if upgrade else None
        if hit:
            findings.append(FidelityFinding(
                "scope_upgraded", "FACTUAL_CONFLICT",
                f'Scope qualifier "{name}" was dropped and "{hit.group(0)}" now '
                "states a broader outcome than the source.", hit.group(0),
            ))
        else:
            findings.append(FidelityFinding(
                "qualifier_removed", "FACTUAL_REVIEW_REQUIRED",
                f'Scope qualifier "{name}" was dropped; the claim may now read broader.',
            ))
    for name in sorted(proposal_qualifiers - licensed_qualifiers):
        if name in {"shared", "independent"}:
            findings.append(FidelityFinding(
                "provenance_unsupported", "FACTUAL_REVIEW_REQUIRED",
                f'Provenance qualifier "{name}" is not supported by the source.',
            ))

    lowered_source = licensed_text.lower()
    lowered_proposal = proposal.lower()
    for code, pattern, licences, severity in _UPGRADES:
        hit = re.search(pattern, lowered_proposal)
        if hit and not any(re.search(licence, lowered_source) for licence in licences):
            findings.append(FidelityFinding(
                code, severity,
                f'"{hit.group(0)}" is not supported by the source.', hit.group(0),
            ))
    if _AZURE_CLOUD_RE.search(proposal) and not _AZURE_CLOUD_RE.search(licensed_text):
        findings.append(FidelityFinding(
            "azure_devops_to_azure_cloud", "FACTUAL_CONFLICT",
            'Proposal names "Azure" without "DevOps"; the source supports Azure DevOps only.',
            "Azure",
        ))

    proposal_keys = {(q.kind, q.value) for q in proposal_quantities}
    own_source = extract_quantities(source)
    omitted = [q for q in own_source if (q.kind, q.value) not in proposal_keys]
    return FidelityResult(
        status=worst_status(finding.status for finding in findings),
        findings=findings,
        proposal_quantities=proposal_quantities,
        source_quantities=source_quantities,
        omitted_quantities=omitted,
    )
