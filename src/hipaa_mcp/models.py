from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Relationship(str, Enum):
    synonym = "synonym"
    hyponym = "hyponym"
    contextual = "contextual"
    anti = "anti"


class GlossaryEntry(BaseModel):
    term: str
    maps_to: str
    relationship: Relationship
    scope: list[str] | None = None
    notes: str | None = None


class Glossary(BaseModel):
    entries: list[GlossaryEntry]
    version: int


class Citation(BaseModel):
    title: int
    part: int
    section: int
    subdivisions: list[str] = Field(default_factory=list)

    def format(self) -> str:
        # Title 42 needs explicit CFR prefix to distinguish from title 45
        prefix = f"§ {self.title} CFR " if self.title != 45 else "§ "
        subs = "".join(f"({s})" for s in self.subdivisions)
        return f"{prefix}{self.part}.{self.section}{subs}"


class RegulationChunk(BaseModel):
    chunk_id: str
    citation: Citation
    heading: str
    text: str
    source_corpus: Literal["hipaa", "part2"]


class SearchHit(BaseModel):
    chunk: RegulationChunk
    score: float
    matched_via: Literal["vector", "bm25", "hybrid"]


class SearchResults(BaseModel):
    query: str
    expanded_query: str | None = None
    hits: list[SearchHit]


class Section(BaseModel):
    citation: Citation
    heading: str
    full_text: str
    source_corpus: Literal["hipaa", "part2"]


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None
