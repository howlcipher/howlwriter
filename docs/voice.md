# Voice Profile

There are two generations of this feature and they take opposite
positions on one question, so it is worth naming them up front.

The **hand-authored profile** below (`voice learn`, `--voice-profile`) is
the original. It keeps a few verbatim excerpts on purpose.

**[Voice Corpus Profiling](voice-corpus.md)** (`voice build`, `--voice`)
derives a private profile from a real corpus of your own writing, and keeps
no excerpts at all. If you are looking for the feature that reads your
documents, that is the one.

---

## Hand-authored profiles

### Why not just "conversational" or "professional"

Vague descriptors alone lose exactly the quirks HowlWriter is supposed to
preserve. `domain/voice.py`'s `VoiceProfile` requires
`representative_examples` -- verbatim excerpts from the author's own
writing -- alongside its numeric fields, so voice matching has real
material to work from, not just adjectives.

### Fields

`author_name`, `formality`, `sentence_length_mean`,
`sentence_length_stdev`, `paragraph_length_mean`, `contraction_rate`,
`rhetorical_question_rate`, `fragment_rate`, `preferred_phrases`,
`disliked_phrases`, `representative_examples`, `structural_notes`, and
`generated_from` (`"corpus_stats" | "model_hook" | "manual"`).

### What's real today: `CorpusStatsLearner`

`voice/learner.py`'s `CorpusStatsLearner.learn(corpus)` computes, from a
list of the author's own texts, using only the standard library
(`re`, `statistics`):

- sentence length mean and population standard deviation (word count per
  sentence)
- paragraph length mean (sentences per paragraph)
- contraction rate (`n't`, `'re`, `'ll`, `'ve`, `'d`, `'m` occurrences over
  total words)
- rhetorical-question rate (sentences ending in `?` over total sentences)
- an **approximate** fragment rate -- a sentence under four words, or one
  with no common auxiliary/modal verb and no `-s`/`-ed`/`-ing` suffix,
  counts as a fragment. This has no real grammatical parsing behind it and
  will misjudge some sentences either way; it's a heuristic signal, not a
  precision claim.
- `representative_examples`, picked from the corpus's shortest, longest,
  and closest-to-mean-length sentences, verbatim

No model call, no network access. This is the complete real MVP voice
capability, exposed via `howlwriter voice learn <files...>`.

### What's reserved: the model hook

`voice/model_hook.py`'s `VoiceAnalyzer` Protocol is reserved for a future
qualitative pass -- tone, humor, formality judgment -- that a deterministic
corpus scan can't honestly produce. It's unconfigured by default
(`NotConfiguredVoiceAnalyzer`, raising `ModelRoleNotConfiguredError`); see
[docs/howlplane-integration.md](howlplane-integration.md) for why HowlWriter
doesn't implement this itself.

### Using a hand-authored profile with the Humanizer

`howlwriter.humanize.rewriter` treats `config.voice_profile` as a file path
first. If the value points to an existing JSON file, it is loaded as a
`VoiceProfile` and its real statistics (sentence-length mean/stdev,
contraction rate, fragment rate, etc.) plus up to three representative
examples are injected into the Humanizer prompt. If the value is not a
file path, it is treated as an author label and no profile content is
injected.

The CLI accepts a `--voice-profile` argument:

```bash
howlwriter humanize post.md --mode linkedin --voice-profile ~/.howlwriter/voice.json
```

### Why "voice match %" doesn't appear in reports yet

Computing a defensible similarity score between a piece of generated text
and a `VoiceProfile` needs either a validated comparison model or a
carefully validated deterministic distance metric -- neither exists yet.
`WritingReport.voice_match` stays `None` and is omitted from
`render_text()` output entirely rather than showing an invented
percentage. See [docs/architecture.md](architecture.md) for the general
"omit, don't fake" rule this follows.

---

## The corpus-derived profile

Everything above describes a profile someone wrote by hand. The larger half
of this feature builds one from a real corpus instead, and is documented
separately in **[docs/voice-corpus.md](voice-corpus.md)**: how a corpus is
discovered and cleaned, what is kept and what is deliberately not, where a
personal voice is stored, and why a corpus-built profile holds no excerpts
even though the schema still supports them for hand-authored ones.
