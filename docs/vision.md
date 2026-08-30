# Vision

This document is the north star, not the current state. For what actually
exists today, see the root [README](../README.md) and [ROADMAP](../ROADMAP.md).

## The problem

Most "AI writing" tools are a thin wrapper: prompt in, prose out, no
verification, no memory of what changed or why, no way for the writing to
be challenged before it's called finished. HowlWriter exists to prove a
different shape is possible, one that applies HowlPlane's control-plane
philosophy to prose:

```
PROPOSE -> CHALLENGE -> EVALUATE -> VERIFY -> REVISE -> AUTHORIZE -> OUTPUT
```

AI models are components inside a controlled writing process, not the
process itself. Drafts get proposed, criticized, researched, fact-checked,
rewritten, verified, and approved before being presented as finished work.

## What HowlWriter should eventually do

Given an idea, notes, rough human writing, existing AI-generated writing,
an article, a LinkedIn post, technical documentation, academic writing, or
other prose, produce writing that:

1. preserves the author's intended meaning
2. sounds like the author, not the underlying model
3. removes generic or recognizable LLM writing habits
4. improves clarity without unnecessarily polishing away personality
5. detects unsupported factual claims
6. researches claims when requested
7. records which sources support which claims
8. generates properly formatted citations when requested
9. generates reference/bibliography pages when requested
10. allows independent models or processes to critique one another
11. exposes what changed and why
12. fails honestly when information cannot be verified

## Humanization is not AI-detector evasion

AI detectors are unreliable and are not treated as an objective measurement
anywhere in this project. Humanization means making writing more closely
resemble authentic human writing and, when a voice profile exists, the
writing of that particular author. See [docs/humanization.md](humanization.md)
for the full philosophy.

## Author voice

HowlWriter should eventually learn an author's style from a corpus of real
writing (social posts, emails, essays, documentation, articles) and build a
reusable Voice Profile that favors preservation of the author's quirks
(fragments, uneven sentence lengths, unusual transitions, slight
repetition, personal expressions) over generically "better" prose. See
[docs/voice.md](voice.md).

## Fact checking and provenance as first-class concerns

Fact checking is a major subsystem, not an afterthought. Every claim
extracted from a document should be traceable to whether it's supported,
contradicted, or unverifiable, and every source should be traceable to the
claims it backs. Quantitative claims deserve particular scrutiny. HowlWriter
never invents a statistic, study, quotation, author, date, journal, URL,
DOI, or page number merely because the real one can't be verified. See
[docs/provenance.md](provenance.md).

## Citations

Starting with APA 7, eventually MLA, Chicago, IEEE, and Harvard. Citation
formatting operates only on collected source metadata; missing metadata
gets the citation style's own missing-information rule (e.g. `(n.d.)`), a
retrieval attempt, or an explicit warning -- never a fabricated value. See
[docs/citations.md](citations.md).

## Writing modes

CASUAL, PROFESSIONAL, LINKEDIN, TECHNICAL, DOCUMENTATION, ACADEMIC, EMAIL,
ARTICLE, CUSTOM -- modes adjust behavior (how aggressively to humanize, how
strict fact-checking is, whether citations are visible) rather than being
separate applications.

## Multi-model review

Writer, Editor, Humanizer, Voice Reviewer, Fact Checker, Researcher, Red
Pen, Citation Validator, and Final Reviewer are independent roles.
HowlWriter never assumes one model performs every role, and never routes,
retries, or executes a model call itself -- that belongs to HowlPlane or
whatever runtime is configured. See
[docs/howlplane-integration.md](howlplane-integration.md).

## Meaning preservation

Rewriting risks sounding better while becoming less accurate. Every
significant rewrite should be checked against the original for removed
qualifications, strengthened or weakened claims, changed opinions, lost
technical detail, changed numbers, altered attribution, and changed
conclusions. A final reviewer should be able to reject a rewrite that reads
well but says something different.

## The long-term pipeline

```
INPUT -> RESEARCH -> DRAFT -> HUMANIZE -> VOICE MATCH -> EDIT -> LINT ->
CLAIM EXTRACTION -> FACT CHECK -> SOURCE VERIFICATION -> RED PEN ->
INDEPENDENT CRITIQUE -> MINIMAL REWRITE -> MEANING VERIFICATION ->
CITATION GENERATION -> FINAL OUTPUT
```

Today's `howl` command runs a real subset of this
(INPUT -> EDIT -> HUMANIZE -> LINT -> RED PEN -> FINAL REVIEW -> OUTPUT).
Growing it into the full pipeline above is the roadmap, not a promise this
version makes.
