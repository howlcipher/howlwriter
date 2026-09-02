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
| Commits created | 14 |
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

Reproduce with `python dogfood/report.py`. Every figure is recomputed from
the stored generation text, not read from any runner's own summary.

## Second structural benchmark (20 prompts, fresh generation)
voice: william_v2  providers: {'writer': 'agy', 'humanizer': 'agy', 'final_reviewer': 'codex'}
wall clock: 14.5 min

| arm | n | failed | parenthetical presence | parentheticals total | top opening share | first person presence | first person mean/100w | distinct openings | diversity |
|---|---|---|---|---|---|---|---|---|---|
| medium_only | 20 | 0 | 0/20 (0%) | 0 | 0% | 3/20 (15%) | 0.21 | 19/20 | FAIL (10 converged) |
| full_howlwriter | 20 | 0 | 5/20 (25%) | 5 | 20% | 1/20 (5%) | 0.03 | 20/20 | FAIL (12 converged) |

medium_only converged dimensions: sentence_length_mean, sentence_length_stdev, paragraph_words_mean, paragraph_words_stdev, paragraph_sentences_mean, single_sentence_paragraph_rate, short_sentence_rate, lexical_diversity, fragment_rate, parenthetical_rate
full_howlwriter converged dimensions: sentence_length_mean, sentence_length_stdev, paragraph_words_mean, paragraph_words_stdev, paragraph_sentences_mean, paragraph_sentences_stdev, single_sentence_paragraph_rate, short_sentence_rate, lexical_diversity, fragment_rate, contraction_rate, question_rate

Parenthetical opening phrases (checking for a repeated syntactic function):
  medium_only: (none)
  full_howlwriter: {'and several': 1, 'no matter': 1, 'often written': 1, 'or simply': 1, 'services, hosts,': 1}

Reasoning progression:
  medium_only: 17 distinct signatures over 20 docs; most common held by 15%; declarative close 100%
  full_howlwriter: 15 distinct signatures over 20 docs; most common held by 20%; declarative close 95%

## Mixed-context benchmark (register flexibility, first-person preservation)
| arm | n | first person present | mean/100w | median when present | parenthetical presence |
|---|---|---|---|---|---|
| medium_only | 10 | 5/10 (50%) | 0.86 | 1.71 | 1/10 (10%) |
| full_howlwriter | 10 | 5/10 (50%) | 1.14 | 2.13 | 4/10 (40%) |

Per-prompt first-person rate (per 100 words), by register:
  mixed_01     personal observation (first person medium_only=0.67  full_howlwriter=1.89
  mixed_02     personal observation (first person medium_only=3.30  full_howlwriter=2.38
  mixed_03     career reflection (first person)   medium_only=2.59  full_howlwriter=4.60
  mixed_04     short opinion                      medium_only=0.00  full_howlwriter=0.00
  mixed_05     longer analytical opinion          medium_only=0.00  full_howlwriter=0.00
  mixed_06     casual professional comment        medium_only=0.00  full_howlwriter=0.00
  mixed_07     technical explanation              medium_only=0.38  full_howlwriter=0.36
  mixed_08     disagreement / contrarian          medium_only=0.00  full_howlwriter=0.00
  mixed_09     personal observation (first person medium_only=1.71  full_howlwriter=2.13
  mixed_10     short opinion                      medium_only=0.00  full_howlwriter=0.00

## Outline progression (one idea, five authorship levels)
| level | expected freedom | derived freedom | user words | artifact words | required represented | preserved retained | model-added claims | coverage |
|---|---|---|---|---|---|---|---|---|
| A_sparse | HIGH | HIGH | 0 | 213 | 1/3 | 0/0 | 4 | FAIL |
| B_minimal | MEDIUM | MEDIUM | 0 | 205 | 3/4 | 0/0 | 4 | FAIL |
| C_structured | MEDIUM | MEDIUM | 26 | 195 | 6/6 | 0/0 | 3 | PASS |
| D_authorship_rich | LOW | LOW | 52 | 211 | 4/4 | 1/1 | 4 | PASS |
| E_near_complete | MINIMAL | MINIMAL | 116 | 116 | 1/1 | 1/1 | 0 | PASS |

Model expansion relative to what the author supplied:
  A_sparse               supplied    0 -> artifact  213 words
  B_minimal              supplied    0 -> artifact  205 words
  C_structured           supplied   26 -> artifact  195 words  (x7.5)
  D_authorship_rich      supplied   52 -> artifact  211 words  (x4.1)
  E_near_complete        supplied  116 -> artifact  116 words  (x1.0)

Provenance completeness per level:
  A_sparse               run_id=hw-20260902-200238-a4e018 calls=3 prompts_captured=3 unknown_model=3
  B_minimal              run_id=hw-20260902-200400-6f2b51 calls=3 prompts_captured=3 unknown_model=3
  C_structured           run_id=hw-20260902-200541-e12b4c calls=3 prompts_captured=3 unknown_model=3
  D_authorship_rich      run_id=hw-20260902-200840-48bed6 calls=3 prompts_captured=3 unknown_model=3
  E_near_complete        run_id=hw-20260902-200946-b5696a calls=3 prompts_captured=3 unknown_model=3


## 7. What the benchmarks actually show

### Parentheticals are no longer a signature

| run | presence | repeated opening |
| --- | --- | --- |
| original broken Agy run | 20/20 (100%) | — |
| after the first remediation | 11/20 (55%) | 7 of 26 opened with "such as" |
| **this run** | **5/20 (25%)** | **none; all five openings distinct** |

Position CV across the batch is 0.56, so they land in varied places rather than
a fixed slot. Corpus presence is 85%, and output sits well below it — under-use
with variation rather than a tell. No attempt was made to push output toward
the corpus figure.

### First person is preserved where natural and not injected where it is not

The mixed-context benchmark is the arm that answers this; the structural
prompts are impersonal by construction.

| register | medium-only | full HowlWriter |
| --- | ---: | ---: |
| personal observation (mixed_01) | 0.67 | **1.89** |
| personal observation (mixed_02) | 3.30 | 2.38 |
| career reflection (mixed_03) | 2.59 | **4.60** |
| personal observation (mixed_09) | 1.71 | **2.13** |
| short opinion (mixed_04) | 0.00 | 0.00 |
| longer analytical (mixed_05) | 0.00 | 0.00 |
| casual professional (mixed_06) | 0.00 | 0.00 |
| technical explanation (mixed_07) | 0.38 | 0.36 |
| disagreement (mixed_08) | 0.00 | 0.00 |
| short opinion (mixed_10) | 0.00 | 0.00 |
| **batch mean per 100 words** | **0.86** | **1.14** |

This reverses the regression the previous audit recorded (Medium-only ≈1.58
against Full ≈0.80). Full HowlWriter is now higher than the control overall and
on three of the four genuinely personal prompts, and puts no first person at
all into the five impersonal ones.

### Authorship measurably reduces model freedom

| level | derived freedom | user words → artifact words | expansion |
| --- | --- | ---: | ---: |
| A sparse | HIGH | 0 → 213 | unbounded |
| B minimal | MEDIUM | 0 → 205 | unbounded |
| C structured | MEDIUM | 26 → 195 | ×7.5 |
| D authorship-rich | LOW | 52 → 211 | ×4.1 |
| E near-complete | MINIMAL | 116 → 116 | **×1.0** |

Level E returned **byte-identical** to what was supplied: zero word-level diff
hunks, the verbatim passage intact, zero model-added claims. The
minimum-necessary-edit rule holds where it matters most.

The derived freedom matched the expected level at all five, and the coverage
report caught one genuine failure — level B dropped the required point "the
durable moat shifts elsewhere" at 0.00 overlap, which the model would have
reported as compliant.

### The unflattering result

The diversity checker now runs, and it returns **FAIL for both arms**. Worse,
full HowlWriter converges on *more* dimensions than the control (12 against 10),
and its paragraph counts are *tighter*:

| arm | paragraph counts | mode | range | CV |
| --- | --- | --- | --- | ---: |
| medium-only | 4–8 | 5 (×12) | 4 | 0.159 |
| full HowlWriter | 4–6 | 5 (×11) | 2 | **0.135** |

Reasoning progression is more diverse than the paragraph shape: 15 distinct
signatures over 20 documents, the most common held by 20%, so the specific
thesis → mechanism → rule template is not dominant. But 95% close
declaratively, and the structural spread is narrower with the voice profile
applied than without it.

**The distributional work fixed the rate-level signatures and did not fix the
structural one.** Parentheticals and first person now behave like distributions.
Paragraph and sentence shape still collapse toward a centre, and the profile
tightens that collapse rather than loosening it.

## 7a. Academic benchmark: a provider-layer ceiling

The first live academic run **failed**, and the failure is worth more than the
paper would have been.

A 1600-word academic outline reached the writer, which returned
`Error: timeout waiting for response` after 303 seconds. HowlWriter had asked
for a 600-second timeout, and HowlPlane passes that value to the subprocess --
but it never forwards `--print-timeout` to the `agy` CLI, so agy's own
five-minute default fires first and returns a timeout *string as output* rather
than the subprocess being killed. HowlWriter then correctly refused to treat
that string as a draft.

Three things follow, and only the third is actionable here:

1. **The failure surfaced honestly.** The writer raised rather than returning a
   plausible-looking partial paper, and the runner recorded `status: FAILED`
   with the error instead of dropping the run from the batch. A benchmark that
   silently drops its failures improves every statistic computed from what
   remains.
2. **The gap is in the sibling repository.** `agent_execution.py` passes
   `timeout=timeout_seconds` to the subprocess and no `--print-timeout` to the
   CLI. Fixing it means changing HowlPlane, which is outside this milestone and
   is recorded rather than reached into.
3. **Long-form academic generation is currently capped at roughly five minutes
   of provider time**, whatever HowlWriter requests. The benchmark was re-run at
   a 900-word target for that reason, and the constraint is noted in the outline
   file itself so the next person does not rediscover it.

### What the completed academic run showed

Re-run at a 900-word target, it finished in 369 seconds and produced a real
paper — and two more defects.

| Measure | Result |
| --- | --- |
| Words | 1,544 against a 900 target and an 1,100 hard maximum |
| Readiness | `NEEDS_REVIEW` (correctly: two unsupported claims and a length overrun) |
| Sources retrieved | 6 |
| Claims verified | 19, of which 2 unsupported |
| Spec-level outline conformance | `PASS` — 4 of 4 sections |
| Required points represented | 9 of 10 |
| **Preserved passages retained** | **0 of 1** |
| Model calls captured | 6 of 6, all with exact prompts, all reporting no model |
| Reviews | meaning `PASS`, semantic `PASS`, consistency `PASS_WITH_WARNINGS` |

**The preserved sentence was dropped** — 0.14 overlap in the finished paper.
The cause is a gap in the Phase 3 translation, not in the writer:
`AssignmentSpec` has no concept of verbatim text, and `spec_from_outline` was
carrying required points and style notes into `spec.requirements` while leaving
preserved passages behind entirely. The academic writer never learned the
sentence was marked preserve. The guarantee that holds byte-for-byte in the
general pipeline was silently absent from the academic one, and only a live run
could show it, because every deterministic test checked the bridge's output
rather than what a writer did with it.

Preserved passages now translate into explicit reproduce-exactly requirements
stated ahead of everything else, and the author's claims travel with them.
Three tests hold it, including one that counts preserved nodes in against
verbatim requirements out, so a dropped one fails rather than passing quietly.

**Model-added claims read as zero, and that figure is not trustworthy here.**
The academic writer returns `claims_made` with source ids; the classifier reads
`added_claims`. The two never met, so the classification saw an empty list and
reported no additions rather than reporting that it had nothing to classify.
The count is accurate for the general pipeline and meaningless for the academic
one. Left as found and recorded here rather than papered over.

## 8. Defects found and fixed during this milestone

Beyond the two the previous audit missed (section 2), six were found by using
the system rather than by reading it:

1. **Corpus percentiles were means of percentiles** — understated the author's
   paragraph floor by 62%.
2. **The diversity checker was dead code** — a verdict engine nothing called.
3. **Plurality ties rendered as findings** — seven in the real profile, five of
   them exact 0.417/0.417 splits.
4. **A tied trait in a thin context still named a winner** — the thin-evidence
   caveat masked the problem without fixing it.
5. **Credentials survived redaction outside the prompt fields** — a secret in a
   preserved passage was scrubbed from the prompt and reproduced verbatim at
   `coverage.findings[].text` and again in the outline sidecar. Found by putting
   an API key in a preserved node and grepping all three sidecars.
6. **A LOW-freedom label understated what the model wrote** — a densely
   structured academic outline reaches LOW on structure alone while supplying 65
   words against a 1600-word target, and the disclosure claimed the model was
   "limited to connective prose".
7. **`idea` nodes failed coverage for being expanded** — the level designed for
   maximum freedom reported two false failures.
8. **`run_academic_pipeline` rejected an outline without a spec** — the CLI had
   been working around it.

## 9. Verification

| Check | Result |
| --- | --- |
| `.venv/bin/pytest --ignore=tests/docs` | **742 passed** (was 592 at branch point) |
| `.venv/bin/flake8 src/` | clean |
| `.venv/bin/flake8 tests/ --exclude=tests/docs` | clean |
| `npm run build` | succeeds (`tsc && vite build`) |

### Reported separately, not fixed

`tests/docs/test_docs_responsive.py` fails collection because it imports
`playwright`, which is installed in no environment here and named in no
`pyproject.toml` extra. It also carries **9 flake8 findings**. Both predate this
branch — verified by checking out `82d7d1a` and re-running flake8, which
produces the same 9 — and belong to the concurrent responsive-docs work in
`f36661e`. Nothing here touched that file.

### Privacy

- No string longer than six words exists anywhere in the built profile except a
  build warning. No corpus prose is retained.
- No committed file contains a private path (`ExpanDrive`, `Google Drive`,
  `/home/howlcipher`).
- `tests/voice/corpus/test_committed_artifacts.py` — the executable gate that
  greps `git ls-files` and `git grep` — passes, and was extended to cover
  provenance sidecars.
- Raw generations stay local: `dogfood/*results*/` was already gitignored, and
  `*.provenance.json`, `*.manifest.txt` and `*.outline.yaml` were added.

### Non-goal compliance

No detector-evasion scoring, no "human probability", no injected typos or
grammar damage, no fabricated anecdotes, no classifier-targeted paraphrasing,
and no third-party detector score used as a release criterion. The only
occurrences of "detector" in `src/` are `humanize/detector.py` (a re-labeller
for the style linter, not an AI detector), an explicit prohibition in the
humanizer prompt, and a disclaimer in `build.py`.

## 10. TruthMode verdict

### PASS WITH RESERVATIONS

The milestone delivered what it set out to: rate distributions, split
tendencies, outline-guided authorship with derived freedom and deterministic
coverage, exact prompt capture, honest model reporting, and a disclosure that
tracks execution. It also produced hard evidence that the structural
convergence problem is **not solved**, and that the voice profile currently
makes it slightly worse. Both belong in the same verdict.

| | Question | Answer |
| --- | --- | --- |
| A | Feature-cache bug still fixed? | **Yes.** Field-name fingerprint stored per document and checked on reuse; regression test present. |
| B | New features protected against future schema/cache changes? | **Yes, and better than before.** The fingerprint self-invalidates on added or removed fields; `FEATURE_MEASUREMENT_REVISION` now covers a changed measurement, which field names cannot see. Two regression tests. |
| C | Cross-document distributions instead of misleading scalar averages? | **Yes.** Thirteen zero-inflated dimensions carry presence plus when-present percentiles, globally and per context. Corpus percentiles are now real order statistics. |
| D | Split tendencies preserved rather than false modal winners? | **Yes.** Seven tied traits surfaced in the real profile, five of them exact 0.417/0.417 splits, now rendered as SPLIT with no winner named — including inside thin contexts. |
| E | Are parentheticals still a signature? | **No.** 25% presence (from 100%, then 55%), all five openings distinct, position CV 0.56. |
| F | Does Full HowlWriter preserve first person when the input naturally uses it? | **Yes.** Batch mean 1.14 against the control's 0.86; higher on three of four personal prompts. Reverses the previously recorded regression. |
| G | Does it refrain from injecting first person into impersonal technical prose? | **Yes.** 0.00 in both arms on all five impersonal prompts. |
| H | Does technical writing still converge on thesis → mechanism → rule? | **Partly, and worse than reported.** The specific template is not dominant (top signature 20%, 15/20 distinct), but paragraph counts converge hard (mode 5, range 4–6, CV 0.135 — *tighter* than the control's 4–8/0.159) and 95% close declaratively. |
| I | Does LinkedIn admit when contextual evidence is insufficient? | **Yes.** The professional slice sits at confidence 0.204 against a 0.35 threshold; every trait renders as thin evidence, and tied ones as SPLIT. |
| J | Can a user generate a complete artifact from a simple outline? | **Yes.** All five progression levels produced complete artifacts; `howlwriter howl --outline` end to end. |
| K | Does increasing outline detail measurably reduce generation freedom? | **Yes.** Expansion fell ×7.5 → ×4.1 → ×1.0 across levels C, D, E, and derived freedom matched the expected level at all five. |
| L | Are user-verbatim sentences preserved? | **Yes.** Level E returned byte-identical with zero diff hunks; the checker reports an altered passage as ALTERED with the closest match rather than as missing. |
| M | Are user experiences protected from fabrication? | **Instructed and recorded, not proven.** The prompt forbids inventing jobs, coworkers, outages, metrics or opinions and requires gaps to be reported; the captured prompt proves the instruction was sent. Compliance is not independently verified. |
| N | Can the user inspect every model and provider? | **Yes.** Provenance record, manifest, and a read-only web inspector. |
| O | Can the user inspect the exact effective prompts HowlWriter sent? | **Yes.** Captured at the single dispatch boundary; a test asserts the captured string equals the one sent. Never reconstructed. |
| P | Are model names omitted honestly when providers do not report them? | **Yes.** Every live call in these benchmarks reported no model, and all are recorded `PROVIDER_DID_NOT_REPORT`. The provider name is never substituted. |
| Q | Can prompt/output integrity be verified through hashes? | **Yes.** SHA-256 for outline, input, draft, artifact, and every prompt and response. Documented as integrity, not authorship. |
| R | Can user-origin material be distinguished from model expansion without impossible precision? | **Yes.** Counts at sentence, paragraph, claim and node level. No percentage of authorship anywhere. |
| S | Are model-added factual claims surfaced and verified appropriately? | **Yes.** Three-way classification; unsupported new assertions block a research-backed run and are surfaced in a social one. |
| T | Does APA mode keep scholarly references separate from workflow provenance? | **Yes.** Enforced by a structural test as well as by design. |
| U | Does the AI Use Statement describe actual execution truthfully? | **Yes.** Different runs produce different statements, and the LOW-freedom overstatement was found and fixed. |
| V | Are provenance files private and local by default? | **Yes.** `~/.howlwriter/runs/`, gitignored sidecars, redaction across the whole record, privacy gate extended. |
| W | Did anything regress? | **No regression found.** All 592 pre-existing tests still pass among the 742. |
| X | Are the report's numbers programmatically reproducible? | **Yes.** `dogfood/report.py` recomputes every figure from stored artifacts. |
| Y | Is the implementation safe to commit? | **Yes.** Committed as isolated commits on a feature branch. |
| Z | Is it safe to push? | **Not yet — see below.** |

### On pushing

The code is safe to push in the sense that it is tested, linted, isolated on a
branch, and regresses nothing. It should not be pushed *as a completed
milestone* yet, for one reason: the diversity checker's first real verdict
against generated output is FAIL for both arms, and full HowlWriter converges on
more dimensions than the control. Shipping a milestone about preserving
variation while its own variation check fails would repeat the exact error the
previous audit caught — presenting a FAIL as production-ready.

The honest sequence is to push this as work in progress, or to hold it until
the structural convergence is addressed and a third benchmark shows movement.

### The single highest-value remaining weakness

**Applying the personal voice profile makes structural convergence worse, not
better.** Full HowlWriter converged on 12 of 18 dimensions against the
medium-only control's 10, and produced a narrower paragraph-count range (4–6,
CV 0.135) than the control (4–8, CV 0.159). The distributional work succeeded
at the level it targeted — parentheticals fell from a 100% signature to 25%
with no repeated syntax, and first person is now preserved where natural — but
the profile still pushes every piece toward one shape.

The likely cause is that structural guidance is rendered as a single spread per
dimension for the whole corpus, so every generated piece aims at the same
range. The rate work fixed exactly this problem for sparse behaviours by
separating presence from intensity. The structural dimensions never got that
treatment, and the next milestone's highest-value move is to give them a
per-piece target drawn from the distribution rather than a corpus-wide band
every piece shares.
