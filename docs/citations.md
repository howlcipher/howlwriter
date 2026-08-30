# Citations

## Scope for v1: APA 7 only

`citations/styles.py`'s `CitationStyle` enum reserves `MLA`, `CHICAGO`,
`IEEE`, and `HARVARD` as names, matching the spec's "start with APA 7
(future: MLA, Chicago, IEEE, Harvard)." Asking `get_formatter()` for any of
them raises `NotImplementedError` naming the style -- there is no fallback
to APA7 and no partial implementation pretending otherwise.

`citations/apa7.py`'s `APA7Formatter` operates only on `Source` metadata
that's actually present. It is a **basic** representation (author, year,
title, publisher, one locator) -- it does not attempt full academic-citation
depth (volume/issue/page ranges, edition, translator), which `Source`'s
schema doesn't carry and which is out of scope for the MVP goal of a
"basic APA7 citation representation."

## The three forms, plus a reference page

- `reference_entry(source)` -- a full reference-list entry
- `in_text_parenthetical(source)` -- `(Smith, 2024)` / `(Smith & Jones,
  2024)` / `(Smith et al., 2024)`
- `narrative(source)` -- `Smith (2024)` / `Smith and Jones (2024)` /
  `Smith et al. (2024)`
- `reference_page(sources)` -- every source's reference entry,
  alphabetized by first-author surname (or by title, when a source has no
  author)

Organizational authors (names ending in "Organization," "Institute,"
"University," and similar) are printed as-is rather than inverted into
"Last, F." form.

## Never hallucinate missing metadata

A missing `publication_date` produces the APA7 undated-source form
(`n.d.`) and a `CITATION_METADATA_MISSING` warning naming the field:

```
CITATION_METADATA_MISSING
Publication date could not be verified.
APA reference will use the appropriate undated-source format.
```

A missing author moves the title into the author position, per APA7 rules,
with the same warning shape naming `authors`. A missing URL/DOI omits the
locator and warns naming `url`. Every formatting method returns both its
rendered text and the list of warnings it raised -- callers see exactly
which fields were assumed missing, never a citation that quietly guessed.

## What's not attempted yet

Citation *validation* -- checking that a formatted citation is actually
correct, or that a claimed source genuinely exists -- has no
implementation. `WritingRole.CITATION_VALIDATOR` is part of the role
vocabulary (`integration/model_role.py`) but nothing in this codebase
currently fills it; that's future work, not a hidden shortcut.
