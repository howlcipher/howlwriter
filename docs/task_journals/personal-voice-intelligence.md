# Task Journal: Personal Voice Intelligence

Sanitized by design: counts, states and decisions only. No document titles,
paths inside the drive, or text. Private details live in the identity ledger
(`~/.howlwriter/identities/william/`), never here.

## Summary

Personal Voice Intelligence for HowlWriter: read-only drive scanner with
mandatory exclusions, legacy corpus recovery, authorship review,
`william-academic` and `william-professional` profiles under identity
`william`, calibrated Naturalness and Voice Match, drift, revision comparison,
strict voice activation, CLI and web UI. Design: `docs/voice-intelligence.md`.

- Branch: `feat/personal-voice-intelligence` (based on `origin/main` 6c558bf),
  not pushed, not merged.
- Legacy profiles `william` and `william_v2`: frozen. Content never modified;
  file modes tightened 0644 -> 0600 (logged privately).

## Environment finding

The 14 "baseline failures" in `tests/native` were environmental: the local
venv predated the pinned `howl-provider-core` dependency and was never
re-synced. Installing the exact pinned commit (5837d46) into the venv with
`uv pip install` fixed all 14; no dependency declaration changed.
Baseline on 729e3b4 with the correct environment: 1319 passed, 5 skipped.

## Milestone 1 (commit 729e3b4)

Scanner, identity ledger, classification, review, profiles, scores, drift,
comparison, chat evidence, Drive API fallback, CLI, web tab.

## Milestone 2 (recovery, refinement)

- Legacy corpus recovery (`voice legacy-reconcile`): legacy sources matched by
  path, then by raw-text hash; private reconciliation ledger.
- Publisher worksheet segmentation: answer lines proposed as the only usable
  text (`MIXED_AUTHORSHIP` + `worksheet_answers`); measured answer share on
  real worksheets 4-48%.
- Document families; family-aware holdout split (revisions and template
  siblings never straddle train/holdout).
- Review: value ordering, assistance fields, grouped review with exact-member
  confirmation (CLI and web), category descriptions.
- Strict voice selection layer: names, paths, ambiguity, explicit failures,
  load guard, requested/applied provenance; `--identity/--auto-voice/
  --allow-generic` on humanize, howl, paper; evaluate rejects a missing
  explicit voice; web academic route validates spec voices.
- Drive API fallback: Docs API tabs, pagination, backoff, unstattable names.
- Voice Match: non-pooled style-altered diagnostics.
- Fixed: colon-containing file names were mangled by a prefix-stripping idiom
  (now explicit `source_path`); worksheet header threshold; profile exports
  detected from content; scan report gained an `accounting` block.

## Real-drive state (last scan)

- 659 files: 469 non-prose; 188 eligible (105 extracted, 2 credential-shaped
  excluded before analysis, 4 too small, 3 legacy .doc, 70 native
  placeholders, 4 native-type read failures); 2 names unstattable by the mount.
- Content coverage 57% of eligible files.
- Legacy reconciliation: 70 historical sources, all matched by path, none
  changed; 41 used / 34 trained historically; recommendations: 3 answers-only
  candidates, 27 pending review, 40 excluded; 15 trained sources (18% of
  legacy training words) now excluded.
- Pending authorship reviews: 32. Attestations: 0.
- Profiles `william-academic`, `william-professional`: not built (no
  attestations). Professional evidence essentially absent from readable files.
- Drive API fallback: implemented; not run (no OAuth client or token).

## Tests

- Full suite after milestone 2: 1364 passed, 5 skipped, 0 failed (rerun on the
  committed tree is recorded in the commit/handoff).

## Next Step

1. Owner decisions on the consolidated review queue (grouped review).
2. Optional: OAuth client + `voice google-auth`, then `voice scan --google-api`
   to recover the 70 native Docs (most professional writing).
3. `voice build-identity --identity william`; record calibration counts/AUCs
   here; compare against `william_v2`; dogfood evaluation and generation.
