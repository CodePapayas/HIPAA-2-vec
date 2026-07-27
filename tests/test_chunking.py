from __future__ import annotations

from hipaa_mcp.chunking import parse_ecfr_xml, resolve_subdivision_path, split_definitions

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


_NESTED_XML = (
    '<?xml version="1.0"?>'
    "<ECFR>"
    '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
    '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
    '<DIV8 N="164.308" TYPE="SECTION">'
    "<HEAD>§ 164.308   Administrative safeguards.</HEAD>"
    "<P>A covered entity must comply with the following.</P>"
    "<P>(a) General requirements.</P>"
    "<P>(1) Standard: Security management process.</P>"
    "<P>(i) Risk analysis.</P>"
    "<P>(ii) Risk management.</P>"
    "<P>(A) Conduct an accurate assessment.</P>"
    "<P>(2) Standard: Assigned security responsibility.</P>"
    "<P>(b) Business associate contracts.</P>"
    "</DIV8>"
    "</DIV5></DIV1></ECFR>"
).encode()

# (g) → (h) → (i): the third marker is the next *letter*, not roman numeral one.
_AMBIGUOUS_XML = (
    '<?xml version="1.0"?>'
    "<ECFR>"
    '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
    '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
    '<DIV8 N="164.502" TYPE="SECTION">'
    "<HEAD>§ 164.502   Uses and disclosures.</HEAD>"
    "<P>(g) Personal representatives.</P>"
    "<P>(h) Confidential communications.</P>"
    "<P>(i) Uses and disclosures consistent with notice.</P>"
    "<P>(j) Disclosures by whistleblowers.</P>"
    "</DIV8>"
    "</DIV5></DIV1></ECFR>"
).encode()

_TWO_PARTS_ONE_TITLE_XML = (
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


def _subs(chunks: list, section: int | None = None) -> list[list[str]]:
    return [
        c.citation.subdivisions
        for c in chunks
        if section is None or c.citation.section == section
    ]


class TestSubdivisionPaths:
    def test_intro_paragraph_has_no_subdivisions(self) -> None:
        chunks = parse_ecfr_xml(_NESTED_XML, "hipaa")
        assert chunks[0].citation.subdivisions == []
        assert "must comply with the following" in chunks[0].text

    def test_nested_markers_build_full_path(self) -> None:
        chunks = parse_ecfr_xml(_NESTED_XML, "hipaa")
        assert _subs(chunks) == [
            [],
            ["a"],
            ["a", "1"],
            ["a", "1", "i"],
            ["a", "1", "ii"],
            ["a", "1", "ii", "A"],
            ["a", "2"],
            ["b"],
        ]

    def test_deep_citation_formats_correctly(self) -> None:
        chunks = parse_ecfr_xml(_NESTED_XML, "hipaa")
        deep = next(c for c in chunks if c.citation.subdivisions == ["a", "1", "ii", "A"])
        assert deep.citation.format() == "§ 164.308(a)(1)(ii)(A)"

    def test_alpha_i_after_h_stays_alpha(self) -> None:
        chunks = parse_ecfr_xml(_AMBIGUOUS_XML, "hipaa")
        assert _subs(chunks) == [["g"], ["h"], ["i"], ["j"]]

    def test_heading_kept_on_every_chunk(self) -> None:
        chunks = parse_ecfr_xml(_NESTED_XML, "hipaa")
        assert all("Administrative safeguards" in c.heading for c in chunks)

    def test_nested_chunk_ids_unique(self) -> None:
        chunks = parse_ecfr_xml(_NESTED_XML, "hipaa")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_no_chunk_spans_two_sections_when_nested(self) -> None:
        chunks = parse_ecfr_xml(_TWO_PARTS_ONE_TITLE_XML, "hipaa")
        c160 = next(c for c in chunks if c.citation.part == 160)
        c164 = next(c for c in chunks if c.citation.part == 164)
        assert "Security management" not in c160.text
        assert "Business associate means" not in c164.text


class TestRealisticECFRMarkup:
    """eCFR wraps paragraph headings in <I>; markers live in the P text itself."""

    _XML = (
        '<?xml version="1.0"?>'
        "<ECFR>"
        '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
        '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
        '<DIV8 N="164.308" TYPE="SECTION">'
        "<HEAD>§ 164.308   Administrative safeguards.</HEAD>"
        "<P>(a) <I>General requirements.</I> A covered entity must:</P>"
        "<P>(1)(i) <I>Standard: Security management process.</I> Implement policies.</P>"
        "<P>(ii) <I>Implementation specifications:</I> </P>"
        "<P>(A) <I>Risk analysis</I> (Required). Conduct an accurate assessment.</P>"
        "</DIV8>"
        "</DIV5></DIV1></ECFR>"
    ).encode()

    def test_inline_markup_does_not_break_marker_parsing(self) -> None:
        chunks = parse_ecfr_xml(self._XML, "hipaa")
        assert [c.citation.subdivisions for c in chunks] == [
            ["a"],
            ["a", "1", "i"],
            ["a", "1", "ii"],
            ["a", "1", "ii", "A"],
        ]

    def test_deep_citation_from_realistic_markup(self) -> None:
        chunks = parse_ecfr_xml(self._XML, "hipaa")
        deep = chunks[-1]
        assert deep.citation.format() == "§ 164.308(a)(1)(ii)(A)"
        assert "Conduct an accurate assessment" in deep.text


class TestResolveSubdivisionPath:
    def test_sibling_after_deep_path(self) -> None:
        assert resolve_subdivision_path(["iii"], ["a", "1", "ii"]) == ["a", "1", "iii"]

    def test_reset_to_new_top_level(self) -> None:
        assert resolve_subdivision_path(["b"], ["a", "1", "ii"]) == ["b"]

    def test_multi_marker_paragraph(self) -> None:
        assert resolve_subdivision_path(["a", "1"], []) == ["a", "1"]

    def test_roman_opens_third_level(self) -> None:
        assert resolve_subdivision_path(["i"], ["a", "1"]) == ["a", "1", "i"]

    def test_letter_i_continues_alpha_sequence(self) -> None:
        assert resolve_subdivision_path(["i"], ["h"]) == ["i"]

    def test_resumes_level_opened_inline_by_previous_paragraph(self) -> None:
        """`(e)(1) ... (i) ...` is one <P>; the next <P> is `(ii)`.

        Level 3 was never opened by a paragraph of its own, so `(ii)` must still
        land under (e)(1) rather than becoming a bare top-level `(ii)`.
        """
        assert resolve_subdivision_path(["ii"], ["e", "1"]) == ["e", "1", "ii"]

    def test_upper_alpha_resumes_under_roman_parent(self) -> None:
        assert resolve_subdivision_path(["C"], ["e", "2", "ii"]) == ["e", "2", "ii", "C"]

    def test_numeric_sibling_closes_deeper_levels(self) -> None:
        assert resolve_subdivision_path(["2"], ["e", "1", "iii"]) == ["e", "2"]

    def test_reserved_paragraphs_leave_a_gap(self) -> None:
        """'(b)-(d) [Reserved]' means (b) is followed by (e), not (c)."""
        assert resolve_subdivision_path(["e", "1"], ["b"]) == ["e", "1"]

    def test_roman_wins_over_a_lettered_leap(self) -> None:
        """After (a)(1), '(i)' opens a roman level — it is not a jump to letter 9."""
        assert resolve_subdivision_path(["i"], ["a", "1"]) == ["a", "1", "i"]


class TestDeclinesToInventCitations:
    """When the path cannot be derived, emit no subdivisions rather than a guess."""

    def test_roman_marker_with_no_ancestors_declines(self) -> None:
        # § 160.103 packs definitions into one <P>, each restarting at (1)/(i).
        assert resolve_subdivision_path(["i"], []) is None
        assert resolve_subdivision_path(["v"], []) is None

    def test_bare_numbered_list_with_no_ancestors_declines(self) -> None:
        assert resolve_subdivision_path(["1"], []) is None

    def test_section_may_open_at_any_non_roman_letter(self) -> None:
        assert resolve_subdivision_path(["a"], []) == ["a"]
        assert resolve_subdivision_path(["g"], []) == ["g"]

    def test_marker_that_fits_nowhere_under_its_parent_declines(self) -> None:
        # "(3) Other arrangements. (i) If a covered entity ..." — the (i) level
        # never gets its own paragraph, so a following (A) has no derivable path.
        assert resolve_subdivision_path(["A"], ["e", "3"]) is None

    def test_undecidable_paragraph_folds_into_its_parent(self) -> None:
        xml = (
            '<?xml version="1.0"?>'
            "<ECFR>"
            '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
            '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
            '<DIV8 N="164.504" TYPE="SECTION">'
            "<HEAD>§ 164.504   Organizational requirements.</HEAD>"
            "<P>(e)(3) Other arrangements. (i) If a covered entity satisfies.</P>"
            "<P>(A) The covered entity may comply with this paragraph.</P>"
            "</DIV8>"
            "</DIV5></DIV1></ECFR>"
        ).encode()
        chunks = parse_ecfr_xml(xml, "hipaa")
        assert [c.citation.subdivisions for c in chunks] == [["e", "3"]]
        assert "may comply with this paragraph" in chunks[0].text


class TestDefinitionSplitting:
    def test_long_definitions_blob_splits_per_term(self) -> None:
        blob = (
            "Except as otherwise provided, the following definitions apply: "
            + "Act means the Social Security Act. "
            + "Business associate means, with respect to a covered entity, a person who "
            + "creates or receives protected health information on behalf of the entity. " * 8
            + "Covered entity means a health plan. "
            + "ANSI stands for the American National Standards Institute. "
        )
        parts = split_definitions(blob)
        assert len(parts) > 1
        assert any(p.startswith("Business associate means") for p in parts)
        assert any(p.startswith("ANSI stands for") for p in parts)

    def test_short_paragraph_left_whole(self) -> None:
        text = "Business associate means a person who creates protected health information."
        assert split_definitions(text) == [text]

    def test_split_never_cuts_a_sentence(self) -> None:
        blob = (
            "The following definitions apply: "
            + "Act means the Social Security Act. "
            + "Disclosure means the release of information. " * 20
        )
        for part in split_definitions(blob):
            assert not part[0].islower(), f"chunk begins mid-sentence: {part[:40]!r}"


class TestInlineMultiLevelParagraphs:
    """The § 164.504(e) shape that produced bare `(ii)` / `(2)` citations."""

    _XML = (
        '<?xml version="1.0"?>'
        "<ECFR>"
        '<DIV1 N="45" TYPE="TITLE"><HEAD>Title 45</HEAD>'
        '<DIV5 N="164" TYPE="PART"><HEAD>PART 164</HEAD>'
        '<DIV8 N="164.504" TYPE="SECTION">'
        "<HEAD>§ 164.504   Organizational requirements.</HEAD>"
        "<P>(e)(1) Standard: Business associate contracts. (i) The contract must provide.</P>"
        "<P>(ii) A covered entity is not in compliance with the standards.</P>"
        "<P>(iii) A business associate is not in compliance.</P>"
        "<P>(2) Implementation specifications. A contract must:</P>"
        "<P>(i) Establish the permitted and required uses.</P>"
        "<P>(A) The contract may permit aggregation.</P>"
        "<P>(ii) Provide that the business associate will:</P>"
        "<P>(B) Use appropriate safeguards.</P>"
        "<P>(3) Other arrangements.</P>"
        "</DIV8>"
        "</DIV5></DIV1></ECFR>"
    ).encode()

    def test_no_bare_orphan_paths(self) -> None:
        chunks = parse_ecfr_xml(self._XML, "hipaa")
        assert [c.citation.subdivisions for c in chunks] == [
            ["e", "1"],
            ["e", "1", "ii"],
            ["e", "1", "iii"],
            ["e", "2"],
            ["e", "2", "i"],
            ["e", "2", "i", "A"],
            ["e", "2", "ii"],
            ["e", "2", "ii", "B"],
            ["e", "3"],
        ]

    def test_every_citation_starts_at_a_top_level_letter(self) -> None:
        chunks = parse_ecfr_xml(self._XML, "hipaa")
        for c in chunks:
            first = c.citation.subdivisions[0]
            assert first.isalpha() and first.islower(), f"orphan path {c.citation.format()}"


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
