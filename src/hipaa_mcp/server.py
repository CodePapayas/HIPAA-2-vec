from __future__ import annotations

from fastmcp import FastMCP

from hipaa_mcp.citations import CitationParseError, parse
from hipaa_mcp.config import get_settings
from hipaa_mcp.glossary import expand_query, load_glossary, save_glossary
from hipaa_mcp.llm import rewrite_query
from hipaa_mcp.models import (
    ErrorResponse,
    GlossaryEntry,
    Relationship,
    SearchResults,
    Section,
)
from hipaa_mcp.retrieval import get_section_chunks, search

mcp = FastMCP("hipaa-mcp")


@mcp.tool()
async def search_regulations(query: str, top_k: int = 5) -> SearchResults | ErrorResponse:
    settings = get_settings()
    try:
        expanded = await rewrite_query(query) if settings.use_llm_for_query_understanding else query
        expanded = expand_query(expanded, load_glossary())
        results = search(expanded, top_k=top_k)
        results = results.model_copy(update={"expanded_query": expanded if expanded != query else None})
        return results
    except Exception as exc:
        return ErrorResponse(code="SEARCH_ERROR", message=str(exc))


@mcp.tool()
async def get_section(citation: str) -> Section | ErrorResponse:
    try:
        parsed = parse(citation)
    except CitationParseError as exc:
        return ErrorResponse(code="INVALID_CITATION", message=str(exc))

    try:
        chunks = get_section_chunks(citation)
    except Exception as exc:
        return ErrorResponse(code="RETRIEVAL_ERROR", message=str(exc))

    if not chunks:
        return ErrorResponse(
            code="NOT_FOUND",
            message=f"No chunks found for {parsed.format()}",
        )

    full_text = "\n\n".join(c.text for c in chunks)
    heading = next((c.heading for c in chunks if c.heading), "")
    return Section(
        citation=parsed,
        heading=heading,
        full_text=full_text,
        source_corpus=chunks[0].source_corpus,
    )


@mcp.tool()
async def add_glossary_term(
    phrase: str,
    maps_to: str,
    relationship: str = "synonym",
    notes: str | None = None,
) -> GlossaryEntry | ErrorResponse:
    try:
        rel = Relationship(relationship)
    except ValueError:
        valid = [r.value for r in Relationship]
        return ErrorResponse(
            code="INVALID_RELATIONSHIP",
            message=f"relationship must be one of {valid}",
        )

    glossary = load_glossary()
    # Remove existing entry for the same term
    glossary.entries = [e for e in glossary.entries if e.term.lower() != phrase.lower()]
    entry = GlossaryEntry(term=phrase, maps_to=maps_to, relationship=rel, notes=notes)
    glossary.entries.append(entry)
    save_glossary(glossary)
    return entry


@mcp.tool()
async def list_glossary_terms(filter: str | None = None) -> list[GlossaryEntry]:
    glossary = load_glossary()
    if filter is None:
        return glossary.entries
    f = filter.lower()
    return [e for e in glossary.entries if f in e.term.lower() or f in e.maps_to.lower()]


@mcp.tool()
async def remove_glossary_term(phrase: str) -> bool | ErrorResponse:
    glossary = load_glossary()
    before = len(glossary.entries)
    glossary.entries = [e for e in glossary.entries if e.term.lower() != phrase.lower()]
    if len(glossary.entries) == before:
        return ErrorResponse(
            code="NOT_FOUND",
            message=f"No glossary entry found for {phrase!r}",
        )
    save_glossary(glossary)
    return True
