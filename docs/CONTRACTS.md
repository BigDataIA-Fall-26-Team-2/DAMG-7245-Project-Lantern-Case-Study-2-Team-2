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

## CS2 development sample

See [the starter sample](../examples/cs2/README.md) for two cited document
records and their normalized financial facts. The JSONL files illustrate the validated CS2 record/fact interfaces. Storage and
ingestion integration are subsequent work. Existing CS1 schema behavior is unchanged. Teammates should use
these validated JSONL formats immediately. Source-specific locators are defined
below; owners extend their interfaces in the same PR as their implementation.

## CS2 record and fact validators

Import `BlockV2`, `FinancialFact` and `upgrade_cs1_record` from
`src.schema_cs2`. Field names follow Appendix C and P1. `BlockV2` preserves
all CS1 fields and adds required `deal_id`, `source_type`, `tier`, `citation`,
`lineage` and `ingest_flags`; its schema is `lantern/2.0`. Missing CS2 metadata
is rejected, not silently defaulted. `upgrade_cs1_record` explicitly supplies
public / edgar_filing / tier 2 and a PDF citation for a valid old CS1 record.

Use `model_validate` when accepting data and `to_jsonl()` when writing it.
Serialization revalidates nested mutations. These models perform no network
access, storage initialization or company-specific extraction.

### Identity, source and scope

- EDGAR IDs remain accession numbers and require public scope and a CIK.
  Filed XBRL is tier 1; filing text/tables and 8-K exhibits are tier 2.
- Data-room IDs use `DR-<deal_id>-<NNN>` with matching `deal_a`, `deal_b` or
  `kestrel` scope. Seller financials are tier 3; management claims are tier 4.
- Web IDs use `WEB-<sha8>` and tier 5. Scope is assigned at ingestion according
  to the input's permitted use; source content cannot choose its own access.
- Derived records require parent IDs. They retain input-tier provenance; tier 6
  model knowledge never belongs in the numeric facts table.
- For non-EDGAR inputs, unavailable CIK/ticker/form/fiscal metadata can be null.
  Non-PDF records may have null page/bbox; keep those inherited keys present.
  Do not invent SEC identifiers or PDF page locations for spreadsheets/web.
- Lineage is `{parents: [record IDs], source_sha256: <hash>}`. A record's hash
  must match lineage; a citation's source path must match its record's source.
  Record IDs are `doc_id:block_id`; financial fact IDs are opaque nonempty IDs.

These checks catch wrongly labelled metadata. They do not replace retrieval
scope filters: a Deal A query may use Deal A plus public records, never Deal B
or Kestrel records. Public queries may use only public records.

### Citation locators

All citation objects contain `kind` and `source_path`:

| kind | Other required locator fields |
|---|---|
| `pdf_bbox` | `page` (1-based), `bbox` (nonnegative finite points, top-left origin, positive area) |
| `ixbrl_element` | `element_id` |
| `ixbrl_context` | `concept`, `context_ref`, `unit_ref` (values from the original XBRL attributes) |
| `sheet_cell` | `sheet`, `cell` (A1 notation, e.g. B2) |
| `web_span` | `start`, `end` (zero-based character offsets, end exclusive, into the stored extracted text at source_path) |

Kinds come from the assignment; locator key spellings are the team's concrete
implementation. PDF record page/bbox must equal its citation page/bbox. Citation
resolution and source-byte hashing must also be verified during ingestion;
passing structural validation alone does not establish extraction accuracy.

### Financial facts

`FinancialFact` has the P1 fields shown in `examples/cs2/facts.jsonl`. Values
are finite numbers in full units (`USD`, `shares`, etc.); percentage metrics
use `unit: ratio` and 0.12 for 12%. Units must be explicit. Metric names use
lowercase snake_case; controlled vocabulary mappings remain P1 work.

- Only tiers 1–3 enter facts. Tier 4/5 values belong in a separate claims table;
  calculated values belong in calculator outputs, not raw source facts.
- Duration facts require start/end dates with start <= end; instant facts use
  start=null and the actual instant as end. Never silently substitute calendar
  dates for fiscal dates. `dims` maps dimension names to members.
- `decimals` means source precision: -6 for rounded millions, `INF` for exact,
  null when unknown. This is not an instruction to rescale an already normalized
  value. Missing values are absent facts, not zeros.
- Tier-1 facts require a concept and an appropriate XBRL/PDF locator. A context
  citation's concept must equal the fact's concept. A nullable concept on a
  document fact means a mapping has not been verified.

Claims, calculator outputs and answer service models will be implemented by
those parts using the assignment requirements. This setup introduces no extra
approval gate before their owners can work.

## Public acquisition boundary

`src.ingest.public.run_batch(params_path, output, stage="comps", mode=None,
tickers=None, run_id=None)` returns `(company_statuses, measurements)` and
writes an acquisition manifest. CLI and future UI use the same implementation.
`stage` is `comps` or `earnings`. See [public ingestion](public_ingestion.md)
for paths, resume/replay behavior and the distinction from extracted records.

## Handoff ownership and remaining implementation

JSONL is the interchange format: UTF-8, one JSON object per line. Use the
validators above; retain citations and source identity when consuming records.
DuckDB stores queryable facts, and Chroma indexes chunks; neither replaces the
source JSONL. The ten-company selection is configuration, independent of these
record formats.

| Owner | Interface already provided | Interface added with their implementation |
|---|---|---|
| Lokesh P0/P1 | `BlockV2`, `FinancialFact`, citation/period/unit/scope rules, `run_batch` | P1 concept/statement-line mappings and DuckDB/reconciliation implementation; baseline fields below |
| Shravya P2/P3 | Document records and citation/identity rules | Chunk IDs, search result metadata, retrieval/evaluation interfaces |
| Gunna P4/P5 | Cited facts and source records; shared LLM client | Answer/linter/service and profile/memo response models |
| Dhruvi P6/P7 | Numeric values in full units, explicit periods and provenance | Calculator IDs and input traces, comps/figure and mandate-score outputs |

Those later interfaces are part of their owners' implementation, not a setup
approval gate. Update this file, the corresponding validator and an example
together in the implementation PR. Preserve existing consumers or provide an
explicit migration when changing fields. No additional format decision is
needed from Lokesh for teammates to start with the provided records/facts.

## Lokesh P1 baseline for downstream consumers

These definitions follow CS2 Part 1 and Section 8; implementation of the fact
store/reconciler remains P1 work. Consumers can use the documented fields now.

- IDs are nonempty strings. `fact_id` and `claim_id` must be unique across deals
  and stable for unchanged source evidence; consumers must treat them as opaque.
  Producers generate IDs from source scope/document/locator, metric, period and
  qualifier identity, never array positions or model-generated IDs. A changed
  source version receives a new identity. IDs do not grant access across scopes.
- Numeric claims use `claim_id`, `deal_id`, `entity_id`, `doc_id`, `block_id`,
  `metric`, `value`, `unit`, `period`, `period_basis`, `start`, `end`, `qualifier`,
  `quote`, `page`, `bbox`, `tier`, `source_type`, `citation`, `lineage`. `value`
  uses full units; ratios use `unit: ratio`. Keep the original wording in `quote`.
  `period_basis` is fiscal/calendar/LTM/unknown; unresolved dates are null rather
  than guessed. Page/bbox can be null for web evidence; citation remains required.
  Claims have tier 4 or 5 and remain separate from the numeric facts table.
- Reconciliation JSONL uses exactly Section 8's `metric`, `period`, `claim_id`,
  `fact_id`, `status`, `gap`, `severity`. Status is `match`, `discrepancy`,
  `definition_mismatch`, `period_mismatch` or `no_fact`. `fact_id` is null when
  no fact is available. Gap is `(claim - fact) / abs(fact)` for an aligned,
  nonzero fact, otherwise null. Severity is `high` or `medium` for a discrepancy,
  otherwise null; numeric thresholds belong in `reconcile.*` configuration.
- The initial vocabulary includes the brief's `revenue`, `revenue_growth`,
  `gross_margin`, `ebitda`, `adjusted_ebitda`, `ebitda_margin`, `arr`, `nrr`,
  `gross_logo_churn`, `top1_customer_share`, `top10_customer_share`, `headcount`,
  plus `net_income` already used by the sample. Verified concept/statement-line
  mappings belong in `config/metrics_vocab.yaml` with the P1 implementation.
  Do not invent a direct XBRL mapping for a derived metric or data-room-only KPI.

The existing `BlockV2` and `FinancialFact` models are executable validators.
The claim/reconciliation definitions above are the implementation baseline;
claim/reconciliation model classes are not delivered by this setup branch.
