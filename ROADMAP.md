# Roadmap

## MVP scope (this milestone)

All fifteen items from the initial MVP scope are done:

| # | Item | Status |
| --- | --- | --- |
| 1 | Repository architecture | Done -- see [docs/architecture.md](docs/architecture.md) |
| 2 | Document/domain model | Done -- span-addressable `Document`, `Claim`, `Source`/`Evidence`, `ProvenanceGraph`, `VoiceProfile`, `WritingReport` |
| 3 | Configurable style linting | Done -- `LintEngine`, 10 built-in rule families, all config-gated |
| 4 | Humanizer interface | Done -- deterministic detection (real) + `HumanizerRewriter` Protocol (unconfigured) |
| 5 | Editor interface | Done -- `PassthroughEditor` (real) + `Editor` model-backed mode (unconfigured) |
| 6 | Red Pen interface | Done -- `RedPenEngine`, deterministic, never auto-rewrites |
| 7 | Claim extraction model | Done -- `HeuristicClaimExtractor` (real); `ClaimVerifier` unconfigured |
| 8 | Source/provenance model | Done -- `ProvenanceGraph` with real, working query methods |
| 9 | Basic APA 7 citation representation | Done -- `APA7Formatter`, all forms, missing-metadata warnings |
| 10 | Voice Profile representation | Done -- `VoiceProfile` + `CorpusStatsLearner` (real); `VoiceAnalyzer` unconfigured |
| 11 | Meaning-preservation review interface | Done -- `MeaningPreservationReviewer` (real heuristic diff); `ModelMeaningReviewer` unconfigured |
| 12 | HowlPlane integration boundary | Done -- `.ai-project.toml`, validated against HowlPlane's own `ai project validate` |
| 13 | CLI foundation | Done -- all 13 subcommands (`writer editor humanize voice fact-check research sources cite references red-pen critique lint finalize howl`) |
| 14 | Tests | Done -- 124 passing tests, one module per package |
| 15 | Documentation | Done -- this file plus the seven docs in `docs/` |

The first usable flow (INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN ->
FINAL REVIEW -> OUTPUT) genuinely works end to end via
`howlwriter howl <file>`, against real fixtures, not a stub.

## Explicitly deferred (named, not half-built)

- **Real network research.** `research/researcher.py`'s `Researcher` is
  Protocol-only. Building even a minimal HTTP fetch here risks exactly the
  provider-coupling and duplicated execution logic HowlPlane is meant to
  own.
- **Semantic claim verification.** `facts/verification.py`'s
  `ClaimVerifier` is Protocol-only -- deciding a claim is `SUPPORTED`
  needs a model call or a real search backend.
- **LLM-driven humanization/editing rewrites.** `HumanizerRewriter` and
  the model-backed mode of `Editor` are Protocol-only; the deterministic
  `SafeRewriter` and `PassthroughEditor` are the complete MVP deliverable
  here.
- **MLA/Chicago/IEEE/Harvard citation styles.** `CitationStyle` reserves
  the names; only APA7 has an implementation.
- **Citation validation.** `WritingRole.CITATION_VALIDATOR` is part of the
  role vocabulary; nothing implements it yet.
- **PDF/DOCX/HTML ingestion.** `Document.parse()` handles plain
  text/Markdown only.
- **A real `VoiceAnalyzer` implementation.** `CorpusStatsLearner` is the
  complete real MVP voice capability; qualitative (tone/humor) analysis is
  reserved, unconfigured.
- **A real "voice match %" metric.** `WritingReport.voice_match` stays
  `None` and is omitted from rendered reports rather than approximated.
- **Binding any `WritingRole` to a concrete executor**, including one
  HowlPlane might supply. Documented as an open integration layer in
  [docs/howlplane-integration.md](docs/howlplane-integration.md), not
  filled with a bespoke shim inside HowlWriter.
- **Multi-file / project-wide operations.** Every CLI command operates on
  one file (or one sources file) at a time.

## Growth path

Toward the long-term pipeline in [docs/vision.md](docs/vision.md):

```
INPUT -> RESEARCH -> DRAFT -> HUMANIZE -> VOICE MATCH -> EDIT -> LINT ->
CLAIM EXTRACTION -> FACT CHECK -> SOURCE VERIFICATION -> RED PEN ->
INDEPENDENT CRITIQUE -> MINIMAL REWRITE -> MEANING VERIFICATION ->
CITATION GENERATION -> FINAL OUTPUT
```

Roughly, in order of what unlocks the most:

1. Resolve the HowlPlane execution-binding gap (see
   [docs/howlplane-integration.md](docs/howlplane-integration.md)) so at
   least one `WritingRole` Protocol has a real implementation to test
   against, end to end.
2. Wire a configured `Researcher` and `ClaimVerifier` together so
   `fact-check --verify` can genuinely populate a `ProvenanceGraph`
   instead of only extracting candidates.
3. Extend `howl` to call `/cite` and `/references` when a caller supplies
   collected sources, instead of treating citation generation as fully
   separate from the pipeline.
4. Add a real `voice_match` comparison once there's a validated method,
   and only then add the report line back.
5. Add MLA next (the second-most-requested academic style after APA), as
   a second concrete `CitationStyle` implementation to prove the registry
   generalizes.
6. Revisit the reviewer-role vocabulary gap once HowlWriter has enough
   real usage to make a concrete proposal to HowlPlane, per the Freeze's
   own evidence bar.
