from __future__ import annotations

import importlib.resources
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from hipaa_mcp.config import get_settings
from hipaa_mcp.models import Glossary, GlossaryEntry, Relationship

if TYPE_CHECKING:
    import spacy as spacy_type

_nlp: spacy_type.language.Language | None = None


def _get_nlp() -> spacy_type.language.Language | None:
    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        import spacy

        _nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
        return _nlp
    except (ImportError, OSError):
        return None


class GlossaryError(Exception):
    pass


def _seed_path() -> Path:
    ref = importlib.resources.files("hipaa_mcp") / "../../data/seed_glossary.yaml"
    return Path(str(ref))


def _ensure_glossary_exists(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = _seed_path()
    if seed.exists():
        shutil.copy(seed, path)
    else:
        # Write minimal valid glossary if seed missing
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
            print(f"[glossary] Skipping entry {i} — {exc}: {item!r}")

    return Glossary(entries=entries, version=version)


def save_glossary(glossary: Glossary, path: Path | None = None) -> None:
    resolved: Path = path if path is not None else get_settings().glossary_path
    resolved.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": glossary.version,
        "entries": [e.model_dump(mode="json", exclude_none=True) for e in glossary.entries],
    }
    resolved.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _token_pos_map(query: str) -> dict[str, str]:
    """Return lowercase-token → POS tag for each token in query, or {} if spaCy unavailable."""
    nlp = _get_nlp()
    if nlp is None:
        return {}
    doc = nlp(query)
    return {token.text.lower(): token.pos_ for token in doc}


def expand_query(query: str, glossary: Glossary) -> str:
    q_lower = query.lower()
    pos_map = _token_pos_map(query)

    result = query
    additions: list[str] = []
    exclusions: list[str] = []

    for entry in glossary.entries:
        term = entry.term.lower()
        if term not in q_lower:
            continue

        # POS disambiguation for single-word terms: if the term appears as a
        # VERB in context, substitute it directly rather than appending a
        # synonym. This prevents noun-sense BM25 false matches (e.g. "building"
        # the facility vs. "building" the software).
        pos = pos_map.get(term)
        if pos == "VERB" and entry.relationship in (Relationship.synonym, Relationship.hyponym):
            result = re.sub(re.escape(entry.term), entry.maps_to, result, flags=re.IGNORECASE)
            continue

        match entry.relationship:
            case Relationship.synonym:
                additions.append(entry.maps_to)
            case Relationship.hyponym:
                additions.append(entry.maps_to)
            case Relationship.contextual:
                scope_words = entry.scope or []
                if any(s.lower() in q_lower for s in scope_words):
                    additions.append(entry.maps_to)
            case Relationship.anti:
                exclusions.append(entry.maps_to)

    for add in additions:
        if add.lower() not in result.lower():
            result = f"{result} OR {add}"
    for excl in exclusions:
        result = f"{result} NOT {excl}"

    return result
