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

Records come from providers. A **publisher** record (the issuing body's own page
or document cover) outranks a **registry** record (Crossref), because registries
are often thin or date a revision by its update year. Records you supply with
`--records` are JSON; see `tests/fixtures/citations/canonical_records.json` for
the fields (`provider`, `authority`, `year`, `year_source`, `identifier`, `dates`,
`status`, `authors`, `title`, `doi`, `edition`).

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
- Exit code 0 only when every citation is `VERIFIED`; 3 otherwise.

`paper --verify-sources --records FILE` runs the same comparison on the sources a
paper cites. A `MISMATCH` makes the paper `BLOCKED`; any other state other than
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
The comparison is lexical: it catches invented and stretched attributions in the
common case but cannot prove a paraphrase faithful. Read both texts.

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
| `READY_FOR_HUMAN_REVIEW` | Every required check ran and passed. A person still reads it. |

These sit alongside the `paper` pipeline's `READY`/`NEEDS_REVIEW`/`BLOCKED` and
`project validate`'s `READY_FOR_HUMAN_REVIEW`; they are not a replacement. Exit 0
only for `READY_FOR_HUMAN_REVIEW`; 3 otherwise. The JSON report lists
`verification_records`: for each check, the component that ran it, the evidence it
saw, its status and its limits. A statement in a document or a model reply that
something "was verified" is not evidence and does not change a result;
semantic-review independence is stated only from recorded providers.

Scores such as Human Naturalness and Personal Voice Match are reported when
HowlWriter can compute them. A short post (under 300 words for Voice Match, 250
for Naturalness) gets neither, and that is reported as unavailable, never as a
pass.

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

1. refuses content that differs from the artifact's approved SHA-256;
2. for an update, writes only against the revision it read, re-checks that
   revision immediately before writing and relies on the destination to refuse a
   stale write, so a collaborator's edit is reported (`CONFLICT`) and never
   overwritten;
3. reads the document back and checks paragraphs, duplicated content, in-text
   citations, reference entries, the end of the text and the word count, and
   notes Markdown shown literally or elements the destination cannot carry;
4. keeps a record of the approved artifact (hash, words, citations) beside the
   local deliverables.

`SUCCESS` means the destination confirmed the content. `UNCONFIRMED` means it was
written but the read-back did not match, or could not be done. `CONFLICT` means
nothing was written because the document changed. `FAILED` means nothing was
published. Publishing still requires the existing owner authorization, and
`replace` no longer asks the Docs API to delete the document's final newline.

## What is not covered

- Metadata verification needs a record source. Without `--records` or a
  reachable registry the state is `UNVERIFIABLE`.
- Publisher records are supplied, not scraped; there is no general scraper for
  issuing bodies' pages.
- Reply grounding and meaning preservation are heuristic.
- Only Google Docs is a destination with read-back; other destinations keep the
  previous behavior.
