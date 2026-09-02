# The Necessity of Source-to-Claim Provenance in AI Writing

When generative models draft technical documentation or academic papers, a major risk is their tendency to invent authoritative-sounding citations. A model may confidently cite a non-existent 2023 paper by "Smith et al." in a real IEEE journal.

HowlWriter addresses this with an immutable provenance chain:
`SOURCE -> EVIDENCE -> CLAIM -> IN-TEXT CITATION -> REFERENCE`

Model memory is never treated as a valid source. Before a citation can be generated, an external scholarly API, such as Crossref or arXiv, must retrieve the paper's actual metadata and abstract. The claim verifier compares the draft's assertions with the retrieved text. Claims without textual support in that evidence are flagged, so ungrounded prose cannot receive a READY status.