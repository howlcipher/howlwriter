"""Real scholarly research, query planning, and source extraction."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from howlwriter.academic.spec import AssignmentSpec
from howlwriter.domain.source import (
    DEPTH_ABSTRACT,
    DEPTH_METADATA_ONLY,
    FreshnessStatus,
    RELEVANCE_DIRECT,
    RELEVANCE_IRRELEVANT,
    RELEVANCE_SUPPORTING,
    RELEVANCE_TANGENTIAL,
    Source,
    SourceFreshness,
    SourceType,
    source_from_dict,
)

# Keep distinctive technical tokens (e.g. C++, C#, Rust/C++) intact while
# stripping decorative punctuation.
_QUERY_TOKEN_PRESERVE = re.compile(r"[^\w\s\-+#/]")

_QUERY_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "for", "with", "to", "of",
    "in", "on", "at", "from", "by", "as", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "this", "that", "these", "those",
    "we", "our", "you", "your", "i", "me", "my", "he", "she", "they",
    "them", "his", "their", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "shall",
    "can", "need", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "among", "within", "without", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "any", "both", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "now",
})


def _clean_research_query(text: str) -> str:
    """Strips decorative punctuation but keeps language- and code-relevant tokens."""
    normalized = _QUERY_TOKEN_PRESERVE.sub(" ", text)
    collapsed = re.sub(r"\s+", " ", normalized).strip()
    return collapsed


def _extract_concepts(text: str) -> set[str]:
    """Extracts the distinctive content words from a topic or query."""
    text = _clean_research_query(text)
    tokens = re.findall(r"\b\w[\w\-+#/]*\b", text)
    return {
        t.lower()
        for t in tokens
        if len(t) >= 3 and t.lower() not in _QUERY_STOPWORDS
    }


def derive_research_plan(spec: AssignmentSpec, max_queries: int = 6) -> list[str]:
    """Derives a focused, bounded list of research query strings from assignment spec and outline."""
    queries: list[str] = []

    # 1. Core topic query: preserve distinctive language tokens (C++, Rust, etc.)
    clean_base = _clean_research_query(spec.topic.strip().split("\n")[0])
    if clean_base:
        queries.append(clean_base)

    # 2. Outline-derived queries: preserve the base topic's distinctive terms
    #    rather than replacing them with generic section boilerplate.
    generic_sections = {"introduction", "background", "overview"}
    generic_conclusions = {"conclusion", "summary", "future work"}

    for topic in spec.outline:
        topic_clean = _clean_research_query(topic)
        if not topic_clean:
            continue
        lowered = topic_clean.lower()

        if lowered in generic_sections or lowered in generic_conclusions:
            # Generic section names do not add distinctive terms; keep the base query.
            q = clean_base
        else:
            q = f"{clean_base} {topic_clean}"

        if q not in queries:
            queries.append(q)

        if len(queries) >= max_queries:
            break

    return queries


def fetch_arxiv_sources(query: str, max_results: int = 3) -> list[Source]:
    """Fetches real preprint and academic paper metadata directly from arXiv API."""
    encoded_query = urllib.parse.quote_plus(query)
    url = (
        f"https://export.arxiv.org/api/query?search_query=all:{encoded_query}"
        f"&start=0&max_results={max_results}"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HowlWriter/0.1.0 (academic research client)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            data = resp.read().decode("utf-8")
    except Exception:
        return []

    sources: list[Source] = []
    try:
        root = ET.fromstring(data)
        atom_ns = "{http://www.w3.org/2005/Atom}"
        arxiv_ns = "{http://arxiv.org/schemas/atom}"

        for entry in root.findall(f"{atom_ns}entry"):
            title_elem = entry.find(f"{atom_ns}title")
            title = (
                title_elem.text.strip().replace("\n", " ")
                if title_elem is not None and title_elem.text
                else "Untitled arXiv Paper"
            )

            summary_elem = entry.find(f"{atom_ns}summary")
            summary = (
                summary_elem.text.strip().replace("\n", " ")
                if summary_elem is not None and summary_elem.text
                else ""
            )

            published_elem = entry.find(f"{atom_ns}published")
            pub_date = None
            if published_elem is not None and published_elem.text:
                try:
                    pub_date = date.fromisoformat(published_elem.text.split("T")[0])
                except Exception:
                    pass

            authors: list[str] = []
            for author_elem in entry.findall(f"{atom_ns}author"):
                name_elem = author_elem.find(f"{atom_ns}name")
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            link_elem = entry.find(f"{atom_ns}id")
            source_url = (
                link_elem.text.strip()
                if link_elem is not None and link_elem.text
                else None
            )

            doi_elem = entry.find(f"{arxiv_ns}doi")
            doi = (
                doi_elem.text.strip()
                if doi_elem is not None and doi_elem.text
                else None
            )

            src = Source(
                id=f"S{len(sources)+1:03d}",
                title=title,
                authors=authors,
                publisher="arXiv",
                publication_date=pub_date,
                url=source_url,
                doi=doi,
                access_date=date.today(),
                source_type=SourceType.JOURNAL_ARTICLE,
                retrieved_text=summary,
                reliability_notes="Retrieved from arXiv API; peer-review / preprint.",
                evidence_depth=DEPTH_ABSTRACT if summary.strip() else DEPTH_METADATA_ONLY,
                freshness=SourceFreshness(
                    retrieved_at=date.today().isoformat(),
                    published_at=pub_date.isoformat() if pub_date else None,
                    freshness_status=FreshnessStatus.VERSION_UNKNOWN,
                ),
            )
            sources.append(src)
    except Exception:
        pass

    return sources


def fetch_crossref_sources(query: str, max_results: int = 3) -> list[Source]:
    """Fetches real peer-reviewed journal and conference publications from Crossref API."""
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://api.crossref.org/works?query={encoded_query}&rows={max_results}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HowlWriter/0.1.0 (academic research; mailto:howlcipher@example.com)"
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            raw_json = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    sources: list[Source] = []
    items = raw_json.get("message", {}).get("items", [])

    for item in items:
        titles = item.get("title", [])
        title = titles[0] if titles else "Untitled Crossref Work"

        authors: list[str] = []
        for a in item.get("author", []):
            family = a.get("family", "")
            given = a.get("given", "")
            if family and given:
                authors.append(f"{family}, {given}")
            elif family:
                authors.append(family)
            elif a.get("name"):
                authors.append(a.get("name"))

        publisher = item.get("publisher")
        doi = item.get("DOI")
        source_url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)

        # Extract publication year
        pub_date = None
        issued = item.get("issued", {}).get("date-parts", [])
        if issued and issued[0]:
            parts = issued[0]
            year = parts[0]
            month = parts[1] if len(parts) > 1 else 1
            day = parts[2] if len(parts) > 2 else 1
            try:
                pub_date = date(int(year), int(month), int(day))
            except Exception:
                try:
                    pub_date = date(int(year), 1, 1)
                except Exception:
                    pass

        abstract = item.get("abstract", "")
        if abstract:
            # Strip simple XML tags like <jats:p>
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()

        src_type_str = item.get("type", "")
        if "journal" in src_type_str or "article" in src_type_str:
            st = SourceType.JOURNAL_ARTICLE
        elif "book" in src_type_str or "monograph" in src_type_str:
            st = SourceType.BOOK
        elif "report" in src_type_str or "standard" in src_type_str:
            st = SourceType.REPORT
        elif "dataset" in src_type_str:
            st = SourceType.DATASET
        else:
            st = SourceType.OTHER

        if abstract.strip():
            retrieved_text = abstract
            evidence_depth = DEPTH_ABSTRACT
        else:
            retrieved_text = f"Published academic work by {publisher or 'author'}: {title}"
            evidence_depth = DEPTH_METADATA_ONLY

        src = Source(
            id=f"S{len(sources)+1:03d}",
            title=title,
            authors=authors,
            publisher=publisher,
            publication_date=pub_date,
            url=source_url,
            doi=doi,
            access_date=date.today(),
            source_type=st,
            retrieved_text=retrieved_text,
            reliability_notes=f"Retrieved from Crossref API (type: {src_type_str}).",
            evidence_depth=evidence_depth,
            freshness=SourceFreshness(
                retrieved_at=date.today().isoformat(),
                published_at=pub_date.isoformat() if pub_date else None,
                freshness_status=FreshnessStatus.VERSION_UNKNOWN,
            ),
        )
        sources.append(src)

    return sources


def classify_source_relevance(
    source: Source,
    topic: str,
    query: str,
    outline_topic: str = "",
) -> str:
    """Classifies a retrieved source by its topical relevance to the assignment.

    Uses the actual assignment topic, the query it was retrieved with, and the
    outline topic (if any) to guard against one-keyword coincidences.
    """
    # Build the expected concept set from the request context.
    expected = _extract_concepts(topic)
    expected |= _extract_concepts(query)
    if outline_topic:
        expected |= _extract_concepts(outline_topic)

    if not expected:
        # Nothing to compare against; the source is at best supporting.
        return RELEVANCE_SUPPORTING if source.is_substantive_evidence else RELEVANCE_TANGENTIAL

    # Collect concepts present in the source, keeping title and text separate.
    title_concepts = _extract_concepts(source.title or "")
    text_concepts = _extract_concepts(source.retrieved_text or "")
    matches = expected & (title_concepts | text_concepts)
    title_matches = expected & title_concepts

    # One generic overlap is not enough.
    if not matches:
        return RELEVANCE_IRRELEVANT

    # Direct: the source is central to the topic -- the title carries multiple
    # distinctive concepts, or the combined text coverage is extensive.
    if len(title_matches) >= 2 or len(matches) >= 4:
        return RELEVANCE_DIRECT

    # Supporting: some real overlap, but the source is not central enough for
    # primary claims.
    if len(matches) >= 2:
        return RELEVANCE_SUPPORTING

    # A single keyword overlap is normally tangential.
    return RELEVANCE_TANGENTIAL


class AcademicResearcher:
    """Orchestrates truthful academic source retrieval across scholarly APIs and local sources."""

    def __init__(self, existing_sources: list[Source] | None = None) -> None:
        self.existing_sources = list(existing_sources or [])

    def execute_research(
        self,
        spec: AssignmentSpec,
        max_sources_total: int | None = None,
    ) -> list[Source]:
        """Executes research plan for an assignment and returns collected Source objects.

        Sources are classified for relevance and evidence depth as they are
        retrieved. Retrieval stops once the assignment's minimum usable-source
        requirement is met or the total budget is exhausted, whichever comes
        first -- but the returned list still includes any additional collected
        sources so the report can be truthful about what was found.
        """
        minimum_usable = spec.source_requirements.minimum_sources
        if max_sources_total is None:
            # Give a small retrieval budget above the minimum so the result
            # is not arbitrarily capped at exactly the minimum.
            max_sources_total = max(minimum_usable + 4, 10)

        collected: list[Source] = []
        seen_identifiers: set[str] = set()

        def _add_source(s: Source) -> bool:
            # Key for deduplication
            key = (s.doi or s.url or s.title).lower().strip()
            if key in seen_identifiers:
                return False
            seen_identifiers.add(key)
            # Reassign deterministic ID S001, S002, ...
            s.id = f"S{len(collected)+1:03d}"
            collected.append(s)
            return True

        # 1. First include any pre-loaded sources
        for s in self.existing_sources:
            _add_source(s)

        # If caller explicitly provided enough usable sources, do not search.
        if self.existing_sources and sum(1 for s in collected if s.is_usable) >= minimum_usable:
            return collected

        # 2. Derive research queries
        queries = derive_research_plan(spec)
        topic_clean = _clean_research_query(spec.topic.strip().split("\n")[0])

        # 3. Query scholarly APIs for each plan item
        for q in queries:
            usable_so_far = sum(1 for s in collected if s.is_usable)
            if len(collected) >= max_sources_total or usable_so_far >= minimum_usable:
                break

            # Infer the outline topic that produced this query.
            if topic_clean and q.startswith(topic_clean):
                outline_topic = q[len(topic_clean):].strip()
            else:
                outline_topic = q

            # Query Crossref
            try:
                crossref_res = fetch_crossref_sources(q, max_results=3)
                for s in crossref_res:
                    s.relevance = classify_source_relevance(
                        s,
                        topic=spec.topic,
                        query=q,
                        outline_topic=outline_topic,
                    )
                    _add_source(s)
                    if len(collected) >= max_sources_total:
                        break
            except Exception:
                pass

            if len(collected) >= max_sources_total:
                break

            # Query arXiv
            try:
                arxiv_res = fetch_arxiv_sources(q, max_results=3)
                for s in arxiv_res:
                    s.relevance = classify_source_relevance(
                        s,
                        topic=spec.topic,
                        query=q,
                        outline_topic=outline_topic,
                    )
                    _add_source(s)
                    if len(collected) >= max_sources_total:
                        break
            except Exception:
                pass

        return collected


def load_sources_file(path: str | Path) -> list[Source]:
    """Loads a list of Source objects from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Sources file must contain a JSON list, got {type(data).__name__}")
    return [source_from_dict(item) for item in data]


def save_sources_file(path: str | Path, sources: list[Source]) -> None:
    """Saves a list of Source objects to a JSON file."""
    from howlwriter.domain.io import atomic_write_text

    serialized = [s.to_dict() for s in sources]
    atomic_write_text(path, json.dumps(serialized, indent=2))
