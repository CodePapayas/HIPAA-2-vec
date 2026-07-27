from __future__ import annotations

import json
from datetime import date

import click
import httpx
from rank_bm25 import BM25Okapi

from hipaa_mcp.chunking import SourceCorpus, parse_ecfr_xml
from hipaa_mcp.config import INDEX_FORMAT, get_settings
from hipaa_mcp.models import RegulationChunk

ECFR_BASE = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml"
ECFR_TITLES = "https://www.ecfr.gov/api/versioner/v1/titles"

# (title, part, corpus_label)
#
# Part 160 carries the definitions the rest of HIPAA leans on — "business
# associate" and "covered entity" are defined at § 160.103, not in Part 164 —
# so the flagship "do I need a BAA?" question is unanswerable without it.
# Part 162 (transactions and code sets) is left out: it is EDI format
# specification, not a source of the vocabulary developers ask about.
CORPORA: list[tuple[int, int, SourceCorpus]] = [
    (45, 160, "hipaa"),
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
    click.echo(
        f"Warning: requested {requested}, but Title {title} only available through "
        f"{latest}. Using {latest}.",
        err=True,
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


def _filter_by_part(
    chunks: list[RegulationChunk], part: int, corpus: SourceCorpus
) -> list[RegulationChunk]:
    """Select one part's chunks and stamp the corpus label.

    Labelling happens here rather than at parse time: one CFR title can feed
    more than one corpus, and labelling the whole parsed title with the first
    matching entry's label would silently mislabel every other part.
    """
    return [
        c.model_copy(update={"source_corpus": corpus})
        for c in chunks
        if c.citation.part == part
    ]


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
    # Cosine space is required: retrieval maps distance → similarity assuming
    # a bounded [0, 2] cosine distance. Chroma's default (l2) is unbounded and
    # would make every reported vector score meaningless.
    collection = client.create_collection(
        "regulations",
        metadata={"hnsw:space": "cosine", "index_format": INDEX_FORMAT},
    )

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

    write_bm25_index(chunks)

    from hipaa_mcp.retrieval import reset_caches

    reset_caches()


def write_bm25_index(chunks: list[RegulationChunk]) -> None:
    """Persist the lexical index as JSON.

    Tokens plus chunk data, not a pickled BM25Okapi: unpickling a file from the
    user data directory would execute whatever is in it. BM25Okapi is rebuilt
    from the tokens on load, which is cheap at this corpus size.
    """
    settings = get_settings()
    settings.bm25_index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "index_format": INDEX_FORMAT,
        "tokens": [c.text.lower().split() for c in chunks],
        "chunks": [c.model_dump(mode="json") for c in chunks],
    }
    settings.bm25_index_path.write_text(json.dumps(payload))
    # Constructed here purely to fail loudly at index time if the corpus is
    # degenerate, rather than at first query.
    BM25Okapi(payload["tokens"] or [[""]])


def reindex(as_of: date | None = None) -> None:
    if as_of is None:
        as_of = date.today()

    parsed_by_title: dict[int, list[RegulationChunk]] = {}
    all_chunks: list[RegulationChunk] = []

    with httpx.Client(timeout=120) as client:
        for title, part, corpus in CORPORA:
            if title not in parsed_by_title:
                effective = _resolve_date(title, as_of, client)
                click.echo(f"Downloading Title {title} XML for {effective}...", err=True)
                url = _ecfr_url(title, effective)
                resp = client.get(url, timeout=120)
                resp.raise_for_status()
                parsed_by_title[title] = parse_ecfr_xml(resp.content)

            all_chunks.extend(_filter_by_part(parsed_by_title[title], part, corpus))

    click.echo(f"Indexing {len(all_chunks)} chunks...", err=True)
    build_indices(all_chunks)
    click.echo("Done.", err=True)
