from __future__ import annotations

import re

from hipaa_mcp.models import Citation


class CitationParseError(ValueError):
    def __init__(self, raw: str, reason: str) -> None:
        self.raw = raw
        self.reason = reason
        super().__init__(f"Cannot parse citation {raw!r}: {reason}")


_SECTION_PAT = re.compile(
    r"""
    (?:
        (?P<title>\d+)\s+CFR\s+   # "45 CFR " or "42 CFR "
        |
        (?:§+|[Ss]ec(?:tion|\.)?)\s*  # § / Sec. / Section
    )?
    (?P<part>\d+)\.(?P<section>\d+)  # part.section
    (?P<subs>(?:\([^)]+\))*)         # optional subdivisions
    """,
    re.VERBOSE,
)

_SUB_PAT = re.compile(r"\(([^)]+)\)")


def parse(raw: str) -> Citation:
    cleaned = raw.strip()
    m = _SECTION_PAT.search(cleaned)
    if not m:
        raise CitationParseError(raw, "no recognizable section number found")

    title_str = m.group("title")
    part = int(m.group("part"))
    section = int(m.group("section"))
    subs_str = m.group("subs") or ""
    subdivisions = _SUB_PAT.findall(subs_str)

    # Infer title from part if not explicit
    if title_str is not None:
        title = int(title_str)
    elif part in range(160, 200):
        title = 45
    elif part == 2:
        title = 42
    else:
        title = 45  # default for HIPAA context

    return Citation(title=title, part=part, section=section, subdivisions=subdivisions)


def format_citation(citation: Citation) -> str:
    return citation.format()
