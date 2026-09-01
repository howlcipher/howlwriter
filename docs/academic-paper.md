# Academic Paper & Assignment Writing

HowlWriter provides an end-to-end researched academic paper writing and verification pipeline designed to enforce rigorous academic standards, honest provenance, and strict factual grounding.

## Overview

The academic writing workflow is driven by a typed assignment specification (`assignment.yaml`):

```bash
howlwriter paper assignment.yaml --out paper.md
```

### Philosophy & Critical Invariants

1. **Model Memory is Not a Retrieved Source**:
   The engine only permits citations referencing sources that were actually retrieved or provided. Factual claims must be backed by real evidence snippets in the `ProvenanceGraph`.
2. **Deterministic Word Counting**:
   Word counts are calculated deterministically in code on the paper body, excluding front matter and the References section. Bounded length correction passes adjust thin or bloated sections without fabricating facts or altering outline structure.
3. **Outline Conformance**:
   The supplied outline is treated as a hard requirement. The engine deterministically checks that all required topics and sections are represented.
4. **Citation ↔ Reference Consistency**:
   APA 7 in-text citations and reference list entries are generated deterministically from the same `Source` objects.
5. **No Fake Readiness**:
   If body words fall below the minimum, or exceed an explicit **hard** length ceiling (`length_constraints.max_words`/`max_pages`), required outline sections are missing, or unsupported/contradicted claims exist, the document is flagged with status `NEEDS_REVIEW` instead of `READY`. Falling outside the *soft* preferred target range (`target_words`/`word_tolerance_percent`, or `target_page_min`/`target_page_max`) while still under any hard ceiling is reported as word-count status `TARGET_MISS` -- a quality signal that triggers a tightening/expansion correction attempt, but does not by itself force `NEEDS_REVIEW`. Only a below-minimum or hard-ceiling breach (`HARD_LIMIT_FAILURE`) is a length-driven blocker; see `academic/length.py`'s `evaluate_word_count_bounds`.

---

## Assignment Specification Format

An assignment is specified in YAML or JSON:

```yaml
title: Zero Trust and Autonomous AI Agents
type: academic
topic: >
  Examine how autonomous AI agents complicate identity, authorization,
  and access control in enterprise environments.
target_words: 2000
word_tolerance_percent: 10
citation_style: apa7
source_requirements:
  minimum_sources: 6
  prefer_primary_sources: true
  scholarly_or_authoritative: true
requirements:
  - Support factual claims with citations
  - Do not fabricate sources
  - Include an APA 7 reference page
  - Discuss both security risks and possible controls
outline:
  - Introduction
  - Identity challenges for autonomous agents
  - Delegated authorization
  - Excessive and stale permissions
  - Security controls
  - Conclusion
```

`requirements` is free text, but each item is automatically classified into one of four kinds and routed to the validator best suited to check it, rather than every item being scored by the same content-word-overlap coverage check:

| Kind | Example | Validated by |
| --- | --- | --- |
| Positive content | "Discuss both security risks and possible controls" | Requirements coverage (word overlap) |
| Prohibition | "Do not invent exact technical identifiers..." | Identifier grounding (for the identifier-fabrication sub-type); other prohibitions are reported as present but not automatically validated |
| Length | "Maximum 10 pages" | Length evaluation (`word_count_status`) |
| Style/output | "Keep the paper concise; avoid padding" | Redundancy detection |

An optional `known_identifiers: [...]` field lists exact technical identifiers (CVE IDs, ATT&CK technique IDs, etc.) known to be legitimate for the assignment, so the identifier-grounding check accepts them even if no retrieved source happens to quote them verbatim.

---

## The Academic Pipeline

```
ASSIGNMENT SPEC
      │
      ▼
RESEARCH PLAN & RETRIEVAL (Crossref / arXiv / local sources)
      │
      ▼
STRUCTURED DRAFTING (Writer role grounded in retrieved sources)
      │
      ▼
LENGTH EVALUATION & CORRECTION (Bounded retries)
      │
      ▼
OUTLINE CONFORMANCE CHECK
      │
      ▼
CLAIM VERIFICATION & PROVENANCE GRAPH (Source ↔ Evidence ↔ Claim)
      │
      ▼
HUMANIZATION (Academic tone preservation)
      │
      ▼
DETERMINISTIC LINTING & RED PEN CRITIQUE
      │
      ▼
INDEPENDENT SEMANTIC REVIEW
      │
      ▼
APA 7 REFERENCES GENERATION & ATTACHMENT
      │
      ▼
WRITING REPORT & RUN RECORD DIAGNOSTICS
```

---

## CLI Usage

### 1. Generating an Academic Paper

```bash
howlwriter paper assignment.yaml --out paper.md
```

Options:
- `--out <path>`: Destination markdown file path.
- `--config <path>`: Optional project config path.
- `--sources <sources.json>`: Pre-collected sources to use for offline or deterministic runs.
- `--deterministic`: Runs without model provider invocations.
- `--save-artifacts`: Emits auxiliary `<out>.sources.json` and `<out>.report.json` files.

### 2. Drafting Prose Directly

```bash
howlwriter writer "Examine zero-trust identity for autonomous agents" --target-words 1000 --out draft.md
```

### 3. Researching Scholarly Sources

```bash
howlwriter research "zero trust autonomous AI agents" --max-sources 5 --out sources.json
```
