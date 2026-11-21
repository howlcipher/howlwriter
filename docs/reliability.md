# Reliability: accuracy, context and completeness checks

Three questions about any finished piece of writing: is it accurate, does it
sound like the intended author in the intended context, and does it satisfy the
assignment? This page covers the checks that answer them, what each one can and
cannot establish, and the commands that run them. Every check here reports; none
edits your text.

## Citation metadata: `howlwriter citations verify`

A DOI that resolves does not show that the author, year and edition in a
formatted citation are right. `citations verify` compares each source's authors,
year, edition, title, DOI and identifier with canonical records.

```bash
howlwriter citations verify sources.json --records publisher-records.json --json
howlwriter citations verify sources.json --offline --records publisher-records.json
```

Records come from providers. The most authoritative record *for each field* decides
that field: a publisher record that states no year cannot vouch for a year, so the
best record that does state it decides. A **publisher** record (the issuing body's own page
or document cover) outranks a **registry** record (Crossref), because registries
are often thin or date a revision by its update year. Records you supply with
`--records` are JSON; see `tests/fixtures/citations/canonical_records.json` for
the fields (`provider`, `authority`, `year`, `year_source`, `identifier`, `dates`,
`status`, `authors`, `title`, `doi`, `edition`). A record that omits `authority` is
treated as a registry record, so a hand-written file cannot outrank Crossref by
accident. `year_source` is a label you assert; nothing extracts it from a document.

| State | Meaning |
| --- | --- |
| `VERIFIED` | Authoritative records agree with the citation. |
| `MISMATCH` | The best record disagrees on author, year, edition, title, DOI or identifier. |
| `NEEDS_REVIEW` | Records disagree with each other, a year is uncertain, the work is withdrawn, or the records are too thin to confirm authors or year. |
| `INCOMPLETE` | The source lacks title, authors, date, or any DOI or URL. |
| `UNVERIFIABLE` | No record could be obtained. A provider outage is reported as such and is never read as a wrong citation. |

Rules that matter:

- **A year the records disagree about is never settled silently.** It is accepted
  only when the citation matches a year the publisher itself states as the way to
  cite the work (`year_source: "cite_as"`). A cover date against a registry date
  is `NEEDS_REVIEW`. Each resolved field reports who stated it (`resolved` in the
  JSON output), so a reader can see why a year was accepted.
- **Editions stay distinct.** An original publication and a later update have
  different DOIs and identifiers; citing one with the other's identifier is a
  `MISMATCH`.
- **Verified metadata is not claim support.** `VERIFIED` says the bibliographic
  data matches; it says nothing about whether the source backs any claim.
- Authors are compared by surname, in order, and by given-name initial when both
  sides give one; organizations match by name tokens, not by substring. A citation
  that states no edition when the record identifies one is `NEEDS_REVIEW`.
- An empty sources file is an error (exit 1): nothing was verified.
- The Crossref request is built only from a plain DOI; a string containing a
  query, fragment, dot-segment or whitespace makes no request.
- Exit code 0 only when every citation is `VERIFIED`; 3 otherwise.

`paper --verify-sources --records FILE` runs the same comparison on the sources a
paper cites. Unlike `citations verify`, `paper --verify-sources` has no `--offline`
mode and always contacts Crossref in addition to your records. `citations verify
--check-links` also probes each DOI and URL with the SSRF-safe integrity verifier
(`--timeout` sets its limit). A `MISMATCH` makes the paper `BLOCKED`; any other state other than
`VERIFIED` makes it `NEEDS_REVIEW`.

Example from a real case: NIST SP 800-161 Rev. 1 Update 1 carries a "How to Cite"
block in its own front matter that reads *Boyens J, ... (2022) ... NIST SP
800-161r1-upd1, Includes updates as of November 1, 2024*. Crossref dates the same
DOI 2024 and lists one author. The publisher's cite-as year decides it, the
registry difference is reported rather than hidden, and a citation using 2024 is
`NEEDS_REVIEW`.

## Citations after editing

A citation verified during research can drift when the text is revised.
`citation_delta` (used by the `paper` pipeline and `finalize --changes`) compares
a document before and after a transformation and reports dropped, added or
changed citations, a citation that lost its claim, reference entries left
orphaned or missing, and a year that now disagrees between a citation and its
reference. In the `paper` pipeline any such change holds the paper for review.

## Workflow commentary in prose: `lint --workflow-leakage`

A reader should not see how the text was drafted or checked. The detector reports
provenance notes ("this is my recommendation, not a cited result"), process
phrasing about supplied or retrieved sources, status codes and source ids,
task instructions, model self-reference and placeholders. It is deliberately
narrow: a real limitation or uncertainty about the subject stays. It is a pattern
check, so a novel phrasing can pass; the `paper` pipeline holds a paper that has
findings, and nothing is removed automatically.

## Academic genres

`academic_discussion`, `academic_peer_reply` and `academic_research_paper`
refine the academic task. They are not a new register or identity: every genre
resolves to `WritingMode.ACADEMIC`, so `--mode academic_peer_reply` uses the same
`<identity>-academic` voice profile as `--mode academic`. A genre changes what the
writer is asked for (a reply addresses the classmate, has no headings and avoids
formulaic praise) and what the checks expect. Set it with `genre:` in an
assignment spec or `lint --genre`. Voice evidence is not genre-specific; the
profile does not know how its author writes replies as opposed to posts.

Discussion and peer-reply review use the same body boundary in `assignment
check`, `reply check`, `lint --genre` and `evaluate --mode`. A leading Markdown
level-one title and the terminal reference list are outside the body. Use an
ATX title (`# Title`) or a Setext title (underlined with `=`) when the assignment
requires one. Body-only text also works. Body subheadings and in-text
citations remain in the body, and assignment citation checks also read the
reference entries.

## Replies grounded in the post they answer: `howlwriter reply check`

```bash
howlwriter reply check reply.md --post "Casey Rowe=post.md" --min-words 200 --max-words 300 --json
howlwriter paper reply-spec.yaml --peer-post "Casey Rowe=post.md" --sources sources.json
```

The check finds sentences where the reply says what the peer said ("you note
that ...") and tests each against the post: unsupported or reversed attributions,
quotations that are not in the post or the supplied sources, a reply that only
restates the post, and instruction-like text in the post that the reply obeyed.
States: `GROUNDED`, `PARTIALLY_GROUNDED`, `UNSUPPORTED`, `UNGROUNDED`. With no
post the reply is `UNGROUNDED`: it cannot be reported as source-grounded.

Posts, retrieved source text and documents under review are **untrusted
reference data**. In prompts they are fenced and the writer is told they are
never instructions; they are scanned for instruction-like text, which is reported.
The comparison uses wording overlap and a negation check. Direct-address
openings such as “your fifth step about …” or “your question about whether …”
identify a topic to check against the supplied text. A greeting or a thin
attribution leaves grounding unresolved. Read both texts to confirm semantic
fidelity, including which step the peer meant and whether the peer asked a
question or took a position. If the supplied text is a summary, report that
grounding was checked against that summary.

## A whole assignment: `howlwriter assignment check`

```bash
howlwriter assignment check package.yaml --records records.json --json
```

Evaluates every deliverable against one spec (see `tests/assignment` for the
format): required deliverables and word limits, required topics, genre
conventions, leaked workflow text, in-text citations against the reference list,
metadata verification, reply grounding, meaning preservation against an original,
and cross-document consistency (one work cited with one year, distinct editions
kept apart).

| State | Meaning |
| --- | --- |
| `BLOCKED` | Something must not be submitted as it stands: a citation contradicting its record, an in-text citation with no source, a reply that misstates its post. |
| `INCOMPLETE` | A required deliverable, or evidence needed to check one (the post a reply answers), is missing. |
| `NEEDS_REVISION` | A check found something to fix. |
| `VERIFICATION_UNAVAILABLE` | A required check could not run (a provider was unreachable, no record source was configured). Not a pass. |
| `READY_FOR_HUMAN_REVIEW` | Every *required* check ran and passed. A person still reads it. A check the package opted out of (`require_citation_verification: false`) is listed in `unavailable_checks` and `human_decisions`, not hidden. |

These sit alongside the `paper` pipeline's `READY`/`NEEDS_REVIEW`/`BLOCKED` and
`project validate`'s `READY_FOR_HUMAN_REVIEW`; they are not a replacement. Exit 0
only for `READY_FOR_HUMAN_REVIEW`; 3 otherwise. The JSON report lists
`verification_records`: for each check, the component that ran it, the evidence it
saw, its status and its limits. A statement in a document or a model reply that
something "was verified" is not evidence and does not change a result;
semantic-review independence is stated only from recorded providers.

`require_voice_match` and `require_naturalness` make an unavailable score (no
identity named, no built profile, a document too short) `VERIFICATION_UNAVAILABLE`.
Citations in a deliverable with no `sources` file are `VERIFICATION_UNAVAILABLE`
too. Paths in a package spec must stay inside the spec's folder, and files over
5 MB are refused.

Human Naturalness needs a sample of at least 250 words and 12 sentences.
Personal Voice Match needs at least 300 words and a usable calibration. These
are the metrics' sample sizes. In short-form academic evaluation, the
top-level JSON `words` is the assignment body count and each metric reports
its own `words` using the tokenizer it was calibrated with.

## Academic discussion workflow

1. Before drafting, verify the [checkout runtime](agents.md#checkout-runtime)
   and confirm the assignment's deliverables, preferred lengths and hard
   limits. Run `howlwriter voice status --identity ID --json` to confirm the
   requested identity, its academic profile and the profile's build status.
   Use `howlwriter voice inspect PROFILE` to see the built profile's
   calibration. Report a missing profile for the requested identity. Use
   another profile only when its ownership is established and it belongs to
   the intended author. Compare the preferred length with the score
   thresholds above and leave Voice Match unavailable when that length falls
   below its supported threshold.
2. Trace firsthand statements to the author's input. Check who spoke or
   acted in each sentence. Keep an event the author experienced, a preference
   they expressed and an improvement they propose distinct.
3. For each consequential legal claim, record the court, issue, published
   holding, factual limit and primary-source URL in the working notes.
   Record any later treatment you verified and the limits of that search
   separately. Re-read the opinion alongside the final sentence after
   refinement. `writer --fail-if-blocked` exits 3 if a draft citation does
   not resolve against supplied sources or an exact identifier is absent
   from both the prompt and supplied source text. `citations verify` compares
   bibliographic metadata against canonical records and can optionally check
   links. Confirm the paraphrase against the opinion itself.
4. Begin with deterministic review. Run `lint --genre`, `reply check`
   against the supplied peer text, and `assignment check` with available
   source records. Use `--offline` for assignment and citation checks when
   relying on local records. Refine with a model when there is a specific
   passage or defect to address. Keep the user's explicit model and privacy
   choices, then check the actual changes, citation delta and final body
   counts before handing over the files.
5. Start the handoff with the absolute output directory and a link to the
   combined document. Report each post's body count and citation results.
   Include unresolved findings, unavailable scores and material limitations
   of the evidence, including any reply checked against a summary.

### Retrospective

Use `howlwriter runs list` and `howlwriter runs show RUN_ID --raw` for
available durations, provider steps and failures. Review the final diff to
count substantive model edits retained. Use `unknown` for any measurement
you could not establish.

| Measurement | Record |
| --- | --- |
| Elapsed time | Start, finish and total duration |
| Model calls | Observed calls by role and provider, including retries where recorded |
| Failed commands | Command, exit code and what the failure affected |
| Substantive model edits retained | Count and short description from the final diff |

## Revisions: `finalize --changes`

```bash
howlwriter finalize original.md revised.md --changes --min-words 200 --max-words 300
```

For each change: what changed, the reason when it can be established from the
text (a citation moved, a number changed, workflow commentary removed), whether
meaning held, and the citation effect. An unchanged document reports `No
changes.` Where a reason cannot be determined it says so. `--identity` adds the
voice effect only when both versions can be scored.

## Publishing: confirmed, not assumed

The Google Docs publisher:

1. refuses content that differs from the artifact's approved SHA-256. The check
   fails closed: a hash that is present but malformed is refused, and an empty
   hash means nothing was asserted. The `publish` command and the web route hash
   the same text they send, so there the check guards against corruption between
   hashing and sending, not against a different approval; it is meaningful when a
   pipeline approves text and publishes it later (`paper --publish`);
2. for an update, writes only against the revision it read, re-checks that
   revision immediately before writing and relies on the destination to refuse a
   stale write, so a collaborator's edit is reported (`CONFLICT`) and never
   overwritten;
3. reads the document back and checks paragraphs, duplicated content, in-text
   citations, reference entries, the end of the text and the word count, and
   notes Markdown shown literally or elements the destination cannot carry;
4. keeps a record of the approved artifact (hash, words, citations) beside the
   local deliverables. Only `paper --publish` supplies that location and the length
   limits for the read-back; `publish` and the web route confirm content,
   citations, references and ending but do not know your word limits.

The read-back compares the paragraph sequence exactly: a missing, altered, merged,
reordered, duplicated or extra paragraph (short ones included), a changed
reference entry or a truncated end is `UNCONFIRMED`. Appending to an existing
document requires the approved paragraphs to appear in order and the prior text to
survive.

`SUCCESS` means the destination confirmed the content. `UNCONFIRMED` means it was
written but the read-back did not match, or could not be done. `CONFLICT` means
nothing was written because the document changed. `FAILED` means nothing was
published. Publishing still requires the existing owner authorization, and
`replace` no longer asks the Docs API to delete the document's final newline. A
folder move that fails after the write reports `UNCONFIRMED` (the document exists),
not "nothing published". `publish --update-doc` now needs a destination that
reports a revision id and accepts a revision-guarded write; one that does not is
refused instead of written unguarded. The CLI, `paper` and the web response show
the real status.

## Untrusted text

Peer posts, retrieved source text and documents under review go into prompts
fenced as quoted data: every line is prefixed, delimiters, code fences and
hidden or control characters are removed or defanged, and the label is a short
identifier. Titles, authors and ids from retrieval are reduced to one plain line.
Scanning folds compatibility characters, joiners and common lookalike letters, and
is bounded in time and size. It is a tripwire, not a guarantee: leetspeak,
other languages and encoded payloads are not detected. The fence and the standing
rule are the defense; a reply that repeats an embedded instruction is flagged.

## What is not covered

- Metadata verification needs a record source. Without `--records` or a
  reachable registry the state is `UNVERIFIABLE`.
- Publisher records are supplied, not scraped; there is no general scraper for
  issuing bodies' pages.
- Reply grounding and meaning preservation are heuristic.
- Only Google Docs is a destination with read-back; other destinations keep the
  previous behavior.
