# Personal Voice Intelligence

One person, several context profiles, two calibrated scores.

`voice build` (see [voice-corpus.md](voice-corpus.md)) turns a set of folders
into one profile. Personal Voice Intelligence sits on top of it for the case
where a person wants their writing understood the way they actually produce
it: a mounted drive inventoried once, every document classified and given a
provenance decision, separate **academic** and **professional** profiles built
only from documents the person has confirmed are theirs, and two independent,
empirically calibrated scores for any new document.

```bash
howlwriter voice scan --identity william --source "/path/to/mounted-drive/"
howlwriter voice review --identity william --interactive
howlwriter voice build-identity --identity william --profiles academic,professional
howlwriter voice inspect william-academic
howlwriter evaluate paper.md --mode academic --voice william-academic
howlwriter evaluate draft.md --compare revised.md --identity william --auto-voice
howlwriter voice sync --identity william
```

Nothing here replaces the corpus pipeline. Profiles are still built by
`build_voice`, stored by `VoiceStore`, and consumed by the Humanizer and
Writer through the existing `--voice` seam.

---

## 1. Mounted drive setup

The scanner reads a locally mounted drive (a cloud-drive FUSE client, rclone mount, a synced
folder). No Google OAuth is required to scan.

What was found on a real the cloud-drive client mount, and how it is handled:

| What the mount exposes | Handling |
| --- | --- |
| Regular files (`.docx`, `.pdf`, `.md`, ...) | read once, in binary, read-only |
| Native Google Docs/Sheets/Slides | small extensionless entries whose read is refused (`EPERM`). Recorded as `native_unavailable`, inventoried, not counted as read |
| Names the mount cannot stat (e.g. containing `:`) | recorded as `unreadable` |
| Small readable extensionless files (`LICENSE`, `release`) | non-prose (`no_extension`), not mistaken for placeholders |
| No extended attributes, session-assigned inode numbers | identity is relative path plus content fingerprint |

Coverage is reported honestly. When native documents cannot be read the scan
says `complete: false` and gives the share of eligible files whose content was
actually read.

### Optional: the Drive API fallback for native Google Docs

```bash
howlwriter voice google-auth          # one time; needs an OAuth Desktop client file
howlwriter voice scan --identity william --google-api
```

Off unless the flag is passed. It uses a separate token with the
`drive.readonly` scope only, exports native Docs as plain text, and analyses
them locally exactly like a mounted file. Nothing is sent to any model. Paths
are checked against the exclusions before any lookup, shared drives are not
queried, and a name that matches zero or several Docs is reported rather than
guessed. Drive revision history (count and span) is recorded as provenance.
Without the client file and token it refuses with an explanation; it never
prompts for authorization in the middle of a scan.

If your sync client can expose Google Docs as Office files instead, the
scanner will simply read those.

## 2. Directory exclusions

An identity carries an exclusion policy in its private `identity.yaml`. The
identity `william` is created with the three directories its owner asked
never to be traversed:

```
gemini gems, retroarchsaves, shared drives
```

Enforcement:

* checked **before** a directory is entered, so nothing inside is listed,
  statted, read, classified, cached, or reported;
* at every depth, on whole path components, case-insensitively, after NFKC
  normalization and with `_`, `-`, `.` and whitespace treated as one
  separator (`Gemini Gems`, `GEMINI_GEMS`, `GeminiGems` all match);
* never as a substring: `My Gemini Gems Notes.docx` is a file, not the
  directory;
* symlinks are never followed, and a directory whose real path leaves the
  root is refused;
* re-checked on every path that arrives from somewhere other than the walker
  (an old ledger, an edited worksheet, a preview request).

Add more with `--exclude NAME` (remembered). Version-control and dependency
directories (`.git`, `node_modules`, ...) are pruned as noise and counted.

## 3. Supported formats

Reused from the corpus pipeline, hardened for an untrusted drive:

`.docx` `.odt` `.rtf` `.txt` `.md` `.html` `.htm` `.pdf` (text layer, via the
optional `pypdf`), plus native Google Docs through the optional fallback.
`.doc` is reported as unsupported. Images, audio/video, archives,
executables, databases, game saves, logs, source code, configuration and
spreadsheets are inventoried and excluded with a stated reason.

Each file is read **once**; the same buffer is hashed, parsed, and inspected
for metadata, so a file changing mid-scan cannot produce a hash that describes
one version and text from another (a size/mtime change during the read is
retried, then recorded as `changed_during_read`). Office archive members are
inflated through a bounded reader (64 MB, at most 200:1 compression), PDFs
are capped at 400 pages, nothing is executed, and one malformed document
costs that document (`extraction_failed` / `analysis_failed`), never the scan.

## 4. Classification

Two separate axes.

**Category** (purpose and genre, from content): academic paper, discussion,
lab, research analysis, technical documentation, professional engineering
document, professional article, LinkedIn/public commentary, personal
writing, informal communication, notes and outlines, template, assignment
instructions, copied reference (including software licences), third-party,
AI-generated and mixed-authorship documents, résumé, administrative record,
non-prose, confidential, unknown. Built on the corpus pipeline's quality and
context classifiers, which treat folder names as a small capped prior only.
When the context classifier abstains, lab and citation markers get a second,
low-confidence look so that coursework is not silently kept out of review.

**Authorship** (provenance, not style):

| State | Use in a personal profile |
| --- | --- |
| `CONFIRMED_HUMAN_AUTHORED` | primary evidence, weight 1.0 |
| `HUMAN_AUTHORED_LIGHT_AI_EDITING` | weight 0.5 |
| `MIXED_AUTHORSHIP` | only the paragraphs the person lists |
| `SUBSTANTIALLY_AI_GENERATED` | never |
| `THIRD_PARTY` | never |
| `UNKNOWN_AUTHORSHIP` | never; held for review |

## 5. AI-assisted documents and the review workflow

A document's presence in someone's drive, or their name on it, is not
evidence that its wording is theirs. The scanner therefore only **proposes**
an authorship, with reasons drawn from evidence it can actually see:

* a name/author field naming the identity, or someone else;
* "shared with me" ownership;
* creation by a document-generation library (python-docx, ReportLab, pandoc);
* Word's recorded editing time far below typing time ("arrived by paste");
* modification before public LLM tools (30 Nov 2022), which makes substantial
  generation implausible and says nothing about who wrote it;
* the template owner recorded as the file's creator, reported as exactly that
  and never as "written by someone else";
* Drive revision history, when the fallback is used.

Style signals (dense formulaic phrasing, stock connectives) **raise review
priority only**. No stylometric signal can tell a person's unaided writing
from their AI-assisted drafts, and nothing here claims to.

`CONFIRMED_HUMAN_AUTHORED` is reachable only by attestation:

```bash
howlwriter voice review --identity william                 # list, with reasons
howlwriter voice review --identity william --interactive   # answer one by one
howlwriter voice review --identity william --preview DOC_ID
howlwriter voice review --identity william --set DOC_ID h
howlwriter voice review --identity william --set DOC_ID m --paragraphs "1-4,7"
howlwriter voice review --identity william --apply ~/.howlwriter/identities/william/review_queue.yaml
```

The queue lists only documents that would affect a profile; routine
exclusions (someone else's shared file, a licence text) do not interrupt.
The worksheet `review_queue.yaml` is regenerated each scan; decisions live in
`decisions.json` with an append-only `decisions.log.jsonl`, keyed by a stable
document id so a renamed file keeps its decision. Each attestation stores the
document's content fingerprint: a light edit carries it forward, a material
change reopens it. The web UI offers the same review.

Proceeding while reviews are pending is the normal case: profiles are built
from whatever has been attested and say how many relevant documents still
await a decision.

## 6. Private storage and Git protection

```
~/.howlwriter/identities/<identity>/      HOWLWRITER_IDENTITIES_DIR overrides
    identity.yaml  inventory.json  decisions.json  decisions.log.jsonl
    review_queue.yaml  scan_report.json  profile_changes.jsonl
    chat_evidence.json  calibration/naturalness-<context>.json
~/.howlwriter/voices/<identity>-academic/       HOWLWRITER_VOICES_DIR overrides
~/.howlwriter/voices/<identity>-professional/
    profile.json  sources.json  features.json  overrides.yaml  build.json
    calibration.json  supporting_evidence.json
```

* Directories 0700, files 0600 (profile directories are tightened after each
  build).
* Before anything is written, the target is checked: inside a Git worktree it
  must be ignored by Git (`git check-ignore`), or the write is refused.
* `.gitignore` covers identity ledgers, voices, worksheets, chat exports,
  Google tokens and client files, and private evaluation output, with
  narrow patterns that leave `frontend/src/components/voices/` and all source
  and tests tracked. A test asserts both directions and that nothing private
  is tracked.
* No document text is stored: inventories and calibrations hold hashes,
  numbers, labels and counts. Extracted text lives in memory during a scan or
  build. Scan reports, run records and the web status payload carry no file
  names. Previews re-read the source on demand and are never cached.
* `.gitignore` does not remove anything from history; this feature never
  committed private data, and the repository test checks tracked files.

## 7. Informal chat evidence

```bash
howlwriter voice chat-import --identity william --export ~/Downloads/chatgpt-export/
howlwriter voice chat-import --identity william --provisional   # no export available
```

From a ChatGPT data export (`conversations.json`), only user-authored message
text is read. Assistant, system, developer and tool messages are skipped by
role and hidden context by content type. Code blocks, log lines and quoted
lines are removed; a long heading-structured message that reads like a system
prompt, or one that repeats a 12-word run of the assistant's reply, is
excluded; repeated requests are deduplicated. What is stored is aggregate
statistics and a short list of tendencies, never message text.

It is supporting evidence only: it never sets a score baseline, never raises
profile confidence, and is attached to profiles as a separately attributed,
low-weight note rendered below the mode's rules. The academic profile receives
only formal-safe tendencies (concrete detail, low tolerance for filler,
explicit qualification). Without an export nothing is fabricated: the owner's
own observations are recorded as `provisional_unvalidated`.

## 8. The two scores

Both are **empirical percentiles**, computed independently from different
measurements, and both are withheld when the evidence cannot support them.

### Human Naturalness (0-100)

Eleven deterministic dimensions: sentence variation, paragraph variation,
repeated sentence openings, formulaic language (the existing lint and
humanization rule families), mechanical transitions, structural uniformity,
redundancy, repetitive conclusions, verbosity, readability for the context,
and sentence-to-sentence cohesion.

Each dimension is ranked against a **reference set of human writing in the
same context**, in its mechanical direction only: more variation than every
reference document is not a fault, less is. The overall score is the
percentile of the combined index among the reference documents' own
leave-one-out indices: **70 means less mechanical than 70% of the reference**;
50 is a typical reference document.

* Formal is not mechanical: passive voice, long words and academic register
  are not dimensions, and academic documents are ranked against academic
  references.
* The reference set is the identity's attested writing for that context
  (or any folder passed with `--naturalness-reference`).
* Validation: deterministic mechanical perturbations of the reference texts
  (stock connectives, recap closers, uniform paragraphs, restated sentences)
  plus any documents the person attested were AI-generated. The calibration
  records the AUC separating them from the reference; a score is labelled
  `VALIDATED` only when the 95% interval's lower bound clears 0.65.
* Unavailable below 250 words or 12 sentences, without a calibration, or with
  fewer than 12 reference documents.

It is not the probability that a human wrote the document and not an AI
detector, and it is not tuned against any third-party detector.

### Personal Voice Match (0-100)

Thirty-one features in eleven dimensions (cadence, sentence-length
distribution, paragraph structure, punctuation, word choice and diversity,
technical vocabulary, register and person, hedging and directness,
transitions, structure, reading level), compared to the profile through
floored robust z-scores, each dimension weighted equally.

The score is the percentile against **the author's own unseen writing**:
training documents measured leave-one-out, holdout documents against the full
profile. **40 means at least as close as 40% of the author's own held-out
documents.** A genuine document is as likely to score 20 as 80; that spread
is how much one person's documents differ. Bands make it usable:
`WITHIN_RANGE` (>= 25), `EDGE_OF_RANGE` (10-25), `ATYPICAL` (< 10).

The report also gives the share of comparison-author documents at least as
close. Comparison documents are prose by other people found in the corpus
(third-party documents and assignment instructions, never licence texts),
documents attested as AI-generated, and the same author's documents from the
other context. Their separation from the genuine distribution is reported as
an AUC with a Hanley-McNeil 95% interval.

Withheld, with the reason, when the profile has fewer than 8 genuine
calibration documents, the document is under 300 words, the document is a
training document or a near-duplicate of one (SimHash within 8 bits), or the
profile failed to separate the author from comparison documents (interval
upper bound below 0.60). `VALIDATED` requires a lower bound of 0.70 with at
least five comparison documents; otherwise the score is
`CALIBRATED_UNVALIDATED` and says why.

It is a similarity measure, not authorship detection.

### Confidence labels

Statistical statements (percentiles, AUCs, intervals, sample counts) are
reported as such. Heuristic labels (profile `overall_confidence`, review
priority, drift confidence by passage length) are named as heuristic.

## 9. Voice drift

The document is split into windows of at least 80 words and 3 sentences and
each window is compared with the same measurements over windows of the
profile's training documents (sentence length, long-word share, stock
transitions, padding, hedging, first person, passive constructions, commas,
repeated openings). A finding names the span, the observed value, the
reference passages' typical and 90% ranges, severity, and confidence;
adjacent windows departing the same way are merged. Windows under 120 words
only report extreme departures, at LOW confidence. Findings never say how a
passage was written.

## 10. Before-and-after comparison

```bash
howlwriter evaluate original.md --compare revised.md --identity william --auto-voice \
  --requirements reqs.yaml
```

Both versions are scored against the same profile. The report shows both
scores and deltas, changed dimensions, remaining drift, meaning preservation
(the existing `MeaningPreservationReviewer`), factual integrity (the existing
unit-aware `native.fidelity.compare`), citation preservation, and stated
requirements (`min_words`, `max_words`, `required_terms`,
`required_sections`). Any integrity problem makes the verdict
`REVISION_CHANGES_SUBSTANCE` (exit code 3) whatever the scores say.
Evaluation never rewrites; keeping the original is always a valid outcome.

## 11. Automatic profile selection

```yaml
# ~/.howlwriter/preferences.yaml   (HOWLWRITER_PREFERENCES_FILE overrides)
preferred_identity: william
```

`--auto-voice` uses that identity; `--identity` names one directly; `--voice`
names a profile. Routing: `--mode academic` → the academic profile;
`professional`, `linkedin`, `technical`, `documentation`, `email`, `article`
→ the professional profile; with no mode the document's own content
category decides. A missing or unvalidated profile produces a stated reason,
never a silently substituted profile. No identity is hardcoded into generic
behaviour.

## 12. Incremental rescanning

`voice scan` and `voice sync` (scan, then rebuild) compare each file's size
and modification time with the last scan and re-read only what changed.
Added, modified, removed and renamed files are reported; renames are matched
by content and keep their decisions. Scans checkpoint as they go, so an
interrupted scan resumes. A mount that is down fails the scan and leaves the
inventory untouched.

Profiles are never overwritten by worse evidence: a build is refused (and the
existing profile kept) when fewer than three attested documents qualify, or
when documents the profile was trained on are present but unreadable
(`--allow-shrink` overrides). Builds are atomic, and each one appends to
`profile_changes.jsonl`. No scan is ever scheduled automatically.

## 13. Models

Everything above is deterministic and local. `build-identity --model-traits`
additionally runs the existing HowlPlane `voice_analyst` trait analysis, which
sends cleaned document text to the configured provider; it requires
`--allow-remote-content`. Reading the drive and sending its contents to a
third party are separate permissions.

## 14. Web UI

The **Voice Intelligence** tab has four views: Corpus (mount status, counts,
coverage, rescan of configured sources), Review (pending documents with
reasons, one-click decisions, mixed-paragraph selection, on-demand preview),
Profiles (both context profiles with source counts, holdout counts,
calibration and validation status, characteristics), and Evaluate (both
scores side by side, dimension breakdown, drift, before-and-after). It cannot
choose new folders to read, it never shows a number the evidence does not
support, and it shows document text only in a requested preview.

## 15. Limitations

* Native Google Docs are invisible to the mount; without the Drive API
  fallback a corpus kept mostly in Docs cannot be read.
* Authorship cannot be inferred from style. Profiles are only as authentic
  as the attestations behind them.
* The Naturalness reference is the person's own attested writing unless
  another reference folder is supplied, so it measures "mechanical relative
  to this person's real writing in this context".
* Perturbation controls are a sensitivity test, not a model of AI writing.
* Comparison-author controls come from the same drive and may be few, so
  Voice Match discrimination is often `CALIBRATED_UNVALIDATED`.
* Small corpora make both percentiles coarse: with 12 reference documents
  each step is about eight points.
* Category and context classification are heuristic and correctable in review.
