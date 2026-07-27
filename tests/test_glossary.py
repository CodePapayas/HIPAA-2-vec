from __future__ import annotations

from pathlib import Path

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
        expanded, _ = expand_query("do I need a BAA for this vendor?", g)
        assert "business associate" in expanded.query
        assert expanded.additions == ["business associate"]

    def test_no_duplicate_when_already_present(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        expanded, _ = expand_query("vendor business associate", g)
        assert expanded.query.count("business associate") == 1
        assert expanded.additions == []

    def test_display_renders_or(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        expanded, _ = expand_query("vendor agreement", g)
        assert "OR business associate" in expanded.display()

    def test_retrieval_query_has_no_operators(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        expanded, _ = expand_query("vendor agreement", g)
        assert " OR " not in expanded.query
        assert " NOT " not in expanded.query


class TestHyponymExpansion:
    def test_expands_term_to_target(self) -> None:
        g = _g(_e("send", "disclosure", "hyponym"))
        expanded, _ = expand_query("can I send PHI to a vendor?", g)
        assert "disclosure" in expanded.query

    def test_does_not_expand_reverse(self) -> None:
        g = _g(_e("send", "disclosure", "hyponym"))
        expanded, _ = expand_query("what counts as a disclosure?", g)
        assert expanded.query == "what counts as a disclosure?"
        assert expanded.additions == []


class TestContextualExpansion:
    def test_expands_when_scope_present(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=["audit", "access"]))
        expanded, _ = expand_query("audit logging requirements", g)
        assert "use/disclosure" in expanded.query

    def test_no_expand_without_scope_word(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=["audit", "access"]))
        expanded, _ = expand_query("logging configuration setup", g)
        assert "use/disclosure" not in expanded.query

    def test_no_expand_when_scope_is_none(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=None))
        expanded, _ = expand_query("logging requirements", g)
        assert "use/disclosure" not in expanded.query


class TestAntiExpansion:
    def test_excluded_term_absent_from_retrieval_query(self) -> None:
        """An `anti` entry must never inject its target into the search string.

        BM25 and the embedding model have no notion of negation, so a literal
        `NOT not PHI` suffix would *boost* exactly what it means to suppress.
        """
        g = _g(_e("de-identified", "not PHI", "anti"))
        expanded, _ = expand_query("de-identified data handling", g)
        assert expanded.exclusions == ["not PHI"]
        assert "not PHI" not in expanded.query
        assert "NOT" not in expanded.query

    def test_display_still_shows_not(self) -> None:
        g = _g(_e("de-identified", "not PHI", "anti"))
        expanded, _ = expand_query("de-identified data handling", g)
        assert "NOT not PHI" in expanded.display()

    def test_no_match_unchanged(self) -> None:
        g = _g(_e("de-identified", "not PHI", "anti"))
        q = "what is PHI?"
        expanded, matches = expand_query(q, g)
        assert expanded.query == q
        assert expanded.exclusions == []
        assert matches == []


class TestWordBoundaries:
    def test_substring_does_not_match(self) -> None:
        g = _g(_e("log", "use/disclosure", "synonym"))
        expanded, matches = expand_query("biology of the data model", g)
        assert matches == []
        assert expanded.query == "biology of the data model"

    def test_inflected_form_does_not_match(self) -> None:
        g = _g(_e("share", "disclosure", "hyponym"))
        expanded, matches = expand_query("shared data buckets", g)
        assert matches == []
        assert "disclosure" not in expanded.query

    def test_multi_word_term_matches(self) -> None:
        g = _g(_e("third party", "business associate", "synonym"))
        expanded, _ = expand_query("can a third party read this?", g)
        assert "business associate" in expanded.query

    def test_scope_check_uses_word_boundaries(self) -> None:
        g = _g(_e("logging", "use/disclosure", "contextual", scope=["audit"]))
        expanded, _ = expand_query("auditory logging setup", g)
        assert "use/disclosure" not in expanded.query


class TestNoMatch:
    def test_unmatched_query_unchanged(self) -> None:
        g = _g(_e("vendor", "business associate", "synonym"))
        q = "what is a covered entity?"
        expanded, matches = expand_query(q, g)
        assert expanded.query == q
        assert expanded.changed() is False
        assert matches == []


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

    def test_bad_entry_reported_on_stderr_not_stdout(
        self, tmp_path: Path, capsys: object
    ) -> None:
        """Warnings must never touch stdout — it carries the MCP JSON-RPC frames."""
        f = tmp_path / "glossary.yaml"
        f.write_text("version: 1\nentries:\n  - {bad: entry}\n")
        load_glossary(f)
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert captured.out == ""
        assert "Skipping entry 0" in captured.err

    def test_missing_file_creates_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "glossary.yaml"
        g = load_glossary(path)
        assert isinstance(g, Glossary)

    def test_missing_file_seeded_from_package(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "glossary.yaml"
        g = load_glossary(path)
        assert len(g.entries) > 0, "packaged seed glossary should have been copied"

    def test_version_parsed(self, tmp_path: Path) -> None:
        f = tmp_path / "g.yaml"
        f.write_text("version: 3\nentries: []\n")
        assert load_glossary(f).version == 3
