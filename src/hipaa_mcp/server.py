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
    SearchResultsWithProvenance,
    Section,
)
from hipaa_mcp.retrieval import get_section_chunks, search, search_with_provenance

mcp = FastMCP("hipaa-mcp")


@mcp.tool()
async def search_regulations(query: str, top_k: int = 5) -> SearchResults | ErrorResponse:
    """Search HIPAA (45 CFR) and 42 CFR Part 2 for passages matching a plain-English question.

    Returns matching regulation passages with their exact citations. Passage
    text is verbatim regulatory text; this tool does not interpret, summarize,
    or advise. Quote the passage and cite the section — do not restate what the
    regulation "means".
    """
    settings = get_settings()
    try:
        question = await rewrite_query(query) if settings.use_llm_for_query_understanding else query
        expanded, _ = expand_query(question, load_glossary())
        results = search(expanded.query, top_k=top_k, exclusions=expanded.exclusions)
        display = expanded.display()
        return results.model_copy(
            update={"expanded_query": display if display != query else None}
        )
    except Exception as exc:
        return ErrorResponse(code="SEARCH_ERROR", message=str(exc))


@mcp.tool()
async def get_section(citation: str) -> Section | ErrorResponse:
    """Fetch the verbatim text of one CFR section or subparagraph by citation.

    Accepts citations such as `164.308`, `§ 164.308(a)(1)(ii)(A)`, or
    `42 CFR § 2.11(b)`. When subdivisions are given, only that subparagraph's
    text is returned. The text is reproduced as published; this tool does not
    interpret it.
    """
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
            message=f"No indexed text found for {parsed.format()}",
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
    """Teach the search layer that a developer phrase maps to regulatory vocabulary.

    `relationship` is one of: synonym (interchangeable), hyponym (phrase is a
    narrower case of the target), contextual (expand only when scope words are
    present), anti (the phrase signals the target should be excluded). Notes are
    vocabulary rationale only, never statements about what the law requires.
    """
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
    """List the active vocabulary mappings, optionally filtered by substring.

    Entries map everyday developer phrasing to the terms the regulations use.
    They are search aids, not legal definitions.
    """
    glossary = load_glossary()
    if filter is None:
        return glossary.entries
    f = filter.lower()
    return [e for e in glossary.entries if f in e.term.lower() or f in e.maps_to.lower()]


@mcp.tool()
async def explain_search(
    query: str, top_k: int = 5
) -> SearchResultsWithProvenance | ErrorResponse:
    """Run a search and show why each passage was retrieved.

    Reports the glossary terms that expanded the query and, per hit, the vector
    similarity, the normalized BM25 score, and the fused rank. Same retrieval as
    `search_regulations`; the passages are verbatim regulatory text and are not
    interpreted.
    """
    settings = get_settings()
    try:
        question = await rewrite_query(query) if settings.use_llm_for_query_understanding else query
        expanded, glossary_matches = expand_query(question, load_glossary())
        display = expanded.display()
        return search_with_provenance(
            query=query,
            glossary_matches=glossary_matches,
            top_k=top_k,
            expanded_query=display if display != query else None,
            retrieval_query=expanded.query,
            exclusions=expanded.exclusions,
        )
    except Exception as exc:
        return ErrorResponse(code="EXPLAIN_ERROR", message=str(exc))


@mcp.tool()
async def remove_glossary_term(phrase: str) -> bool | ErrorResponse:
    """Remove a vocabulary mapping by its phrase. Returns true when one was removed."""
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
