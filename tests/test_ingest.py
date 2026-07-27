from __future__ import annotations

from hipaa_mcp.chunking import parse_ecfr_xml
from hipaa_mcp.ingest import CORPORA, _filter_by_part

# One CFR title feeding two different corpus labels — the case that silently
# mislabelled chunks when the label was applied at parse time.
_SHARED_TITLE_XML = (
    '<?xml version="1.0"?>'
    "<ECFR>"
    '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
    '<DIV5 N="160" TYPE="PART"><HEAD>PART 160</HEAD>'
    '<DIV8 N="160.103" TYPE="SECTION">'
    "<HEAD>§ 160.103   Definitions.</HEAD>"
    "<P>Business associate means a person who creates or receives PHI.</P>"
    "</DIV8></DIV5>"
    '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
    '<DIV8 N="164.308" TYPE="SECTION">'
    "<HEAD>§ 164.308   Administrative safeguards.</HEAD>"
    "<P>Security management process.</P>"
    "</DIV8></DIV5>"
    "</DIV1></ECFR>"
).encode()


class TestCorpusLabelling:
    def test_label_applied_per_part_not_per_title(self) -> None:
        parsed = parse_ecfr_xml(_SHARED_TITLE_XML)
        hipaa = _filter_by_part(parsed, 160, "hipaa")
        part2 = _filter_by_part(parsed, 164, "part2")

        assert [c.source_corpus for c in hipaa] == ["hipaa"]
        assert [c.source_corpus for c in part2] == ["part2"]

    def test_filter_selects_only_requested_part(self) -> None:
        parsed = parse_ecfr_xml(_SHARED_TITLE_XML)
        selected = _filter_by_part(parsed, 160, "hipaa")
        assert {c.citation.part for c in selected} == {160}

    def test_original_chunks_not_mutated(self) -> None:
        parsed = parse_ecfr_xml(_SHARED_TITLE_XML)
        before = [c.source_corpus for c in parsed]
        _filter_by_part(parsed, 164, "part2")
        assert [c.source_corpus for c in parsed] == before


class TestCorporaScope:
    def test_part_160_is_indexed(self) -> None:
        """§ 160.103 defines 'business associate'; without Part 160 the flagship
        BAA question has no citable answer."""
        assert (45, 160, "hipaa") in CORPORA

    def test_part_164_and_part2_still_indexed(self) -> None:
        assert (45, 164, "hipaa") in CORPORA
        assert (42, 2, "part2") in CORPORA
