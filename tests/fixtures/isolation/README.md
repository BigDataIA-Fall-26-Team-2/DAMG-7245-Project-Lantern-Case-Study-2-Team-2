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

- `src/schema.py` is still lantern/1.0, so these records do not validate yet.
  `citation` and `lineage` shapes may change once the 2.0 schema lands.
- `sha256` is the hash of each block's text, since there is no source file.

## Regenerate

```bash
python tests/fixtures/isolation/build_fixture.py
```

## Integrity

SHA-256 of the generated files, October 19, 2026:

```text
a6d1e6547ed170dae3ed487a550817b974572e53c0c970e090514108eee3088c  canaries.json
ec2d6e34ecc0f3e4b6eccd9421307ec129f562adaf82d2df14026c6a809c3af3  records.jsonl
```
