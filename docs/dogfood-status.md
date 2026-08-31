# Dogfood Status & Stabilization Report

**Date:** 2026-08-31  
**Milestone:** Stabilization & Real Model-Backed Dogfooding  
**Tested Repositories:** `howlcipher/howlwriter`, `howlcipher/howlplane`

---

## 1. What Was Tested

- **Real End-to-End CLI Executions**:
  - `howlwriter humanize <file>` with real configured HowlPlane providers (`codex`, `agy`, `devin_cli`, `claude_code`).
  - `howlwriter howl <file>` full pipeline (`INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> FINAL REVIEW -> OUTPUT`).
  - Deterministic fallback modes (`--deterministic`, `--safe-only`, `--apply`).
  - Missing and unconfigured role states (`ModelRoleNotConfiguredError`).
- **Dogfood Corpus (15 Checked-In Fixtures in `tests/fixtures/dogfood_corpus/`)**:
  1. `01_generic_ai_buzzwords.md`: Heavy AI clichés and empty transitions.
  2. `02_mostly_good_ai.md`: Technical prose with minor AI tone.
  3. `03_clean_human_prose.md`: High-quality human writing requiring zero changes.
  4. `04_technical_exact_terms.md`: Low-level systems terminology (`mmap`, `epoll_wait`, `O_DIRECT`, `CAS`).
  5. `05_prose_with_numbers.md`: Exact numerical metrics (`12 engineers`, `45 microservices`, `3 data centers`).
  6. `06_prose_with_percentages.md`: SLA metrics (`99.9% uptime`, `42.5% latency reduction`, `0.01% error rate`).
  7. `07_prose_with_dates.md`: Timelines (`March 15, 2024`, `Tuesday 2:00 PM EST`, `Q3`).
  8. `08_prose_with_attribution.md`: Academic attributions (MIT, ACM studies).
  9. `09_hedging_uncertainty.md`: Deliberate uncertainty markers ("may indicate", "suggests", "could possibly").
  10. `10_informal_author_voice.md`: Conversational narrative and personal tone.
  11. `11_linkedin_short.md`: Short bulleted professional takeaways.
  12. `12_long_multi_paragraph.md`: Multi-paragraph technical essay with headings.
  13. `13_banned_words_and_patterns.md`: Configured banned words and repetitive sentence starters.
  14. `14_subtle_meaning_fragile.md`: Security vulnerability disclosure where claim shifts alter safety guarantees.
  15. `15_code_and_quotes.md`: Embedded markdown code blocks and Dijkstra blockquotes.
- **Meaning-Preservation Gate Attacks**:
  - Number mutations (12 -> 20, 45 -> 54).
  - Percentage mutations (99.9% -> 99.99%).
  - Date mutations (Q3 -> Q4).
  - Attribution drops and replacements (MIT -> Stanford).
  - Hedge removal and certainty inflation ("may" -> "will").
  - Causality escalation ("associated with" -> "causes").
  - Polarity reversals ("failed to show" -> "confirmed").

---

## 2. What Failed (Bugs Discovered During Real Dogfooding)

1. **Silent Empty File Generation on Provider Failure**:
   - *Symptom*: When `codex` failed to execute on `/tmp/demo_input.md` due to untrusted workspace checks, `ModelHumanizerRewriter` fell back to `result.raw_output.strip()` (`""`) and silently generated an empty document.
   - *Impact*: Corrupted user documents without alerting the operator to provider errors.
2. **Codex Git Repository Check Block**:
   - *Symptom*: `codex exec` failed when invoked in directories outside a git repository (such as `/tmp` or scratch directories).
   - *Impact*: Prevented running HowlWriter against documents located in arbitrary paths.
3. **Structured Response Extraction with CLI Transcript Envelopes**:
   - *Symptom*: `codex exec` emits transcript metadata (`OpenAI Codex v...`, `user ...`, `codex ...`, `tokens used ...`). When output lacked markdown code fences, raw transcript headers contaminated extracted text.
4. **False Positive Change Records for Clean Text**:
   - *Symptom*: When the model determined zero edits were required (`changes_made: []`), `ModelHumanizerRewriter` fell back to adding a generic `ChangeRecord("Model-backed humanization rewrite")`.
5. **Raw Tracebacks on Configuration and File Errors**:
   - *Symptom*: Bad config files or missing input paths caused unhandled Python exceptions instead of formatted CLI error messages.

---

## 3. What Was Fixed

1. **Strict Failure Propagation in `ModelHumanizerRewriter` & `RealModelMeaningReviewer`**:
   - `ModelHumanizerRewriter` now raises `RuntimeError` immediately if `result.success` is False or if the output is empty, preventing empty/corrupted file output.
   - `RealModelMeaningReviewer` now reports `verdict="FAIL"` and records the provider error when execution fails.
2. **`--skip-git-repo-check` in HowlPlane's `CodexBackend`**:
   - Added `--skip-git-repo-check` to `CodexBackend` so Codex can execute in any workspace directory.
3. **Robust Transcript & Code Block Parsing in `extract_structured_output`**:
   - Enhanced `extract_structured_output` to strip CLI transcript headers (`codex\n...tokens used`) and extract fenced or braced YAML/JSON blocks reliably.
4. **Preservation of Zero-Change Humanizer Decisions**:
   - `ModelHumanizerRewriter` now respects `changes_made: []` when human prose is clean and unchurned.
5. **Clean CLI Error Handling**:
   - Updated `main()` to catch `ValueError`, `FileNotFoundError`, `TypeError`, and `RuntimeError`, outputting formatted `error: <message>` to stderr with appropriate exit codes.
6. **Untouched Prose Instruction in Prompt Contract**:
   - Added explicit priority #8 and #9 to Humanizer contract instructing the model to leave clean sentences and unblemished human prose untouched.

---

## 4. Real Providers & Reviewer Independence Tested

| Provider Pair (Humanizer -> Meaning Reviewer) | Independence Status | Real Live Verification Outcome |
| :--- | :--- | :--- |
| `codex` -> `agy` | `INDEPENDENT` | **Verified**: Humanized with Codex, reviewed with Agy, status `READY`. |
| `codex` -> `codex` | `SAME_PROVIDER` | **Verified**: Correctly reports same-provider status without false claims. |
| `claude_code` (weekly quota reached) | `UNAVAILABLE` | **Verified**: Reports clear quota limit message, fails safely without silent corruption. |
| `nonexistent_provider` | `UNAVAILABLE` | **Verified**: CLI displays `error: Humanizer provider 'nonexistent_provider' failed: Agent 'nonexistent_provider' unavailable`. |

---

## 5. Meaning-Preservation Failures Found & Verified

- Every adversarial mutation (numbers, percentages, dates, attributions, hedges, causality escalation, polarity reversals) was successfully caught by deterministic diffs or semantic review.
- Any failed semantic review or unresolved deterministic difference reliably prevents `STATUS: READY`, forcing `STATUS: NEEDS_REVIEW`.

---

## 6. Current Reliability & Known Limitations

- **System Reliability**: The control plane execution, provider resolution, timeout handling, and verification gating are deterministic, robust, and leak-free.
- **Known Limitations**:
  - External CLI model latency: Real CLI tool execution takes ~20–50 seconds per stage depending on model load.
  - Large document chunking: Multi-thousand-line documents should be split by chapter/section for optimal model context windows.
  - Local Ollama requires at least 8GB available RAM and `qwen2.5-coder:7b-instruct` pulled.

---

## 7. Blockers to Daily Use

- **None** for CLI usage with configured providers (`codex`, `agy`, `devin_cli`, or `local_ollama`).
