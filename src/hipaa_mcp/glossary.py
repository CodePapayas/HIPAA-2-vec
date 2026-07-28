from __future__ import annotations

import importlib.resources
import re
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

import yaml

from hipaa_mcp.config import get_settings
from hipaa_mcp.models import (
    ExpandedQuery,
    Glossary,
    GlossaryEntry,
    GlossaryMatch,
    Relationship,
)


class GlossaryError(Exception):
    pass


def _warn(message: str) -> None:
    """Warnings go to stderr.

    The MCP server speaks JSON-RPC over stdout; any stray stdout write from a
    tool call corrupts the transport framing.
    """
    print(message, file=sys.stderr)


def _copy_seed_to(path: Path) -> bool:
    """Copy the packaged seed glossary to ``path``. Returns False if unavailable."""
    try:
        ref = importlib.resources.files("hipaa_mcp") / "data" / "seed_glossary.yaml"
        with ExitStack() as stack:
            seed = stack.enter_context(importlib.resources.as_file(ref))
            if not seed.is_file():
                return False
            shutil.copy(seed, path)
        return True
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return False


def _ensure_glossary_exists(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if _copy_seed_to(path):
        return
    _warn(
        f"[glossary] Packaged seed glossary not found; wrote an empty glossary to {path}. "
        "Reinstall hipaa-mcp or add terms with `add_glossary_term`."
    )
    path.write_text("version: 1\nentries: []\n")


def load_glossary(path: Path | None = None) -> Glossary:
    resolved: Path = path if path is not None else get_settings().glossary_path
    _ensure_glossary_exists(resolved)

    raw = yaml.safe_load(resolved.read_text())
    if not isinstance(raw, dict):
        raise GlossaryError(f"Glossary file {resolved} is not a YAML mapping")

    version = int(raw.get("version", 1))
    raw_entries = raw.get("entries", [])
    if not isinstance(raw_entries, list):
        raise GlossaryError("'entries' must be a list")

    entries: list[GlossaryEntry] = []
    for i, item in enumerate(raw_entries):
        try:
            entries.append(GlossaryEntry.model_validate(item))
        except Exception as exc:
            _warn(f"[glossary] Skipping entry {i} — {exc}: {item!r}")

    return Glossary(entries=entries, version=version)


def save_glossary(glossary: Glossary, path: Path | None = None) -> None:
    resolved: Path = path if path is not None else get_settings().glossary_path
    resolved.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": glossary.version,
        "entries": [e.model_dump(mode="json", exclude_none=True) for e in glossary.entries],
    }
    resolved.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _word_pattern(term: str) -> re.Pattern[str]:
    """Word-boundary pattern for a glossary term.

    Substring matching is wrong here: `log` would match `biology`, and a bare
    `re.sub` of `share` turns `shared` into `disclosured`.
    """
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def contains_term(text: str, term: str) -> bool:
    return _word_pattern(term).search(text) is not None


def _glossary_match_confidence(entry: GlossaryEntry, scope_triggered: list[str]) -> float:
    match entry.relationship:
        case Relationship.synonym:
            return 1.0
        case Relationship.hyponym:
            return 0.9
        case Relationship.contextual:
            total = len(entry.scope or [])
            matched = len(scope_triggered)
            if total == 0 or matched == 0:
                return 0.5
            return round(0.5 + (matched / total) * 0.45, 4)
        case Relationship.anti:
            return 1.0


def _match(entry: GlossaryEntry, scope_triggered: list[str] | None = None) -> GlossaryMatch:
    return GlossaryMatch(
        term=entry.term,
        maps_to=entry.maps_to,
        relationship=entry.relationship,
        scope_triggered=scope_triggered or None,
        confidence=_glossary_match_confidence(entry, scope_triggered or []),
    )


def expand_query(query: str, glossary: Glossary) -> tuple[ExpandedQuery, list[GlossaryMatch]]:
    """Expand a plain-English query with regulatory vocabulary.

    The retrieval query is a plain bag of terms. Boolean operators are not
    emitted: neither BM25Okapi nor embedding search understands them, so an
    `anti` entry rendered as `NOT <term>` would inject the very term it means
    to exclude. Exclusions are returned separately and applied as a
    post-retrieval filter.
    """
    additions: list[str] = []
    exclusions: list[str] = []
    matches: list[GlossaryMatch] = []

    for entry in glossary.entries:
        if not contains_term(query, entry.term):
            continue

        match entry.relationship:
            case Relationship.synonym | Relationship.hyponym:
                additions.append(entry.maps_to)
                matches.append(_match(entry))
            case Relationship.contextual:
                triggered = [s for s in (entry.scope or []) if contains_term(query, s)]
                if triggered:
                    additions.append(entry.maps_to)
                    matches.append(_match(entry, triggered))
            case Relationship.anti:
                exclusions.append(entry.maps_to)
                matches.append(_match(entry))

    kept_additions: list[str] = []
    retrieval_query = query
    for add in additions:
        if contains_term(retrieval_query, add):
            continue
        kept_additions.append(add)
        retrieval_query = f"{retrieval_query} {add}"

    return (
        ExpandedQuery(
            original=query,
            query=retrieval_query,
            additions=kept_additions,
            exclusions=exclusions,
        ),
        matches,
    )
