import pytest

from hipaa_mcp.citations import CitationParseError, parse
from hipaa_mcp.models import Citation


def _c(title: int, part: int, section: int, *subs: str) -> Citation:
    return Citation(title=title, part=part, section=section, subdivisions=list(subs))


class TestParsePlain:
    def test_plain_section(self) -> None:
        c = parse("164.308")
        assert c == _c(45, 164, 308)

    def test_section_mark(self) -> None:
        c = parse("§ 164.308")
        assert c == _c(45, 164, 308)

    def test_section_mark_no_space(self) -> None:
        c = parse("§164.308")
        assert c == _c(45, 164, 308)

    def test_sec_dot(self) -> None:
        c = parse("Sec. 164.308")
        assert c == _c(45, 164, 308)

    def test_section_word(self) -> None:
        c = parse("Section 164.308")
        assert c == _c(45, 164, 308)


class TestParseCFRPrefix:
    def test_45_cfr(self) -> None:
        c = parse("45 CFR 164.308")
        assert c == _c(45, 164, 308)

    def test_42_cfr(self) -> None:
        c = parse("42 CFR 2.11")
        assert c == _c(42, 2, 11)

    def test_42_cfr_with_subs(self) -> None:
        c = parse("42 CFR 2.11(b)")
        assert c == _c(42, 2, 11, "b")


class TestParseSubdivisions:
    def test_single_sub(self) -> None:
        c = parse("164.308(a)")
        assert c == _c(45, 164, 308, "a")

    def test_deep_nesting(self) -> None:
        c = parse("§ 164.308(a)(1)(ii)(A)")
        assert c == _c(45, 164, 308, "a", "1", "ii", "A")

    def test_two_levels(self) -> None:
        c = parse("164.502(a)(1)")
        assert c == _c(45, 164, 502, "a", "1")


class TestWhitespace:
    def test_leading_trailing(self) -> None:
        c = parse("  164.308  ")
        assert c == _c(45, 164, 308)

    def test_extra_space_after_mark(self) -> None:
        c = parse("§  164.308(a)")
        assert c == _c(45, 164, 308, "a")


class TestRoundTrip:
    @pytest.mark.parametrize(
        "raw",
        [
            "§ 45 CFR 164.308",
            "45 CFR 164.308(a)(1)(ii)(A)",
            "42 CFR 2.11(b)",
            "42 CFR § 2.11(b)",
            "164.502",
            "160.103",
            "§ 164.312(a)(2)(iv)",
        ],
    )
    def test_round_trip(self, raw: str) -> None:
        c = parse(raw)
        c2 = parse(c.format())
        assert c == c2


class TestFormat:
    def test_title_45_omits_cfr_designation(self) -> None:
        assert _c(45, 164, 308, "a", "1", "ii", "A").format() == "§ 164.308(a)(1)(ii)(A)"

    def test_title_42_puts_mark_after_designation(self) -> None:
        assert _c(42, 2, 11, "b").format() == "42 CFR § 2.11(b)"

    def test_part_160_formats(self) -> None:
        assert _c(45, 160, 103).format() == "§ 160.103"


class TestPart160:
    def test_bare_160_infers_title_45(self) -> None:
        assert parse("160.103") == _c(45, 160, 103)

    def test_explicit_45_cfr_160(self) -> None:
        assert parse("45 CFR 160.103") == _c(45, 160, 103)


class TestMalformed:
    def test_garbage(self) -> None:
        with pytest.raises(CitationParseError):
            parse("not a citation")

    def test_empty(self) -> None:
        with pytest.raises(CitationParseError):
            parse("")

    def test_only_section_mark(self) -> None:
        with pytest.raises(CitationParseError):
            parse("§")

    def test_no_dot(self) -> None:
        with pytest.raises(CitationParseError):
            parse("164308")

    def test_citation_embedded_in_prose_rejected(self) -> None:
        """`.search` would turn this into § 1.2 — a wrong-but-plausible citation."""
        with pytest.raises(CitationParseError):
            parse("version 1.2 of doc")

    def test_bare_version_number_rejected(self) -> None:
        with pytest.raises(CitationParseError):
            parse("1.2")

    def test_unsupported_part_rejected(self) -> None:
        with pytest.raises(CitationParseError):
            parse("45 CFR 100.1")

    def test_unsupported_title_rejected(self) -> None:
        with pytest.raises(CitationParseError):
            parse("21 CFR 11.10")

    def test_part_not_in_title_rejected(self) -> None:
        with pytest.raises(CitationParseError):
            parse("42 CFR 164.308")

    def test_unbalanced_parens_rejected(self) -> None:
        with pytest.raises(CitationParseError):
            parse("164.308(a)(1")

    def test_trailing_prose_rejected(self) -> None:
        with pytest.raises(CitationParseError):
            parse("164.308 requires a risk analysis")
