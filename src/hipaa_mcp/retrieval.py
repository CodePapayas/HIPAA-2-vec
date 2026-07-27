from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from rank_bm25 import BM25Okapi

from hipaa_mcp.config import INDEX_FORMAT, Settings, get_settings
from hipaa_mcp.models import (
    Citation,
    GlossaryMatch,
    RegulationChunk,
    SearchHit,
    SearchHitProvenance,
    SearchResults,
    SearchResultsWithProvenance,
)

REINDEX_HINT = "Run `hipaa-mcp reindex` to build it."


class IndexUnavailableError(RuntimeError):
    """Raised when the on-disk index is missing or written by an older version."""


# --- caches -----------------------------------------------------------------
# Chroma clients and the BM25 index are rebuilt per process, not per query.
# Both are keyed by path so a test that swaps the data dir gets a fresh one.

_bm25_cache: dict[str, tuple[float, BM25Okapi, list[RegulationChunk]]] = {}
_collection_cache: dict[str, Any] = {}


def reset_caches() -> None:
    """Drop cached indexes. Called after a reindex, and available to tests."""
    _bm25_cache.clear()
    _collection_cache.clear()


def _get_collection(settings: Settings) -> Any:
    key = str(settings.chroma_dir)
    cached = _collection_cache.get(key)
    if cached is not None:
        return cached

    import chromadb

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    try:
        collection = client.get_collection("regulations")
    except Exception as exc:
        raise IndexUnavailableError(f"No regulation index found at {settings.chroma_dir}. {REINDEX_HINT}") from exc

    metadata = collection.metadata or {}
    if int(metadata.get("index_format", 1)) < INDEX_FORMAT:
        raise IndexUnavailableError(
            "The regulation index was built by an older version of hipaa-mcp "
            f"(format {metadata.get('index_format', 1)}, expected {INDEX_FORMAT}). {REINDEX_HINT}"
        )

    _collection_cache[key] = collection
    return collection


def _load_bm25(path: Path) -> tuple[BM25Okapi, list[RegulationChunk]]:
    key = str(path)
    if not path.exists():
        raise IndexUnavailableError(f"No lexical index found at {path}. {REINDEX_HINT}")

    mtime = path.stat().st_mtime
    cached = _bm25_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1], cached[2]

    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IndexUnavailableError(f"Lexical index at {path} is not readable. {REINDEX_HINT}") from exc

    if int(payload.get("index_format", 1)) < INDEX_FORMAT:
        raise IndexUnavailableError(
            f"The lexical index at {path} was built by an older version of hipaa-mcp. {REINDEX_HINT}"
        )

    chunks = [RegulationChunk.model_validate(c) for c in payload["chunks"]]
    tokens: list[list[str]] = payload["tokens"]
    bm25 = BM25Okapi(tokens or [[""]])
    _bm25_cache[key] = (mtime, bm25, chunks)
    return bm25, chunks


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value))


def _chunk_from_metadata(chunk_id: str, doc: str, meta: dict[str, object]) -> RegulationChunk:
    subdivisions = str(meta.get("subdivisions", ""))
    subs = [s for s in subdivisions.split("|") if s]
    citation = Citation(
        title=_as_int(meta["title"]),
        part=_as_int(meta["part"]),
        section=_as_int(meta["section"]),
        subdivisions=subs,
    )
    source_corpus = str(meta.get("source_corpus", "hipaa"))
    sc: Literal["hipaa", "part2"] = "part2" if source_corpus == "part2" else "hipaa"
    return RegulationChunk(
        chunk_id=chunk_id,
        citation=citation,
        heading=str(meta.get("heading", "")),
        text=doc,
        source_corpus=sc,
    )


def _rrf_merge(
    vector_ids: list[str],
    bm25_ids: list[str],
    k: int,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, doc_id in enumerate(vector_ids):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, doc_id in enumerate(bm25_ids):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _matched_via(
    doc_id: str, vector_set: set[str], bm25_set: set[str]
) -> Literal["vector", "bm25", "hybrid"]:
    if doc_id in vector_set and doc_id in bm25_set:
        return "hybrid"
    if doc_id in vector_set:
        return "vector"
    return "bm25"


def _excluded(chunk: RegulationChunk, exclusions: list[str]) -> bool:
    from hipaa_mcp.glossary import contains_term

    return any(contains_term(chunk.text, term) for term in exclusions)


def _run_searches(
    query: str, k: int, settings: Settings
) -> tuple[
    list[str],  # vector_ids
    list[str],  # vector_docs
    list[dict[str, object]],  # vector_metas
    dict[str, float],  # vector_similarity by id (0-1)
    list[str],  # bm25_ids
    dict[str, float],  # bm25_norm_score by id (0-1)
    list[RegulationChunk],  # all bm25 chunks
]:
    collection = _get_collection(settings)

    vector_results = collection.query(
        query_texts=[query],
        n_results=min(k * 3, 50),
        include=["documents", "metadatas", "distances"],
    )
    vector_ids: list[str] = vector_results["ids"][0]
    vector_docs: list[str] = vector_results["documents"][0]
    vector_metas: list[dict[str, object]] = vector_results["metadatas"][0]
    raw_distances: list[float] = vector_results["distances"][0]
    # Invariant: the collection is created with `hnsw:space=cosine`, so distance
    # ∈ [0, 2] and similarity = (2 - dist) / 2 ∈ [0, 1]. Clamped defensively —
    # a value outside the range means the index was not built with cosine space.
    vector_similarity: dict[str, float] = {
        cid: round(min(1.0, max(0.0, (2.0 - dist) / 2.0)), 6)
        for cid, dist in zip(vector_ids, raw_distances)
    }

    bm25, bm25_chunks = _load_bm25(settings.bm25_index_path)
    tokenized_query = query.lower().split()
    bm25_raw: list[float] = bm25.get_scores(tokenized_query)
    top_bm25_idx = sorted(range(len(bm25_raw)), key=lambda i: bm25_raw[i], reverse=True)[: k * 3]
    bm25_ids = [bm25_chunks[i].chunk_id for i in top_bm25_idx]
    max_bm25 = max((bm25_raw[i] for i in top_bm25_idx), default=1.0) or 1.0
    bm25_norm: dict[str, float] = {
        bm25_chunks[i].chunk_id: round(bm25_raw[i] / max_bm25, 6) for i in top_bm25_idx
    }

    return vector_ids, vector_docs, vector_metas, vector_similarity, bm25_ids, bm25_norm, bm25_chunks


def _chunk_index(
    vector_ids: list[str],
    vector_docs: list[str],
    vector_metas: list[dict[str, object]],
    bm25_chunks: list[RegulationChunk],
) -> dict[str, RegulationChunk]:
    chunk_by_id: dict[str, RegulationChunk] = {}
    for cid, doc, meta in zip(vector_ids, vector_docs, vector_metas):
        chunk_by_id[cid] = _chunk_from_metadata(cid, doc, meta)
    for chunk in bm25_chunks:
        chunk_by_id[chunk.chunk_id] = chunk
    return chunk_by_id


def search(
    query: str, top_k: int | None = None, exclusions: list[str] | None = None
) -> SearchResults:
    settings = get_settings()
    k: int = top_k if top_k is not None else settings.top_k_default

    vector_ids, vector_docs, vector_metas, _, bm25_ids, _, bm25_chunks = _run_searches(
        query, k, settings
    )

    chunk_by_id = _chunk_index(vector_ids, vector_docs, vector_metas, bm25_chunks)
    merged = _rrf_merge(vector_ids, bm25_ids, k=settings.rrf_k)

    vector_set = set(vector_ids)
    bm25_set = set(bm25_ids)
    hits: list[SearchHit] = []
    for doc_id, score in merged:
        chunk = chunk_by_id.get(doc_id)
        if chunk is None:
            continue
        # Exclusions are filtered here rather than being fed to the search
        # engines, which have no notion of negation. Filtering before the top-k
        # cut means the caller still gets k results when they exist.
        if exclusions and _excluded(chunk, exclusions):
            continue
        hits.append(
            SearchHit(chunk=chunk, score=score, matched_via=_matched_via(doc_id, vector_set, bm25_set))
        )
        if len(hits) >= k:
            break

    return SearchResults(query=query, hits=hits)


def search_with_provenance(
    query: str,
    glossary_matches: list[GlossaryMatch],
    top_k: int | None = None,
    expanded_query: str | None = None,
    retrieval_query: str | None = None,
    exclusions: list[str] | None = None,
) -> SearchResultsWithProvenance:
    settings = get_settings()
    k: int = top_k if top_k is not None else settings.top_k_default
    search_query = retrieval_query or query

    vector_ids, vector_docs, vector_metas, vector_sim, bm25_ids, bm25_norm, bm25_chunks = (
        _run_searches(search_query, k, settings)
    )

    chunk_by_id = _chunk_index(vector_ids, vector_docs, vector_metas, bm25_chunks)
    merged = _rrf_merge(vector_ids, bm25_ids, k=settings.rrf_k)

    vector_set = set(vector_ids)
    bm25_set = set(bm25_ids)
    hits: list[SearchHitProvenance] = []
    for doc_id, rrf_score in merged:
        chunk = chunk_by_id.get(doc_id)
        if chunk is None:
            continue
        if exclusions and _excluded(chunk, exclusions):
            continue
        hits.append(
            SearchHitProvenance(
                chunk=chunk,
                rrf_score=rrf_score,
                vector_score=vector_sim.get(doc_id),
                bm25_score=bm25_norm.get(doc_id),
                matched_via=_matched_via(doc_id, vector_set, bm25_set),
            )
        )
        if len(hits) >= k:
            break

    return SearchResultsWithProvenance(
        query=query,
        expanded_query=expanded_query if expanded_query and expanded_query != query else None,
        glossary_matches=glossary_matches,
        hits=hits,
    )


def get_section_chunks(citation_str: str) -> list[RegulationChunk]:
    """Return the chunks for a citation.

    When the citation carries subdivisions, only chunks whose own subdivision
    path starts with the requested one are returned — otherwise the caller gets
    a whole section's text labelled as one of its subparagraphs.
    """
    from hipaa_mcp.citations import parse

    citation = parse(citation_str)
    settings = get_settings()
    collection = _get_collection(settings)

    where: dict[str, object] = {
        "$and": [
            {"title": {"$eq": citation.title}},
            {"part": {"$eq": citation.part}},
            {"section": {"$eq": citation.section}},
        ]
    }
    results = collection.get(where=where, include=["documents", "metadatas"])
    chunks = [
        _chunk_from_metadata(cid, doc, dict(meta))
        for cid, doc, meta in zip(results["ids"], results["documents"], results["metadatas"])
    ]

    if citation.subdivisions:
        wanted = citation.subdivisions
        chunks = [
            c for c in chunks if c.citation.subdivisions[: len(wanted)] == wanted
        ]

    chunks.sort(key=lambda c: c.citation.subdivisions)
    return chunks
