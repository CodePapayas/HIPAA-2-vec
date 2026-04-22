from __future__ import annotations

import time

from rich.console import Console
from rich.text import Text

console = Console(highlight=False)

_BANNER = r"""
 ██╗  ██╗██╗██████╗  █████╗  █████╗       ██████╗       ██╗   ██╗███████╗ ██████╗
 ██║  ██║██║██╔══██╗██╔══██╗██╔══██╗      ╚════██╗      ██║   ██║██╔════╝██╔════╝
 ███████║██║██████╔╝███████║███████║        ███╔═╝█████╗ ██║   ██║█████╗  ██║
 ██╔══██║██║██╔═══╝ ██╔══██║██╔══██║      ██╔══╝ ╚════╝ ╚██╗ ██╔╝██╔══╝  ██║
 ██║  ██║██║██║     ██║  ██║██║  ██║      ███████╗        ╚████╔╝ ███████╗╚██████╗
 ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝      ╚══════╝         ╚═══╝  ╚══════╝ ╚═════╝
"""

_SUBTITLE = "REGULATORY REFERENCE ENGINE  //  45 CFR 164 + 42 CFR PART 2"

_BOOT_SEQUENCE = [
    ("BIOS", "Initialising memory model...                          [OK]"),
    ("KERNEL", "Mounting corpus: 45 CFR Part 164 (HIPAA Security Rule)  [OK]"),
    ("KERNEL", "Mounting corpus: 42 CFR Part 2  (SUD Confidentiality)   [OK]"),
    ("CHROMA", "Opening vector store (ChromaDB, local persistent)        [OK]"),
    ("BM25  ", "Loading lexical index (rank_bm25, BM25Okapi)             [OK]"),
    ("RRF   ", "Configuring Reciprocal Rank Fusion  k=60                 [OK]"),
    ("GLOSS ", "Loading glossary  (synonym / hyponym / contextual / anti)[OK]"),
    ("LLM   ", "Connecting to Ollama  gemma4:e4b  @ localhost:11434       [OK]"),
    ("MCP   ", "Binding FastMCP tools over stdio transport               [OK]"),
    ("READY ", "System ready.  Queries never leave this machine.          >>>"),
]

_GLOSS_PANEL = [
    ("PHI",              "Protected Health Information — any individually identifiable health data"),
    ("ePHI",             "Electronic PHI — PHI in digital form; triggers Security Rule safeguards"),
    ("BAA",              "Business Associate Agreement — contract required before a vendor touches PHI"),
    ("QSO",              "Qualified Service Organization — Part 2 equivalent of a BAA"),
    ("Covered Entity",   "Health plan, clearinghouse, or provider that transmits PHI electronically"),
    ("Business Associate","Person/org that creates, receives, or transmits PHI on a CE's behalf"),
    ("Disclosure",       "Release of PHI outside the entity holding it (≠ internal Use)"),
    ("Minimum Necessary","Only access/share PHI needed for the stated purpose — § 164.502(b)"),
    ("De-identification","Removal of 18 HIPAA identifiers; de-identified data is NOT PHI"),
    ("SUD",              "Substance Use Disorder — Part 2 adds restrictions beyond HIPAA"),
    ("Authorization",    "Patient's signed permission for non-TPO disclosure — § 164.508"),
    ("TPO",              "Treatment, Payment, Operations — PHI sharing allowed without auth"),
    ("Breach",           "Unsecured PHI acquisition/access/use/disclosure not permitted by rule"),
    ("Safeguards",       "Admin / Physical / Technical controls required under Security Rule"),
    ("RRF",              "Reciprocal Rank Fusion — merges vector + BM25 rankings into one list"),
    ("BM25",             "Best Match 25 — probabilistic lexical ranking; good on exact CFR terms"),
    ("Vector search",    "Embedding similarity search — good on semantic / plain-English queries"),
    ("Hybrid retrieval", "RRF merge of BM25 + vector; beats either alone on regulatory text"),
    ("Chunk",            "Subparagraph-level slice of CFR text carrying its full citation"),
    ("Citation",         "§ 164.308(a)(1)(ii)(A) — title · part · section · subdivisions"),
]


def _type_out(text: str, style: str, delay: float = 0.018) -> None:
    for ch in text:
        console.print(ch, style=style, end="")
        time.sleep(delay)
    console.print()


def _print_banner() -> None:
    for line in _BANNER.strip("\n").splitlines():
        console.print(line, style="bold green")
        time.sleep(0.03)
    console.print()
    _type_out(_SUBTITLE, style="green", delay=0.012)
    console.print()


def _print_boot_sequence() -> None:
    console.print("─" * 72, style="dim green")
    for tag, msg in _BOOT_SEQUENCE:
        line = f"  [{tag}]  {msg}"
        _type_out(line, style="green", delay=0.008)
        time.sleep(0.04)
    console.print("─" * 72, style="dim green")
    console.print()


def _print_glossary_panel() -> None:
    console.print("  TERMINOLOGY REFERENCE", style="bold green")
    console.print("  " + "─" * 68, style="dim green")
    for term, definition in _GLOSS_PANEL:
        left = Text(f"  {term:<22}", style="bold bright_green")
        right = Text(definition, style="green")
        console.print(left + right)
        time.sleep(0.03)
    console.print()


def boot_screen(mode: str = "serve") -> None:
    """Print the Apple-1 / DOS style boot screen to stderr so it doesn't
    pollute the stdio MCP transport on stdout."""
    global console
    console = Console(highlight=False, stderr=(mode == "serve"))

    _print_banner()
    _print_boot_sequence()
    _print_glossary_panel()

    if mode == "serve":
        console.print("  Listening on stdio.  Send MCP requests now.", style="bold green")
    elif mode == "reindex":
        console.print("  Fetching eCFR XML...  This may take 30–60 s.", style="bold green")
    console.print()
