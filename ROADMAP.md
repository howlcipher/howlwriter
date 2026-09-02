# Roadmap

## Completed Milestones

The following capabilities are implemented, tested, and active on `main`:

| # | Capability | Implementation Status |
| --- | --- | --- |
| 1 | Repository architecture | Done -- see [docs/architecture.md](docs/architecture.md) |
| 2 | Document/domain model | Done -- span-addressable `Document`, `Claim`, `Source`/`Evidence`, `ProvenanceGraph`, `VoiceProfile`, `WritingReport` |
| 3 | Configurable style linting | Done -- `LintEngine`, built-in rule families, LinkedIn anti-slop rules, all config-gated |
| 4 | Humanizer interface | Done -- deterministic detection + `SafeRewriter` + model-backed `ModelHumanizer` via HowlPlane bridge |
| 5 | Editor interface | Done -- `PassthroughEditor` (real) + model-backed `Editor` seam |
| 6 | Red Pen interface | Done -- `RedPenEngine`, deterministic, never auto-rewrites |
| 7 | Claim extraction & verification | Done -- `HeuristicClaimExtractor` (real) + `AcademicClaimVerifier` populating `ProvenanceGraph` |
| 8 | Source / provenance model | Done -- `ProvenanceGraph` with referential integrity, source relevance & evidence depth tiers |
| 9 | APA 7 citation & reference formatting | Done -- `APA7Formatter`, in-text and reference page generation with missing-metadata warnings |
| 10 | Voice Corpus Profiling & registry | Done -- multi-format corpus extraction (DOCX, ODT, RTF, HTML, TXT, MD, PDF), ~35 style features, train/holdout split, discrete traits, leakage scrubbing, local private store `~/.howlwriter/voices/` |
| 11 | Meaning-preservation review | Done -- deterministic heuristic diffing (numbers, dates, hedges, attributions) + model-backed semantic review |
| 12 | HowlPlane role binding | Done -- `HowlPlaneWritingBridge` binding `WritingRole` to HowlPlane's `RoleDispatcher` with independent reviewer tracking |
| 13 | Academic paper pipeline | Done -- `howlwriter paper` with assignment specification, outline enforcement, identifier grounding, and bounded length remediation |
| 14 | Local Web Application | Done -- FastAPI backend + React SPA (`howlwriter ui`) with workspace, diff inspection, academic pipeline rail, runs ledger |
| 15 | Diagnostic run records | Done -- durable local records in `~/.howlwriter/runs/` with SHA-256 hashes, latency metrics, failure classification |
| 16 | CLI foundation | Done -- all 16 subcommands (`paper writer editor humanize voice fact-check research sources cite references red-pen critique lint finalize howl runs ui`) |
| 17 | Tests & Verification | Done -- 568 passing tests across unit, integration, dogfood, and web suites |

## Explicitly Deferred (Named, Not Half-Built)

- **Alternative Citation Styles (MLA / Chicago / IEEE / Harvard).** `CitationStyle` reserves the names; APA 7 is the primary production implementation.
- **Automated Upstream Citation Validation against Remote Registrar APIs.** `WritingRole.CITATION_VALIDATOR` is defined in the role vocabulary; live remote registrar validation is deferred.
- **Real "Voice Match %" Similarity Metric.** `WritingReport.voice_match` stays `None` and is omitted from rendered reports rather than approximated with a fake percentage.
- **Multi-file / Project-wide Batch Rewriting.** Every CLI command operates on one file or assignment spec at a time to ensure reviewability and human authority gating.

## Growth Path

Toward future multi-document and extended citation capabilities:

1. Add MLA citation style as a second concrete implementation to prove multi-style generalization.
2. Add automated upstream metadata verification against DOI registrars where network access is permitted.
3. Explore batch project operations under explicit user confirmation boundaries.

