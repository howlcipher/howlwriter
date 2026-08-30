# Provenance: SOURCE ↔ EVIDENCE ↔ CLAIM

## Why not just a list of URLs

Appending a list of links after generated writing doesn't answer the
questions that actually matter: which source backs which sentence, whether
a cited source was ever really retrieved, or which claims are still
unsupported. `domain/provenance.py`'s `ProvenanceGraph` exists to answer
those honestly.

## The model

- **`Claim`** (`domain/claim.py`) -- text, type, `verification_status`
  (`SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED,
  UNVERIFIABLE, OPINION, INFERENCE`), confidence, supporting/contradicting
  source ids, and a `document_span` pointing back at the exact paragraph
  and sentence it came from.
- **`Source`** (`domain/source.py`) -- id, title, authors, publisher,
  publication date, url/doi, access date, source type, retrieved text, and
  reliability notes. `Source.was_accessed` is true only when
  `retrieved_text` or `access_date` is actually set -- citing a source by
  id is not the same as having retrieved it.
- **`Evidence`** (`domain/source.py`) -- its own first-class object (not a
  field on `Claim`), linking one source to one claim with a snippet and
  whether it supports or contradicts. Keeping evidence separate is what
  makes the graph queryable in both directions without denormalizing data
  into either `Claim` or `Source`.

## The query methods that answer the spec's own questions

| Question | Method |
| --- | --- |
| Which source supported this sentence? | `sources_for_claim(claim_id)` |
| Which claims depend on this source? | `claims_for_source(source_id)` |
| What evidence supports this claim? | `evidence_for_claim(claim_id)` |
| Which claims remain unsupported? | `unsupported_claims()` |
| Was this source actually accessed? | `unaccessed_sources()` |

`add_evidence()` enforces referential integrity: attaching evidence that
references an unknown claim or source id raises `ValueError` rather than
silently creating a dangling reference.

## How a claim gets there

`facts/extraction.py`'s `HeuristicClaimExtractor` is real, deterministic
code: it flags candidate claims by pattern (a digit or percent sign, or a
statistical-attribution marker like "according to") and returns every one
as `UNVERIFIABLE`. It never guesses `SUPPORTED` -- that requires real
`Evidence` attached through the graph, which requires either a human
supplying sources or a configured `ClaimVerifier`
(`facts/verification.py`, unconfigured by default -- see
[docs/howlplane-integration.md](howlplane-integration.md)).

This is the actual mechanism behind "never invent a statistic merely
because the existing one can't be verified": there is no code path in this
project that marks a claim verified without a real `Evidence` object
behind it.
