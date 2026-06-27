# 🏥 hipaa-mcp

> **Write queries in developer language. Get exact regulatory citations back.**

A local-first MCP server that searches **45 CFR Part 164 (HIPAA)** and **42 CFR Part 2** and returns precise regulatory citations like `§ 164.308(a)(1)(ii)(A)`.

HIPAA was written by lawyers. Developers write code. The two vocabularies barely overlap — "vendor" is "business associate", "logging" is "audit controls", "delete" is "destruction". `hipaa-mcp` ships with a living glossary that bridges that gap automatically at query time, so you can ask questions in terms that make sense to you and receive the exact regulation text that applies.

---

> ### ⚠️ Important disclaimer
>
> **`hipaa-mcp` is a research tool for locating verbatim regulatory text.**
>
> It retrieves exact passages from HIPAA (45 CFR Part 164) and 42 CFR Part 2. The tool surfaces the text of the law so that you — or your legal counsel — can read and apply it directly. It is designed to return exact language because every compliance determination depends on the precise wording of the relevant regulation.
>
> **All results must be independently verified.** Regulations change, and parsing is imperfect. Consult a qualified attorney before making compliance, legal, or architectural decisions based on any regulatory text.
>
> This tool is unaffiliated with HHS, OCR, SAMHSA, or any government body.

---

## ✨ What it does

| Tool | What it returns |
|---|---|
| `search_regulations("do I need a BAA for my analytics vendor?")` | Ranked `§ X.Y` citations with full regulation text |
| `get_section("§ 164.308(a)(1)")` | Full text of that specific section |
| `explain_search("why did my microservice query return these results?")` | Results with full provenance: which glossary terms fired, confidence scores, per-hit vector/BM25 scores |
| `add_glossary_term / list_glossary_terms / remove_glossary_term` | Extend or modify the vocabulary bridge with terms specific to your stack |

**How search works:** hybrid vector + BM25 retrieval merged with reciprocal rank fusion → your query gets expanded (e.g. "vendor" → "business associate") before hitting the index → results ranked by combined score. All processing runs locally.

---

## 🚀 Quick start

### Prerequisites

| Dependency | Install |
|---|---|
| Python 3.12+ | [python.org](https://www.python.org/downloads/) or `pyenv install 3.12` |
| `uv` (package manager) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Ollama *(optional, improves search)* | [ollama.com](https://ollama.com) |

### 1. Install

```bash
pip install hipaa-mcp
```

Or with `uv`:

```bash
uv add hipaa-mcp
```

### 2. Download the spaCy language model

```bash
uv run python -m spacy download en_core_web_sm
```

> Used for POS tagging to improve query precision — verb forms and noun phrases are weighted appropriately against regulation text.

### 3. Index the regulations

```bash
uv run hipaa-mcp reindex
```

Downloads eCFR XML from the federal government, parses it into chunks, and builds a local ChromaDB vector index + BM25 index. Takes a minute or two. Re-run whenever you want fresh regulation text.

### 4. *(Optional)* Set up Ollama for LLM-assisted query rewriting

**What Ollama is:** a tool for running LLMs locally. `hipaa-mcp` uses it to rewrite your plain-English query into better retrieval terms before hitting the index — so a vague question like "do I need to notify someone if my database leaks?" gets expanded into language that actually matches HIPAA text.

**Without Ollama:** glossary-based expansion still runs. Common developer terms ("vendor", "share", "delete") get mapped to their regulatory equivalents automatically. Works well for most queries.

**With Ollama:** the LLM reads your full query in context and rewrites it — catching phrasing the glossary doesn't cover, handling ambiguity, and producing more precise retrieval terms. Recommended if your queries tend to be conversational or domain-specific.

#### Install Ollama

**Mac:**
```bash
brew install ollama
```

**Windows / Linux:** download the installer from [ollama.com](https://ollama.com) and run it.

Verify it's running:
```bash
ollama list
```

#### Pull the model

```bash
ollama pull gemma4:e4b
```

This downloads ~3GB. Run it once — the model is cached locally after that.

Ollama runs as a background service on `http://localhost:11434` by default. `hipaa-mcp` connects to it automatically. To use a different endpoint, set `HIPAA_MCP_OLLAMA_URL` in your `.env`.

---

## 🔌 Connect to Claude Desktop (or any MCP client)

Add this to your MCP config file:

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "hipaa-mcp": {
      "command": "hipaa-mcp",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop. You'll see the 🔨 tools icon — `search_regulations`, `get_section`, `explain_search`, and the glossary tools will be available.

---

## 💬 Example queries

```
"Do I need a BAA with my logging vendor?"
"What are the minimum necessary standards?"
"Can I share patient data with a data analytics subprocessor?"
"What does HIPAA say about breach notification timelines?"
"What's required for de-identified data?"
```

Each returns the matching regulation sections verbatim with their `§` citations.

---

## 🗂️ CLI reference

```bash
# Start MCP server over stdio (used by Claude Desktop / MCP clients)
hipaa-mcp serve

# Rebuild the index (re-downloads eCFR XML, rebuilds ChromaDB + BM25)
hipaa-mcp reindex
hipaa-mcp reindex --date 2026-01-01   # pin to a specific regulation date

# Glossary management
hipaa-mcp glossary list               # show all term mappings
hipaa-mcp glossary path               # show where the YAML file lives
```

---

## 📖 The glossary

HIPAA text uses a precise, closed vocabulary developed over decades of rulemaking. Searching it with developer terminology — "vendor", "log", "delete", "send" — produces weak results because those words rarely appear verbatim in the regulation.

The glossary solves this at query time. Before your query hits the index, it gets expanded: `vendor` → `business associate`, `logging` → `audit controls`, `delete` → `destruction`. The regulation text stays indexed as-is. Only your query changes, and only for the duration of that search. Updating the glossary takes effect immediately with no reindexing.

~50 mappings ship out of the box. Add your own for terms specific to your stack, your org's internal vocabulary, or the specific regulations you're working with most.

### Built-in mappings (sample)

| What you say | What HIPAA says |
|---|---|
| SaaS, vendor, contractor | business associate |
| share, send, transmit | disclosure |
| delete, purge, wipe | destruction |
| consent, opt-in | authorization |
| logging, audit log | audit controls |
| least privilege | minimum necessary |
| breach, data leak | breach notification |
| de-identified | *(anti)* not PHI |

### Relationship types

| Type | Behavior |
|---|---|
| `synonym` | Expand in both directions |
| `hyponym` | One-way only (your term → regulatory term) |
| `contextual` | Only expand if a scope keyword appears in the query |
| `anti` | When your term is present, exclude the target from expansion |

### Inspecting expansion with `explain_search`

`explain_search` returns the same hits as `search_regulations` plus full provenance data:

- **`glossary_matches`** — every glossary entry that fired, with `confidence` (0–1), the relationship type, and which `scope_triggered` words caused a contextual match
- **`vector_score`** — cosine similarity (0–1) between the query and the chunk
- **`bm25_score`** — lexical match score normalized to the top BM25 result (0–1)
- **`rrf_score`** — the final merged rank fusion score

```
explain_search("does my microservice need a BAA if it processes PHI?")
→ glossary_matches:
    "microservice" → "business associate"  [contextual, scope: PHI]  confidence: 0.95
    "processes"    → "use"                 [synonym, VERB subst.]    confidence: 1.0
→ hits:
    § 164.308  vector=0.71  bm25=1.00  rrf=0.032  [hybrid]
    § 164.314  vector=0.65  bm25=0.84  rrf=0.031  [hybrid]
```

### Adding your own mappings

```bash
# Via MCP tool (works inside Claude)
add_glossary_term(phrase="my term", maps_to="regulatory term", relationship="synonym")

# Or edit the YAML directly
hipaa-mcp glossary path   # shows the file location
```

The glossary lives in your platform's user data directory and is preserved across upgrades.

---

## ⚙️ Configuration

All env vars are prefixed `HIPAA_MCP_`. You can set them in a `.env` file in the project root.

| Variable | Default | What it does |
|---|---|---|
| `HIPAA_MCP_OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `HIPAA_MCP_LLM_MODEL` | `gemma4:e4b` | Model used for query rewriting |
| `HIPAA_MCP_USE_LLM_FOR_QUERY_UNDERSTANDING` | `true` | Set `false` to use glossary expansion alone |
| `HIPAA_MCP_DATA_DIR` | platform user data dir | Where ChromaDB, BM25 index, and glossary are stored |
| `HIPAA_MCP_TOP_K_DEFAULT` | `5` | Default number of results returned |

**Example `.env`:**
```env
HIPAA_MCP_USE_LLM_FOR_QUERY_UNDERSTANDING=false
HIPAA_MCP_TOP_K_DEFAULT=10
```

---

## 🧪 Running tests

```bash
uv run pytest
```

Tests run fully offline with in-memory ChromaDB and a stub LLM client.

---

## 🗺️ Coverage

Regulations indexed:

- HIPAA — 45 CFR Part 164
- Substance use records — 42 CFR Part 2

Design boundaries:

- All inference runs locally via Ollama
- Glossary expansion and retrieval require zero network access after initial index build
- Query logs are off by default; if enabled, output goes to a local file only

---

## 📦 Stack

`Python 3.12` · `FastMCP` · `ChromaDB` · `rank_bm25` · `Pydantic v2` · `spaCy` · `lxml` · `Ollama (Gemma 4 E4B)` · `uv`

---

## 📄 License

MIT License — Copyright (c) 2026 CodePapayas

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

**The software is provided "as is", without warranty of any kind, express or implied.** The authors are not responsible for any compliance decisions made based on output from this tool. See [LICENSE](./LICENSE) for the full text.
