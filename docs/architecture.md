# Architecture

## Package layout

```
src/howlwriter/
├── domain/       Document/Paragraph/Sentence, Claim, Source/Evidence,
│                 ProvenanceGraph, VoiceProfile, WritingReport, WritingMode
├── config/       HowlWriterConfig schema, built-in defaults, the layered loader
├── linting/      LintEngine + builtin_rules/ (one module per rule family)
├── humanize/     detector (reuses LintEngine) + SafeRewriter
├── editing/      PassthroughEditor + the model-backed Editor Protocol
├── redpen/       RedPenEngine (criticism, not rewriting)
├── facts/        HeuristicClaimExtractor + the ClaimVerifier Protocol
├── research/     the Researcher Protocol (no real implementation)
├── citations/    CitationStyle registry + the APA7Formatter
├── voice/        CorpusStatsLearner + the VoiceAnalyzer Protocol
├── review/       MeaningPreservationReviewer + the WritingRole registry
├── integration/  ModelBackedRole / ModelRoleNotConfiguredError -- the one
│                 seam every model-backed capability above shares
├── pipeline/      run_howl_pipeline -- the one genuinely-working
│                 end-to-end path
└── cli/          argparse root + one module per subcommand, zero business
                  logic of its own
```

`tests/` mirrors this layout package-by-package, plus `tests/fixtures/`
(a draft with deliberate AI-style patterns, a clean human draft, sample
source metadata, and a small voice corpus).

## The domain model

Everything downstream depends on `domain/`, so it was built first (see the
commit history) and never partially. The two ideas worth understanding to
navigate the rest of the codebase:

**Span-addressable text.** `Document.parse()` splits plain text or
Markdown into `Paragraph`s and `Sentence`s (blank-line paragraph breaks, a
regex sentence-boundary heuristic). This is a known-approximate splitter --
it doesn't handle abbreviations or decimals perfectly -- but it's what lets
Red Pen and lint findings cite "paragraph 4, sentence 2" instead of an
opaque string offset, and what lets `Claim.document_span` point a claim
back at the exact sentence it came from.

**The provenance graph is real, not a stub.** `domain/provenance.py`'s
`ProvenanceGraph` is a genuine in-memory data structure over
`{claims, sources, evidence}` with working query methods
(`sources_for_claim`, `claims_for_source`, `evidence_for_claim`,
`unsupported_claims()`, `unaccessed_sources()`) and referential-integrity
checks on `add_evidence`. See [docs/provenance.md](provenance.md).

## Configuration

`config/loader.py::ConfigLoader.load()` implements the spec's layering
order -- `defaults -> mode -> user profile -> project -> request` -- as
field-by-field overrides (`apply_overrides`): a layer only replaces the
fields it actually sets, so a project config that only touches
`banned_words` never clobbers a mode's `citation_style`. The schema
(`config/schema.py`) is deliberately limited to the fields the spec names,
plus one MVP-specific field, `apply_safe_rewrites`, that gates the one
rewrite the humanizer performs on its own.

## The model-backed-role seam

`integration/model_role.py` defines `WritingRole` (WRITER, EDITOR,
HUMANIZER, VOICE_REVIEWER, FACT_CHECKER, RESEARCHER, RED_PEN,
CITATION_VALIDATOR, FINAL_REVIEWER), `ModelRoleNotConfiguredError`, and
`NotConfiguredRole`. Every capability that needs a model --
`humanize.rewriter.HumanizerRewriter`, the model-backed mode of
`editing.editor.Editor`, `facts.verification.ClaimVerifier`,
`research.researcher.Researcher`, `voice.model_hook.VoiceAnalyzer`,
`review.meaning.ModelMeaningReviewer` -- is a typed `Protocol` plus a
`NotConfigured*` default that raises a named error instead of silently
faking a result. HowlWriter never calls a model API itself; this is the
seam where an external executor (e.g. one HowlPlane supplies) would plug
in. See [docs/howlplane-integration.md](howlplane-integration.md) for why
that binding doesn't exist yet, and why that's not a bug HowlWriter should
paper over on its own.

## The lint engine and everything that reuses it

`linting/engine.py::LintEngine.run(document, config)` walks a registry of
pure functions, one per rule family under `linting/builtin_rules/`. Every
rule checks `config.banned_words` / `config.banned_patterns` for itself and
returns no findings when its pattern isn't configured -- nothing is
hard-coded as universally wrong. `humanize/detector.py` re-labels the
humanization-relevant subset of `LintEngine`'s output rather than
maintaining a second, driftable pattern list, and `redpen/critic.py`
imports the same filler-phrase constants from
`linting/builtin_rules/banned_patterns.py` for the same reason.

## The `howl` pipeline

`pipeline/howl.py::run_howl_pipeline()` is the one genuinely-working
end-to-end path: `INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN ->
FINAL REVIEW -> OUTPUT`. Every stage is real and deterministic; nothing in
it calls a model. See the root [README](../README.md) for the
stage-by-stage table of what each step actually does and doesn't do.

## The CLI

`cli/main.py` builds one `argparse` subcommand per capability
(`writer editor humanize voice fact-check research sources cite references
red-pen critique lint finalize howl`) and dispatches to
`cli/commands/<name>.py`. Every command module parses its own arguments and
calls straight into the corresponding `howlwriter.<domain>` function --
there is no business logic in the CLI package. A `ModelRoleNotConfiguredError`
raised by any command surfaces as a clean one-line stderr message and exit
code 2, never a traceback.

## Explicit non-goals for v1

- No PDF/DOCX/HTML ingestion -- `Document.parse()` handles plain
  text/Markdown only.
- No multi-file or directory-wide operations -- every command operates on
  one file (or one sources file) at a time.
- No real model execution anywhere in this codebase, by design.
- No attempt at a defensible "voice match %" without both a learned
  profile and a real comparison implementation -- the field stays `None`
  and is omitted from rendered reports rather than approximated.
