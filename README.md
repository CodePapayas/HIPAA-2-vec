# 🏥 hipaa-mcp

> **Ask HIPAA questions in plain English. Get exact citations back. Nothing else.**

A local-first MCP server that searches **45 CFR Part 164 (HIPAA)** and **42 CFR Part 2** and returns precise regulatory citations like `§ 164.308(a)(1)(ii)(A)` — not summaries, not interpretations, not vibes.

Built for healthtech developers who need to answer "do I need a BAA for this vendor?" without reading 200 pages of CFR or trusting a Reddit thread.

---

> ⚠️ **This is a reference tool, not a compliance tool.** It retrieves and cites regulation text. It does not tell you what the regulation means for your situation. When in doubt, talk to a lawyer.

---

## ✨ What it does

| Tool | What it returns |
|---|---|
| `search_regulations("do I need a BAA for my analytics vendor?")` | Ranked `§ X.Y` citations with full regulation text |
| `get_section("§ 164.308(a)(1)")` | Full text of that specific section |
| `add_glossary_term / list_glossary_terms / remove_glossary_term` | Tune how your developer vocabulary maps to regulatory terms |

**How search works:** hybrid vector + BM25 retrieval merged with reciprocal rank fusion → your query gets expanded (e.g. "vendor" → "business associate") before hitting the index → results ranked by combined score. No cloud, no OpenAI, no Anthropic. Everything runs on your machine.

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
git clone https://github.com/CodePapayas/hipaa-2-vec
cd hipaa-2-vec
uv sync
```

### 2. Download the spaCy language model

```bash
uv run python -m spacy download en_core_web_sm
```

> This is used for POS tagging so "building a SaaS" doesn't match regulation text about building facilities.

### 3. Index the regulations

```bash
uv run hipaa-mcp reindex
```

This downloads the eCFR XML from the federal government, parses it into chunks, and builds a local ChromaDB vector index + BM25 index. Takes a minute or two. Only needs to run once (or when you want fresh regulation text).

### 4. *(Optional)* Pull the LLM for smarter query rewriting

```bash
ollama pull gemma4:e4b
```

Without this, glossary-based expansion still runs — you just won't get LLM-assisted query rewriting. Works fine either way.

---

## 🔌 Connect to Claude Desktop (or any MCP client)

Add this to your MCP config file:

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "hipaa-mcp": {
      "command": "uv",
      "args": ["run", "hipaa-mcp", "serve"],
      "cwd": "/path/to/hipaa-2-vec"
    }
  }
}
```

Restart Claude Desktop. You'll see the 🔨 tools icon — `search_regulations`, `get_section`, and the glossary tools will be available.

---

## 💬 Example queries

```
"Do I need a BAA with my logging vendor?"
"What are the minimum necessary standards?"
"Can I share patient data with a data analytics subprocessor?"
"What does HIPAA say about breach notification timelines?"
"What's required for de-identified data?"
```

Each returns the matching regulation sections verbatim with their `§` citations. The tool never interprets — just retrieves.

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

## 📖 The glossary: why it exists and how to use it

HIPAA uses different words than developers do. The glossary bridges that gap at query time — no re-indexing required when you change it.

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
| `anti` | When your term is present, *exclude* the target from expansion |

### Adding your own mappings

```bash
# Via MCP tool (works inside Claude)
add_glossary_term(phrase="my term", maps_to="regulatory term", relationship="synonym")

# Or edit the YAML directly
hipaa-mcp glossary path   # shows the file location
```

The glossary lives in your platform's user data directory — it won't be overwritten by upgrades.

---

## ⚙️ Configuration

All env vars are prefixed `HIPAA_MCP_`. You can set them in a `.env` file in the project root.

| Variable | Default | What it does |
|---|---|---|
| `HIPAA_MCP_OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `HIPAA_MCP_LLM_MODEL` | `gemma4:e4b` | Model used for query rewriting |
| `HIPAA_MCP_USE_LLM_FOR_QUERY_UNDERSTANDING` | `true` | Set `false` to skip LLM rewriting (glossary expansion still runs) |
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

Tests use in-memory ChromaDB and a stub LLM — no real Ollama calls, no network required.

---

## 🗺️ What's in scope / not in scope

| ✅ In scope | ❌ Not in scope |
|---|---|
| HIPAA 45 CFR Part 164 | Legal interpretation of any kind |
| 42 CFR Part 2 (substance use records) | Cloud inference of any kind |
| Plain-English → citation search | A web UI |
| Local-only, air-gappable | Authentication |
| Glossary-tunable query expansion | Regs beyond HIPAA + Part 2 |

---

## 📦 Stack

`Python 3.12` · `FastMCP` · `ChromaDB` · `rank_bm25` · `Pydantic v2` · `spaCy` · `lxml` · `Ollama (Gemma 4 E4B)` · `uv`

---

## 🗒️ TODO

- **Glossary expansion preview during reindex** — while `hipaa-mcp reindex` runs, sample ~1 in 5 glossary mappings and print them as they're applied, e.g.:

  ```
  expanding  "vendor"       →  "business associate"
  expanding  "share"        →  "disclosure"
  expanding  "delete"       →  "destruction"
  ...
  ```

  Goal: visual confirmation the glossary is wired up correctly + teaches developers the regulatory vocabulary while they wait. Not all terms — just a representative sample, whatever looks good in the terminal.
