from __future__ import annotations

import re
from typing import Literal

from lxml import etree

from hipaa_mcp.models import Citation, RegulationChunk


SourceCorpus = Literal["hipaa", "part2"]

# CFR subdivision levels, in order of nesting depth.
#   (a) → (1) → (i) → (A) → (1) → (i)
LevelType = Literal["alpha_lower", "digit", "roman_lower", "alpha_upper"]
_LEVEL_TYPES: list[LevelType] = [
    "alpha_lower",
    "digit",
    "roman_lower",
    "alpha_upper",
    "digit",
    "roman_lower",
]

_LEADING_MARKERS = re.compile(r"^\s*((?:\([0-9A-Za-z]{1,4}\)\s*)+)")
_MARKER = re.compile(r"\(([0-9A-Za-z]{1,4})\)")
# "(2) Heading text—(i) " — an em dash opening a deeper level on the same line.
_EM_DASH_MARKERS = re.compile(r"[—–]\s*((?:\([0-9A-Za-z]{1,4}\)\s*)+)")

_ROMAN_VALUES: list[tuple[int, str]] = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def _to_roman(n: int) -> str:
    out: list[str] = []
    for value, numeral in _ROMAN_VALUES:
        while n >= value:
            out.append(numeral)
            n -= value
    return "".join(out)


def _from_roman(s: str) -> int | None:
    """Parse a lowercase roman numeral, or return None if it is not one."""
    digits = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    if not s or any(ch not in digits for ch in s):
        return None
    total = 0
    prev = 0
    for ch in reversed(s):
        val = digits[ch]
        total += -val if val < prev else val
        prev = max(prev, val)
    return total if _to_roman(total) == s else None


_ROMAN_LETTERS = set("ivxlcdm")


def _alpha_to_index(s: str, upper: bool) -> int | None:
    """'a'→1, 'b'→2, ..., 'z'→26, 'aa'→27. Returns None if not a plain alpha run."""
    ref = s.upper() if upper else s.lower()
    if s != ref or not s.isalpha():
        return None
    # eCFR repeats the letter past z: aa, bb, cc
    if len(set(ref)) != 1:
        return None
    # A multi-character run of roman letters is a numeral, not a letter: (ii) is
    # roman two, not the 35th lowercase paragraph. The alpha reading only becomes
    # plausible past (z), which these parts never reach.
    if len(ref) > 1 and ref[0].lower() in _ROMAN_LETTERS:
        return None
    return 26 * (len(ref) - 1) + (ord(ref[0]) - ord("A" if upper else "a")) + 1


def _marker_index(marker: str, level_type: LevelType) -> int | None:
    """Position of ``marker`` within its level's sequence, or None if it doesn't fit."""
    match level_type:
        case "digit":
            return int(marker) if marker.isdigit() else None
        case "alpha_lower":
            return _alpha_to_index(marker, upper=False)
        case "alpha_upper":
            return _alpha_to_index(marker, upper=True)
        case "roman_lower":
            return _from_roman(marker)


def _is_ambiguous_roman(marker: str) -> bool:
    """True when a lowercase marker could equally be a roman numeral.

    "(i)", "(v)", "(x)" are both the 9th/22nd/24th letters and roman 1/5/10.
    Where the surrounding paragraphs don't settle it, the roman reading wins:
    CFR nests roman levels constantly and never reaches the 9th letter without
    passing through (a) through (h) first.
    """
    return marker.islower() and all(ch in _ROMAN_LETTERS for ch in marker)


def _level_type(depth: int) -> LevelType:
    return _LEVEL_TYPES[depth] if depth < len(_LEVEL_TYPES) else _LEVEL_TYPES[-1]


def resolve_subdivision_path(markers: list[str], previous: list[str]) -> list[str] | None:
    """Resolve a paragraph's leading markers into a full subdivision path.

    Ambiguity is real: after ``(h)`` a marker of ``(i)`` is the next *letter*,
    but after ``(a)(1)`` the same ``(i)`` opens a roman sub-level. Resolve by
    checking continuation of the previous path from the deepest level outward
    before treating the marker as opening a new level.

    Returns ``None`` when the marker cannot be placed under the known ancestors.
    The caller folds those paragraphs into the parent chunk rather than guessing:
    a citation this tool cannot derive is one it must not invent.
    """
    if not markers:
        return []
    first = markers[0]
    rest = markers[1:]

    # Continuation of an existing level: deepest first, so (h) → (i) stays alpha.
    # Gaps are allowed — "(b)-(d) [Reserved]" means (b) is followed by (e) — but
    # a gapped jump must not be a roman-digit letter, or "(a)(1)" followed by the
    # roman "(i)" would read as a leap to the ninth lettered paragraph.
    for depth in range(len(previous) - 1, -1, -1):
        ltype = _level_type(depth)
        prev_idx = _marker_index(previous[depth], ltype)
        cur_idx = _marker_index(first, ltype)
        if prev_idx is None or cur_idx is None or cur_idx <= prev_idx:
            continue
        if cur_idx > prev_idx + 1 and _is_ambiguous_roman(first):
            continue
        return previous[:depth] + [first] + rest

    # Opening the next level down.
    child_type = _level_type(len(previous))
    if _marker_index(first, child_type) == 1:
        return previous + [first] + rest

    # Neither a sibling nor a first child. This happens constantly in real eCFR,
    # because one <P> can carry several levels inline — "(e)(1) Standard: ... (i)
    # The contract ..." is a single paragraph, so the next <P>, "(ii)", resumes a
    # level that was never opened by a paragraph of its own. Place the marker at
    # the deepest level whose sequence type accepts it, keeping the ancestors
    # above it. Falling back to a bare top-level path here would emit citations
    # like § 164.504(ii), which name nothing.
    # Stop at depth 1: this rule resumes a level *under* known ancestors. At
    # depth 0 there is nothing to anchor to, and every lowercase marker would
    # match — turning a roman "(i)" into a bogus top-level paragraph (i).
    deepest = min(len(previous), len(_LEVEL_TYPES) - 1)
    for depth in range(deepest, 0, -1):
        if _marker_index(first, _level_type(depth)) is not None:
            return previous[:depth] + [first] + rest

    # Nothing above this paragraph. A section opens at (a); a marker arriving
    # here that is anything else has ancestors we never saw. That is the shape of
    # a definitions section — § 160.103 and 42 CFR § 2.11 pack many definitions
    # into one <P>, each restarting its own (1), (2), (i) — where the addressable
    # unit is the defined term, not a paragraph letter. Decline, so those
    # passages are cited as the section itself rather than as a path we guessed.
    if not previous:
        opens_section = (
            _marker_index(first, "alpha_lower") is not None
            and not _is_ambiguous_roman(first)
        )
        return markers if opens_section else None

    # An ancestor exists but the marker fits nowhere under it. This happens when
    # eCFR opens a level mid-sentence ("(3) Other arrangements. (i) If a covered
    # entity ...") and the level never gets a paragraph of its own. Emitting
    # (e)(3)(A) here would silently drop the (i) and name a paragraph that does
    # not exist, so decline and let the caller attribute the text to (e)(3).
    return None


def _split_markers(text: str) -> tuple[list[str], str]:
    """Split leading ``(a)(1)`` markers off a paragraph, returning (markers, body).

    eCFR also opens a deeper level after an em dash on the same line:
    ``(2) Implementation specifications (Required)—(i) Business associate ...``.
    Those markers count toward the paragraph's path; missing them strands every
    following ``(A)``/``(B)`` with no parent to attach to.
    """
    m = _LEADING_MARKERS.match(text)
    if not m:
        return [], text.strip()
    markers = _MARKER.findall(m.group(1))
    body = text[m.end() :]

    dash = _EM_DASH_MARKERS.search(body)
    if dash:
        markers += _MARKER.findall(dash.group(1))
        body = body[dash.end() :]

    return markers, body.strip()


# A defined term opening a sentence: "Business associate: (1) ...",
# "Covered entity means ...", "ANSI stands for ...". The lookbehind keeps the
# split on a sentence boundary, so no chunk ever cuts a sentence in half.
#
# "includes" is deliberately absent: no CFR definition in the corpus opens with
# it, but continuations do ("Health care includes, but is not limited to ...",
# "It includes the following types ..."). Splitting on those orphans a fragment
# from the term it belongs to.
_DEFINED_TERM = r"[A-Z][A-Za-z0-9 ,'\-/()]{1,60}?"
# The colon form has no verb to anchor on, so the term is kept narrow — letters,
# spaces and hyphens only. Commas would let it swallow a clause such as
# "Health care includes, but is not limited to, the following: (1) ...".
_COLON_TERM = r"[A-Z][A-Za-z\- ]{1,40}?"
_DEFINITION_START = re.compile(
    rf"(?<=[.:]\s)(?="
    rf"{_DEFINED_TERM}\s(?:means|stands for|has the same meaning)\b"
    rf"|{_COLON_TERM}:\s*\(1\)"
    rf")"
)

# Definitions sections pack many terms into one <P>; below this length a
# paragraph is a normal passage and is left whole.
_DEFINITION_SPLIT_MIN_CHARS = 400


def split_definitions(text: str) -> list[str]:
    """Split a definitions blob into one passage per defined term.

    § 160.103 and 42 CFR § 2.11 put dozens of definitions inside a single
    paragraph element. Left whole, the passage is far too long to embed and
    "business associate" is unfindable inside it. Every piece keeps the same
    section citation — the defined term, not a paragraph letter, is the
    addressable unit here, and it stays in the text.
    """
    if len(text) < _DEFINITION_SPLIT_MIN_CHARS:
        return [text]
    parts = [p.strip() for p in _DEFINITION_START.split(text)]
    return [p for p in parts if p] or [text]


def _text(el: etree._Element) -> str:
    return "".join(el.itertext()).strip()


def _subdivision_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_ecfr_xml(xml_bytes: bytes, source_corpus: SourceCorpus = "hipaa") -> list[RegulationChunk]:
    root = etree.fromstring(xml_bytes)
    chunks: list[RegulationChunk] = []
    _walk(root, source_corpus, chunks, title=None, part=None, section=None)
    return chunks


def _structural_type(el: etree._Element) -> str:
    """Return canonical structural type for an element.

    eCFR full-title XML uses DIV* elements with a TYPE attribute:
      DIV1 TYPE="TITLE", DIV5 TYPE="PART", DIV8 TYPE="SECTION"
    Fall back to the local tag name for any other shape.
    """
    local = _subdivision_tag(el.tag)
    if local.upper().startswith("DIV"):
        t = el.get("TYPE", "")
        if t:
            return t.upper()
    return local.upper()


def _paragraph_elements(section_el: etree._Element) -> list[etree._Element]:
    direct = [c for c in section_el if _subdivision_tag(c.tag).upper() in ("P", "FP")]
    if direct:
        return direct
    return [e for e in section_el.iter() if _subdivision_tag(e.tag).upper() in ("P", "FP")]


def _chunk_id(citation: Citation, taken: set[str]) -> str:
    base = (
        citation.format()
        .replace(" ", "_")
        .replace("§", "sec")
        .replace("(", "_")
        .replace(")", "")
    )
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f"{base}__{n}"
        n += 1
    taken.add(candidate)
    return candidate


def _emit_section_chunks(
    section_el: etree._Element,
    source_corpus: SourceCorpus,
    chunks: list[RegulationChunk],
    title: int,
    part: int,
    section: int,
    heading: str,
) -> None:
    """Emit one chunk per subparagraph of a section.

    A paragraph with no leading marker either opens the section (intro text) or
    continues the paragraph above it, so it is folded into the current chunk
    rather than emitted separately. That keeps sentences intact and chunk ids
    unique.
    """
    taken: set[str] = set()
    current_path: list[str] = []
    buffer: list[str] = []

    def flush(path: list[str]) -> None:
        text = " ".join(t for t in buffer if t).strip()
        buffer.clear()
        if not text:
            return
        citation = Citation(title=title, part=part, section=section, subdivisions=list(path))
        # Only section-level text can be a definitions blob; a lettered paragraph
        # is already a single passage.
        pieces = split_definitions(text) if not path else [text]
        for piece in pieces:
            chunks.append(
                RegulationChunk(
                    chunk_id=_chunk_id(citation, taken),
                    citation=citation,
                    heading=heading,
                    text=piece,
                    source_corpus=source_corpus,
                )
            )

    for p_el in _paragraph_elements(section_el):
        raw = _text(p_el)
        if not raw:
            continue
        is_flush_para = _subdivision_tag(p_el.tag).upper() == "FP"
        markers, body = _split_markers(raw)
        resolved = resolve_subdivision_path(markers, current_path) if markers else None

        if resolved is not None:
            flush(current_path)
            current_path = resolved
            # Keep the marker in the text so the passage reads as it does in the CFR.
            buffer.append(raw)
        elif markers or is_flush_para or not current_path:
            # A marker we could not place, an <FP> continuation, or section intro
            # text: all belong to the paragraph above rather than to a citation
            # we would have to invent.
            buffer.append(raw if markers else body)
        else:
            # An unmarked <P> arriving after a marked one starts a new passage at
            # section level — this is how § 160.103 is built, one definition per
            # paragraph. Folding it into the preceding subdivision would attribute
            # "Business associate means ..." to whatever numbered item came before.
            flush(current_path)
            current_path = []
            buffer.append(body)

    flush(current_path)


def _walk(
    el: etree._Element,
    source_corpus: SourceCorpus,
    chunks: list[RegulationChunk],
    title: int | None,
    part: int | None,
    section: int | None,
) -> None:
    stype = _structural_type(el)

    # N attribute holds the structural number (e.g. "45", "164", "164.308")
    num = el.get("N") or el.get("n") or el.get("num") or ""

    if stype == "TITLE":
        title = int(num) if num.isdigit() else title
    elif stype == "PART":
        part = int(num) if num.isdigit() else part
        section = None
    elif stype == "SECTION":
        # N is "part.section" (e.g. "164.308"); try that first
        if "." in num:
            try:
                part_s, sec_s = num.split(".", 1)
                part = int(part_s.strip())
                section = int(sec_s.strip())
            except ValueError:
                pass
        else:
            # Legacy: look for a SECTNO child element
            sectno_el = el.find(".//{*}SECTNO") or el.find(".//{*}sectno")
            if sectno_el is not None:
                raw = (sectno_el.text or "").strip().lstrip("§").strip()
                if "." in raw:
                    try:
                        part_s, sec_s = raw.split(".", 1)
                        part = int(part_s.strip())
                        section = int(sec_s.strip())
                    except ValueError:
                        pass

        heading_el = el.find("{*}HEAD")
        if heading_el is None:
            heading_el = el.find("HEAD")
        heading = _text(heading_el) if heading_el is not None else ""

        if title and part and section is not None:
            _emit_section_chunks(
                el, source_corpus, chunks, title, part, section, heading
            )
        # Sections do not nest; everything inside was handled above.
        return

    for child in el:
        _walk(child, source_corpus, chunks, title, part, section)
