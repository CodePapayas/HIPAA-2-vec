# hipaa-mcp

Local MCP server for querying HIPAA (45 CFR Part 164) and 42 CFR Part 2 by plain English. Returns exact citations. No cloud. No opinions.

**This is a reference tool, not a compliance tool.** It retrieves and cites regulation text. It does not interpret what the regulation means for your situation. When in doubt, talk to a lawyer.

---

## What it does

- `search_regulations(query)` — hybrid vector + BM25 search, returns ranked `§ X.Y` citations with full text
- `get_section(citation)` — fetch a specific section by citation string (e.g. `§ 164.308(a)(1)`)
- `add_glossary_term / list_glossary_terms / remove_glossary_term` — tune query expansion vocabulary

Query expansion uses a local glossary (no LLM required) plus an optional Ollama rewrite step. spaCy POS tagging disambiguates verb vs. noun usage so developer vocabulary ("building a SaaS") maps correctly to regulatory terms rather than false-matching facility text.

---

## Setup

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) (optional)

```bash
# Install dependencies
uv sync

# Download spaCy model (required for query expansion)
uv run python -m spacy download en_core_web_sm

# Index the regulations (downloads eCFR XML, builds ChromaDB + BM25 index)
uv run hipaa-mcp reindex

# Optional: pull the LLM for query rewriting (improves results but not required)
ollama pull gemma4:e4b
```

## MCP server (Claude Desktop / any MCP client)

Add to your MCP config:

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

---

## CLI

```bash
# Run MCP server over stdio
hipaa-mcp serve

# Rebuild index (re-downloads eCFR, wipes and recreates ChromaDB collection)
hipaa-mcp reindex
hipaa-mcp reindex --date 2026-01-01

# Glossary
hipaa-mcp glossary list
hipaa-mcp glossary path
```

---

## Query expansion and the glossary

Queries are expanded before retrieval using a local YAML glossary at the path shown by `hipaa-mcp glossary path`. Common developer terms are pre-mapped to regulatory vocabulary:

| Developer term | Regulatory term |
|---|---|
| SaaS, vendor, contractor | business associate |
| share, send, transmit | disclosure |
| delete, purge, wipe | destruction |
| consent, opt-in | authorization |
| logging, audit log | audit controls |
| least privilege | minimum necessary |
| breach, data leak | breach notification |

spaCy POS tagging handles verb/noun ambiguity. "I'm **building** a SaaS" substitutes "creating" before search so it doesn't false-match facility directory sections that use "building" as a noun.

To add your own mappings:

```
# via MCP tool
add_glossary_term(phrase="my term", maps_to="regulatory term", relationship="synonym")

# or edit the YAML directly
hipaa-mcp glossary path
```

Relationships: `synonym` (expand both directions), `hyponym` (one-way), `contextual` (scope-gated), `anti` (exclude target when term present).

---

## Environment variables

All prefixed `HIPAA_MCP_`:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `LLM_MODEL` | `gemma4:e4b` | Model for query rewriting |
| `USE_LLM_FOR_QUERY_UNDERSTANDING` | `true` | Set `false` to disable LLM rewrite; glossary expansion still runs |
| `DATA_DIR` | platform user data dir | Where ChromaDB, BM25 index, and glossary are stored |
| `TOP_K_DEFAULT` | `5` | Default number of results |

---

## TODO

False positives in search results are the current priority. The approach: surgical glossary additions, not model changes.

**Known false positive patterns to address:**

- [ ] `speak / talk / communicate` — matches patient-facing communication sections (§ 164.510 oral agreement text) instead of TPO or BA disclosure sections. Map to `disclosure` or `communication` with appropriate relationship.
- [ ] `directly` — amplifies the above; appears in "directly relevant" in § 164.510(b). Low-signal word, consider suppressing via `anti` if it appears without a regulatory noun.
- [ ] `doctors / physicians` — may match "health care provider" sections broadly; add `hyponym → covered health care provider` to tighten vector alignment.
- [ ] `patients` — similar; `hyponym → individual` (the HIPAA term) would improve precision.
- [ ] `covered` (as adjective, "stay covered") — ambiguous; spaCy should tag as ADJ, no action needed if POS substitution is extended to ADJ context.
- [ ] `serving / serves` — verb; may match "services" noun in BA definitions. Candidate for POS substitution → `providing services to`.

**Not in scope for this phase:**
- Improving chunk boundaries or re-indexing strategy
- Changing the LLM prompt or switching models
- Adding new regulation corpora
- Any feature that requires cloud inference
