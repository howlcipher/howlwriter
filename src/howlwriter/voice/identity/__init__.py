"""Personal Voice Intelligence: one person, several context profiles.

`voice build` turns a set of roots into one profile. This package sits above
it for the case where a person wants their writing understood the way they
actually produce it: a mounted drive inventoried once, every document
classified and given a provenance decision, and several context-specific
profiles (academic, professional) built from only the documents that person
has confirmed are theirs.

It does not replace any part of the corpus pipeline. Profiles are still built
by `howlwriter.voice.corpus.build.build_voice`, stored by `VoiceStore`, and
consumed by the Humanizer and Writer through the same seam as every other
voice. What this package adds is the bookkeeping the root-based build cannot
do on its own: a persistent private inventory, an authorship review ledger
that survives rescans, and the calibration data the evaluation scores need.

Everything it writes lives under `~/.howlwriter/identities/<identity>/`
(overridable with HOWLWRITER_IDENTITIES_DIR), outside any repository, with
owner-only permissions.
"""
