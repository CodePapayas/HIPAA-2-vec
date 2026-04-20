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
            "164.502",
            "§ 164.312(a)(2)(iv)",
        ],
    )
    def test_round_trip(self, raw: str) -> None:
        c = parse(raw)
        c2 = parse(c.format())
        assert c == c2


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
