from __future__ import annotations

import pickle
from pathlib import Path

from hipaa_mcp.config import get_settings
from hipaa_mcp.models import Citation, RegulationChunk, SearchHit, SearchResults


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


def search(query: str, top_k: int | None = None) -> SearchResults:
    settings = get_settings()
    k: int = top_k if top_k is not None else settings.top_k_default

    import chromadb

    chroma_client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    collection = chroma_client.get_collection("regulations")

    # Vector search
    vector_results = collection.query(
        query_texts=[query],
        n_results=min(k * 3, 50),
        include=["documents", "metadatas", "distances"],
    )
    vector_ids: list[str] = vector_results["ids"][0]
    vector_docs: list[str] = vector_results["documents"][0]
    vector_metas: list[dict[str, object]] = vector_results["metadatas"][0]  # type: ignore[assignment]

    # BM25 search
    bm25, bm25_chunks = _load_bm25(settings.bm25_index_path)
    tokenized_query = query.lower().split()
    bm25_scores: list[float] = bm25.get_scores(tokenized_query)  # type: ignore[attr-defined]
    top_bm25_idx = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[
        : k * 3
    ]
    bm25_ids = [bm25_chunks[i].chunk_id for i in top_bm25_idx]

    # RRF merge
    merged = _rrf_merge(vector_ids, bm25_ids, k=settings.rrf_k)[:k]

    # Build chunk map for fast lookup
    chunk_by_id: dict[str, RegulationChunk] = {}
    for cid, doc, meta in zip(vector_ids, vector_docs, vector_metas):
        chunk_by_id[cid] = _chunk_from_metadata(cid, doc, meta)
    for chunk in bm25_chunks:
        chunk_by_id[chunk.chunk_id] = chunk

    hits: list[SearchHit] = []
    for doc_id, score in merged:
        if doc_id not in chunk_by_id:
            continue
        in_vector = doc_id in set(vector_ids)
        in_bm25 = doc_id in set(bm25_ids)
        if in_vector and in_bm25:
            matched_via = "hybrid"
        elif in_vector:
            matched_via = "vector"
        else:
            matched_via = "bm25"
        hits.append(SearchHit(chunk=chunk_by_id[doc_id], score=score, matched_via=matched_via))

    return SearchResults(query=query, hits=hits)


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
