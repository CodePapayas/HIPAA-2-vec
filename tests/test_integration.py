from __future__ import annotations

import json
from pathlib import Path

import pytest

from hipaa_mcp.config import INDEX_FORMAT
from hipaa_mcp.models import Citation, RegulationChunk


_SECTIONS: list[tuple[int, str, str]] = [
    (308, "Administrative safeguards", "security management process risk analysis workforce training"),
    (310, "Organizational requirements", "business associate contracts covered entity obligations"),
    (312, "Technical safeguards", "access control audit controls encryption transmission security"),
    (314, "Business associate contracts", "business associate agreement satisfactory assurances"),
    (316, "Documentation", "policies procedures retention written documentation"),
]

# Subparagraphs of § 164.312, so subdivision-scoped lookups have something to hit.
_SUBDIVISIONS: list[tuple[list[str], str]] = [
    (["a", "1"], "Standard: Access control. Implement technical policies and procedures."),
    (["a", "2", "i"], "Unique user identification. Assign a unique name or number."),
    (["b"], "Standard: Audit controls. Implement hardware and software mechanisms."),
]


def _make_chunks() -> list[RegulationChunk]:
    chunks = []
    for section, heading, text in _SECTIONS:
        chunks.append(
            RegulationChunk(
                chunk_id=f"sec_164.{section}",
                citation=Citation(title=45, part=164, section=section, subdivisions=[]),
                heading=heading,
                text=text,
                source_corpus="hipaa",
            )
        )
    for subs, text in _SUBDIVISIONS:
        citation = Citation(title=45, part=164, section=312, subdivisions=subs)
        chunks.append(
            RegulationChunk(
                chunk_id="sec_164.312_" + "_".join(subs),
                citation=citation,
                heading="Technical safeguards",
                text=text,
                source_corpus="hipaa",
            )
        )
    return chunks


@pytest.fixture()
def indexed_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build in-memory indices from fake chunks; patch settings + chromadb."""
    import chromadb

    from hipaa_mcp.config import Settings

    settings = Settings(
        data_dir=str(tmp_path),
        use_llm_for_query_understanding=False,
    )
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)

    fake_client = chromadb.EphemeralClient()

    monkeypatch.setattr("hipaa_mcp.retrieval.get_settings", lambda: settings)
    monkeypatch.setattr("hipaa_mcp.ingest.get_settings", lambda: settings)
    monkeypatch.setattr(chromadb, "PersistentClient", lambda **kw: fake_client)

    from hipaa_mcp.retrieval import reset_caches

    reset_caches()

    chunks = _make_chunks()

    # Populate chroma — cosine space and the current index format marker, matching
    # what `ingest.build_indices` writes.
    col = fake_client.get_or_create_collection(
        "regulations",
        metadata={"hnsw:space": "cosine", "index_format": INDEX_FORMAT},
    )
    col.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "citation": c.citation.format(),
                "heading": c.heading,
                "source_corpus": c.source_corpus,
                "title": c.citation.title,
                "part": c.citation.part,
                "section": c.citation.section,
                "subdivisions": "|".join(c.citation.subdivisions),
            }
            for c in chunks
        ],
    )

    # Populate BM25 — JSON, same shape ingest writes
    settings.bm25_index_path.parent.mkdir(parents=True, exist_ok=True)
    settings.bm25_index_path.write_text(
        json.dumps(
            {
                "index_format": INDEX_FORMAT,
                "tokens": [c.text.lower().split() for c in chunks],
                "chunks": [c.model_dump(mode="json") for c in chunks],
            }
        )
    )

    yield settings
    reset_caches()


class TestEndToEndSearch:
    def test_search_returns_hits(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        results = search("security management process", top_k=3)
        assert len(results.hits) > 0

    def test_section_308_top_for_security_query(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        results = search("security management process risk analysis", top_k=3)
        top_section = results.hits[0].chunk.citation.section
        assert top_section == 308

    def test_baa_query_returns_correct_section(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        results = search("business associate agreement", top_k=3)
        sections = {h.chunk.citation.section for h in results.hits}
        assert 314 in sections or 310 in sections

    def test_citations_are_well_formed(self, indexed_env: object) -> None:
        from hipaa_mcp.citations import parse
        from hipaa_mcp.retrieval import search
        results = search("access control", top_k=5)
        for hit in results.hits:
            formatted = hit.chunk.citation.format()
            reparsed = parse(formatted)
            assert reparsed == hit.chunk.citation

    def test_matched_via_values_valid(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        results = search("policies procedures", top_k=5)
        valid = {"vector", "bm25", "hybrid"}
        for hit in results.hits:
            assert hit.matched_via in valid

    def test_top_k_respected(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        results = search("safeguards", top_k=2)
        assert len(results.hits) <= 2


class TestExclusionFilter:
    def test_hits_containing_excluded_term_are_dropped(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        unfiltered = search("business associate agreement", top_k=5)
        assert any("business associate" in h.chunk.text for h in unfiltered.hits)

        filtered = search("business associate agreement", top_k=5, exclusions=["business associate"])
        assert all("business associate" not in h.chunk.text for h in filtered.hits)

    def test_exclusion_still_fills_top_k(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import search
        results = search("safeguards controls documentation", top_k=3, exclusions=["encryption"])
        assert len(results.hits) == 3


class TestGetSectionChunks:
    def test_returns_chunk_for_known_section(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import get_section_chunks
        chunks = get_section_chunks("164.308")
        assert len(chunks) == 1
        assert chunks[0].citation.section == 308

    def test_unknown_section_returns_empty(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import get_section_chunks
        chunks = get_section_chunks("164.999")
        assert chunks == []

    def test_subdivision_request_returns_only_that_subdivision(
        self, indexed_env: object
    ) -> None:
        from hipaa_mcp.retrieval import get_section_chunks
        chunks = get_section_chunks("164.312(b)")
        assert [c.citation.subdivisions for c in chunks] == [["b"]]
        assert "Audit controls" in chunks[0].text
        assert all("Access control" not in c.text for c in chunks)

    def test_subdivision_prefix_includes_descendants(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import get_section_chunks
        chunks = get_section_chunks("164.312(a)")
        assert [c.citation.subdivisions for c in chunks] == [["a", "1"], ["a", "2", "i"]]

    def test_bogus_subdivision_returns_empty(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import get_section_chunks
        assert get_section_chunks("164.312(z)(9)") == []

    def test_whole_section_returns_all_chunks(self, indexed_env: object) -> None:
        from hipaa_mcp.retrieval import get_section_chunks
        chunks = get_section_chunks("164.312")
        assert len(chunks) == 4


class TestStaleIndex:
    def test_old_index_format_tells_user_to_reindex(
        self, indexed_env: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An index built before the cosine/JSON switch must fail loudly, not silently."""
        from hipaa_mcp.retrieval import IndexUnavailableError, _load_bm25, reset_caches

        settings = indexed_env
        reset_caches()
        payload = json.loads(settings.bm25_index_path.read_text())  # type: ignore[attr-defined]
        payload["index_format"] = 1
        settings.bm25_index_path.write_text(json.dumps(payload))  # type: ignore[attr-defined]

        with pytest.raises(IndexUnavailableError, match="reindex"):
            _load_bm25(settings.bm25_index_path)  # type: ignore[attr-defined]

    def test_missing_lexical_index_is_clear(self, tmp_path: Path) -> None:
        from hipaa_mcp.retrieval import IndexUnavailableError, _load_bm25

        with pytest.raises(IndexUnavailableError, match="reindex"):
            _load_bm25(tmp_path / "nope.json")
