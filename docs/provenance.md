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

---

# Generation provenance: what ran, what it was told, what it added

The graph above answers *which source backs which sentence*. It cannot answer
the question someone asks when they are about to put their name on a piece of
writing: what was this system told, by whom, and what did it add that I did
not. That is a different record, in `domain/generation_provenance.py`.

## Captured, not reconstructed

Every model call in HowlWriter passes through one method,
`HowlPlaneWritingBridge.execute_writing_role`, which holds the only
`dispatcher.execute` call in the codebase. The recorder is instrumented there,
so the prompt in the record is the string the provider received, in the same
call that produced the response.

This is the whole basis for calling the record exact. A provenance file
assembled afterwards by re-rendering "the prompt that would have been sent" is
a reconstruction: it drifts the moment a prompt builder changes, and it drifts
silently. There is no second prompt builder here to drift away from the first.

## Unavailable is not absent

HowlPlane returns `model` as an optional field and returns no token usage or
request id at all.

- A provider that did not report its model is recorded as
  `model_status: PROVIDER_DID_NOT_REPORT`. The provider's own name is not
  substituted -- `agy` is a CLI, not a model, and putting it where a model
  belongs would be a fabrication with an audit trail.
- Token usage stays `null` rather than becoming `0`. "Not reported" and "none
  used" are different facts.

## Levels, and what each keeps

`--provenance-level summary` records roles, providers, models, durations,
independence, and the SHA-256 and character length of every prompt and
response. `--provenance-level full` additionally records the exact prompt text.

Hashes survive at both levels, so a summary record can be checked against a
full one taken from the same run. Credentials are stripped from captured text
at both levels before anything is written.

## What the hashes do and do not establish

They establish that the recorded artifact is the one the record describes and
that it has not changed since. They establish nothing about who wrote it. No
hash here is evidence of human authorship and none should ever be presented as
such.

## Origin granularity

Content origin is recorded at the level of a sentence, a paragraph, a claim, or
an outline node. Not a token. Token-level attribution would require knowing
which spans of output derive from which spans of input, which nothing in this
system can establish.

For the same reason there is no "83% human" figure anywhere. The contribution
summary reports counts -- claims supplied and represented, preserved sentences
supplied and retained, factual assertions added -- because those are facts. A
percentage would be read as a measurement of authorship, and that measurement
does not exist.

## Where records live

Beside the diagnostic run records, in `~/.howlwriter/runs/<run_id>.provenance.json`:
outside any repository, under the user's home, private by default. Sidecars
written next to an artifact (`.provenance.json`, `.manifest.txt`,
`.outline.yaml`) are gitignored and are never published by HowlWriter.

## Reading one

    howlwriter howl --outline post.yaml --provenance --provenance-level full
    howlwriter paper --outline paper.yaml --provenance

In the local web app, a run's record is served read-only at
`GET /api/provenance/{run_id}`. Prompts are withheld unless
`?include_prompts=true` is passed, matching the stance `/api/voices` takes with
source paths: the prompts contain the user's own sentences.

## Generative-AI disclosure is a third, separate thing

`academic/ai_disclosure.py` keeps three concepts apart:

1. **Scholarly references** -- the evidence the paper rests on. Nothing from a
   provenance record ever appears there. A prompt is not a source.
2. **Generative-AI disclosure** -- what current APA guidance asks for: describe
   the use in the Method section and cite the tool. The template is
   `Company. (Year). Tool (Version) [Large language model]. URL`, with the
   company as author, because an AI cannot consent to authorship.
3. **Generation provenance** -- routing, prompts, hashes. Appendix or sidecar.

The disclosure is generated from the run. A run with no model calls says no
generative model produced or altered the text. A humanizer-only run says
nothing was generated from scratch. A sparse outline expanded into a full post
says most of the sentence-level wording was the model's. The statements differ
because the runs differ.

Where the provider reported no model, no reference entry is emitted and the
reason is stated, because APA's template requires a tool and a version and
HowlWriter does not have them.
