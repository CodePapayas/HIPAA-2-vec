from __future__ import annotations

from hipaa_mcp.chunking import parse_ecfr_xml

_MINIMAL_XML = (
    '<?xml version="1.0"?>'
    "<ECFR>"
    '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
    '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
    '<DIV8 N="164.308" TYPE="SECTION">'
    "<HEAD>\u00a7 164.308   Administrative safeguards.</HEAD>"
    "<P>Standard: Security management process.</P>"
    "<P>Implementation specification: Risk analysis required.</P>"
    "</DIV8>"
    '<DIV8 N="164.312" TYPE="SECTION">'
    "<HEAD>\u00a7 164.312   Technical safeguards.</HEAD>"
    "<P>Access control standard.</P>"
    "</DIV8>"
    "</DIV5></DIV1></ECFR>"
).encode()

_PART2_XML = (
    '<?xml version="1.0"?>'
    "<ECFR>"
    '<DIV1 N="42" TYPE="TITLE"><HEAD>Title 42</HEAD>'
    '<DIV5 N="2" TYPE="PART"><HEAD>PART 2</HEAD>'
    '<DIV8 N="2.11" TYPE="SECTION">'
    "<HEAD>\u00a7 2.11   Definitions.</HEAD>"
    "<P>Patient means any individual who has applied for diagnosis or treatment.</P>"
    "</DIV8>"
    "</DIV5></DIV1></ECFR>"
).encode()


class TestChunkCount:
    def test_two_sections_two_chunks(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        assert len(chunks) == 2

    def test_single_section_one_chunk(self) -> None:
        chunks = parse_ecfr_xml(_PART2_XML, "part2")
        assert len(chunks) == 1


class TestCitationAttribution:
    def test_section_numbers_correct(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        sections = {c.citation.section for c in chunks}
        assert sections == {308, 312}

    def test_part_number_correct(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        assert all(c.citation.part == 164 for c in chunks)

    def test_title_correct(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        assert all(c.citation.title == 45 for c in chunks)

    def test_part2_title_42(self) -> None:
        chunks = parse_ecfr_xml(_PART2_XML, "part2")
        assert chunks[0].citation.title == 42
        assert chunks[0].citation.part == 2
        assert chunks[0].citation.section == 11


class TestChunkBoundaries:
    def test_no_chunk_spans_two_sections(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        c308 = next(c for c in chunks if c.citation.section == 308)
        c312 = next(c for c in chunks if c.citation.section == 312)
        assert "Access control" not in c308.text
        assert "Security management" not in c312.text

    def test_all_paragraphs_in_section_chunk(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        c308 = next(c for c in chunks if c.citation.section == 308)
        assert "Security management process" in c308.text
        assert "Risk analysis required" in c308.text


class TestMetadata:
    def test_heading_extracted(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        c308 = next(c for c in chunks if c.citation.section == 308)
        assert "Administrative safeguards" in c308.heading

    def test_source_corpus_set(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        assert all(c.source_corpus == "hipaa" for c in chunks)

    def test_chunk_ids_unique(self) -> None:
        chunks = parse_ecfr_xml(_MINIMAL_XML, "hipaa")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_empty_corpus_returns_empty(self) -> None:
        xml = b"""<?xml version="1.0"?>
<ECFR><DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD></DIV1></ECFR>"""
        assert parse_ecfr_xml(xml, "hipaa") == []
