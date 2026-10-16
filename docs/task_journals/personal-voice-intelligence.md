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

## Milestone 3 (authorship, profiles, calibration fixes)

- Owner attested 31 documents through grouped review (12 + 2 light AI editing,
  14 human, 3 worksheets answers-only); one attestation was corrected to
  third-party after its contents showed it was an institutional letter.
  Two documents' categories were corrected from professional to academic
  (a course midterm, a lab worksheet) so academic work cannot fill the
  professional profile.
- Families: generic assignment numbering no longer links documents (on the
  real corpus it joined unrelated courses and pushed the holdout to 12/27).
- Naturalness: length-weighted calibration (v2). Real corpus: length vs
  unweighted index rho -0.67 -> -0.12 after weighting; scores withheld when
  fewer than 8 comparable references exist. Reports state resolution.
- Citation preservation: multi-word organisational authors, multisets.
- Voice activation verified through the real `howl` pipeline with a recording
  dispatcher (zero-change): the request carried the `william-academic` block,
  provenance recorded requested/applied/loaded; automatic professional
  selection refused with zero provider calls; a nonexistent voice stopped the
  run with no output. Local model generation was refused by HowlPlane's RAM
  gate (RESOURCE_CONSTRAINED); writing roles are unbound in HowlPlane config.

## Milestone 4 (Voice Workshop, commit c73f562)

- `voice workshop` CLI and web Workshop tab: local prompt bank, verbatim
  private samples, explicit approval, fixed train/calibration sides,
  duplicate and repeated-prompt protection, capped down-weighted bundles kept
  out of scoring references, evidence coverage without percentages.
- No real workshop samples exist yet (feature delivered, not yet used).

## Real-drive state (last scan)

- 659 files: 469 non-prose; 188 eligible (105 extracted, 2 credential-shaped
  excluded before analysis, 4 too small, 3 legacy .doc, 70 native
  placeholders, 4 native-type read failures); 2 names unstattable by the mount.
- Content coverage 57% of eligible files.
- Legacy reconciliation: 70 historical sources, all matched by path, none
  changed; 15 legacy-trained sources (about 18% of legacy training words)
  excluded as non-William or publisher text.
- Pending authorship reviews: 0.
- `william-academic`: BUILT. 30 attested documents (46,149 words), 23 train /
  6 holdout (family-aware), sufficiency strong, holdout validation
  MEDIUM_LOW. Voice Match: 29 genuine calibration documents, 4 comparison
  documents, AUC 0.784 (95% 0.583-0.986): CALIBRATED_UNVALIDATED.
  Naturalness: 25 reference documents, control AUC 0.814: VALIDATED.
- `william-professional`: NOT BUILT. 0 attested professional documents;
  professional writing is in native Google Docs.
- Drive API fallback: implemented, not run; owner is setting up the OAuth
  client (read-only Drive scope).

## Tests

- Full suite on the final tree (c73f562): 1391 passed, 0 failed, 0 skipped
  (HowlPlane installed editable in the venv, as the CI contract job does;
  pinned howl-provider-core installed).

## Next Step

1. When `~/.howlwriter/credentials/google_drive_readonly_token.json` exists:
   `howlwriter voice scan --identity william --google-api`, review the
   recovered professional candidates, then
   `howlwriter voice build-identity --identity william --profiles professional`.
2. More comparison-author prose would let Voice Match reach VALIDATED (needs
   at least 5 comparison documents and an AUC interval lower bound of 0.70).

## Update 2026-10-16: Google Docs, both profiles, voice fidelity

Sanitized: counts and decisions only.

- Read-only Drive OAuth completed by the owner; 65 native Google Docs
  exported and processed locally (9 native files were not single Docs).
- All authorship decisions were made by the owner (51 recorded at that point;
  4 new candidates surfaced later and are pending). Documents produced with
  HowlWriter and the voice profile were recorded as mixed authorship with no
  attested paragraphs, so they never train the profile (no feedback loop).
- `william-professional` built from 3 documents (limited, no holdout; Voice
  Match not usable yet). `william-academic` rebuilt: 29 train / 7 holdout.
- Bugs found on the real corpus and fixed with tests:
  - an unmounted FUSE drive was scanned as "everything removed" (#25);
  - exported Google Docs were attested but never reached a profile (#25);
  - exported Google Docs kept one line break per paragraph, so whole
    documents read as two or three paragraphs; the profile told the model
    "paragraphs typically 10-127 words (mean ~889)". Exports are now one
    paragraph per block (the raw hash is unchanged, so decisions hold);
  - the build reused cached measurements when only paragraph breaks changed
    (its content hash ignores layout); reuse now also needs the exact text;
  - a decision without a category followed later re-classification, which
    moved one attested professional document out of its profile; decisions
    now pin the category shown when decided.
- After the fixes the academic description reads paragraphs 7-115 words
  (mean ~77), 1-6 sentences (mean ~3.6).
- Voice fidelity for drafting: style-example bank per profile (training
  documents only, private), drafts in parts sized for the model, one measured
  revision pass per part guarded by marker/number checks, scores in provenance.
- Academic Voice Match after the rebuild: AUC 0.80, interval lower bound below
  the 0.70 validation floor; more comparison-author prose is still the way to
  validate it.
