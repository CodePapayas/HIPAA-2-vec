from __future__ import annotations

from hipaa_mcp.retrieval import _rrf_merge


class TestRRFMerge:
    def test_shared_doc_scores_higher_than_single_source(self) -> None:
        shared = "doc_a"
        vector_only = "doc_v"
        bm25_only = "doc_b"
        merged = dict(_rrf_merge([shared, vector_only], [shared, bm25_only], k=60))
        assert merged[shared] > merged[vector_only]
        assert merged[shared] > merged[bm25_only]

    def test_rank_order_respected(self) -> None:
        merged = _rrf_merge(["a", "b", "c"], ["a", "b", "c"], k=60)
        ids = [m[0] for m in merged]
        assert ids == ["a", "b", "c"]

    def test_empty_inputs(self) -> None:
        assert _rrf_merge([], [], k=60) == []

    def test_disjoint_lists_all_present(self) -> None:
        merged = dict(_rrf_merge(["v1", "v2"], ["b1", "b2"], k=60))
        assert set(merged.keys()) == {"v1", "v2", "b1", "b2"}

    def test_all_scores_positive(self) -> None:
        merged = _rrf_merge(["a", "b"], ["b", "c"], k=60)
        assert all(s > 0 for _, s in merged)

    def test_k_parameter_affects_scores(self) -> None:
        low_k = dict(_rrf_merge(["a"], ["a"], k=1))
        high_k = dict(_rrf_merge(["a"], ["a"], k=1000))
        assert low_k["a"] > high_k["a"]

    def test_descending_order(self) -> None:
        merged = _rrf_merge(["a", "b", "c"], ["a", "c", "b"], k=60)
        scores = [s for _, s in merged]
        assert scores == sorted(scores, reverse=True)


