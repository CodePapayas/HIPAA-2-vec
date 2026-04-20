from __future__ import annotations

from typing import Literal

from lxml import etree

from hipaa_mcp.models import Citation, RegulationChunk


SourceCorpus = Literal["hipaa", "part2"]

def _text(el: etree._Element) -> str:
    return "".join(el.itertext()).strip()


def _subdivision_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_ecfr_xml(xml_bytes: bytes, source_corpus: SourceCorpus) -> list[RegulationChunk]:
    root = etree.fromstring(xml_bytes)
    chunks: list[RegulationChunk] = []
    _walk(root, source_corpus, chunks, title=None, part=None, section=None, subs=[])
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


def _walk(
    el: etree._Element,
    source_corpus: SourceCorpus,
    chunks: list[RegulationChunk],
    title: int | None,
    part: int | None,
    section: int | None,
    subs: list[str],
) -> None:
    local = _subdivision_tag(el.tag)
    stype = _structural_type(el)

    # N attribute holds the structural number (e.g. "45", "164", "164.308")
    num = el.get("N") or el.get("n") or el.get("num") or ""

    if stype == "TITLE":
        title = int(num) if num.isdigit() else title
    elif stype == "PART":
        part = int(num) if num.isdigit() else part
        section = None
        subs = []
    elif stype == "SECTION":
        subs = []
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
            # Collect all direct P children as the section body
            p_texts = [
                _text(child)
                for child in el
                if _subdivision_tag(child.tag).upper() in ("P", "FP")
            ]
            text = " ".join(t for t in p_texts if t)
            if not text:
                # Fallback: any P descendant
                para_el = el.find(".//{*}P") or el.find(".//{*}p")
                text = _text(para_el) if para_el is not None else ""
            if text:
                citation = Citation(title=title, part=part, section=section, subdivisions=[])
                chunk_id = citation.format().replace(" ", "_").replace("§", "sec")
                chunks.append(
                    RegulationChunk(
                        chunk_id=chunk_id,
                        citation=citation,
                        heading=heading,
                        text=text,
                        source_corpus=source_corpus,
                    )
                )
        # Don't recurse into SECTION children — we collected them above
        return

    elif local.upper() in ("P", "FP") and part and section is not None and title:
        text = _text(el)
        if text and subs:
            citation = Citation(title=title, part=part, section=section, subdivisions=list(subs))
            chunk_id = (
                citation.format()
                .replace(" ", "_")
                .replace("§", "sec")
                .replace("(", "_")
                .replace(")", "")
            )
            chunks.append(
                RegulationChunk(
                    chunk_id=chunk_id,
                    citation=citation,
                    heading="",
                    text=text,
                    source_corpus=source_corpus,
                )
            )
            return

    new_subs = list(subs)
    if local.upper() in ("PARA", "SUBPARA") and num:
        new_subs = list(subs) + [num]

    for child in el:
        _walk(child, source_corpus, chunks, title, part, section, new_subs)
