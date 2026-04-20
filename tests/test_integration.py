from __future__ import annotations

import pickle
from pathlib import Path
from typing import Literal

import pytest

from hipaa_mcp.models import Citation, RegulationChunk


_SECTIONS: list[tuple[int, str, str]] = [
    (308, "Administrative safeguards", "security management process risk analysis workforce training"),
    (310, "Organizational requirements", "business associate contracts covered entity obligations"),
    (312, "Technical safeguards", "access control audit controls encryption transmission security"),
    (314, "Business associate contracts", "business associate agreement satisfactory assurances"),
    (316, "Documentation", "policies procedures retention written documentation"),
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

    chunks = _make_chunks()

    # Populate chroma
    col = fake_client.get_or_create_collection("regulations")
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

    # Populate BM25
    from rank_bm25 import BM25Okapi
    tokenized = [c.text.lower().split() for c in chunks]
    bm25 = BM25Okapi(tokenized)
    settings.bm25_index_path.parent.mkdir(parents=True, exist_ok=True)
    settings.bm25_index_path.write_bytes(pickle.dumps({"bm25": bm25, "chunks": chunks}))

    return settings


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
