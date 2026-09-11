# Empirical Evaluation & Benchmarking (Milestone 26)

## Purpose & Core Question

The objective of Milestone 26 is to provide a durable, rigorous, and scientific evaluation system capable of directly answering the core empirical question:

> **Does HowlWriter actually produce better, safer, and more useful writing than a strong raw-model baseline?**

This is an empirical evaluation framework, not a marketing benchmark. The system is designed to report `HOWLWRITER WINS`, `BASELINE WINS`, `TIE`, or `INCONCLUSIVE` depending strictly on verifiable evidence.

---

## 1. Baselines & Fairness Rules

The benchmark compares four primary baselines under strict fairness parity:

1. **`raw_model`**: The underlying model given the raw assignment prompt and context with minimal system instructions (`"You are a helpful writing assistant."`).
2. **`strong_prompt`**: The underlying model given an expertly engineered single-turn prompt containing:
   - Complete assignment specifications and context
   - Explicit target word count and tolerance boundaries
   - Section-by-section outline expectations
   - APA 7 citation directives and reference formatting rules
   - Anti-slop guidelines (banning generic clichés and formulaic transitions)
   - The full reference source corpus and excerpts
   *Note:* The strong-prompt baseline is deliberately not handicapped. HowlWriter must justify its architectural overhead against a genuinely capable single-turn competitor.
3. **`howlwriter_minimal`**: The generation-only drafting path of HowlWriter, skipping post-draft verification, humanization, style linting, Red Pen critique, and independent review.
4. **`howlwriter_full`**: The complete end-to-end HowlWriter pipeline, including source retrieval and reachability verification, outline enforcement, humanizer rewriting, style linting, Red Pen critique, heuristic and semantic meaning review, reviewer independence, and reference generation.

### Architectural Ablations

The framework supports targeted ablations to isolate which layers earn their complexity:
- `no_source_verification`: Bypasses URL/DOI reachability and claim verification.
- `no_voice`: Disables personal voice profiling and per-piece structural realization.
- `no_independent_review`: Runs reviews without provider-independence constraints.
- `no_red_pen`: Disables Red Pen critique.
- `no_meaning_preservation`: Bypasses deterministic and semantic meaning review.
- `no_humanizer`: Skips humanizer and safe rewriter stages.

---

## 2. Benchmark Dataset

The evaluation suite includes 35+ benchmark tasks across 11 diverse categories:
1. `academic/research`: Privacy regulations (GDPR/CCPA/NIS2), post-quantum cryptography standards (NIST FIPS 203/204), Zero Trust architectures (NIST SP 800-207), clinical differential privacy.
2. `technical explanation`: Raft vs Multi-Paxos consensus, hardware memory models & acquire-release semantics, eBPF kernel execution, Linux namespaces & cgroups v2.
3. `technical documentation`: HMAC-SHA256 webhook signatures, PgBouncer pool sizing, OAuth 2.1 PKCE flows, distributed circuit breaker specifications.
4. `argumentative analysis`: Modular monoliths vs microservices, open-weights vs closed-API models, static typing in enterprise codebases.
5. `professional writing`: Incident Severity 1 postmortems, Executive risk memos, API v1 sunset announcements.
6. `LinkedIn/social professional writing`: Staff engineer transitions, technical debt leverage, test coverage anti-patterns.
7. `editing/rewrite`: Tightening bloated vendor proposals, de-slopification of marketing briefs, academic draft hedging reductions.
8. `voice-preserving rewrite`: 3 AM cluster deadlock retrospective, founder beta update, systems engineering debug narrative.
9. `source-grounded synthesis`: Reconciling NIST SP 800-63B vs ISO/IEC 27002 passwords, Generative AI fair use doctrines, CIS Docker vs SLSA Level 3 supply chain security.
10. `fact-sensitive writing`: Chronology of Log4Shell (CVE-2021-44228), GDPR Article 83 enforcement fines, PEP 703 free-threaded Python evolution.
11. `outline-constrained authorship`: SOC 2 Type II Gap Assessments, Datacenter Disaster Recovery SOPs, Enterprise RFP compliance matrices.

---

## 3. Independent Metric Families

Rather than collapsing evaluation into a single opaque score, metrics are reported independently:

### 1. Requirement Satisfaction (Deterministic)
- **Word count compliance**: Evaluates whether output words fall strictly within `[min_words, max_words]`.
- **Required sections**: Deterministic regex matching verifying all requested section headings appear.
- **Required content points**: Keyword and semantic checks confirming key arguments are present.
- **Verbatim phrases**: Checks exact retention of required phrases.
- **Citation requirements**: Verifies citations are present when required or omitted when prohibited.
- **Forbidden words**: Enforces absence of banned words and AI clichés.

### 2. Factuality & Grounding
- Extracts claims via `HeuristicClaimExtractor`.
- Checks claims against provided source snippets and assignment context.
- Detects invented numbers, dates, statistics, and fabricated citations.

### 3. Citation Integrity
- Reuses Milestone 25/25.1 verification standards:
  - **ACCESS**: URL/DOI pattern validity and reachability.
  - **METADATA**: In-text authors and years match reference list entries.
  - **AUTHORITY**: Classified source authority tier (`PRIMARY_LAW`, `STANDARD`, `GOVERNMENT`, `SCHOLARLY`).
  - **EVIDENCE**: Citation binds to documented source in corpus.
  - **FRESHNESS**: Verified currency status.

### 4. Source Quality
- Semantic classification via `classify_source_authority`.
- Computes weighted authority score prioritizing primary statutes and standards over blogs and forums.

### 5. Meaning Preservation (Rewriting/Editing)
- Deterministic diffing via `MeaningPreservationReviewer`:
  - Number changes and date modifications
  - Polarity and negation inversions
  - Hedge word additions or deletions
  - Causal vs correlational shifts
  - Attribution modifications

### 6. Voice Fidelity (Multidimensional — No Fake Percentage)
- Extracts `DocumentFeatures`:
  - Sentence length mean, median, stdev, p10, p90
  - Paragraph length mean and stdev
  - First-person pronoun rate
  - Punctuation rates (semicolon, colon, em-dash, parentheticals)
  - Lexical diversity (TTR)
  - Transition word density
  - Passive voice rate
- Reports independent dimensional deviations against reference writing rather than fabricating an arbitrary "95% match" figure.

### 7. Structural Diversity & Template Convergence
- Evaluates batches of outputs from each system across repeated runs.
- Calculates coefficient of variation ($CV = \sigma / \mu$) on sentence lengths, paragraph sizes, transition rates, and first-person rates.
- Flags structural convergence as `PASS`, `WARNING`, or `FAIL`.
- *Capable of showing HowlWriter worse than the raw model baseline when HowlWriter converges into rigid templates.*

### 8. Writing Quality Signals
- AI-slop banned words (`AI_STYLE_BANNED_WORD`).
- Redundancy and paragraph near-duplicates (`detect_redundancy`).
- Style linter violations (`LintEngine`).
- Red Pen critique findings (`RedPenEngine`).

---

## 4. Blinded Independent Judging

Subjective dimensions (clarity, coherence, naturalness, conciseness) are judged via pairwise blinded comparisons:
- **Randomized Position**: Candidate A and Candidate B are assigned randomly (50/50) to prevent position bias.
- **Blinded Evaluation**: Candidate system identities are stripped. The judge only sees Candidate A and Candidate B.
- **Position Bias Tracking**: The system monitors position win rates to detect judge bias toward A or B.
- **Provider Independence**: When models are configured via HowlPlane, the judge uses `WritingRole.FINAL_REVIEWER` with `avoid_provider` set to the candidate's provider. Independence is audited and recorded as `INDEPENDENT`, `SAME_PROVIDER`, or `INDEPENDENCE_NOT_VERIFIABLE`.
- **Deterministic Judge**: Zero-model rule-based judge available for hermetic, fast CI testing.

---

## 5. Statistical Rigor

- **Descriptive Statistics**: Mean, median, standard deviation, IQR, min, max.
- **Confidence Intervals**:
  - Wilson score interval for win rates.
  - Non-parametric 1,000-sample bootstrap 95% confidence intervals for score differences.
- **Sign Tests**: Exact two-sided binomial test under $H_0: p = 0.5$.
- **Effect Sizes**: Cohen's d (pooled standard deviation) and Cliff's delta.
- **Sample Size Guard**: If total samples $N < 5$, the system explicitly outputs `INSUFFICIENT EVIDENCE` rather than premature claims of victory.
- **Verdicts**:
  - `HOWLWRITER WINS`: Statistically significant improvement ($p < 0.05$, 95% CI > 0).
  - `BASELINE WINS`: Statistically significant degradation.
  - `TIE`: Negligible effect size within margin of equivalence.
  - `INCONCLUSIVE`: High variance or insufficient sample size.

---

## 6. Cost & Latency Transparency

Architecture has a real cost. The system reports:
- Wall-clock latency (seconds)
- Token usage (prompt, completion, total)
- Model call counts
- Verification calls
- **Latency Multiplier** ($Latency_{HW} / Latency_{Baseline}$)
- **Token Multiplier** ($Tokens_{HW} / Tokens_{Baseline}$)

---

## 7. CLI & Deliverables

```bash
# Run core benchmark suite with deterministic metrics and mock models
howlwriter benchmark run --suite core --deterministic-only --mock-models

# Run full evaluation against real providers
howlwriter benchmark run --suite core --baseline raw_model,strong_prompt,howlwriter_full --repeat 3

# List benchmark cases
howlwriter benchmark list

# Render benchmark report
howlwriter benchmark report

# Compare run against reference baseline to catch regressions
howlwriter benchmark compare --current output/evaluation/benchmark-results.json --reference baseline.json
```

Reports are automatically written to `output/evaluation/`:
- `benchmark-summary.md` (Markdown summary)
- `benchmark-results.json` (Machine-readable full run record)
- `cases/{case_id}.json` (Individual case details)
