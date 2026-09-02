# The Necessity of Source-to-Claim Provenance in AI Writing

When generative models draft technical documentation or academic papers, their greatest flaw is hallucinating authoritative-sounding citations. A model will cite a non-existent 2023 paper by "Smith et al." in a real IEEE journal with complete confidence.

To solve this, HowlWriter enforces an immutable provenance chain:
`SOURCE -> EVIDENCE -> CLAIM -> IN-TEXT CITATION -> REFERENCE`

Under this rule, model memory is never considered a valid source. An external scholarly API (Crossref or arXiv) must retrieve actual paper metadata and abstracts before any citation can be generated. The claim verifier then matches the draft's assertions against the retrieved text. If a claim lacks textual support in the retrieved evidence, it is flagged, preventing ungrounded prose from receiving a READY status.
