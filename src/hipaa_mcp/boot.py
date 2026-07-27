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

_SUBTITLE = "REGULATORY REFERENCE ENGINE  //  45 CFR 160 + 164 + 42 CFR PART 2"

_BOOT_SEQUENCE = [
    ("BIOS", "Initialising memory model...                          [OK]"),
    ("KERNEL", "Mounting corpus: 45 CFR Part 160 (HIPAA definitions)    [OK]"),
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

# Regulatory terms point at where they are DEFINED. This tool cites; it does
# not paraphrase what a regulation requires — a paraphrase is an interpretation,
# and interpretations are out of scope. Use `get_section` to read the text.
_GLOSS_PANEL = [
    ("PHI",              "Protected Health Information — defined at § 160.103"),
    ("ePHI",             "Electronic PHI — see 'protected health information', § 160.103"),
    ("BAA",              "Business associate contract — terms specified at § 164.504(e)"),
    ("QSO",              "Qualified Service Organization — defined at 42 CFR § 2.11"),
    ("Covered Entity",   "Defined at § 160.103"),
    ("Business Associate","Defined at § 160.103"),
    ("Disclosure",       "Defined at § 160.103; compare 'use', same section"),
    ("Minimum Necessary","Standard stated at § 164.502(b)"),
    ("De-identification","Standard and method stated at § 164.514(a)–(b)"),
    ("SUD records",      "Part 2 program records — scope stated at 42 CFR § 2.12"),
    ("Authorization",    "Requirements stated at § 164.508"),
    ("TPO",              "Treatment, payment, health care operations — defined at § 164.501"),
    ("Breach",           "Defined at § 164.402; notification rules at § 164.404–§ 164.410"),
    ("Safeguards",       "Administrative § 164.308 · Physical § 164.310 · Technical § 164.312"),
    ("RRF",              "Reciprocal Rank Fusion — merges vector + BM25 rankings into one list"),
    ("BM25",             "Best Match 25 — probabilistic lexical ranking; good on exact CFR terms"),
    ("Vector search",    "Embedding similarity search — good on semantic / plain-English queries"),
    ("Hybrid retrieval", "RRF merge of BM25 + vector; beats either alone on regulatory text"),
    ("Chunk",            "Subparagraph-level slice of CFR text carrying its full citation"),
    ("Citation",         "§ 164.308(a)(1)(ii)(A) — title · part · section · subdivisions"),
]


# Scales every sleep in the boot screen. 0.0 means "render instantly", which is
# what `serve` uses: the animation costs 5–8 seconds, and MCP clients time out
# waiting for the initialization handshake that can't start until it finishes.
_speed = 0.0


def _pause(seconds: float) -> None:
    if _speed:
        time.sleep(seconds * _speed)


def _type_out(text: str, style: str, delay: float = 0.018) -> None:
    if not _speed:
        console.print(text, style=style)
        return
    for ch in text:
        console.print(ch, style=style, end="")
        time.sleep(delay * _speed)
    console.print()


def _print_banner() -> None:
    for line in _BANNER.strip("\n").splitlines():
        console.print(line, style="bold green")
        _pause(0.03)
    console.print()
    _type_out(_SUBTITLE, style="green", delay=0.012)
    console.print()


def _print_boot_sequence() -> None:
    console.print("─" * 72, style="dim green")
    for tag, msg in _BOOT_SEQUENCE:
        line = f"  [{tag}]  {msg}"
        _type_out(line, style="green", delay=0.008)
        _pause(0.04)
    console.print("─" * 72, style="dim green")
    console.print()


def _print_glossary_panel() -> None:
    console.print("  TERMINOLOGY REFERENCE", style="bold green")
    console.print("  " + "─" * 68, style="dim green")
    for term, definition in _GLOSS_PANEL:
        left = Text(f"  {term:<22}", style="bold bright_green")
        right = Text(definition, style="green")
        console.print(left + right)
        _pause(0.03)
    console.print()


def boot_screen(mode: str = "serve", animate: bool = False) -> None:
    """Print the Apple-1 / DOS style boot screen to stderr so it doesn't
    pollute the stdio MCP transport on stdout.

    Rendering is instant unless ``animate`` is set — `serve` must reach
    ``mcp.run()`` immediately or clients time out during initialization.
    """
    global console, _speed
    console = Console(highlight=False, stderr=(mode == "serve"))
    _speed = 1.0 if animate else 0.0

    _print_banner()
    _print_boot_sequence()
    _print_glossary_panel()

    if mode == "serve":
        console.print("  Listening on stdio.  Send MCP requests now.", style="bold green")
    elif mode == "reindex":
        console.print("  Fetching eCFR XML...  This may take 30–60 s.", style="bold green")
    console.print()
