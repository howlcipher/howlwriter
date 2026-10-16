# Task Journal: Source Intelligence and Browser-Assisted Research

Sanitized by design: counts, states, and decisions only. No document titles,
excerpts, packet contents, or screenshots. Private project data lives in
`~/.howlwriter/projects/<id>/`, never here. Design: `docs/source-intelligence.md`.

## State

- Branch: `feat/personal-voice-intelligence` (continues the Voice
  Intelligence work; based on `origin/main` 6c558bf).
- Voice Intelligence preserved: `william-academic` not rebuilt; legacy
  `william` / `william_v2` untouched; `william-professional` still pending
  (needs the Google Docs OAuth step, unchanged from the previous mission).

## Architecture decisions

1. **One subsystem, `howlwriter.projects`**, reusing the corpus extractors,
   the identity privacy guard and exclusion policy, the requirement-line
   extractor, the voice selection layer and `render_profile`, the HowlPlane
   writer role, and the web job manager. No parallel writing framework.
2. **Four stores, four provenances**: requirements (instructions/rubrics
   only), evidence (located, status-tagged), voice (untouched), actions
   (append-only audit). Nothing in `projects` writes to voice data; a test
   proves the voice and identity trees are byte-identical after a scan and a
   draft.
3. **Proof needs observation evidence.** Requirements of kind experiment /
   evidence / comparison are satisfied only by the user's captures,
   screenshots, data or lab observations; screenshots need an image;
   comparisons need two sources. Instructions and references never count.
4. **Evidence markers as citations** (`[ev-…]`), so the validator can check
   fabricated citations, numbers absent from cited evidence, instructions
   cited as observations, and coverage mechanically.
5. **Browser: Playwright library in-process**, not the Playwright MCP server
   or raw CDP: enforcement (allowlist, read-only by HTTP method, approval
   gates, graded-submission refusal) must be our code, not an agent's
   discretion. Private pipe, no debugging port, dedicated profile. MCP
   evaluated and documented as the right tool for agent-driven use.
6. **Heavy work governed** (added after the first real scan pinned the CPU
   for two hours on one screenshot): a separate worker process at
   `SCHED_IDLE` + nice 19, 2 threads, 4 GiB memory cap, per-job deadline with
   kill-and-restart, load-average backoff, images downscaled before OCR;
   external tools at the same priority.
7. **Local-first.** OCR (RapidOCR/ONNX), ASR (faster-whisper), ffmpeg, TShark
   or dpkt all run locally. Remote inference is a separate, recorded,
   per-project authorization; local providers (Ollama, llama.cpp) need none.

## Supported formats (actual)

PDF (page text; image-only pages OCR'd), DOCX/ODT/RTF/HTML/MD/TXT (by
section), PNG/JPEG/GIF/BMP/TIFF/WebP (OCR with boxes and confidence),
MP4/WebM/MKV/MOV (timed transcript + sampled-frame OCR), common audio
(transcript), PCAP/PCAPNG (TShark via flatpak, dpkt fallback), CSV/LOG/JSON
(line blocks), web pages (browser research). Google Docs via the existing
Voice Intelligence Drive API fallback.

## Security decisions

- Workspace private (0700/0600), refused inside a Git worktree.
- A project authorizes its folder only; web route refuses roots, home, and
  `~/.howlwriter`.
- Symlinks never followed; identity exclusions inherited; browser profiles
  and caches inside project folders never entered (found one in a real lab
  folder: it held a saved automation profile).
- Packet payload bytes never stored; URL query strings redacted.
- Browser secrets filled from environment variables and redacted.

## Bugs found by dogfooding and tests (all fixed)

- OCR on default ONNX Runtime threading hung on one real screenshot for two
  hours at full CPU -> governed worker (same image: 13.7 s).
- Duplicates inherited the original's category even for images whose name
  carries the role -> classified by their own name.
- Image-only PDF pages failed OCR when the render cache did not exist yet.
- Imperative requirements ("Cite at least two sources") were missed by the
  modal/bullet extractor -> imperative detection in the projects layer.
- A text log satisfied a screenshot requirement by shared words -> proof by
  requirement kind.
- The skeleton cut an IP address into a different number -> clipping at word
  boundaries.
- A file first scanned with OCR/transcription off was never reprocessed when
  they were enabled -> extraction options are part of the incremental check.
- Transcription failed on both real videos: faster-whisper's file decoding
  calls a PyAV API that PyAV 19 removed -> the worker passes the 16 kHz PCM
  it already decoded with ffmpeg.
- Interrupted scans stayed "running"; deleted originals left duplicates
  orphaned; unchanged duplicates were re-hashed every rescan -> fixed.
- The validator split quoted bullets into sentences and treated file names
  in citations as claims -> bullet items are one claim unit; citation text
  counts as present.
- Prompts reached 100 k characters for a 50-requirement lab -> evidence in
  the prompt is capped (60 items, 500 chars each).

## Tests

Final regression on the final tree (all tests, including docs and HowlPlane
contract tests): 1498 passed, 0 failed, 0 skipped (1391 before + 107 in
`tests/projects`). `flake8 src/ --select=F821,F401` clean; new code clean
under `setup.cfg` (110 columns); every changed file compiles on Python 3.11.
Real-engine tests ran locally (RapidOCR, TShark via flatpak, ffmpeg,
headless Chromium); in CI they skip where an engine is absent, and the
policy tests run everywhere.

## Dogfood (real course folders; counts only)

Lab folder A (1,162 files; instructions PDF, rubric image, 2 videos of 7 and
22 minutes, 6 distinct captures, ~470 screenshots, prior drafts and tooling):

- First full scan: 1,162 files, 0 failed, 1,680 evidence items, 48 min;
  471 OCR jobs, 0 timeouts; scanning process <15% of a core, worker ~2 cores
  at SCHED_IDLE, 12-core load ~2.2-3. 234 duplicates extracted once; one
  saved browser profile and one symlink not entered.
- Incremental rescans: newly supported rules/scripts/subtitles and key
  material picked up without re-reading anything else; both videos
  transcribed locally (29 min of audio in 2 min 39 s at idle priority);
  reclassification under new rules from stored text in 5-9 s, no OCR.
- A. 50 requirements, each cited to its PDF page; questions now wait for an
  answer in the draft.
- B. TShark: TLS 1.2 handshakes with certificates in cleartext vs TLS 1.3
  with certificates encrypted, cited by frame range; deterministic
  before/after capture comparison.
- C. Timestamped transcript segments and 54 OCR'd frames; subtitles parsed
  directly.
- D. Rubric image: 109 OCR lines with boxes; original hash recorded.
- E/F/G. Local test site: research read with provenance and injection flag;
  off-allowlist origin blocked; observe mode left lab state unchanged while
  blocking a page script's POST; interactive mode refused "Submit
  assignment", ran one approved experiment, recorded it as approved
  automation. (Test-site records were archived out of the real project.)
- H. `william-academic` selected automatically; the recorded writer request
  carried the voice block and 60 evidence markers (48 k chars, bounded);
  voice profile and identity ledger byte-identical before and after.
- I. Evidence skeleton: 94 citations, 0 integrity issues, 7 `[MISSING]`
  placeholders, verdict INCOMPLETE; a fabricated draft: BLOCKED.
- Grounding hazard found and fixed: rendered pages of earlier reports and
  frames of the instructor video were counted as observations and
  "satisfied" most experiment requirements. After the fix: 8 satisfied by
  real logs and screenshots, 41 pending.

Lab folder B (80 files, 29 MB capture):

- J. CLI scan interrupted with Ctrl-C after 2 files (exit 130, state
  "interrupted"); resume read the other 78 only; a further rescan read 0
  files in 1.1 s.

## Remaining

- Classification is heuristic: a contact sheet of video frames still passed
  as a screenshot; `project classify` corrects it and the correction sticks.
- "Appears answered" for questions is lexical; the reason asks the user to
  confirm.
- Real model drafting is untested end to end here: HowlPlane has no writer
  role bound and refused the local model on RAM. The prompt, voice block,
  provenance, and the remote gate are verified with an in-process recorder.
- Voice Match validation and `william-professional` remain as in the Voice
  Intelligence journal.

## Exact next commands

```
howlwriter project open "<folder>"                 # or: project scan <id>
howlwriter project requirements <id>
howlwriter project draft <id> --skeleton --out draft.md
howlwriter project validate <id> draft.md
howlwriter voice google-auth                       # then: voice scan --identity william --google-api
```
