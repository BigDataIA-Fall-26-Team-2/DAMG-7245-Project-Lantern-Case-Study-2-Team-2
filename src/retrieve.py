"""Scoped retrieval for CS2 Parts 2 and 3.

Every query must name a scope (public, deal_a, deal_b or kestrel). A deal
scope may return that deal's records plus public ones; public returns only
public records. The filter runs on the candidate set before ranking, so
out-of-scope records are never scored, ranked or returned.

This first version ranks single blocks with BM25. Chunking strategies and
dense/hybrid search plug in later without changing the interface.

Usage:
    python -m src.retrieve --records <records.jsonl> --scope deal_a "top customer share"
"""
import argparse
import json
import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("public", "deal_a", "deal_b", "kestrel")
Scope = Literal["public", "deal_a", "deal_b", "kestrel"]
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.%][a-z0-9]+)*")


class ScopeError(ValueError):
    """A query had no scope or an unknown one."""


def allowed_deal_ids(scope):
    """Return the deal_ids a query in this scope may see."""
    if not scope:
        raise ScopeError(f"every query must name a scope: one of {', '.join(SCOPES)}")
    if scope not in SCOPES:
        raise ScopeError(f"unknown scope {scope!r}: expected one of {', '.join(SCOPES)}")
    return {"public"} if scope == "public" else {scope, "public"}


def apply_scope(records, scope):
    """Keep only records this scope may see. The isolation test removes this to prove it has teeth."""
    allowed = allowed_deal_ids(scope)
    return [r for r in records if r.get("deal_id") in allowed]


class SearchResult(BaseModel):
    """One ranked hit. chunk_id equals the record ID (doc_id:block_id) until the chunker lands."""
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    block_ids: list[str] = Field(min_length=1)
    deal_id: Scope
    source_type: str
    tier: int = Field(ge=1, le=6)
    section: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    text: str
    score: float
    rank: int = Field(ge=1)
    method: Literal["bm25", "dense", "hybrid"]


def load_params(path=None):
    path = Path(path) if path else ROOT / "params.yaml"
    return yaml.safe_load(path.read_text())["retrieval"]


def load_records(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def record_text(rec):
    """Searchable text for a block; tables use their header and row text."""
    if rec.get("text"):
        return rec["text"]
    table = rec.get("table") or {}
    parts = [" ".join(table.get("columns") or [])]
    parts += [" ".join(c for c in row if c) for row in table.get("rows") or []]
    return " ".join(p for p in parts if p).strip()


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


class Retriever:
    def __init__(self, records, params=None):
        self.params = params if params is not None else load_params()
        self.records = list(records)

    def search(self, query, scope, k=None):
        allowed_deal_ids(scope)  # fail fast on a missing or unknown scope
        if not query or not query.strip():
            raise ValueError("query must be non-empty")
        k = k or self.params["k"]
        candidates = apply_scope(self.records, scope)
        if not candidates:
            return []
        # BM25 statistics come only from in-scope records, so other deals
        # cannot influence the ranking either.
        bm25 = BM25Okapi([tokenize(record_text(r)) or [""] for r in candidates])
        scores = bm25.get_scores(tokenize(query))
        order = sorted(
            range(len(candidates)),
            key=lambda i: (-scores[i], f"{candidates[i]['doc_id']}:{candidates[i]['block_id']}"),
        )
        results = []
        for rank, i in enumerate(order[:k], start=1):
            r = candidates[i]
            results.append(SearchResult(
                chunk_id=f"{r['doc_id']}:{r['block_id']}",
                doc_id=r["doc_id"],
                block_ids=[r["block_id"]],
                deal_id=r["deal_id"],
                source_type=r["source_type"],
                tier=r["tier"],
                section=r.get("section"),
                page=r.get("page"),
                text=record_text(r),
                score=float(scores[i]),
                rank=rank,
                method="bm25",
            ))
        return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scoped BM25 search over lantern/2.0 records")
    parser.add_argument("query")
    parser.add_argument("--records", required=True)
    parser.add_argument("--scope", default=None, help="public, deal_a, deal_b or kestrel (required)")
    parser.add_argument("--k", type=int, default=None)
    args = parser.parse_args(argv)
    retriever = Retriever(load_records(args.records))
    for hit in retriever.search(args.query, args.scope, args.k):
        print(f"{hit.rank:>2}  {hit.score:7.3f}  {hit.deal_id:<8} {hit.chunk_id}  {hit.text[:60]}")


if __name__ == "__main__":
    main()
