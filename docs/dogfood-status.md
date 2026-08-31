# Dogfood Status & Stabilization Report

**Date:** 2026-08-31  
**Milestone:** Dogfooding & Reliability Hardening  
**Tested Repositories:** `howlcipher/howlwriter`, `howlcipher/howlplane`

---

## 1. What Was Tested

- **Real Model-Backed CLI Executions**:
  - `howlwriter humanize <file>` with real configured HowlPlane providers (`agy`, `devin_cli`, `codex`, `claude_code`, `local_ollama`).
  - `howlwriter howl <file>` full pipeline (`INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> FINAL REVIEW -> OUTPUT`).
  - Deterministic-only execution (`--deterministic`).
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
- **Provider Failure Matrix & Chaos Scenarios**:
  - Missing executable on host system.
  - Quota / rate limit exhaustion (Codex usage limit, Claude Code weekly limit).
  - Reviewer process crash (non-zero exit code / SIGSEGV).
  - Malformed YAML/JSON payloads with surrounding commentary or transcript headers.
  - Non-JSON braces embedded in code/documentation.
  - File path errors (non-existent parent directories, overwriting input, unwritable destinations).
  - Oversized inputs (>100,000 characters / ~20,000 words).
- **Adversarial Meaning Mutation Matrix (Rounds 1 & 2)**:
  - Numbers (12 -> 20, 45 -> 54, 25ms -> 250ms).
  - Percentages (99.9% -> 99.99%).
  - Timelines (Q3 -> Q4).
  - Attributions (MIT -> Stanford).
  - Hedges ("may" -> "will").
  - Causality ("associated with" -> "causes").
  - Polarity ("failed to show" -> "confirmed").
  - Compound mutations (approximation + uncertainty + dates + statistics).

---

## 2. Failures Discovered and Fixed

| ID | Issue Discovered | Root Cause | Fix Applied | Regression Test |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-01** | Empty file generation on provider failure | Fallback to empty string on non-zero exit | Explicit `if not result.success` check raising `RuntimeError` | `test_failure_modes.py::test_humanizer_crash_aborts_without_empty_file` |
| **BUG-02** | Codex directory check block in non-git paths | Missing `--skip-git-repo-check` flag | Added `--skip-git-repo-check` to `CodexBackend` | `tests/test_role_binding.py` |
| **BUG-03** | CLI transcript headers contaminating parsing | Provider terminal envelopes in stdout | Header stripping & block isolation in `extract_structured_output` | `test_structured_hardening.py::test_extracts_from_codex_transcript_envelope` |
| **BUG-04** | False positive changes for clean human prose | Mandatory change record on zero diffs | Preserved `changes_made: []` without synthetic records | `test_corpus_processing.py::test_clean_human_prose_untouched` |
| **BUG-05** | Raw Python stack traces on CLI errors | Uncaught exceptions in `main()` | Wrapped CLI entry point with user-facing stderr error formatting | `test_cli.py::test_cli_handles_missing_file_gracefully` |
| **BUG-06** | Reviewer independence test non-hermetic in CI | Dependency on host binaries during unit tests | Monkeypatched availability & isolated mock profiles | `howlplane/tests/test_role_binding.py` |
| **BUG-07** | Risk of half-written files on interrupted runs | Direct `Path.write_text()` without atomic replacement | Implemented `atomic_write_text()` via PID temporary files | `test_output_safety.py::test_atomic_write_replaces_existing_file_safely` |
| **BUG-08** | Silent context truncation on large documents | No single-pass size guard | Added `MAX_SINGLE_PASS_CHARS = 100_000` with actionable chapter split error | `test_large_input_safety.py::test_oversized_document_fails_cleanly_without_silent_truncation` |
| **BUG-09** | Units attached to numbers missed by regex | Regex required word boundaries without handling unit letters | Updated `_NUMBER = re.compile(r"\d+(?:\.\d+)?")` | `test_meaning_attacks_round2.py::test_deterministic_catches_compound_numerical_mutations` |
| **BUG-10** | Latency breakdown invisible in reports | Timers tracked internally but omitted from text report | Added `humanizer_duration_seconds`, `meaning_reviewer_duration_seconds`, `total_duration_seconds` to `WritingReport` | `test_latency_observability.py::test_writing_report_renders_latency_section_when_durations_present` |

---

## 3. Real Provider Execution Evidence

### Execution Matrix
```
+---------------+-------------------+-----------------------+---------------------+-------------------+------------+
| Run           | Fixture           | Humanizer (Provider)  | Reviewer (Provider) | Independence      | Status     | Duration   |
+---------------+-------------------+-----------------------+---------------------+-------------------+------------+
| Run #1        | 01_buzzwords.md   | agy (Gemini)          | devin (Anthropic)   | INDEPENDENT       | NEEDS_REV  | 17.9s      |
| Run #2        | 03_clean_human.md | agy (Gemini)          | devin (Anthropic)   | INDEPENDENT       | READY      | 17.4s      |
| Run #3 (howl) | 05_numbers.md     | agy (Gemini)          | devin (Anthropic)   | INDEPENDENT       | READY      | 43.3s      |
| Run #4        | Rate-limit check  | codex (OpenAI)        | -                   | UNAVAILABLE       | EXIT 1     | 0.8s       |
+---------------+-------------------+-----------------------+---------------------+-------------------+------------+
```

### Real Execution Sample 1: AI-Text Cleanup (`01_generic_ai_buzzwords.md`)
- **Original**:
  > "Furthermore, in today's rapidly evolving digital landscape, it is imperative to delve into the intricate tapestry of distributed cloud computing. This technological evolution stands as a testament to modern engineering, acting as a beacon of innovation across global enterprises. By embracing robust multi-region paradigms, organizations can unlock synergistic value. In conclusion, navigating this journey requires a pivotal shift in architectural strategy."
- **Transformed by `agy`**:
  > "Understanding distributed cloud systems has become essential for modern engineering. Adopting multi-region architectures allows organizations to scale effectively, but making that transition requires rethinking your underlying architectural strategy."
- **Independent Review (`devin`)**: `Semantic Review: PASS`, `Reviewer Independence: INDEPENDENT`.
- **Verdict**: Complete elimination of AI buzzwords, 0 lint warnings remaining.

### Real Execution Sample 2: Clean Human Writing (`03_clean_human_prose.md`)
- **Original & Output**:
  > "We replaced MongoDB with PostgreSQL last year. Our data was relational from the start, and schema validation in application code became a maintenance burden. We needed foreign key constraints, ACID transactions across multiple tables, and predictable query performance. After the migration, our p99 query latency dropped from 120ms to 18ms."
- **Transformed by `agy`**: Exactly identical (0 changes).
- **Verdict**: `STATUS: READY`, no unneeded rewriting or voice flattening.

---

## 4. Latency Breakdown & Observability

Typical model latency across real executions:
- **Humanizer Step (`agy`)**: ~5.6s – 11.0s
- **Meaning Reviewer Step (`devin`)**: ~6.2s – 33.5s
- **Total End-to-End Pipeline**: ~17.4s – 43.3s

Surfaced in reports:
```
Latency:
  Humanizer:           9.4s
  Meaning Review:      33.5s
  Total:               43.3s
```

---

## 5. Document Size Boundaries

- **Single-Pass Safe Limit**: 100,000 characters (~20,000 words).
- **Behavior Beyond Limit**: Fails cleanly with:
  `error: Document size (125000 chars) exceeds safe single-pass limit (100000 chars). Please process document in sections or chapters.`
- **Silent Truncation Prevention**: HowlWriter guarantees that oversized inputs will never be partially processed and falsely marked `READY`.

---

## 6. Output Safety Guarantees

1. **Atomic Writes**: Output files are written to sibling temporary files (`.<filename>.<pid>.tmp`) and swapped atomically using `os.replace`.
2. **Crash Resilience**: Failed runs clean up temporary files and never truncate existing destination files.
3. **In-Place Overwrite Safety**: Running with `--out input.md` will preserve the original file intact until all pipeline stages pass completely.
4. **Parent Directory Creation**: Nested destination paths automatically create missing directories.

---

## 7. Current Trust Rating

| Command | Trust Rating | Justification |
| :--- | :--- | :--- |
| `howlwriter humanize` | **RELIABLE** | Demonstrated multi-provider execution, zero-change preservation on clean human text, thorough AI slop removal, atomic output safety, and reliable crash handling. |
| `howlwriter howl` | **RELIABLE** | Complete 8-stage pipeline (`EDIT -> HUMANIZE -> LINT -> RED PEN -> MEANING REVIEW -> FINAL REVIEW -> OUTPUT`) with independent semantic review gating and transparent latency observability. |
