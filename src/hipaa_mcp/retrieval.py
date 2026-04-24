from __future__ import annotations

import pickle
from pathlib import Path

from hipaa_mcp.config import get_settings
from hipaa_mcp.models import (
    Citation,
    GlossaryMatch,
    RegulationChunk,
    SearchHit,
    SearchHitProvenance,
    SearchResults,
    SearchResultsWithProvenance,
)


def _load_bm25(path: Path) -> tuple[object, list[RegulationChunk]]:
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data["bm25"], data["chunks"]


def _chunk_from_metadata(chunk_id: str, doc: str, meta: dict[str, object]) -> RegulationChunk:
    subdivisions = str(meta.get("subdivisions", ""))
    subs = [s for s in subdivisions.split("|") if s]
    citation = Citation(
        title=int(meta["title"]),  # type: ignore[arg-type]
        part=int(meta["part"]),  # type: ignore[arg-type]
        section=int(meta["section"]),  # type: ignore[arg-type]
        subdivisions=subs,
    )
    source_corpus = str(meta.get("source_corpus", "hipaa"))
    if source_corpus not in ("hipaa", "part2"):
        source_corpus = "hipaa"
    from typing import Literal

    sc: Literal["hipaa", "part2"] = "hipaa" if source_corpus == "hipaa" else "part2"
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


def _run_searches(
    query: str, k: int, settings: object
) -> tuple[
    list[str],  # vector_ids
    list[str],  # vector_docs
    list[dict[str, object]],  # vector_metas
    dict[str, float],  # vector_similarity by id (0-1)
    list[str],  # bm25_ids
    dict[str, float],  # bm25_norm_score by id (0-1)
    list[RegulationChunk],  # all bm25 chunks
]:
    import chromadb

    from hipaa_mcp.config import Settings

    s: Settings = settings  # type: ignore[assignment]

    chroma_client = chromadb.PersistentClient(path=str(s.chroma_dir))
    collection = chroma_client.get_collection("regulations")

    vector_results = collection.query(
        query_texts=[query],
        n_results=min(k * 3, 50),
        include=["documents", "metadatas", "distances"],
    )
    vector_ids: list[str] = vector_results["ids"][0]
    vector_docs: list[str] = vector_results["documents"][0]
    vector_metas: list[dict[str, object]] = vector_results["metadatas"][0]  # type: ignore[assignment]
    raw_distances: list[float] = vector_results["distances"][0]
    # ChromaDB cosine distance ∈ [0, 2]; map to similarity ∈ [0, 1] via (2 - dist) / 2
    vector_similarity: dict[str, float] = {
        cid: round((2.0 - dist) / 2.0, 6) for cid, dist in zip(vector_ids, raw_distances)
    }

    bm25, bm25_chunks = _load_bm25(s.bm25_index_path)
    tokenized_query = query.lower().split()
    bm25_raw: list[float] = bm25.get_scores(tokenized_query)  # type: ignore[attr-defined]
    top_bm25_idx = sorted(range(len(bm25_raw)), key=lambda i: bm25_raw[i], reverse=True)[: k * 3]
    bm25_ids = [bm25_chunks[i].chunk_id for i in top_bm25_idx]
    max_bm25 = max((bm25_raw[i] for i in top_bm25_idx), default=1.0) or 1.0
    bm25_norm: dict[str, float] = {
        bm25_chunks[i].chunk_id: round(bm25_raw[i] / max_bm25, 6) for i in top_bm25_idx
    }

    return vector_ids, vector_docs, vector_metas, vector_similarity, bm25_ids, bm25_norm, bm25_chunks


def search(query: str, top_k: int | None = None) -> SearchResults:
    settings = get_settings()
    k: int = top_k if top_k is not None else settings.top_k_default

    vector_ids, vector_docs, vector_metas, _, bm25_ids, _, bm25_chunks = _run_searches(
        query, k, settings
    )

    merged = _rrf_merge(vector_ids, bm25_ids, k=settings.rrf_k)[:k]

    chunk_by_id: dict[str, RegulationChunk] = {}
    for cid, doc, meta in zip(vector_ids, vector_docs, vector_metas):
        chunk_by_id[cid] = _chunk_from_metadata(cid, doc, meta)
    for chunk in bm25_chunks:
        chunk_by_id[chunk.chunk_id] = chunk

    hits: list[SearchHit] = []
    vector_set = set(vector_ids)
    bm25_set = set(bm25_ids)
    for doc_id, score in merged:
        if doc_id not in chunk_by_id:
            continue
        in_vector = doc_id in vector_set
        in_bm25 = doc_id in bm25_set
        if in_vector and in_bm25:
            matched_via = "hybrid"
        elif in_vector:
            matched_via = "vector"
        else:
            matched_via = "bm25"
        hits.append(SearchHit(chunk=chunk_by_id[doc_id], score=score, matched_via=matched_via))

    return SearchResults(query=query, hits=hits)


def search_with_provenance(
    query: str,
    glossary_matches: list[GlossaryMatch],
    top_k: int | None = None,
    expanded_query: str | None = None,
) -> SearchResultsWithProvenance:
    settings = get_settings()
    k: int = top_k if top_k is not None else settings.top_k_default
    search_query = expanded_query or query

    vector_ids, vector_docs, vector_metas, vector_sim, bm25_ids, bm25_norm, bm25_chunks = (
        _run_searches(search_query, k, settings)
    )

    merged = _rrf_merge(vector_ids, bm25_ids, k=settings.rrf_k)[:k]

    chunk_by_id: dict[str, RegulationChunk] = {}
    for cid, doc, meta in zip(vector_ids, vector_docs, vector_metas):
        chunk_by_id[cid] = _chunk_from_metadata(cid, doc, meta)
    for chunk in bm25_chunks:
        chunk_by_id[chunk.chunk_id] = chunk

    hits: list[SearchHitProvenance] = []
    vector_set = set(vector_ids)
    bm25_set = set(bm25_ids)
    for doc_id, rrf_score in merged:
        if doc_id not in chunk_by_id:
            continue
        in_vector = doc_id in vector_set
        in_bm25 = doc_id in bm25_set
        if in_vector and in_bm25:
            matched_via = "hybrid"
        elif in_vector:
            matched_via = "vector"
        else:
            matched_via = "bm25"
        hits.append(
            SearchHitProvenance(
                chunk=chunk_by_id[doc_id],
                rrf_score=rrf_score,
                vector_score=vector_sim.get(doc_id),
                bm25_score=bm25_norm.get(doc_id),
                matched_via=matched_via,
            )
        )

    return SearchResultsWithProvenance(
        query=query,
        expanded_query=expanded_query if expanded_query and expanded_query != query else None,
        glossary_matches=glossary_matches,
        hits=hits,
    )


def get_section_chunks(citation_str: str) -> list[RegulationChunk]:
    from hipaa_mcp.citations import parse

    citation = parse(citation_str)
    settings = get_settings()

    import chromadb

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    collection = client.get_collection("regulations")

    where: dict[str, object] = {
        "$and": [
            {"title": {"$eq": citation.title}},
            {"part": {"$eq": citation.part}},
            {"section": {"$eq": citation.section}},
        ]
    }
    results = collection.get(where=where, include=["documents", "metadatas"])
    chunks = []
    for cid, doc, meta in zip(results["ids"], results["documents"], results["metadatas"]):
        chunks.append(_chunk_from_metadata(cid, doc, meta))  # type: ignore[arg-type]
    return chunks
