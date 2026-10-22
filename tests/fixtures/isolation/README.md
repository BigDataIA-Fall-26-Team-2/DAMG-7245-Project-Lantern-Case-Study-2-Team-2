# Isolation fixture (Part 3)

Synthetic records for the deal-isolation test in `tests/test_retrieval.py`.
Committed to Git, not DVC, so CI can run the test without remote access.
Everything here is made up. It contains no data-room content.

| File | Purpose |
|---|---|
| `records.jsonl` | 7 lantern/2.0-shaped Text blocks: 3 `deal_a`, 3 `deal_b`, 1 `public` |
| `canaries.json` | Planted canary strings per deal, same shape as `data/dataroom/canaries_visible.json` |
| `build_fixture.py` | Regenerates both files |

## Design

- Both toy deals cover the same topics (customers, revenue, management), so a
  `deal_a` query with the scope filter removed should also return `deal_b`
  blocks. That is what lets the test fail when isolation breaks.
- Each deal plants one canary in its customer block. The public block has none.
- A `deal_a` scope must return `deal_a` + `public` blocks only.

## Known gaps

- Records validate against `src/schema_cs2.py` (`BlockV2`), checked October 22, 2026 with
  `python -m src.schema_cs2 records tests/fixtures/isolation/records.jsonl`.
- `cik` and `ticker` are placeholders for the private toy deals.
- `sha256` is the hash of each block's text, since there is no source file.

## Regenerate

```bash
python tests/fixtures/isolation/build_fixture.py
```

## Integrity

SHA-256 of the generated files, October 22, 2026:

```text
a6d1e6547ed170dae3ed487a550817b974572e53c0c970e090514108eee3088c  canaries.json
b188dc256c58e6086262fae67ad82e713797b39f413b3d07db2026cffc79c658  records.jsonl
```
