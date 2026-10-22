"""Build the synthetic isolation fixture for the Part 3 deal-isolation test.

Everything here is made up. It contains no data-room content.
Regenerate with:
    python tests/fixtures/isolation/build_fixture.py
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent

CANARIES = {
    "deal_a": ["CANARY-ALPHA-4471"],
    "deal_b": ["CANARY-BRAVO-9038"],
    "kestrel": [],
}

# Same topics in both deals on purpose: if the scope filter is removed,
# a deal_a query should also pull deal_b blocks, so the test can fail.
BLOCKS = [
    # (deal_id, doc_id, page, block_id, section, text)
    ("deal_a", "DR-deal_a-001", 1, "p0001_b001", "Customers",
     "Alpha's top customer accounted for 18% of revenue in FY2025. CANARY-ALPHA-4471"),
    ("deal_a", "DR-deal_a-001", 2, "p0002_b001", "Financial Summary",
     "Alpha revenue grew 12% to $40.0 million with an EBITDA margin of 21%."),
    ("deal_a", "DR-deal_a-002", 1, "p0001_b001", "Management",
     "Alpha's management team is led by a CEO appointed in 2021."),
    ("deal_b", "DR-deal_b-001", 1, "p0001_b001", "Customers",
     "Bravo's top customer accounted for 31% of revenue in FY2025. CANARY-BRAVO-9038"),
    ("deal_b", "DR-deal_b-001", 2, "p0002_b001", "Financial Summary",
     "Bravo revenue grew 9% to $55.0 million with an EBITDA margin of 17%."),
    ("deal_b", "DR-deal_b-002", 1, "p0001_b001", "Management",
     "Bravo's management team is led by a CEO appointed in 2019."),
    ("public", "0000000001-25-000001", 1, "p0001_b001", "Item 7",
     "The public comparable's revenue grew 6% and customer concentration is low."),
]


def record(deal_id, doc_id, page, block_id, section, text):
    is_public = deal_id == "public"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    bbox = [72.0, 100.0, 540.0, 160.0]
    return {
        "schema": "lantern/2.0",
        "deal_id": deal_id,
        "source_type": "edgar_filing" if is_public else "dataroom",
        "doc_id": doc_id,
        "company": "Public Comp Co" if is_public else f"Toy {deal_id} Co",
        # Placeholders for private targets until the 2.0 schema decides these.
        "cik": "0000000001" if is_public else "0000000000",
        "ticker": "PUBC" if is_public else "PRIVATE",
        "form": "10-K" if is_public else "CIM",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "page": page,
        "section": section,
        "block_id": block_id,
        "block_type": "Text",
        "bbox": bbox,
        "units": "pt",
        "origin": "top-left",
        "text": text,
        "table": None,
        "extractor": "synthetic-fixture",
        "extractor_version": "1",
        "ocr": False,
        "ocr_conf": None,
        "source_path": f"tests/fixtures/isolation/{doc_id}.pdf",  # notional, no PDF
        "sha256": sha,  # hash of the text, since there is no real source file
        "tier": 2 if is_public else 4,
        "citation": {"kind": "pdf_bbox", "source_path": f"tests/fixtures/isolation/{doc_id}.pdf", "page": page, "bbox": bbox},
        "lineage": {"parents": [], "source_sha256": sha},
        "ingest_flags": [],
    }


def main():
    records = [record(*b) for b in BLOCKS]
    with open(HERE / "records.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (HERE / "canaries.json").write_text(
        json.dumps(CANARIES, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(records)} records and canaries.json")


if __name__ == "__main__":
    main()
