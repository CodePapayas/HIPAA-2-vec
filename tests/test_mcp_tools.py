from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hipaa_mcp.models import (
    Citation,
    ErrorResponse,
    Glossary,
    GlossaryEntry,
    RegulationChunk,
    Relationship,
    SearchHit,
    SearchResults,
    Section,
)


def _chunk(section: int = 308) -> RegulationChunk:
    return RegulationChunk(
        chunk_id=f"sec_164.{section}",
        citation=Citation(title=45, part=164, section=section, subdivisions=[]),
        heading="Administrative safeguards",
        text="The covered entity must implement a security management process.",
        source_corpus="hipaa",
    )


def _fake_results(query: str = "test") -> SearchResults:
    return SearchResults(
        query=query,
        hits=[SearchHit(chunk=_chunk(), score=0.9, matched_via="hybrid")],
    )


@pytest.mark.asyncio
class TestSearchRegulations:
    async def test_returns_search_results(self) -> None:
        with (
            patch("hipaa_mcp.server.rewrite_query", new_callable=AsyncMock, return_value="test"),
            patch("hipaa_mcp.server.search", return_value=_fake_results("test")),
        ):
            from hipaa_mcp.server import search_regulations
            result = await search_regulations("test query", top_k=5)
        assert isinstance(result, SearchResults)
        assert len(result.hits) == 1

    async def test_expanded_query_set_when_rewritten(self) -> None:
        with (
            patch("hipaa_mcp.server.rewrite_query", new_callable=AsyncMock, return_value="business associate"),
            patch("hipaa_mcp.server.search", return_value=_fake_results("business associate")),
            patch("hipaa_mcp.server.get_settings") as mock_settings,
        ):
            mock_settings.return_value.use_llm_for_query_understanding = True
            from hipaa_mcp.server import search_regulations
            result = await search_regulations("vendor contract")
        assert isinstance(result, SearchResults)

    async def test_returns_error_response_on_exception(self) -> None:
        with (
            patch("hipaa_mcp.server.rewrite_query", new_callable=AsyncMock, return_value="q"),
            patch("hipaa_mcp.server.search", side_effect=RuntimeError("index missing")),
        ):
            from hipaa_mcp.server import search_regulations
            result = await search_regulations("test")
        assert isinstance(result, ErrorResponse)
        assert result.code == "SEARCH_ERROR"


@pytest.mark.asyncio
class TestGetSection:
    async def test_returns_section_for_valid_citation(self) -> None:
        with patch("hipaa_mcp.server.get_section_chunks", return_value=[_chunk()]):
            from hipaa_mcp.server import get_section
            result = await get_section("164.308")
        assert isinstance(result, Section)
        assert result.citation.section == 308

    async def test_invalid_citation_returns_error(self) -> None:
        from hipaa_mcp.server import get_section
        result = await get_section("not a citation")
        assert isinstance(result, ErrorResponse)
        assert result.code == "INVALID_CITATION"

    async def test_not_found_returns_error(self) -> None:
        with patch("hipaa_mcp.server.get_section_chunks", return_value=[]):
            from hipaa_mcp.server import get_section
            result = await get_section("164.999")
        assert isinstance(result, ErrorResponse)
        assert result.code == "NOT_FOUND"

    async def test_full_text_joins_chunks(self) -> None:
        chunks = [_chunk(308), _chunk(308)]
        chunks[1] = chunks[1].model_copy(update={"text": "second paragraph"})
        with patch("hipaa_mcp.server.get_section_chunks", return_value=chunks):
            from hipaa_mcp.server import get_section
            result = await get_section("164.308")
        assert isinstance(result, Section)
        assert "second paragraph" in result.full_text


@pytest.mark.asyncio
class TestSearchExclusions:
    async def test_anti_entry_exclusions_reach_retrieval(self) -> None:
        """The excluded term must be filtered, never appended to the search string."""
        from hipaa_mcp.models import Glossary

        g = Glossary(
            entries=[
                GlossaryEntry(
                    term="de-identified",
                    maps_to="not PHI",
                    relationship=Relationship.anti,
                )
            ],
            version=1,
        )
        captured: dict[str, object] = {}

        def _fake_search(query: str, top_k: int = 5, exclusions: list[str] | None = None):
            captured["query"] = query
            captured["exclusions"] = exclusions
            return _fake_results(query)

        with (
            patch("hipaa_mcp.server.rewrite_query", new_callable=AsyncMock, return_value="de-identified data"),
            patch("hipaa_mcp.server.load_glossary", return_value=g),
            patch("hipaa_mcp.server.search", _fake_search),
        ):
            from hipaa_mcp.server import search_regulations
            result = await search_regulations("de-identified data")

        assert isinstance(result, SearchResults)
        assert captured["exclusions"] == ["not PHI"]
        assert "not PHI" not in str(captured["query"])
        assert "NOT" not in str(captured["query"])

    async def test_expanded_query_display_keeps_operators(self) -> None:
        from hipaa_mcp.models import Glossary

        g = Glossary(
            entries=[
                GlossaryEntry(
                    term="vendor",
                    maps_to="business associate",
                    relationship=Relationship.synonym,
                )
            ],
            version=1,
        )
        with (
            patch("hipaa_mcp.server.rewrite_query", new_callable=AsyncMock, return_value="vendor contract"),
            patch("hipaa_mcp.server.load_glossary", return_value=g),
            patch("hipaa_mcp.server.search", return_value=_fake_results("vendor contract")),
        ):
            from hipaa_mcp.server import search_regulations
            result = await search_regulations("vendor contract")

        assert isinstance(result, SearchResults)
        assert result.expanded_query == "vendor contract OR business associate"


@pytest.mark.asyncio
class TestLLMDegradation:
    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ConnectError("refused"),
            httpx.HTTPStatusError(
                "404",
                request=httpx.Request("POST", "http://localhost:11434/api/generate"),
                response=httpx.Response(404),
            ),
            json.JSONDecodeError("bad json", "", 0),
        ],
    )
    async def test_llm_failure_falls_back_to_original_question(self, exc: Exception) -> None:
        """Retrieval must survive a dead Ollama — the LLM is an optional layer."""
        from hipaa_mcp.llm import BaseLLMClient, rewrite_query

        class Failing(BaseLLMClient):
            async def complete(self, prompt: str) -> str:
                raise exc

        with patch("hipaa_mcp.llm.get_settings") as mock_settings:
            mock_settings.return_value.use_llm_for_query_understanding = True
            result = await rewrite_query("do I need a BAA?", client=Failing())

        assert result == "do I need a BAA?"

    async def test_search_still_returns_hits_when_llm_dies(self) -> None:
        with (
            patch(
                "hipaa_mcp.server.rewrite_query",
                new_callable=AsyncMock,
                side_effect=lambda q: q,
            ),
            patch("hipaa_mcp.server.load_glossary", return_value=Glossary(entries=[], version=1)),
            patch("hipaa_mcp.server.search", return_value=_fake_results("q")),
        ):
            from hipaa_mcp.server import search_regulations
            result = await search_regulations("q")
        assert isinstance(result, SearchResults)
        assert len(result.hits) == 1


@pytest.mark.asyncio
class TestGetSectionSubdivisions:
    async def test_subdivision_text_only(self) -> None:
        sub = RegulationChunk(
            chunk_id="sec_164.312_a_1",
            citation=Citation(title=45, part=164, section=312, subdivisions=["a", "1"]),
            heading="Technical safeguards",
            text="Standard: Access control.",
            source_corpus="hipaa",
        )
        with patch("hipaa_mcp.server.get_section_chunks", return_value=[sub]):
            from hipaa_mcp.server import get_section
            result = await get_section("164.312(a)(1)")
        assert isinstance(result, Section)
        assert result.citation.subdivisions == ["a", "1"]
        assert result.full_text == "Standard: Access control."

    async def test_bogus_subdivision_returns_not_found(self) -> None:
        with patch("hipaa_mcp.server.get_section_chunks", return_value=[]):
            from hipaa_mcp.server import get_section
            result = await get_section("164.312(z)(9)")
        assert isinstance(result, ErrorResponse)
        assert result.code == "NOT_FOUND"
        assert "§ 164.312(z)(9)" in result.message


@pytest.mark.asyncio
class TestGlossaryTools:
    async def test_add_term_returns_entry(self, tmp_path: pytest.TempPathFactory) -> None:
        from hipaa_mcp.models import Glossary
        empty = Glossary(entries=[], version=1)
        with (
            patch("hipaa_mcp.server.load_glossary", return_value=empty),
            patch("hipaa_mcp.server.save_glossary"),
        ):
            from hipaa_mcp.server import add_glossary_term
            result = await add_glossary_term("vendor", "business associate", "synonym")
        assert isinstance(result, GlossaryEntry)
        assert result.term == "vendor"
        assert result.maps_to == "business associate"

    async def test_add_term_invalid_relationship(self) -> None:
        from hipaa_mcp.server import add_glossary_term
        result = await add_glossary_term("vendor", "business associate", "bogus")
        assert isinstance(result, ErrorResponse)
        assert result.code == "INVALID_RELATIONSHIP"

    async def test_list_returns_entries(self) -> None:
        from hipaa_mcp.models import Glossary
        entries = [
            GlossaryEntry(term="vendor", maps_to="business associate", relationship=Relationship.synonym),
            GlossaryEntry(term="send", maps_to="disclosure", relationship=Relationship.hyponym),
        ]
        g = Glossary(entries=entries, version=1)
        with patch("hipaa_mcp.server.load_glossary", return_value=g):
            from hipaa_mcp.server import list_glossary_terms
            result = await list_glossary_terms()
        assert len(result) == 2

    async def test_list_filter_applied(self) -> None:
        from hipaa_mcp.models import Glossary
        entries = [
            GlossaryEntry(term="vendor", maps_to="business associate", relationship=Relationship.synonym),
            GlossaryEntry(term="send", maps_to="disclosure", relationship=Relationship.hyponym),
        ]
        g = Glossary(entries=entries, version=1)
        with patch("hipaa_mcp.server.load_glossary", return_value=g):
            from hipaa_mcp.server import list_glossary_terms
            result = await list_glossary_terms(filter="vendor")
        assert len(result) == 1
        assert result[0].term == "vendor"

    async def test_remove_existing_term(self) -> None:
        from hipaa_mcp.models import Glossary
        entries = [
            GlossaryEntry(term="vendor", maps_to="business associate", relationship=Relationship.synonym),
        ]
        g = Glossary(entries=entries, version=1)
        with (
            patch("hipaa_mcp.server.load_glossary", return_value=g),
            patch("hipaa_mcp.server.save_glossary"),
        ):
            from hipaa_mcp.server import remove_glossary_term
            result = await remove_glossary_term("vendor")
        assert result is True

    async def test_remove_missing_term_returns_error(self) -> None:
        from hipaa_mcp.models import Glossary
        with (
            patch("hipaa_mcp.server.load_glossary", return_value=Glossary(entries=[], version=1)),
        ):
            from hipaa_mcp.server import remove_glossary_term
            result = await remove_glossary_term("nonexistent")
        assert isinstance(result, ErrorResponse)
        assert result.code == "NOT_FOUND"
