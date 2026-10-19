# LANTERN shared contracts

Shapes every stage's script must produce/consume identically. Internal-only details stay in each owner's own code, not here.

## File stems

`{ticker}_{form}_{YYYYMMDD}`, date = filing/period-end date from the manifest. Examples:
- `AAPL_10K_20250927` — FY2025 10-K, accession `0000320193-25-000079`
- `AAPL_10Q_20260627` — Q3 FY2026 10-Q, accession `0000320193-26-000020`

`doc_id` = the accession number, taken from the manifest (not re-derived from the stem).

## Pages and boxes

- Pages are **1-based**.
- `bbox` is `[x0, top, x1, bottom]` in points, **top-left origin**. If your tool returns bottom-left origin (e.g. PDF native), convert inside your own script before it crosses a stage boundary.

## Table CSV

Path: `data/tables/{stem}_p{NNNN}_t{K}.csv` (`NNNN` = zero-padded page, `K` = table index on that page, both 1-based).

Columns: `row_label, col_label, raw, value, scale`

## Block schema

Emitted per detected layout block: `page, block_id, block_type, bbox, score, model`

## Shared functions

- `tables.extract_best_df(pdf_path, page, bbox=None)` — returns `(df, info)`. `df` is the best table on the page in the table CSV format above (`row_label, col_label, raw, value, scale`), or `None` if no candidate is accepted. `info` = `{method, score, extractor_version, accepted, skipped_rows}`; use `method` and `extractor_version` for the Part 5 `extractor` fields. `bbox` = `[x0, top, x1, bottom]` in points, top-left origin (converted for Camelot inside).
- `managed.managed_fallback(page_image, ocr_conf)` — returns managed-OCR output when local OCR confidence is low.

Thresholds (`accept_score`, `ocr_conf` cutoffs, etc.) live in `params.yaml`, not here.

## XBRL facts and comparison (Part 11)

- `python src/xbrl.py --input data/rendered/manifest.csv --output data/xbrl` -> `data/xbrl/facts.csv`, one row per numeric XBRL fact: `stem, accession, form, concept, prefix, label, value, unit, decimals, period_type, start, end, months, period_label, n_dims, dims, n_copies`. `value` is in full units. `period_label` uses the same text as the table CSV `col_label` ("FY ended 2025-09-27", "9M ended 2026-06-27", instants "2025-09-27"), so the two join on `(stem, period_label)`. `n_dims == 0` means a face (statement) fact.
- `python src/xbrl.py compare --path traditional --tables data/tables` -> `data/xbrl/comparison_{path}.csv` (one row per table cell on the pages in `params.yaml` `xbrl.statement_pages`) and `data/xbrl/match_rates_{path}.csv` (per statement and ALL). Columns: `path, stem, statement, page, pdf_label, period_label, xbrl_period, prefix, concept, dims, mapping, pdf_raw, pdf_value, xbrl_value, decimals, tolerance, status, cause`.
- Any extraction path (e.g. `--path docling --tables <folder>`) must write tables in the Table CSV format above, named `{stem}_p{NNNN}_t1.csv`.
- `status`: `match` (abs(pdf - xbrl) <= tolerance), `sign` (same magnitude, opposite sign), `scale_x1e{N}` / `scale_x1e-{N}` (xbrl = pdf x 10^N), `mismatch`, `pdf_missing`, `xbrl_missing`. `tolerance` = 0.5 x 10^(-decimals); 0.5 when decimals is INF.
- `mapping`: `manual` (`config/label_map.yaml`), `label` (the filing's `_lab.xml`), `fuzzy` (difflib, cutoff `xbrl.fuzzy_cutoff`), `ambiguous` (several concepts, none agrees by value), `none`.
- `cause` is filled automatically for `sign` rows whose concept has a negated preferredLabel in the filing's `_pre.xml`. Other causes are diagnosed in `reports/xbrl.md`.


## CS2 shared model and embedding boundary

`src.llm.client.Client(params_path=None, default_model=None)` loads configuration explicitly; the
module itself performs no I/O. `structured(response_model, messages, model=None,
*, scope, task_id, stage="build", max_tokens=None, input_token_bound=None)`
returns a validated Pydantic object. `embed(texts, model=None, compute=None,
*, scope, task_id, stage="embed")` returns a finite float32 matrix in input order.
Module-level wrappers expose the same methods plus `params_path=`.

Scope is explicitly `public`, `deal_a`, `deal_b` or `kestrel`; task IDs group
per-task spending across stages. Cache keys isolate scopes and include content,
model/settings/schema or embedding revision. Unknown scope/missing configuration
fails explicitly. `CacheMiss` never triggers a live fallback in replay.
`BudgetExceeded` rejects a new estimated paid attempt that cannot fit the local
ledger caps. See [client guide](llm_client.md) for reservations, unknown failure
costs, live/record/replay semantics and provider-level billing limits.

The rest of this document still describes inherited CS1 contracts; full
`lantern/2.0` records and retrieval/fact/calc/answer interfaces remain separate
setup work. This client does not implement financial grounding or deal profiles.


### Session model selection

`llm.model_choices` lists approved text models for the UI; `llm.prices` holds
their verified rates. `Client(..., default_model=selected)` validates that
selection against the choices. An explicit per-call `model=` takes precedence,
then the session default, then the configured role. Selection does not change
provider, budgets, generation settings, scopes or global params.

Streamlit `app.app.session_llm_client(params_path)` creates the shared Client
using session key `llm_model`. New app inference actions must use this factory.
The inherited explorer currently has no Q&A action: its existing panels keep
showing pipeline outputs rather than pretending model selection regenerates them.
