# TODO

## BM25 matching — refinement + edge cases

Current BM25 impl uses default tokenization and scoring. Known gaps to work through:

- **Stopword handling** — HIPAA text is dense with legal boilerplate ("shall", "means", "with respect to"). These terms inflate BM25 scores for chunks where they appear frequently. A domain-specific stopword list or IDF floor would improve ranking precision.
- **Section number tokenization** — `164.308` tokenizes differently depending on whether the dot is treated as punctuation or part of the token. Queries containing `§ 164.308` may miss chunks indexed as `164 308`. Need a consistent normalization pass on both index and query sides.
- **Subdivision matching** — queries like `(a)(1)(ii)` rarely survive tokenization intact. Subdivision structure carries no BM25 signal in the current impl; a pre-processing step that normalizes subdivisions before indexing would improve recall on citation-style queries.
- **Short chunk scoring** — very short chunks (single sentence definitions) score high on BM25 for single-term matches. Length normalization tuning via the `b` param may produce more useful ranking across chunk sizes.
- **Score normalization for RRF** — BM25 scores are unbounded. Current normalization divides by the top score. Worth verifying behavior when the top score is a strong outlier (e.g. a single high-frequency term dominating a small corpus slice).
- **Definition chunks rank too low** — measured 2026-07-28 against a fresh index (1891 chunks): the glossary-expanded query "do I need a BAA for this vendor" ranks the § 160.103 *business associate* definition at **36**, behind a wall of § 164.504(e) / § 164.308(b) contract-requirement paragraphs. The definition chunk is 3164 chars, so it loses on BM25 length normalization and is truncated by the embedding model's context, while short paragraphs repeating "business associate" win. Options: length-aware boosting for chunks in definitions sections, a definition-intent signal in expansion, or splitting long definitions while keeping the term in every piece. Blocks the `fixes.md` definition-of-done item that wanted § 160.103 in the top hits.
- **Reindex reproducibility** — confirm BM25 index produces identical rankings for identical input across Python versions and `rank_bm25` versions. Floating point drift has caused silent ranking changes in other projects.
