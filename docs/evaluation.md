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

## 2.1 Evaluator Calibration & Sensitivity Suite (Milestone 26.1)

To ensure future architectural decisions are based on trustworthy metrics rather than broken evaluators, every evaluation family is calibrated against positive and negative control pairs:

- **Factuality Controls**: Positive controls with valid paraphrases, synonyms, and grounded numbers must score $\ge 0.70$. Negative controls with fabricated statistics or inverted polarities must score $\le 0.40$.
- **Voice Fidelity Controls**: Measured against genuine human author reference corpora. Distinguishes authentic personal style from generic bland LLM prose with a sensitivity gap $\ge 0.25$. If reference features are absent, the evaluator records `NO_DEMONSTRATED_VOICE_EFFECT` rather than defaulting to $1.000$.
- **Citation Integrity Controls**: Requires resolvable URLs and DOIs that match genuine source corpus metadata.
- **Judge Symmetry & Position-Bias Controls**: Audits pairwise judges using position-swapped candidate pairs and identical inputs (which must declare `TIE`).

---

## 3. Independent Metric Families

Metrics are strictly partitioned into **Final Output Quality** and **Assurance & Verification Coverage**:

### 3.1 Final Output Quality

Measures the intrinsic writing quality, accuracy, voice, and requirement adherence of produced prose:

1. **Factuality & Semantic Entailment (`factuality/v2-semantic`)**:
   - Evaluates claims via `DeterministicEntailmentEvaluator` with semantic entailment rules (handling synonyms, modal hedges, polarity, and clause splitting).
   - Preserves strict deterministic verification for dates, numbers, currency, and percentages.
2. **Voice Fidelity (`voice-fidelity/v2-distance`)**:
   - Multi-dimensional distribution distance from held-out human reference author features (`DocumentFeatures`).
   - Penalizes distance in sentence length percentiles, punctuation rates, paragraph pacing, and lexical diversity.
   - Guarded with `NO_DEMONSTRATED_VOICE_EFFECT` when no reference profile exists.
3. **Meaning Preservation**:
   - Detects factual shifts, hedge additions/removals, polarity inversions, and causal shifts in rewrites.
4. **Requirement Satisfaction**:
   - Deterministic verification of word counts, outline sections, required points, and forbidden phrases.
5. **Structural Diversity (`structural-diversity/v2`)**:
   - Computes distance from reference human writing distribution.
   - Penalizes both rigid template collapse (hyper-uniformity) and chaotic randomness.
   - Reports normalized $[0.0, 1.0]$ score alongside raw coefficient of variation ($CV$).

### 3.2 Assurance & Verification Coverage

Measures the depth and integrity of pipeline verification stages:

1. **Citation Integrity (`citation-integrity/v2`)**:
   - Validates that citations resolve against known `case.source_corpus` URLs, DOIs, and author/year metadata.
2. **Source Authority Quality**:
   - Classifies authority tiers (`PRIMARY_LAW`, `STANDARD`, `GOVERNMENT`, `SCHOLARLY`).
3. **Red Pen Critique Enforcement**:
   - Measures detection and elimination of AI slop words, filler, and passive bloat.
4. **Style Lint Compliance**:
   - Evaluates rule compliance across custom and built-in lint families.

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
# Validate evaluator calibration, sensitivity gaps, and judge bias
howlwriter benchmark validate

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
