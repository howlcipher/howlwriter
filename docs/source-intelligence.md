# Source Intelligence

Evidence-grounded projects: point HowlWriter at a folder of assignment
materials and it inventories them, extracts located evidence, builds a
requirements ledger, retrieves evidence per section, drafts in your selected
voice, and checks every citation and requirement before you hand anything in.
Browser research and lab interaction are optional and separately authorized.

```
howlwriter project open "/path/to/assignment"        # inventory + extract (resumable)
howlwriter project requirements "/path/to/assignment"
howlwriter project search  "/path/to/assignment" "TLS 1.3 certificate visibility"
howlwriter project draft   "/path/to/assignment" --skeleton        # no model
howlwriter project draft   "/path/to/assignment" --identity william --mode academic
howlwriter project validate "/path/to/assignment" draft.md
```

The web UI has the same workflow under **Projects**.

## The separation rule

**Reference material is not voice evidence.** Four kinds of information are
kept apart, each with its own store and provenance:

| | Decides | Lives in | Never |
|---|---|---|---|
| Task instructions | what to produce | `requirements.json` | counts as proof that work was done |
| Source evidence | factual content | `evidence.json` | is invented; every item has an exact location |
| Voice | expression | `~/.howlwriter/voices/` (Voice Intelligence) | is learned from project material |
| Lab / browser actions | what was observed or done | `actions.jsonl` | is represented as done by hand |

Nothing in `howlwriter.projects` writes to a voice store, identity ledger, or
corpus. A test proves it: scanning and drafting a project leaves the voice and
identity directories byte-for-byte unchanged. A project document can only
enter a voice corpus through Voice Intelligence's own authorship review.

## Architecture

```
project folder (read-only)
   │  walk: no symlinks, exclusions, browser profiles/caches skipped, ≤2000 files
   ▼
classify ──► adapters ──────────────► evidence library (located, status-tagged)
             pdf/docx/odt/rtf/html/md/txt   │
             png/jpg (OCR)                  ├──► requirements ledger (instructions/rubrics only)
             mp4/webm/audio (ASR + frames)  │        status from observation evidence
             pcap/pcapng (TShark | dpkt)    │
             csv/log/json                   ├──► retrieval (BM25 + purpose priors, explained)
   heavy work → governed worker             │
                                            ▼
browser (Playwright, dedicated profile) ─► brief ─► skeleton | writer role (HowlPlane) + voice block
                                            ▼
                                       validate: citations, numbers, claims, coverage
```

Modules (`src/howlwriter/projects/`): `workspace` (private store),
`classify`, `scan` (incremental, checkpointed), `adapters/*`, `resources`
(heavy-work governor), `requirements`, `retrieval`, `writing`, `validate`,
`browser`, `testlab`, `service`. CLI: `cli/commands/project.py`. Web:
`web/routes/projects.py`, `frontend/src/components/projects/ProjectsPanel.tsx`.

Reused rather than rebuilt: the corpus document extractors (DOCX/ODT/RTF/HTML
parsing without executing anything), the voice identity privacy guard
(owner-only files, refusal inside a Git worktree), the exclusion policy, the
existing requirement-line extractor, the voice selection layer, the
`render_profile` voice block, the HowlPlane writer role, and the web job
manager.

## Supported formats

What each adapter really does. "Not read" is always reported, never guessed.

| Format | Extraction | Location in citations | Limits and honesty |
|---|---|---|---|
| PDF | page text (pypdf); image-only pages rendered (pdftoppm) and OCR'd | `file.pdf, page 4` | pages with screenshots are flagged; image text inside text pages is not read; encrypted PDFs reported |
| DOCX, ODT, RTF, HTML, MD, TXT | text by heading section; HTML scripts dropped | `file.docx, section "Rules"` | tables flattened to text; no macros or embedded objects run |
| PNG, JPEG, GIF, BMP, TIFF, WebP | local OCR (RapidOCR) with per-line box and confidence | `shot.png, whole image (OCR)` with boxes in the record | low-confidence lines kept but marked uncertain; layout/colour not described |
| MP4, WebM, MKV, MOV | speech (faster-whisper, local) in timed segments; frames sampled every ≥30 s and OCR'd | `talk.mp4, 03:14–03:27`; `frame at 05:00` | a silent video says so; unread frames are counted; frame timing is approximate to the interval |
| MP3, WAV, M4A, OGG, FLAC | speech transcription | `audio.m4a, 01:02–01:40` | ASR mishears names and numbers; flagged |
| PCAP, PCAPNG | TShark (or dpkt): summary, conversations, TLS handshakes (SNI, versions, cipher, certificate visibility), DNS, HTTP, payload entropy per stream | `cap.pcap, frames 216–240` | no decryption claimed; payload bytes never stored; URL queries redacted |
| CSV, TSV, LOG, JSON(L) | 40-line blocks | `eve.json, lines 1–40` | first 4000 lines indexed |
| SRT, VTT subtitles | timed cues as transcript segments | `overview.srt, 02:28–03:14` | timing is the subtitle file's |
| Rules, scripts, configs (`.rules`, `.sh`, `.py`, `.yaml`, …) | 40-line blocks, never executed | `local.rules, lines 1–40` | work products or tooling, never observations |
| Keys and certificates (`.pem`, `.key`, `.p12`, …), `id_rsa`, credential files | not read | | inventoried by name only; never hashed or opened |
| Google Docs | through Voice Intelligence's Drive API fallback (read-only OAuth) | | separate authorization |
| Web pages | browser research mode | `Title, URL, retrieved 2026-10-15` | visiting a page does not establish accuracy |

## Evidence

Every item records: evidence id, project, source id and path, source type,
extraction method and version, extraction time, source SHA-256, exact
location (human and machine form), a bounded excerpt and/or structured
observation, confidence and limitations, and a citation string.

Statuses, and how the writer must treat them:

| Status | Example | In prose |
|---|---|---|
| `directly_observed` | packet counts from your capture; a lab page you observed; lines of a data file classified as experimental evidence | fact |
| `extracted_from_source` | a sentence from a reference PDF | fact, attributed |
| `derived_by_calculation` | entropy of a stream; a capture comparison | fact, with method |
| `supported_interpretation` | | phrased as interpretation |
| `tentative_inference` | | hedged |
| `contradicted` | | blocks the draft |
| `unknown_or_missing` | a required observation that does not exist | `[MISSING: …]` |

## What counts as an observation

Only material that records what happened: captures, data and logs in
evidence/results folders, screenshots, and lab browser observations. Not:
rendered pages of a document (an image whose path or OCR text marks it as
"page N" / "Page 3 of 13"), frames extracted from a video (a `frames` folder
or an ffmpeg-style `name-0001.png`), rules, scripts and configs (work
products or tooling), or generated files in working/output folders. On a real
lab folder, earlier reports rendered to images and frames of the instructor's
video had been "satisfying" most experiment requirements; these rules are
why that no longer happens. When the rules change, existing files are
reclassified from their stored text without re-extraction, and a manual
`project classify` always wins. The same data file is `directly_observed` as
experimental evidence and `extracted_from_source` in any other category (a
rating table or a reference's figures states what someone wrote), and the
status follows when the category changes.

A manual category records who set it: `user` at a terminal or in
HowlWriter's page, `owner_relayed` when an agent passes `--owner-confirmed`
(web: `X-HowlWriter-Owner-Confirmed: 1`) to relay the owner's word, and
`agent` otherwise. All three survive rescans; only `user` means the owner
was asked.

## Requirements

Requirements are extracted only from material classified as instructions or a
rubric (bullets, modal sentences, imperative sentences), each with its page or
section. Status:

- experiments, evidence and comparisons are **satisfied** only by observation
  evidence (your captures, screenshots, data, lab observations), with the
  matching terms named; screenshots need an image; a comparison needs
  observations from two sources. A reference document or a video explaining
  the procedure never satisfies them;
- sections, citations and deliverables are checked against a draft;
  formatting and submission need a human;
- your own status (`project req-status … not_applicable`) wins and persists.

## Citation integrity (`project validate`)

Draft citations are evidence markers, `[ev-1a2b3c4d5e6f]`. The validator
reports fabricated markers, unsupported factual sentences, numbers absent
from the cited evidence, instructions cited as if they were observations,
unhedged tentative inferences, contradicted support, and `[MISSING]`
placeholders; then the requirements coverage. Verdicts: `BLOCKED`,
`INCOMPLETE`, `REVIEW`, `READY_FOR_HUMAN_REVIEW`. The CLI exits non-zero for
anything but the last.

## Writing

`project brief` maps each requirement to the evidence retrieved for it, with
the reason each item was chosen, and lists missing observations.
`project draft --skeleton` turns the brief into a citation-marked scaffold
with no model. `project draft` sends the brief through the HowlPlane writer
role with the voice block rendered exactly as `howl` renders it, under a
system instruction that separates requirements, evidence and voice, forbids
invented markers and results, and treats excerpts as untrusted data.

**Remote inference.** Drafting sends evidence excerpts to the bound writer
model. Unless that provider is local (Ollama, llama.cpp, LM Studio), the
project must be authorized once (`project authorize-remote`, recorded with a
timestamp) or the call passes `--allow-remote`. Raw files are never sent; only
the selected excerpts in the brief. Both are the owner's decision: without a terminal
they exit 4 unless `--owner-confirmed` relays it, and the web API refuses them
(403) except from HowlWriter's own page or with
`X-HowlWriter-Owner-Confirmed: 1` ([agents.md](agents.md)).

**Drafting in parts.** Sections are packed into parts that fit the chosen
model: about 24,000 characters per call (system instruction included) for a
local model, whose context is 8,192 tokens, and 90,000 for a remote CLI,
whose prompt is one command-line argument. Each part names the sections it
must write and carries the last paragraph of the previous part for
continuity. A section too large on its own keeps its best-ranked evidence.
Local models get a compact voice description (measurements and short rules);
remote models get the full one.

**Sounding like you.** Three things, all local and deterministic around the
model:

- *Style examples.* Each identity profile build stores, privately beside the
  profile, short prose paragraphs from its attested training documents (never
  holdout documents, never unattested paragraphs, never Workshop bundles; fully
  attested writing first). Each part shows the model up to three, from
  different documents, as a pattern for how you write, never for content.
  These are your private writing: `--voice-examples auto` (default) shows them
  to local models only, `on` also to remote models, `off` never. The same
  setting applies to `humanize` and `howl`.
- *Citation repair.* Before any voice work, each part is checked by the
  validator. Uncited claims, invented markers, numbers absent from the
  evidence, or instructions cited as observations get one repair pass that
  lists the exact sentences and the only markers allowed. The repair is kept
  only if it reduces the problems, uses only offered markers, keeps the
  headings, and adds no number.
- *Measured revision.* Each drafted part is measured against your profile's
  drift baseline (the windows `howlwriter evaluate` uses). Notable differences
  ("uses substantially longer sentences (31 words); typical 17-24") become
  revision instructions for one pass. The revision replaces the part only if it
  keeps every evidence marker, every `[MISSING]` placeholder, every heading,
  adds no number, and measures closer to your writing than the original (fewer
  or weaker drift findings); otherwise the original stays and the reason is
  recorded. `--no-voice-revision` skips it.
- *Scores and verdict.* The finished draft's Voice Match, Naturalness,
  remaining drift findings and the validator's verdict are reported and saved
  in its provenance; a BLOCKED or INCOMPLETE draft is labelled not ready. A draft revised toward
  your profile is not an independent sample of your writing, so these say how
  close it came, not who wrote it.

Voice selection is the existing strict layer: `--voice`, `--identity` (with
`--mode academic` → `william-academic`), `--allow-generic`. A missing or
unbuilt profile stops the run; nothing falls back silently. Provenance records
the requested and applied voice and the voice block's SHA-256.

## Resource governance

The first real scan showed why this is needed: ONNX Runtime, left to default
to one thread per core, pinned the CPU on a single screenshot for two hours.
Now heavy work never runs in the scanning process:

- OCR and transcription run in one worker process scheduled `SCHED_IDLE` and
  `nice 19`, so it only uses CPU nothing else wants;
- 2 compute threads by default (`--threads`), enforced through the engines'
  options and `OMP_NUM_THREADS` and friends; ffmpeg gets `-threads`;
- each job has a deadline (`--job-timeout`, 90 s for an image); a job past it
  is killed, recorded as failed for that file, and a fresh worker continues;
- the worker is memory-limited (4 GiB address space);
- before each job the governor waits (bounded) while the load average is
  above 0.8 per core;
- images are downscaled to 1600 px on the long side before OCR;
- ffmpeg, pdftoppm and TShark run at the same idle priority.

On a real lab folder (about 1,100 files): the scanning process stayed under 15% of one core;
the worker under ~2 cores at idle priority; 12-core load around 2.2; the
screenshot that hung for two hours finished in 13.7 s.

## Browser

### Choice: Playwright library, driven in-process

| | Playwright library (chosen) | Playwright MCP server (`@playwright/mcp`) | Custom CDP control |
|---|---|---|---|
| Enforcement | our code routes every request: allowlist, read-only, approval gates are mechanical | origin allow/block lists exist; approval gates and read-only-by-method would have to live in the MCP client | possible, but rebuilds Playwright |
| Exposure | private pipe to the browser; no port | stdio, or an HTTP/SSE port (binds localhost by default) | debugging port |
| Fit | Python, same process as HowlWriter, testable headless | Node; designed for an *agent* to drive a browser through tool calls | high maintenance |
| Bazzite/Linux | bundled Chromium in `~/.cache/ms-playwright`; Wayland visible window works | same browsers via npx; needed Node/npm versions differ here | |

The MCP server is the right tool when an AI agent (Claude Code, for instance)
should drive a browser interactively. HowlWriter needs the opposite: its own
code enforcing the user's authorization regardless of what any page or model
says. A compatible MCP configuration for agent use, with the same posture, is:

```
npx @playwright/mcp@latest --isolated --allowed-origins "https://docs.suricata.io" \
    --output-dir ~/.howlwriter/projects/<id>/browser/mcp      # stdio; no --port, no --host 0.0.0.0
```

### Modes

| Mode | Can | Cannot |
|---|---|---|
| `research` | navigate approved sites (exact origins or `https://*.domain`), read, screenshot | send any non-GET request; leave the allowlist |
| `observe` | the same on an approved lab origin; evidence is `directly_observed` | change state (non-GET blocked in the network layer, even from page scripts) |
| `interactive` | click/fill/press/select on approved lab origins, each after explicit approval | act without approval; touch non-lab origins; submit graded work |

Enforcement details: navigations and redirects outside the allowlist are
aborted; service workers and downloads are disabled; in interactive mode a
POST is allowed only to a lab origin and only while an approved action runs;
controls that look like graded submission ("Submit assignment", "Turn in",
"Submit for grading") are refused outright; secrets are filled from an
environment variable and redacted in every record. Page text that addresses
an AI agent is flagged on the evidence and never acted on.

The browser is a dedicated persistent Chromium profile in the project
workspace, launched visible by default (`--headless` to hide), never the
daily browser. Every action is appended to `actions.jsonl`: URL, title,
time, mode, decision, outcome, whether state changed, and evidence ids. Lab
results produced by approved automation are recorded as such ("performed by
HowlWriter browser automation, approved by the user"), never as work done by
hand.

## Privacy and security

- Workspace `~/.howlwriter/projects/<id>/` (override `HOWLWRITER_PROJECTS_DIR`):
  0700 directories, 0600 files, refused inside an unignored Git worktree.
- Opening a folder authorizes that folder only. The web route refuses
  filesystem roots, the home directory itself, and `~/.howlwriter`.
- Source files are opened read-only; nothing is written beside them.
- Exclusions configured for any local voice identity (for William: `gemini
  gems`, `retroarchsaves`, `shared drives`) are inherited by new projects and
  enforced before a directory is entered.
- Browser profiles and caches found inside a project folder (cookies, session
  storage) are never entered.
- Packet captures: payload bytes are never stored; URL query strings are
  redacted; nothing is uploaded.
- Nothing is sent to a remote model without the project's authorization.

## Setup

```
pip install -e ".[sources]"            # pypdf, dpkt, RapidOCR, Pillow, ffmpeg, PyAV, faster-whisper, Playwright
python -m playwright install chromium   # only for browser modes
# TShark (preferred for captures): the distro package, or on Bazzite/Silverblue
flatpak install flathub org.wireshark.Wireshark   # used read-only via `flatpak run --command=tshark`
```

The Whisper model (`base.en`, ~150 MB) downloads once from the model hub on
first transcription; media itself never leaves the machine.

## Limitations

- OCR reads text, not meaning: charts, colours and diagrams are not described.
  A vision model could, but none is used without authorization.
- Image text inside PDF pages that also have a text layer is flagged, not read.
- Requirement matching is lexical; every automatic link names its terms and
  should be reviewed. A question counts as "appears answered" when the draft
  shares its terms; the reason asks you to confirm.
- Classification is heuristic (for example, a contact sheet of video frames
  can pass as a screenshot); correct it with `project classify`.
- The unsupported-claim check is a heuristic (numbers, protocol vocabulary,
  observation verbs); hedged sentences are allowed through.
- Embeddings are not used; BM25 is enough at project scale and keeps text local.
- Drafting asks which model to use (or takes `--provider`); see `docs/howlplane-integration.md`.
- A 7B local model on CPU is slow (minutes per part), writes plainer prose,
  and often fails to cite evidence; the validator catches it, but expect to
  fix such drafts by hand or redraft with a larger model. `--local-model`
  (or `HOWLWRITER_LOCAL_MODEL`) picks the Ollama model; HowlPlane's default is
  a coding model, and a general instruct model of the same size writes better.
