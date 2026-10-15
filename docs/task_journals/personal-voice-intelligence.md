# Task Journal: Personal Voice Intelligence

Sanitized by design: counts, states and decisions only. No document titles,
paths inside the drive, or text. Private details live in the identity ledger
(`~/.howlwriter/identities/william/`), never here.

## Summary

Implement the HowlWriter Personal Voice Intelligence system (drive scanner
with mandatory exclusions, authorship review, `william-academic` and
`william-professional` profiles, calibrated Naturalness and Voice Match,
drift, before/after comparison, CLI, web UI) and dogfood it on the owner's
mounted cloud drive.

- Branch: `feat/personal-voice-intelligence` (based on `origin/main` 6c558bf)
- Design and method: `docs/voice-intelligence.md`

## Pre-flight (recorded before any change)

- Baseline suite on `main`: 1151 passed, 14 failed, 5 skipped. All 14
  failures are `tests/native/test_native_pipeline.py` and share one
  environment cause: `howl_provider_core` is not installed in the local venv.
- Git privacy audit: existing ignore rules worked; identity ledgers, chat
  exports, Google tokens/client files and review worksheets were NOT covered.
  No private voice data found in history (only `VoicesPanel.tsx` matched,
  which is legitimate source).
- Drive mount: the cloud-drive client FUSE (`fuse.exfs`), listable. Native Google files
  are listed but reads are refused (EPERM). No xattrs; inode numbers are
  session-assigned.

## Progress Log

1. Shared infrastructure fixes found during dogfood:
   - `Document.parse` raised `ValueError: substring not found` when an
     abbreviation split fell across a newline; merged sentences are now
     character spans (exact offsets).
   - DOCX/ODT inflated body parts without limits and read files twice; now a
     single read with a bounded archive reader. PDFs capped at 400 pages.
2. Identity layer `src/howlwriter/voice/identity/`: exclusions, privacy,
   store, provenance, classify, analysis, scanner, review, profiles, chat,
   google_fallback, status.
3. Scores `src/howlwriter/evaluation/`: empirical, naturalness, voice_match,
   drift, perturb, personal. `WritingReport.voice_match` now filled from
   calibrated profiles in howl, humanize and academic pipelines.
4. `build_voice` gained `selection=` and `artifacts=` (backward compatible).
5. CLI: `evaluate`; `voice scan|review|build-identity|sync|status|chat-import|google-auth`.
6. Web: `/api/voice-intel/*` and the Voice Intelligence tab (bundle rebuilt).
7. Defects found by dogfood or tests and fixed: whole-scan abort on one bad
   document; 211 readable extensionless files misreported as cloud
   placeholders; software licence texts classified as academic papers;
   coursework hidden when the context classifier abstained; resume needed
   sources saved at scan start; Git-ignore probe for not-yet-created
   directories; case-sensitive byline fields; reopened decisions dropping out
   of the queue; capped shared-run search making pasted-AI detection inert;
   multi-line f-strings that broke Python 3.11 compatibility.

## Real-drive state (last scan)

- Files inventoried: 659 (3 excluded directories skipped before traversal,
  0 symlinks followed)
- Eligible prose-bearing files: 188; read successfully: 107 (105 extracted,
  2 credential-shaped files excluded before analysis); native Google files
  unavailable through the mount: 70; unreadable or failed: 9
- Content coverage: 57% of eligible files (incomplete: native Docs)
- Academic candidates: 38; professional candidates: 4
- Pending authorship reviews: 37; attestations recorded: 0
- Profiles: not built (no attested documents). Existing legacy voices
  `william` and `william_v2` untouched.

## Test state

- Full suite after implementation: see the final handoff in the PR; the
  14 baseline native failures are unchanged and unrelated.

## Next Step

1. Owner attests authorship (`howlwriter voice review --identity william
   --interactive`, the worksheet, or the web Review view).
2. Optionally enable the Drive API fallback (`voice google-auth`, then
   `voice scan --google-api`) to read the 70 native Docs; most professional
   writing is there.
3. `howlwriter voice build-identity --identity william`, then record the
   calibration outcomes (counts and AUCs only) here.
