# Humanization

## What this is not

AI-detector evasion is **not** the objective. AI detectors are unreliable
and are not treated as an objective measurement anywhere in this codebase.
There is no code in this project that tries to beat, fool, or score against
a detector, and none should be added. HowlWriter does **not**:

- call AI detectors,
- optimize detector scores,
- intentionally misspell words,
- inject grammar errors,
- randomly alter punctuation,
- introduce fake personal anecdotes,
- add false uncertainty,
- deliberately corrupt prose,
- rewrite repeatedly until some classifier says 'human'.

The quality target is **authentic writing**, not classifier manipulation.

## What this is

Humanization means making AI-assisted writing read more like the actual author
wrote it. When a Voice Profile exists (see [docs/voice.md](voice.md)), the
target is that author's voice, not a generic 'conversational' template.
Authentic writing often contains fragments, uneven sentence lengths, unusual
transitions, slight repetition, personal expressions, and occasional roughness.
HowlWriter does not remove these simply because a model would normally smooth
them away.

The Humanizer's priorities are:

1. **Preserve facts** -- numbers, dates, percentages, names, attribution,
   technical terms, citations, uncertainty/hedging, and causal meaning.
2. **Preserve intent** -- the author's argument, question, criticism,
   emphasis, and stance.
3. **Preserve author voice** -- uneven rhythm, contractions, personal phrasing,
   concrete details, humor, opinion, mild roughness.
4. **Remove generic LLM habits** -- canned openings, canned conclusions,
   mechanical transitions, formulaic contrasts, repetitive three-part lists,
   generic intensifiers, abstract corporate filler, and artificially uniform
   structure.
5. **Make the minimum necessary edit** -- if the input is already clean and
   natural, the best result is **zero changes**.

## Writing modes

Mode-specific instructions guide the model-backed Humanizer. Current modes:

- `linkedin` / short-form: direct opening, conversational professional tone,
  varied sentence length, no unnecessary conclusions, no fake
  thought-leadership tone, preserve humor/sarcasm, keep technical terms.
- `academic`: keep formal clarity, citations, technical terminology,
  qualifications, scholarly tone; remove generic LLM filler but do not
  casualize.
- `technical`: preserve precise terminology and numbers, remove marketing
  language.
- `casual`: keep relaxed voice, contractions, fragments, personal phrasing.

Use a mode from the CLI:

```bash
howlwriter humanize post.md --mode linkedin
howlwriter howl post.md --mode academic
```

## The pattern families

`humanize/detector.py` detects the humanization-relevant subset of
`linting/engine.py`'s findings (see [docs/architecture.md](architecture.md)
for why the two are not a separate pattern list):

| Rule code | What it flags |
| --- | --- |
| `AI_STYLE_BANNED_WORD` | A configured banned word (`delve`, `tapestry`, `crucial` by default) |
| `AI_STYLE_NOT_X_BUT_Y` | 'It is not X, it is Y' / 'It is not just X, it is Y' contrast constructions |
| `AI_STYLE_FORMULAIC_CONTRAST` | 'Not only X but also Y' / 'This is not about X; it is about Y' patterns |
| `AI_STYLE_EMPTY_TRANSITION` | Empty setup phrases such as 'At its core,' 'In today's rapidly evolving...' |
| `AI_STYLE_CANNED_OPENING` | Canned opening phrases (early paragraphs only) |
| `AI_STYLE_CANNED_CONCLUSION` | 'In conclusion,' 'The reality is,' 'Ultimately, it is clear that...' |
| `AI_STYLE_GENERIC_TRANSITION` | Mechanical overuse of `furthermore`, `moreover`, `additionally`, `consequently`, etc. |
| `AI_STYLE_GENERIC_INTENSIFIER` | Abstract intensifiers such as `crucial`, `pivotal`, `transformative`, `groundbreaking` |
| `AI_STYLE_CORPORATE_FILLER` | `leverage`, `synergy`, `unlock`, `empower`, `drive value`, `seamless`, `holistic`, etc. |
| `AI_STYLE_REPETITIVE_TRICOLON` | Three or more parallel three-item lists in one document |
| `AI_STYLE_REPETITIVE_MINI_CONCLUSION` | Paragraphs repeatedly ending with mini-conclusion phrases |
| `AI_STYLE_EXCESSIVE_EM_DASH` | Four or more em dashes in one document |
| `AI_STYLE_REPETITIVE_PARAGRAPH_STRUCTURE` | Three or more paragraphs opening with the same word |
| `AI_STYLE_PARAGRAPH_LENGTH_SYMMETRY` | Paragraphs with suspiciously uniform sentence counts |
| `AI_STYLE_EXCESSIVE_RHETORICAL_QUESTIONS` | Question sentences making up a quarter or more of the document |

Excessive headings and excessive bold are detected too
(`AI_STYLE_EXCESSIVE_HEADINGS`, `AI_STYLE_EXCESSIVE_BOLD`), but
`humanize/detector.py` leaves them out of its subset -- they read as
formatting/structure concerns rather than 'this sentence sounds like an
AI wrote it.' They still surface through `howlwriter lint`.

Every rule is config-gated: absent from `config.banned_words` /
`config.banned_patterns`, a rule finds nothing. Nothing here is hard-coded
as universally wrong -- see [docs/architecture.md](architecture.md) for how
the gating works.

## Findings over rewrites

The default behavior for every pattern above is **findings-only**. The one
exception is `humanize/rewriter.py`'s `SafeRewriter`: a literal
substitution of a banned word for its configured replacement --
`banned_words: [{word: delve, replacement: 'look into'}]` -- and only when
`config.apply_safe_rewrites` is explicitly set. No pattern-based rewriting
(rewriting a 'not X but Y' sentence, restructuring a paragraph, cutting a
rhetorical question) happens automatically anywhere in this codebase.

Prose-level rewriting that genuinely 'makes this sound less AI' needs
judgment a regex cannot provide. That is `humanize/rewriter.py`'s
`HumanizerRewriter` Protocol -- model-backed, unconfigured by default
(`NotConfiguredHumanizer`), and not invoked by the `howl` pipeline unless a
caller wires an implementation in.

## Zero-change behavior

If the input is already natural and free of the patterns above, the
Humanizer returns the original text exactly and reports zero changes.
A clean human-written paragraph surviving untouched is **success**, not a
failure. The model prompt explicitly instructs the Humanizer to do this.

## Minimal editing and change reasons

Every model-backed edit should have a reason. The Humanizer prompt asks the
model to return a reason from a compact taxonomy:

- `GENERIC_LLM_PHRASE`
- `REDUNDANT_SETUP`
- `CANNED_TRANSITION`
- `CANNED_OPENING`
- `CANNED_CONCLUSION`
- `UNNECESSARY_SUMMARY`
- `VOICE_MISMATCH`
- `OVERPOLISHED`
- `REPETITIVE_STRUCTURE`
- `CORPORATE_FILLER`
- `RHYTHM_NORMALIZATION`
- `FACT_PRESERVATION_NOTE`

`ChangeRecord` stores the reason alongside the description, and
`WritingReport.render_text()` includes it when present. This keeps
Humanizer output explainable without inventing fake precision.

## Voice Profile integration

If `config.voice_profile` is a path to an existing JSON file, the Humanizer
loads it as a `VoiceProfile` and includes real statistics
(sentence-length mean/stdev, contraction rate, fragment rate, etc.) and up
to three representative examples in the prompt. It never synthesizes a fake
'Voice match: 92%' score. If `voice_profile` is not a file path, it is
treated as an author label and no profile is injected.

## Over-polish handling

The Humanizer should often move *away* from unnecessary polish. It must not
upgrade vocabulary, replace simple verbs with formal ones, remove
contractions, add transitions the author did not need, convert opinions
into neutral consultant prose, add summaries, remove humor, or smooth away
mild natural repetition. The goal is to keep the author's actual voice, not
to produce structurally perfect prose.

## Academic boundary

Academic mode stays academically appropriate. It keeps formal clarity,
citation structure, technical terminology, qualifications, and scholarly
tone. It removes generic LLM filler, canned transitions, repetitive
summaries, inflated importance language, and mechanical paragraph
structures. It does not inject casual contractions, jokes, fragments, or
LinkedIn-style language merely because the author's short-form Voice Profile
contains them.

## Meaning preservation

Naturalization may change style but may not change proposition. HowlWriter
keeps the existing deterministic meaning-preservation reviewer
(`review/meaning.py`) and the independent semantic reviewer. It continues to
protect numbers, dates, names, attribution, citations, certainty, hedging,
causality, negation, comparisons, and scope. It also preserves the
commit `971ead5` calibration that treats benign style edits (e.g., dropping
'Furthermore') differently from substantive semantic drift (e.g., changing
'may reduce' to 'reduces').

## Red Pen coordination

The Humanizer transforms prose; the Red Pen critiques remaining problems.
They may share explainable categories (corporate filler, redundant setup),
but their responsibilities stay distinct: Humanizer performs the rewrite,
Red Pen flags what is still wrong.
