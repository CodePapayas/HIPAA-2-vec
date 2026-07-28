from __future__ import annotations

import re

from hipaa_mcp.models import Citation


class CitationParseError(ValueError):
    def __init__(self, raw: str, reason: str) -> None:
        self.raw = raw
        self.reason = reason
        super().__init__(f"Cannot parse citation {raw!r}: {reason}")


# Parts carried by the indexed corpus, keyed by CFR title.
SUPPORTED_PARTS: dict[int, set[int]] = {
    45: {160, 162, 164},
    42: {2},
}

_PART_TO_TITLE: dict[int, int] = {
    part: title for title, parts in SUPPORTED_PARTS.items() for part in parts
}

_SECTION_PAT = re.compile(
    r"""
    (?:(?:§+|[Ss]ec(?:tion|\.)?)\s*)?    # optional leading § / Sec. / Section
    (?:(?P<title>\d+)\s+CFR\s*)?         # optional "45 CFR " / "42 CFR "
    (?:§+\s*)?                           # optional § after the CFR designation
    (?P<part>\d+)\.(?P<section>\d+)      # part.section
    (?P<subs>(?:\([^()]+\))*)            # optional subdivisions
    """,
    re.VERBOSE,
)

_SUB_PAT = re.compile(r"\(([^()]+)\)")


def _supported_parts_message() -> str:
    return "; ".join(
        f"title {title}: {sorted(parts)}" for title, parts in sorted(SUPPORTED_PARTS.items())
    )


def parse(raw: str) -> Citation:
    # Anchored match: the whole string must be a citation. A `.search` here
    # would happily turn "version 1.2 of doc" into § 1.2 — a wrong-but-plausible
    # citation is the worst failure mode this tool has.
    cleaned = " ".join(raw.split())
    m = _SECTION_PAT.fullmatch(cleaned)
    if not m:
        raise CitationParseError(raw, "not a citation (expected e.g. '164.308(a)(1)')")

    title_str = m.group("title")
    part = int(m.group("part"))
    section = int(m.group("section"))
    subdivisions = _SUB_PAT.findall(m.group("subs") or "")

    if title_str is not None:
        title = int(title_str)
        if title not in SUPPORTED_PARTS:
            raise CitationParseError(
                raw, f"unsupported CFR title {title} (supported: {_supported_parts_message()})"
            )
    else:
        inferred = _PART_TO_TITLE.get(part)
        if inferred is None:
            raise CitationParseError(
                raw, f"unsupported part {part} (supported: {_supported_parts_message()})"
            )
        title = inferred

    if part not in SUPPORTED_PARTS[title]:
        raise CitationParseError(
            raw, f"part {part} is not part of title {title} (supported: {_supported_parts_message()})"
        )

    return Citation(title=title, part=part, section=section, subdivisions=subdivisions)


def format_citation(citation: Citation) -> str:
    return citation.format()
