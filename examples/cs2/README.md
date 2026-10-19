# CS2 starter sample

Two manually prepared document records and two corresponding financial facts,
using the existing Apple statement fixture. These are development examples,
not new ingestion results, Kestrel data, evaluation answers or a comparable set.
No instructor/private documents or model caches are included.

- `records.jsonl`: selected FY2025 revenue and net-income rows in the assignment's
  `lantern/2.0` shape (all inherited fields plus Appendix C extensions).
- `facts.jsonl`: the same values normalized to full USD, with period, tier and
  citations. This is the validated shared fact interface, not a DuckDB database.
- Source: `../../tests/fixtures/statement.pdf`, a one-page excerpt of Apple FY2025
  10-K, original rendered PDF page 32 / printed page 29. Citations deliberately
  use **page 1 of the actual fixture file**, not page 32 of the original filing.

## How to use

Run from the repository root:

```python
import json
from pathlib import Path

records = [json.loads(line) for line in
           Path("examples/cs2/records.jsonl").read_text().splitlines()]
facts = [json.loads(line) for line in
         Path("examples/cs2/facts.jsonl").read_text().splitlines()]
print(records[0]["text"])
print(facts[0]["metric"], facts[0]["value"], facts[0]["unit"])
```

Shravya can use record text and source locators for retrieval prototyping.
Gunna can use cited facts for answer-format prototyping. Dhruvi can load numeric
facts and periods for calculator prototyping. Two Apple facts are insufficient
for real comps, model training, evaluation or a full integration run.

## Conventions illustrated

- The statement says **in millions**: 416,161 becomes 416,161,000,000 USD;
  112,010 becomes 112,010,000,000 USD. `decimals: -6` records source precision.
- These are tier-2 filed-document facts, not tier-1 XBRL facts. `concept: null`
  means no XBRL mapping has been verified. Do not invent one from the row label.
- Bounds use points, top-left origin; pages are 1-based. Each PDF locator is
  relative to `source_path`, whose exact bytes match the recorded SHA-256.
- Record IDs are `doc_id:block_id`. Facts reference their parent record through
  `lineage.parents`; record lineage has no extracted-record parent.
- Citation locator keys (`source_path`, `page`, `bbox`) and fact IDs are team
  conventions; the assignment requires the citation kinds and fact fields,
  but does not prescribe these exact locator key names or ID encoding.
- Actual pipelines must derive these values from each selected input. Apple,
  dates, paths and these identifiers are fixture values, never processing defaults.
- Missing numeric facts are absent; do not create a zero-valued fact. Reporting
  an unavailable requested metric belongs in the downstream response contract.

## Validate or load

```bash
python -m src.schema_cs2 records examples/cs2/records.jsonl
python -m src.schema_cs2 facts examples/cs2/facts.jsonl
```

```python
from src.schema_cs2 import BlockV2, FinancialFact

record = BlockV2.model_validate(records[0])
fact = FinancialFact.model_validate(facts[0])
# Validate again on serialization before writing a JSONL line.
line = record.to_jsonl()
```

## What remains

`src/schema_cs2.py` validates CS2 records and financial facts. The inherited
`src/schema.py` and existing exporters retain CS1 behavior. New CS2 ingestion
must call `BlockV2.model_validate(...).to_jsonl()` when writing; existing CS1
records can be converted with `upgrade_cs1_record`.

The validator checks field shapes and record consistency, not whether an amount
was extracted correctly or a citation actually resolves. Source-file checks and
facts-to-source verification belong in ingestion/P1 integration. It does not
implement retrieval filtering, a DuckDB store, reconciliation or Q&A. Instructor
and private inputs stay in DVC; do not copy them into examples.
