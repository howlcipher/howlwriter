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
| 17 | Tests & Verification | Done -- 585 passing tests across unit, integration, dogfood, and web suites |
| 18 | Contextual Structural Variance v1 | Done -- between-document structural variance measurement, paragraph & sentence spread percentiles rendered as bounded guidance, split tendencies rendered as varying rather than absolute, extended diversity validation, and hyper-symmetry detection. Context-conditioned pacing is implemented but stays inactive until a context slice carries enough documents to support it |
| 19 | Distributional Voice Fidelity | Done -- behaviours a corpus mean misdescribes are stored as cross-document presence plus when-present percentiles; corpus percentiles are real order statistics rather than averaged per-document percentiles; plurality ties are reported as split instead of resolved alphabetically; the feature-cache fingerprint now covers changed measurements as well as changed fields |
| 20 | Outline-Guided Authorship | Done -- versioned `outline/v1` schema, seventeen node kinds, an explicit authority order, generation freedom derived from what the user supplied, a writer stage in front of the existing chain, and a deterministic coverage report checking verbatim retention, required points and ordering against the finished artifact |
| 21 | Generation Provenance | Done -- every model call captured at the single dispatch boundary with the exact prompt sent, honest `PROVIDER_DID_NOT_REPORT` handling, credential redaction, summary/full levels, local sidecars, a generated manifest, a read-only web inspector, and model-added claims classified and gated by mode |
| 22 | Generative-AI Disclosure | Done -- an AI Use Statement generated from actual execution, kept separate from the scholarly References page and from workflow provenance, declining to emit an APA reference entry when the provider reported no model rather than substituting its own name |
| 23 | Source Freshness Gating v1 | Done -- verification of authority currency against claim temporal context, explicit historical justification support, version-mismatch blocking, replacement diagnostics, and independent evaluation from evidence depth |
| 24 | CI & Repository Portability v1 | Done -- machine-independent environment discovery, elimination of workstation-specific paths, hermetic test doubles, Playwright responsive testing, and automated GitHub Actions CI matrix |

## Explicitly Deferred (Named, Not Half-Built)

- **Alternative Citation Styles (MLA / Chicago / IEEE / Harvard).** `CitationStyle` reserves the names; APA 7 is the primary production implementation.
- **Automated Upstream Citation Validation against Remote Registrar APIs.** `WritingRole.CITATION_VALIDATOR` is defined in the role vocabulary; live remote registrar validation is deferred.
- **Real "Voice Match %" Similarity Metric.** `WritingReport.voice_match` stays `None` and is omitted from rendered reports rather than approximated with a fake percentage.
- **Multi-file / Project-wide Batch Rewriting.** Every CLI command operates on one file or assignment spec at a time to ensure reviewability and human authority gating.

## Known Limitations Surfaced by Milestone 19-22

- **Structural convergence is not solved.** The diversity checker now runs
  against generated batches instead of being dead code, and on a fresh
  twenty-prompt benchmark it returns FAIL for both the medium-only control and
  full HowlWriter. Generated output varies less than the corpus on sentence
  length, paragraph size, and lexical diversity. Parentheticals are no longer a
  signature; overall structural spread still is.
- **First person is dampened rather than preserved.** On impersonal technical
  prompts that is arguably correct. Whether it holds for personal input is what
  the mixed-context benchmark measures, and it is the open question.
- **Reviewer independence is tracked asymmetrically.** Only the meaning
  reviewer passes `avoid_provider`. The consistency reviewer requests the same
  role without it, and the writer has no independence tracking at all.
- **No APA reference entry can be generated for most runs.** HowlPlane's
  providers routinely report no model name, and APA's template requires a tool
  and version.

## Growth Path

Toward future multi-document and extended citation capabilities:

1. Add MLA citation style as a second concrete implementation to prove multi-style generalization.
2. Add automated upstream metadata verification against DOI registrars where network access is permitted.
3. Explore batch project operations under explicit user confirmation boundaries.

