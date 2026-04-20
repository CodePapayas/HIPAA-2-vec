from __future__ import annotations

import pickle
from datetime import date

import httpx
from rank_bm25 import BM25Okapi

from hipaa_mcp.chunking import SourceCorpus, parse_ecfr_xml
from hipaa_mcp.config import get_settings
from hipaa_mcp.models import RegulationChunk

ECFR_BASE = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml"
ECFR_TITLES = "https://www.ecfr.gov/api/versioner/v1/titles"

# (title, part, corpus_label)
CORPORA: list[tuple[int, int, SourceCorpus]] = [
    (45, 164, "hipaa"),
    (42, 2, "part2"),
]


def _latest_available_date(title: int, client: httpx.Client) -> date:
    resp = client.get(ECFR_TITLES, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    for entry in payload.get("titles", []):
        if entry.get("number") != title:
            continue
        # Prefer up_to_date_as_of; fall back to meta.date when not importing
        if uad := entry.get("up_to_date_as_of"):
            return date.fromisoformat(uad)
        meta = entry.get("meta", {})
        if not meta.get("import_in_progress") and (md := meta.get("date")):
            return date.fromisoformat(md)
    raise ValueError(f"Title {title} not found in eCFR titles endpoint")


def _resolve_date(title: int, requested: date, client: httpx.Client) -> date:
    latest = _latest_available_date(title, client)
    if requested <= latest:
        return requested
    print(
        f"Warning: requested {requested}, but Title {title} only available through "
        f"{latest}. Using {latest}."
    )
    return latest


def _ecfr_url(title: int, as_of: date) -> str:
    return ECFR_BASE.format(date=as_of.isoformat(), title=title)


def download_xml(title: int, as_of: date, client: httpx.Client | None = None) -> bytes:
    def _fetch(c: httpx.Client) -> bytes:
        effective = _resolve_date(title, as_of, c)
        url = _ecfr_url(title, effective)
        resp = c.get(url, timeout=120)
        resp.raise_for_status()
        return resp.content

    if client is not None:
        return _fetch(client)
    with httpx.Client(timeout=120) as c:
        return _fetch(c)


def _filter_by_part(chunks: list[RegulationChunk], part: int) -> list[RegulationChunk]:
    return [c for c in chunks if c.citation.part == part]


def build_indices(chunks: list[RegulationChunk]) -> None:
    settings = get_settings()
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)

    import chromadb

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    try:
        client.delete_collection("regulations")
    except Exception:
        pass
    collection = client.create_collection("regulations")

    ids = [c.chunk_id for c in chunks]
    documents = [c.text for c in chunks]
    metadatas: list[dict[str, str | int]] = [
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
    ]

    batch = 100
    for i in range(0, len(chunks), batch):
        collection.upsert(
            ids=ids[i : i + batch],
            documents=documents[i : i + batch],
            metadatas=metadatas[i : i + batch],
        )

    tokenized = [doc.lower().split() for doc in documents]
    bm25 = BM25Okapi(tokenized)
    with open(settings.bm25_index_path, "wb") as f:
        pickle.dump({"bm25": bm25, "chunks": chunks}, f)


def reindex(as_of: date | None = None) -> None:
    if as_of is None:
        as_of = date.today()

    parsed_by_title: dict[int, list[RegulationChunk]] = {}
    all_chunks: list[RegulationChunk] = []

    with httpx.Client(timeout=120) as client:
        for title, part, corpus in CORPORA:
            if title not in parsed_by_title:
                effective = _resolve_date(title, as_of, client)
                print(f"Downloading Title {title} XML for {effective}...")
                url = _ecfr_url(title, effective)
                resp = client.get(url, timeout=120)
                resp.raise_for_status()
                xml_bytes = resp.content
                parsed_by_title[title] = parse_ecfr_xml(xml_bytes, corpus)

            part_chunks = _filter_by_part(parsed_by_title[title], part)
            all_chunks.extend(part_chunks)

    print(f"Indexing {len(all_chunks)} chunks...")
    build_indices(all_chunks)
    print("Done.")
