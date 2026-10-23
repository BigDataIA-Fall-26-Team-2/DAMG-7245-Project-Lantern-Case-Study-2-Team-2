"""Scope enforcement tests for src/retrieve.py (CS2 Part 2 item 6, Part 3 item 3)."""
import pytest

from src.retrieve import Retriever, ScopeError, SearchResult, allowed_deal_ids


def rec(deal_id, doc_id, text, source_type="dataroom", tier=4):
    return {"deal_id": deal_id, "doc_id": doc_id, "block_id": "p0001_b001",
            "source_type": source_type, "tier": tier, "section": None, "page": 1, "text": text}


RECORDS = [
    rec("deal_a", "DR-deal_a-001", "Alpha top customer share of revenue is 18%"),
    rec("deal_b", "DR-deal_b-001", "Bravo top customer share of revenue is 31% BRAVO-CANARY"),
    rec("kestrel", "DR-kestrel-001", "Kestrel top customer share of revenue is 25% KESTREL-CANARY"),
    rec("public", "0000000001-25-000001", "Public comparable customer revenue", "edgar_filing", 2),
]


@pytest.fixture
def retriever():
    return Retriever(RECORDS, params={"k": 10})


@pytest.mark.parametrize("scope", [None, ""])
def test_missing_scope_raises(retriever, scope):
    with pytest.raises(ScopeError, match="must name a scope"):
        retriever.search("customer share", scope)


@pytest.mark.parametrize("scope", ["deal_c", "DEAL_A", "all", "*"])
def test_unknown_scope_raises(retriever, scope):
    with pytest.raises(ScopeError, match="unknown scope"):
        retriever.search("customer share", scope)


@pytest.mark.parametrize("scope, expected", [
    ("deal_a", {"deal_a", "public"}),
    ("deal_b", {"deal_b", "public"}),
    ("kestrel", {"kestrel", "public"}),
    ("public", {"public"}),
])
def test_scope_table_matches_contract(scope, expected):
    assert allowed_deal_ids(scope) == expected


@pytest.mark.parametrize("scope", ["deal_a", "deal_b", "kestrel", "public"])
def test_results_stay_in_scope(retriever, scope):
    hits = retriever.search("top customer share of revenue", scope)
    assert hits, "expected at least the public record"
    assert {h.deal_id for h in hits} <= allowed_deal_ids(scope)


def test_deal_a_sees_no_other_deal_canaries(retriever):
    hits = retriever.search("top customer share of revenue", "deal_a")
    text = " ".join(h.text for h in hits)
    assert "BRAVO-CANARY" not in text
    assert "KESTREL-CANARY" not in text


def test_results_follow_contract(retriever):
    hits = retriever.search("top customer share of revenue", "deal_a")
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(isinstance(h, SearchResult) and h.method == "bm25" for h in hits)
    assert hits[0].chunk_id == "DR-deal_a-001:p0001_b001"


def test_k_limits_results(retriever):
    assert len(retriever.search("customer", "deal_a", k=1)) == 1


def test_empty_query_raises(retriever):
    with pytest.raises(ValueError):
        retriever.search("   ", "deal_a")
