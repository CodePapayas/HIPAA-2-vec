from __future__ import annotations

from pathlib import Path

import pytest

from hipaa_mcp.glossary import expand_query, load_glossary
from hipaa_mcp.models import Glossary, GlossaryEntry, Relationship


def _g(*entries: GlossaryEntry) -> Glossary:
    return Glossary(entries=list(entries), version=1)


def _e(
    term: str,
    maps_to: str,
    rel: str,
    scope: list[str] | None = None,
) -> GlossaryEntry:
    return GlossaryEntry(term=term, maps_to=maps_to, relationship=Relationship(rel), scope=scope)


class TestSynonymExpansion:
    def test_adds_mapped_term(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        result = expand_query("do I need a BAA for this vendor?", g)
        assert "business associate" in result

    def test_no_duplicate_when_already_present(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        result = expand_query("vendor business associate", g)
        assert result.count("business associate") == 1

    def test_or_semantics(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        result = expand_query("vendor agreement", g)
        assert "OR" in result


class TestHyponymExpansion:
    def test_expands_term_to_target(self) -> None:
        g = _g(_e("send", "disclosure", "hyponym"))
        result = expand_query("can I send PHI to a vendor?", g)
        assert "disclosure" in result

    def test_does_not_expand_reverse(self) -> None:
        g = _g(_e("send", "disclosure", "hyponym"))
        result = expand_query("what counts as a disclosure?", g)
        assert result == "what counts as a disclosure?"


class TestContextualExpansion:
    def test_expands_when_scope_present(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=["audit", "access"]))
        result = expand_query("audit logging requirements", g)
        assert "use/disclosure" in result

    def test_no_expand_without_scope_word(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=["audit", "access"]))
        result = expand_query("logging configuration setup", g)
        assert "use/disclosure" not in result

    def test_no_expand_when_scope_is_none(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=None))
        result = expand_query("logging requirements", g)
        assert "use/disclosure" not in result


class TestAntiExpansion:
    def test_excludes_mapped_term(self) -> None:
        g = _g(_e("de-identified", "not PHI", "anti"))
        result = expand_query("de-identified data handling", g)
        assert "NOT" in result
        assert "not PHI" in result

    def test_no_match_unchanged(self) -> None:
        g = _g(_e("de-identified", "not PHI", "anti"))
        q = "what is PHI?"
        assert expand_query(q, g) == q


class TestNoMatch:
    def test_unmatched_query_unchanged(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        q = "what is a covered entity?"
        assert expand_query(q, g) == q


class TestLoadGlossary:
    def test_bad_entry_skipped_rest_loaded(self, tmp_path: Path) -> None:
        f = tmp_path / "glossary.yaml"
        f.write_text(
            "version: 1\nentries:\n"
            "  - {term: ok, maps_to: fine, relationship: synonym}\n"
            "  - {bad: entry}\n"
        )
        g = load_glossary(f)
        assert len(g.entries) == 1
        assert g.entries[0].term == "ok"

    def test_missing_file_creates_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "glossary.yaml"
        g = load_glossary(path)
        assert isinstance(g, Glossary)

    def test_version_parsed(self, tmp_path: Path) -> None:
        f = tmp_path / "g.yaml"
        f.write_text("version: 3\nentries: []\n")
        assert load_glossary(f).version == 3
