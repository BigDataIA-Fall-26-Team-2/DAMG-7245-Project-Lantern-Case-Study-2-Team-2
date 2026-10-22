# CS2 public source acquisition

The current configuration uses ten companies; the initial smoke run used AAPL, NVDA and COST. This mixed-sector set is
for engineering checks, not the final sector-justified graded comparable list.
All company inputs are configuration, not extraction-code branches.

## Run

From the repository root with the shared Python 3.11 environment installed:

```bash
# Explicit network acquisition; no model API calls or AWS operations.
python -m src.ingest.public --stage comps --output data/edgar_comps --mode record
python -m src.ingest.public --stage earnings --output data/earnings --mode record

# Reuse recorded SEC responses without network (the repository default).
python -m src.ingest.public --stage comps --output data/edgar_comps --mode replay
python -m src.ingest.public --stage earnings --output data/earnings --mode replay
```

`comps.tickers`, `forms`, `after`, `before` and `earnings_8k_quarters` in
`params.yaml` control selection. Dates filter **filing dates**, inclusive;
10-K/10-Q selection chooses the latest original inline-XBRL filing per form
in that window. Earnings selects the latest Item 2.02 8-K per calendar quarter
of its report date, using filing date only when report date is absent. This
quarter grouping is acquisition policy, not a fiscal-quarter inference. All
EX-99.1 exhibits in each selected full submission are retained.

For another batch, use another run ID and override the tickers, without editing
Python. CIKs are also accepted. For example:

```bash
python -m src.ingest.public --stage comps --output data/edgar_comps --mode record \
  --run-id public-ten-20261016 \
  --tickers AAPL NVDA MSFT GOOGL AMZN COST WMT JPM V XOM
```

If a ticker's current SEC registry entry differs from the CIK holding the requested
historical reports (for example, after a corporate reorganization), configure
`comps.historical_ciks` with prior registrant CIKs. The current CIK is resolved
from the SEC ticker registry; submissions from both are combined before form or
quarter selection. Each filing's registrant CIK determines its Archive URL and
is checked against its header; an accession may begin with a filing agent's CIK.

Run earnings with the same choices and its own `data/earnings` output. A run ID
cannot be reused with changed company/configuration inputs; resume with the
original inputs or create a new ID. Same-run reruns reuse hash-verified cached
responses and rebuild manifests/unpacked files locally. Different run IDs
currently record independent HTTP snapshots; cross-run cache sharing is not
implemented. New snapshots can reflect SEC updates, even for an older window.

The UI can call `run_batch(params_path, output, tickers=[...], run_id=...)`.
Overrides are captured per run, never written back to shared YAML. The current
Streamlit UI does not yet invoke this function. Inputs must be tickers/CIKs;
company-name search is future UI work, not implemented by this CLI.

## Outputs and failures

Each stage writes `<output>/<run_id>/`:

- `config.json`: effective non-secret input/settings snapshot.
- `status.json`: per-company running/completed/partial/failed state, each selected
  filing's acquisition result and actionable failures. Missing filings are
  explicitly unavailable. Failures do not discard successful companies.
- `manifest.jsonl`: successfully acquired primary filings, identities, dates,
  source URLs, paths and SHA-256 hashes; earnings entries link to exhibit sources
  with their own hashes. This is an **acquisition manifest**, not the rendered
  manifest or final lantern/2.0 extraction output.
- `<CIK>/<accession>/`: primary document, full submission, and either unpacked
  XBRL filing documents or earnings exhibits. `companyfacts.json` is stored per
  CIK for comps; raw companyfacts is not filtered/normalized into as-of facts.
- `http_cache/`: atomic URL-keyed SEC responses with source hashes. Corruption
  raises an error. Replay misses do not attempt a request.
- `measurements.json`: current invocation's elapsed and CPU seconds, process
  lifetime peak RSS, request/cache counts and acquisition totals. It is replaced
  on rerun; retain record/replay evidence separately when benchmarking.

The CLI exits nonzero for incomplete companies while preserving their files and
status. Retry the same command to resume cached work. This is a serial downloader
with a declared team/email User-Agent, configured below SEC's 10 requests/second
ceiling, bounded timeouts/retries and no redirect following. Run these commands
sequentially; the limiter is process-local, not a team-wide rate coordinator.
No proxy fallback or access-limit bypass is used.

DVC registers `ingest_comps` and `ingest_earnings`, with replay as the default.
After explicit acquisition, `dvc repro ingest_comps ingest_earnings` can register
outputs locally. DVC caching/push and clean-machine replay are separate checks;
no new artifacts have been uploaded to the inherited S3 remote.

## Scope and next processing work

This implementation acquires raw public inputs and unpacks 10-K/10-Q XBRL
attachments using the existing CS1 helper. It does **not** yet perform Arelle
fact extraction, Docling Items 1/1A/7 processing, validated financial outputs,
metric coverage checks or a full P0 scale-up comparison. Those processing steps
must follow before the public portion of P0 is complete. Private ingestion,
synthetic-web ingestion and the final sector-based selection also remain.

SEC API and fair-access references:
[API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [access policy](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

## Portability smoke evidence (2026-10-16)

- AAPL, NVDA and COST: all six configured 10-K/10-Q filings were acquired.
- Ten-company statements: all ten issuers acquired their selected 10-K and
  10-Q (20 filings total). XOM's ticker is registered under a successor CIK;
  `historical_ciks.XOM = ["0000034088"]` joins earlier filings to the current issuer.
- Ten-company earnings: all ten issuers acquired four distinct latest calendar
  report-date quarters (40 8-Ks total), each with its corresponding EX-99.1
  exhibit. XOM's four dates were 2026-07-31, 2026-05-01, 2026-01-30 and 2025-10-31,
  selected across current and historical registrant submissions.
- Final ten-company record runs measured 44.92 s elapsed / 5.17 s CPU and 71
  SEC requests for statements, then 38.76 s elapsed / 4.35 s CPU and 141
  requests for earnings. Process lifetime peak RSS was 540,327,936 and
  415,399,936 bytes respectively. These local acquisition measurements include
  SEC response times and are not extraction-throughput or cloud-cost estimates.
- SEC's response cache allowed failed Microsoft/JPMorgan acquisitions to resume
  after correcting Archive URL construction: URLs use the filing registrant CIK,
  because accession prefixes can identify filing agents. The final ten-company
  runs completed successfully after these fixes.
- These are raw acquisition results only. No Arelle fact extraction, Docling
  processing, metric-coverage check, DVC tracking/push, Linux replay, or full P0
  acceptance run is claimed. Local downloaded inputs and caches remain untracked
  and have not been pushed to the inherited S3 remote.


## Shared download (2026-10-19)

Use `python -m src.handoff` as documented in the README to pull the selected
recorded public snapshots and synthetic model caches. The compressed artifact
is tracked by `data/handoff.dvc`; it excludes old/failed acquisition runs.
The expanded stage outputs persist locally and are not separately uploaded.
The earlier evidence section describes the state at the time of those runs;
its "not pushed" limitation is superseded by this handoff once uploaded.
