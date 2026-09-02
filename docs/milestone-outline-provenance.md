# Milestone Report: Outline-Guided Authorship, Distributional Voice Fidelity & Generation Provenance v1

Every number below is either a command's own output or is produced by
`dogfood/report.py`, which recomputes from the stored generation text rather
than reading any runner's summary. Nothing is transcribed by hand.

## 1. Repository

| Item | Value |
| --- | --- |
| Starting HEAD | `82d7d1a` (also `origin/main`) |
| Branch | `feat/outline-authorship-provenance` |
| Concurrent commits during the milestone | none; `origin/main` still at `82d7d1a` |
| Working tree at start | clean |
| Commits created | 11 |
| Files changed | 61 (+8,736 / -344) |
| Pushed | no |

**The brief's premise was stale.** It described the Contextual Structural
Variance remediation as uncommitted (13 modified, 34 untracked, 3 commits
ahead, nothing pushed). In fact that work had already been committed as
`a0bfe35`, `bac450d` and the merge `82d7d1a`, and pushed: `main` and
`origin/main` were identical and the tree was clean. Phase 0's "stabilize the
uncommitted remediation" had nothing to rescue, so it became verification of
the committed fixes instead. `f36661e` (responsive docs) is merged ancestry,
not loose concurrent work.

## 2. Phase 0 — the committed fixes, verified against code

| Audit finding | State | Evidence |
| --- | --- | --- |
| Feature-cache schema bug | Fixed, soundly | `build.py:118` hashes the `DocumentFeatures` field names into a per-document fingerprint checked on reuse (`build.py:322-327`). Every record in `features.json` carries one. |
| Zero-range prompt rendering | Fixed | `application.py:76 _has_spread()` requires `high > low > 0`, so a stale-cache `0.0` and a degenerate corpus are both suppressed. |
| Categorical split tendencies | Already landed | `_is_split()` with `MIN_TRAIT_AGREEMENT = 0.50` renders `VARIES`. Fires on real data for `first_person_presence` (0.441) and `parenthetical_asides` (0.474). |
| Context-slice evidence | Honest | The professional slice (which LinkedIn draws on) holds 3 documents / 2,371 words at confidence **0.204**, below the 0.35 threshold, so every trait renders as "thin evidence; do not let this override the global tendency". |
| Symmetry heuristic | Re-evaluated | It is a *lint rule*, `linting/builtin_rules/structure.py:24-43`, not part of voice aggregation. Its own comment already concedes 0.12 is "heuristic, not derived", set below an observed human range of 0.15–0.75 and "deliberately biased towards missing cases". Kept as is. |
| Document-size mismatch | Correct | `diversity.py:206-219` flags a fourfold gap and routes "nothing converged but the sample could not have detected convergence" to `NOT_EVALUATED` rather than `PASS`. |

### Two defects the previous audit did not catch

**Corpus percentiles were means of per-document percentiles.**
`_aggregate_distributions` applied one word-weighted mean to every name in
`COMPARABLE_FEATURES`, and the percentile fields were just more names in that
list. A mean of order statistics is not an order statistic: it is pulled to the
centre by construction and to the longest documents by the weighting. Measured
effect on the real corpus after the fix:

| field | before (mean of percentiles) | after (cross-document median) |
| --- | ---: | ---: |
| `paragraph_words_p10` | 35.47 | **21.85** |
| `paragraph_words_p50` | 79.33 | **53.00** |
| `paragraph_words_p90` | 127.91 | **115.00** |
| `sentence_length_p10` | 8.74 | **6.60** |
| `sentence_length_p90` | 31.62 | **29.00** |

The old values understated the author's floor by 62% on paragraph length. The
feature whose entire purpose was to preserve spread was itself compressing it.

**The diversity checker was dead code.** It was fully implemented and fully
tested, and invoked from no live path: `build.py:576` recorded
`NOT_EVALUATED` unconditionally because no generated text exists at
corpus-build time, and nothing else called it. A verdict engine nothing calls
cannot catch a regression. It now runs in the benchmark path, and what it says
is in section 6.

## 3. Distributional voice fidelity

The gap the brief identified — "carry the split-tendency idea into the rates as
well as the labels" — measured on the live corpus:

| feature | % of documents at zero | corpus mean | median where present |
| --- | ---: | ---: | ---: |
| `first_person_rate` | 42% | 1.012 | 1.361 |
| `contraction_rate` | 63% | 0.099 | 0.185 |
| `em_dash_rate` | 82% | 0.050 | 0.159 |
| `question_rate` | 77% | 0.028 | 0.091 |
| `parenthetical_rate` | 23% | 1.264 | 1.112 |

The contraction mean is roughly half the typical value in documents that use
contractions. It describes neither the 63% that use none nor the rest.

`RateDistribution` now stores presence across documents separately from
intensity within the documents that have the behaviour, for thirteen
zero-inflated dimensions, globally and per context. Percentiles are taken over
present documents only; including the zeros would drag every percentile toward
zero and re-create the flattening. The list is fixed rather than derived per
corpus so two profiles stay comparable field for field, and measures that are
not zero-inflated keep their mean and percentile pair.

`william_v2`, built from the same corpus, carries all thirteen:

| dimension | presence | p10 | p50 | p90 (where present) |
| --- | ---: | ---: | ---: | ---: |
| `parenthetical_rate` | 85% | 0.29 | 1.42 | 3.10 |
| `fragment_rate` | 79% | 0.01 | 0.09 | 0.33 |
| `second_person_rate` | 68% | 0.07 | 0.35 | 4.93 |
| `first_person_rate` | 65% | 0.24 | 1.57 | 4.83 |
| `transition_rate` | 62% | 0.03 | 0.08 | 0.14 |
| `contraction_rate` | 53% | 0.07 | 0.24 | 0.52 |
| `semicolon_rate` | 41% | 0.07 | 0.20 | 0.68 |
| `em_dash_rate` | 29% | 0.12 | 0.15 | 0.40 |
| `heading_rate` | 18% | 0.04 | 0.32 | 0.43 |
| `exclamation_rate` | 9% | — | — | — (too few to describe) |

### False modal winners

`_label_agreement` breaks ties lexicographically so rebuilds stay stable, which
made the winner on a dead heat alphabetical rather than evidential. Seven tied
traits exist in the real profile:

| scope | trait | primary | secondary |
| --- | --- | --- | --- |
| global | `lexical_variety` | low (0.362) | medium (0.342) |
| global | `sentence_length` | medium (0.375) | short (0.355) |
| professional | `first_person_presence` | prominent (0.417) | absent (0.417) |
| professional | `paragraph_length` | short (0.417) | long (0.417) |
| professional | `paragraph_variation` | medium (0.417) | high (0.417) |
| professional | `rhetorical_questions` | occasional (0.417) | frequent (0.417) |
| professional | `sentence_length` | very_short (0.417) | short (0.417) |

Five of these are exact 0.417/0.417 splits that previously rendered as
definite values. They now render as `SPLIT`, naming no winner — including
inside a thin context, where the "thin evidence" caveat previously masked the
problem without fixing it.

## 4. Outline-guided authorship

`pipeline/howl.py` could only transform prose that already existed. Outline
mode adds a writer stage in front of the same chain.

- **Schema**: `outline/v1`, YAML or JSON, seventeen node kinds. Kinds are not
  interchangeable: `preserve` may not be rewritten, `claim` may be rephrased but
  not contradicted, `idea` invites expansion, `voice_seed` shapes register and
  is deliberately not required to appear.
- **Authority order**: thirteen ranked layers from evidence down to the model's
  own stylistic preference, written once and appealed to by the prompt, the
  coverage checks and the provenance record.
- **Generation freedom**: derived from the outline, never declared. The primary
  route to `LOW` is concrete authored material — passages the user wrote and
  examples only they could supply — because counting alone cannot separate a
  structured outline from an authorship-rich one.
- **Coverage**: computed from the finished artifact, never asked of the model.
  Verbatim retention is exact and reports altered text with the closest match
  found; required points use a documented overlap threshold biased toward
  reporting `MISSING`; ordering is checked, which the academic outline checker
  never did.

## 5. Generation provenance

Every model call passes through one method,
`HowlPlaneWritingBridge.execute_writing_role`, which holds the only
`dispatcher.execute` call in the codebase. The recorder is instrumented there,
so the captured prompt is the string the provider received in the same call
that produced the response. Nothing is reconstructed.

What HowlPlane actually returns constrains what can honestly be recorded:
`provider` always, `model` optionally, and **no token usage or request id at
all**. An unreported model is recorded as `PROVIDER_DID_NOT_REPORT`; the
provider's own name is not substituted, because `agy` is a CLI and putting it
where a vendor belongs would be a fabrication with an audit trail. Token usage
stays `null` rather than becoming `0`.

In the live benchmarks, **every** model call ran on a provider that reported no
model name. That is the honest state of this deployment, and the manifest says
so in those words.

## 6. Dogfood results

See the generated tables in section 7 and `dogfood/report.py` to reproduce them.
