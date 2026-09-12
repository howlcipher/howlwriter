# HowlWriter Research-Quality Audit — 2026-09-01

**Scope:** Focused real-usage audit of `howlwriter humanize` / `howlwriter howl` short-form workflows and `howlwriter paper` academic workflows.  
**Commit base:** `howlcipher/howlwriter@a27eb45` (academic-writing milestone).  
**Worktree:** `audit/research-quality-2026-09-01` at `/run/media/system/tallgeese/dev/worktrees/howlwriter-audit`.  
**No production code changes were made while the UI milestone is in progress.**

---

## 1. Short-Form Review Calibration

Six short pieces were written and run through `howlwriter humanize` with live HowlPlane providers.

| # | Input style | Topic | Humanizer | Reviewer | Status | Run ID |
|---|-------------|-------|-----------|----------|--------|--------|
| 1 | Already human | SRE alert-routing story | agy | codex | **READY** | `hw-20260901-170328-ce2baf` |
| 2 | Already human | Feature-flag cleanup story | codex | agy | **READY** | `hw-20260901-170328-094e8b` |
| 3 | Moderately AI | SRE overview | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-170302-8630bc` |
| 4 | Moderately AI | Data-driven product teams | codex | agy | **READY** | `hw-20260901-170328-7965d7` |
| 5 | Heavily AI | Cloud-native transformation | agy | codex | **NEEDS_REVIEW** | `hw-20260901-170328-82854a` |
| 6 | Heavily AI | Digital leadership | codex | claude_code | **NEEDS_REVIEW** | `hw-20260901-170328-90319a` |

### 1.1 Observed humanizer behavior

- Runs 1 and 2 rewrote already-natural human prose (contractions, minor rephrasing). No lint or meaning flags remained; both were marked **READY**.
- Runs 3–6 removed empty transitions, banned words, and corporate filler. The transformed prose was plainer and more direct.
- Run 4 left three AI-style pattern warnings after humanization but still passed because semantic review passed and no banned words remained.

### 1.2 Semantic-review classification

| Run | Deterministic meaning diff | Reviewer verdict | Classification of concern |
|-----|------------------------------|------------------|---------------------------|
| 1 | PASS | PASS | — |
| 2 | PASS | PASS | — |
| 3 | `sentence_count_changed` 10 → 8 | FAIL | **REVIEWER_FALSE_POSITIVE** — only removed filler transitions and replaced "crucial" with "vital" |
| 4 | PASS | PASS | — |
| 5 | `sentence_count_changed` 8 → 6 | FAIL | **REVIEWER_FALSE_POSITIVE** — removed clichés and tricolons, no factual shift |
| 6 | PASS | FAIL | **REVIEWER_FALSE_POSITIVE** — only removed generic phrases and simplified inflated wording |

No instance of **TRUE_SEMANTIC_DRIFT** or **PLAUSIBLE_SEMANTIC_RISK** was observed in the short-form set. All three NEEDS_REVIEW cases were benign style rewrites.

### 1.3 Reviewer calibration note

The same Run-3 pair (`03_mod_ai_sre.md` → humanized) was submitted to a second reviewer:

- `claude_code` reviewer: **FAIL** (reported the rewrite as a semantic change).
- `codex` reviewer: **PASS_WITH_WARNINGS** (noted minor strengthening of "more costly" → "significantly more costly" and dropped "data-driven" emphasis).

This shows real reviewer variability on otherwise benign de-stiffening.

---

## 2. Academic Assignments

Six realistic APA-7 assignments (~1,500 words, 5–8 requested sources) were run with `howlwriter paper --save-artifacts`.

| # | Topic | Writer | Humanizer | Reviewer | Status | Run ID |
|---|-------|--------|-----------|----------|--------|--------|
| 1 | Zero Trust architecture | codex | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-170425-17257f` |
| 2 | Rust memory safety vs C/C++ | codex | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-171005-e6b1f0` |
| 3 | Software supply-chain security | codex | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-171005-30fc1e` |
| 4 | SRE error budgets / SLOs | codex | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-171005-f4f031` |
| 5 | Prompt-injection defenses | codex | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-171005-ed0b44` |
| 6 | Workload identity / SPIFFE | codex | agy | claude_code | **NEEDS_REVIEW** | `hw-20260901-171005-037e83` |

No academic run reached **READY**.

### 2.1 NEEDS_REVIEW root causes per run

| Run | Word count | Outline | Source min | Unsupported claims | Semantic review | Deterministic meaning | Other |
|-----|------------|---------|------------|--------------------|-----------------|-----------------------|-------|
| Zero Trust | PASS | PASS | **FAIL** (5/6) | 0 | **FAIL** | FLAGGED | lint AI-style warnings |
| Rust | PASS | PASS | **FAIL** (3/6) | **2** | **FAIL** | FLAGGED | citation warning (n.d.) |
| Supply chain | PASS | PASS | PASS (6/6) | 0 | **FAIL** | FLAGGED | — |
| SRE | PASS | PASS | **FAIL** (4/6) | **1** | **FAIL** | FLAGGED | — |
| Prompt injection | PASS | PASS | **FAIL** (5/6) | 0 | **FAIL** | FLAGGED | lint AI-style warnings |
| Workload identity | PASS | PASS | **FAIL** (5/6) | 0 | **FAIL** | FLAGGED | — |

**Summary:**
- **5 of 6** runs failed the source-count gate (retrieved fewer usable sources than the requested minimum of 6).
- **All 6** runs failed the model semantic-review gate.
- **All 6** runs were flagged by the deterministic meaning reviewer.
- Word-count and outline checks passed every time.

---

## 3. Source Relevance Audit

Sources were classified per the actual role they played in the paper, not just by whether the DOI resolved.

| Paper | Used sources | DIRECT | SUPPORTING | TANGENTIAL | IRRELEVANT |
|-------|-------------|--------|------------|------------|------------|
| Zero Trust | 5 | 5 | 0 | 0 | 0 |
| Rust | 3 | 0 | 1 | 2 | 0 |
| Supply chain | 6 | 4 | 2 | 1 | 0 |
| SRE | 4 | 1 | 0 | 0 | 3 |
| Prompt injection | 5 | 5 | 0 | 0 | 0 |
| Workload identity | 5 | 3 | 0 | 0 | 2 |
| **Total (28 unique source instances)** | | **18** | **3** | **3** | **5** |

### 3.1 Relevance problems found

- **Rust:** two of three used sources were a 1988 IEEE paper on compile-time program restructuring and an ACM proceedings entry titled only "BOGO" with no abstract. Neither substantiates Rust-vs-C/C++ claims.
- **SRE:** three of four used sources were a video about international-organization budgets, the CMS High-Level Trigger, and continuous-time quantum error correction. They are unrelated to SRE error budgets.
- **Workload identity:** two of five used sources were a 2013 SOAP/HTTPI web-service-security paper and a quantum-identity-authentication paper. The paper explicitly disclaims them, but they still appear in the References section.
- **Supply chain:** one used source was an OSS bot-detection paper (BotHawk); it is tangential to dependency risk.

**Verdict:** HowlWriter often retrieves **real but weakly relevant** material. The retrieval step does not reliably rank topical fit above keyword overlap.

---

## 4. Source Quality Audit

Quality was judged from available metadata, not from a fabricated score.

| Category | Count | Notes |
|----------|-------|-------|
| PRIMARY_STANDARD | 1 | Rust S001 — Chulalongkorn dissertation with full abstract (BoundWarden). |
| PEER_REVIEWED_RESEARCH | 5 | IEEE journal/proceedings, IEEE TSE, SCITEPRESS proceedings. |
| SCHOLARLY_PREPRINT | 16 | arXiv preprints and SSRN/TechRxiv posted content. |
| GREY_LITERATURE | 2 | River Publishers book chapter; Latest Thinking GmbH video/article. |
| QUESTIONABLE_VENUE | 3 | International Journal of Science and Research; IJ Research Organization / JETNR; United Research Forum. |
| UNKNOWN | 1 | ACM proceedings entry "BOGO" with no abstract. |

### 4.1 Quality problems found

- Several Crossref records returned no abstract (metadata-only), so the writer had only a title and DOI to infer content.
- Low-tier journals with generic titles appeared in the result set.
- The "BOGO" entry demonstrates that Crossref can return a real ACM DOI whose title is uninformative without an abstract.

---

## 5. Claim / Evidence Fit

A minimum of five claims per paper were inspected against the source material actually retrieved.

| Paper | DIRECTLY_SUPPORTS | REASONABLY_SUPPORTS | PARTIAL_SUPPORT | DOES_NOT_SUPPORT | Inspected |
|-------|--------------------:|--------------------:|----------------:|-----------------:|----------:|
| Zero Trust | 5 | 0 | 0 | 0 | 5 |
| Rust | 1 | 4 | 0 | 0 | 5 |
| Supply chain | 4 | 1 | 0 | 0 | 5 |
| SRE | 0 | 1 | 1 | 3 | 5 |
| Prompt injection | 4 | 1 | 0 | 0 | 5 |
| Workload identity | 2 | 3 | 0 | 0 | 5 |
| **Total** | **16** | **10** | **1** | **3** | **30** |

### 5.1 Representative good fits

- **Zero Trust:** The claim that Prasad et al. (2025) recorded a 60% reduction in unauthorized-access attempts and ≤8% latency overhead is directly supported by the retrieved abstract.
- **Prompt injection:** Claims about UniGuardian, gradient-based universal injections, and classifier-based detection are all directly supported by the corresponding arXiv abstracts.
- **Supply chain:** Comchecker accuracy figures (93.51% / 91.04%) and the 80% dependency-smell prevalence figure are directly supported.

### 5.2 Representative poor fits

- **SRE:** Claims about error-budget policy enforcement were supported only by a metadata-only, questionable-venue article titled "Governed Autonomy in Reliability Engineering: Integrating Error Budgets with AI-Driven Remediation." Three other cited sources were completely irrelevant to SRE.
- **Rust:** Claims about Rust's borrow checker could not be supported because no retrieved source discussed Rust. The paper correctly noted this gap, but two of its three references were still tangential.

---

## 6. Abstract vs Full-Text Truth

HowlWriter did **not** retrieve full-text PDFs. Evidence origin for the 28 used source instances:

| Evidence origin | Count |
|-----------------|------:|
| FULL_TEXT | 0 |
| ABSTRACT | 20 |
| METADATA | 8 |
| OTHER_EXCERPT | 0 |

### 6.1 Limitations observed

- **8 of 28** used sources (29%) were metadata-only. Prose that relies on them is effectively guessing from titles.
- **No full-text retrieval** means quantitative claims, caveats, and scope statements from abstracts cannot be verified against the paper body.
- The writer generally acknowledged these limits (e.g., the Rust and Workload-Identity papers explicitly flag what is unsupported), but the citation manager still attached the thin references.

---

## 7. Overgeneralization Audit

The strongest papers (Zero Trust, Prompt Injection, Supply Chain) mostly avoided overgeneralization. The weakest was **SRE**, where sources about international budgets, particle-physics triggers, and quantum error correction were used as analogies for "control mechanisms in other disciplines." The prose correctly labels them as cross-domain examples, but their inclusion in the References section still creates the appearance of scholarly support for SRE claims.

No clear instances of the following were found in the better papers:

- scope/population expansion beyond the study,
- certainty escalation,
- correlation → causation,
- prototype result → production generalization.

The Rust paper correctly refused to generalize BoundWarden's benchmark results to all real-world applications.

---

## 8. APA Metadata Quality

### 8.1 Formatter defects

- **Title case not converted to sentence case.** APA 7 article titles should use sentence case. Crossref titles arrive in title case and are emitted unchanged (e.g., "Enhancing Enterprise Security with Zero Trust Architecture"). This is a **FORMATTER DEFECT**; the formatter has the title text and could normalize it.

### 8.2 Upstream metadata defects

- **SRE paper — `Thinking, L., & GOETZ, K. H. (2017)`**: Crossref lists "Latest Thinking" as an author and emits "GOETZ, Klaus H." in all caps. The formatter correctly parses the strings it receives, but the input is bad.
- **SRE paper — `Trigger, T. C., & Group, D. A. (2005)`**: "The CMS Trigger Data Acquisition Group" was split into two personal names. Upstream author metadata is wrong.
- **Rust paper — `Dhumbumroong, S. (n.d.)`**: Crossref returned no publication date for the dissertation. The formatter honestly emits `n.d.` and a warning.

### 8.3 Ingestion / normalization defects

- The "BOGO" reference is emitted as a one-word title because Crossref supplied only that title. That is **UPSTREAM_METADATA_DEFECT**, not a formatter defect, but the pipeline could flag uninformative titles.

### 8.4 Citation/reference consistency

For the six papers:

- Every in-text citation had a corresponding Reference entry.
- Every Reference entry was cited in the body.
- No source ID mapped to the wrong reference.
- No "merely discovered" source was left in the reference list; unused sources were omitted.

---

## 9. Reviewer Calibration Matrix

Same unchanged candidate output (Run 3, moderate-AI SRE piece) was reviewed by two different providers.

| Reviewer | Verdict | Key rationale |
|----------|---------|---------------|
| claude_code | **FAIL** | No rationale persisted by default, but the rewrite was treated as a semantic change. |
| codex | **PASS_WITH_WARNINGS** | Noted "significantly more costly" as a slight strengthening and the loss of "data-driven" emphasis, but no blocker. |

This suggests the semantic reviewer is **noisier than the deterministic gate** for benign style changes, and provider choice affects the outcome.

---

## 10. False READY Hunt

**No FALSE READY cases were discovered** in the 12 primary workflows.

- Every academic run was flagged NEEDS_REVIEW, usually for good reasons (missing sources, unsupported claims, semantic-review failure).
- The short-form READY runs were correctly marked; no unsafe semantic drift slipped through.

The absence of false READY is the most positive finding of this audit.

---

## 11. False NEEDS_REVIEW Measurement

### 11.1 Short form

3 of 6 short-form runs were NEEDS_REVIEW. All three are classified as **LIKELY FALSE POSITIVE** caused by benign style rewrites.

### 11.2 Academic form

6 of 6 academic runs were NEEDS_REVIEW. The source-count gate alone made most of these **legitimate** (real source deficiency). The model semantic-review gate also fired every time. Because the source-count failure already forced NEEDS_REVIEW, it is hard to isolate how many semantic-review flags were false positives, but the short-form calibration suggests a nontrivial fraction may be noise.

| Category | Count |
|----------|------:|
| TRUE PROBLEM (source/claim deficiency) | 5 academic runs |
| REASONABLE CAUTION (semantic review on thin evidence) | 6 academic runs |
| LIKELY FALSE POSITIVE | 3 short-form runs |

---

## 12. Three Most Important Defects / Limitations

1. **Retrieval relevance is unreliable.** Crossref/arXiv keyword search returns real sources that are often tangential or irrelevant (e.g., international budgets and quantum error correction for an SRE paper). A real source with a DOI is not the same as a relevant source.
2. **Frequent source-count failures.** Five of six academic assignments did not retrieve the requested minimum of usable sources. The pipeline is honest about this, but it means the academic workflow almost never reaches READY on real topics without human-curated sources.
3. **Semantic review is too noisy on benign rewrites.** Both short-form and academic humanization passes are flagged for changes that do not alter factual meaning. Reviewer variability (claude_code FAIL vs. codex PASS_WITH_WARNINGS on the same text) confirms the gate is not well calibrated.

---

## 13. Final Questions

1. **Does HowlWriter select academically relevant sources, not merely real sources?**
   - **Partially.** When the query terms are specific and the topic is well covered on arXiv (e.g., prompt injection, Zero Trust), it finds relevant abstracts. When terms are generic ("budget," "error correction," "security"), it returns real but irrelevant items.

2. **Does claim-level evidence actually support the resulting prose?**
   - **For well-sourced topics, yes.** For Zero Trust, Prompt Injection, and Supply Chain, most inspected claims were directly or reasonably supported. For SRE and Rust, many claims were unsupported because the retrieved sources were off-topic or metadata-only.

3. **How often is retrieved evidence only an abstract?**
   - **71% of used sources were abstracts, 29% were metadata-only, and 0% were full-text.** No full-text retrieval occurred.

4. **Is the current research quality sufficient for graduate-level academic drafting WITH HUMAN REVIEW?**
   - **With heavy human review, it is a useful starter.** It does not fabricate sources, it passes word-count and outline checks, and it flags unsupported claims. However, source curation, relevance filtering, full-text verification, and semantic-review calibration still require human intervention.

5. **Are APA problems primarily formatter issues or upstream metadata issues?**
   - **Mostly upstream metadata issues** (missing dates, organizations parsed as people, all-caps names). The one clear formatter defect is failure to convert article titles to APA sentence case.

6. **Why are so many academic runs NEEDS_REVIEW?**
   - **Source-count failures** are the biggest driver (5/6). The semantic-review gate also fires every time, and deterministic meaning flags compound the result.

7. **Is semantic review appropriately conservative or too noisy?**
   - **Too noisy for benign style changes.** Short-form calibration showed three false-positive semantic-review failures. Academic humanization produced similarly benign rewrites that the reviewer flagged. The gate is conservative in a useful direction, but it is generating excessive friction.

8. **Were any FALSE READY results discovered?**
   - **No.** All 12 primary workflows were either correctly READY or correctly NEEDS_REVIEW.

9. **What are the three most important defects or limitations now visible?**
   - Unrelevant source retrieval.
   - Chronic source-count shortfalls.
   - Noisy semantic review.

10. **Which findings should influence the UI AGY is currently building?**
    - Expose **source relevance and evidence-origin badges** (abstract vs. metadata) so users can see why a source is weak.
    - Surface **gate-level breakdowns** (source count, unsupported claims, semantic review) explicitly, not just a NEEDS_REVIEW badge.
    - Provide a **source-curation workflow** before drafting, because automatic retrieval alone often misses the minimum.
    - Show **reviewer variability / confidence** when semantic review flags a benign rewrite, so the user can override or re-run with another reviewer.

---

## 14. Artifact Locations

All audit inputs, outputs, and source artifacts are in the isolated worktree:

```
/run/media/system/tallgeese/dev/worktrees/howlwriter-audit/audit/
├── shortform/              # 6 short-form inputs
├── academic/               # 6 assignment YAML files
└── outputs/                # Humanized short-form outputs and 6 academic papers
    ├── *.md
    └── *.sources.json
```

Run records are stored locally under `~/.howlwriter/runs/`.
