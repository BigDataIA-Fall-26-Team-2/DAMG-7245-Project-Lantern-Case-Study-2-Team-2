# DAMG-7245-Project-Lantern-Case-Study-2-Team-2

## Starting point

This repository is the Case Study 2 workspace. Its baseline is copied from the
Case Study 1 `submission` tag, commit `d4c19247ecd2281e7ea5e7c7ef2e03e914c00e0f`.
The submitted CS1 repository remains unchanged. This is a file snapshot; the
new repository retains its own Git history and origin.

The [original CS1 README](docs/cs1_submission_README.md) documents the inherited
pipeline, setup, and results. Existing reports and work plans describe CS1;
they are historical evidence, not completed CS2 work.

Source code, tests and fixtures, configuration, pinned dependencies, committed
reports, and DVC pointers are included. Local environments, secrets, untracked
data, and the old Git directory were not copied. Retrieve required external
artifacts using `dvc pull` after configuring authorized access. The inherited
DVC remote still points to the CS1 artifact store; review the CS2 storage
configuration before pushing new artifacts.

CS2 development must extend ingestion to configurable companies and document
sets while preserving citations, scope, and reproducibility.

## Shared Python environment (CS2)

Use **Python 3.11**. `requirements.txt` contains the inherited CS1 stack plus
DuckDB, local Chroma, the model-client dependencies, retrieval and evaluation
libraries. It freezes the actual resolved packages, including transitive
versions; do not freeze a global or unrelated environment over it.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -q
```

Use Linux/WSL on Windows. The full environment was installed on macOS arm64
with Python 3.11.11; full Linux installation and each teammate's setup still
need verification. `appnope` has a macOS environment marker. Platform-specific
transitive dependencies may still be selected by pip on another OS; report
resolver errors rather than unpinning packages independently.

Install system tools separately: macOS `brew install tesseract poppler`; on
Ubuntu/WSL use `sudo apt-get update` then
`sudo apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils`.
For the inherited filing renderer, run `python -m playwright install chromium`
(macOS) or `python -m playwright install --with-deps chromium` (Linux).
Docker must also be installed/running for the later containerized QA service.
Python requirements do not install these tools or start Docker.

The environment includes open-embedding/model libraries, **not downloaded
model weights**. Model selection and recording happen in the shared-client
setup task; submission replay must use prepared caches without downloads.
Do not run live model calls until budget limits and billing alerts are ready.
DVC data access remains a separate prerequisite; use the existing configured
remote for `dvc pull` once authorized access is verified.

### Tools in use

| Purpose | Selected packages |
|---|---|
| Inherited document pipeline | Docling, Arelle, pdfplumber, Camelot, Tesseract adapter, LayoutParser/PyTorch; retained from CS1 |
| Facts and spreadsheet inputs | DuckDB, pandas, openpyxl |
| Vector store | Chroma (`chromadb`), local persistent mode by default |
| Structured model calls | Instructor, OpenAI SDK, Pydantic through `src/llm/client.py` |
| Open embeddings | sentence-transformers, shared PyTorch/Transformers stack |
| Chunking and keyword retrieval | langchain-text-splitters, rank-bm25 |
| Retrieval evaluation | ranx |
| Calibration and plots | scikit-learn, matplotlib, seaborn |
| Answering API and UI | FastAPI, Uvicorn, Streamlit |
| Reproduction and tests | DVC with S3 support, pytest |

The CS2 packages were chosen from the course tutorial. The inherited
`rich==15.0.0` pin conflicted with Instructor 1.17.0, so the resolved environment
uses `rich==14.3.4`; other inherited package versions were retained.

**Chroma Cloud is optional infrastructure, not a setup dependency.** The
[official pricing page](https://www.trychroma.com/pricing) describes free
credits followed by usage-based pricing, not an unlimited free team database.
Keep local Chroma available for offline reproduction. A hosted/shared database,
team access and any cloud configuration will be considered during infrastructure
setup; no Chroma account or cloud database is provisioned by this change.

To update dependencies later, work in a clean Python 3.11 environment, install
and validate the additions, then run `python -m pip freeze --all --exclude pip`
and preserve the macOS marker on `appnope`. Review version changes and run
`pip check` plus the applicable tests before replacing the shared pins. The
lighter `requirements-ci.txt` uses these pins as constraints for fixture CI;
it is not the full developer environment.

## Shared model helper

Use the [shared-client guide](docs/llm_client.md) for structured model responses,
hosted/open embeddings, scoped record/replay and task cost tracking. Run
`python -m pytest tests/test_llm_client.py -q` for a zero-cost offline check.
Luna text models and prices are configured, with initial local-ledger caps of
$1 total and $0.05 per task. Replay remains the default; no API key is required
for the test suite. All downstream modules must
use this helper rather than direct provider calls.

### App model control

Run `python -m streamlit run app/app.py -- --params params.yaml` to see the
sidebar model selector. Options come from `llm.model_choices`; Luna stays the
default and the mini snapshot is available as an alternative. Selection is
session-only and feeds `session_llm_client`; it never edits shared params or
starts a paid call. Existing explorer panels display saved outputs; Q&A request
integration remains pending. See the [client guide](docs/llm_client.md).

### Local OpenAI key

Copy `.env.example` to `.env` and paste the key into `OPENAI_API_KEY=` locally.
The shared helper reads it lazily for provider calls; an exported environment
variable takes precedence. `.env` and other real environment files are ignored
by Git. Adding a key does not change the default replay mode.

## CS2 public-company acquisition

Start with the [public ingestion guide](docs/public_ingestion.md) for the
configurable ten-company test batch, earnings acquisition, record/replay and
per-company status. Raw source acquisition is implemented; financial and text
processing are subsequent P0 work, not claimed complete by downloaded files.


## CS2 teammate document handoff

**Publication status:** the 352 MB document/cache archive is uploaded to the
team's DVC S3 remote. Use `python -m src.handoff` to download, restore and check
it. For just the Git-shared JSONL examples without AWS, run
`python -m src.handoff --samples-only`.

Development runs on each teammate's laptop; S3 stores the shared DVC download.
No EC2 instance is required. Instructor inputs are pending and do not block use
of the public documents, cited Apple examples and clearly fictional practice memo.

Get this branch before it is merged (start from a clean working tree):

```bash
git fetch origin
git switch --track origin/lokesh/cs2-document-handoff
```

If you already have that local branch, use `git switch lokesh/cs2-document-handoff`
and `git pull --ff-only`. After merge, use updated `main` instead. Install the
shared Python 3.11 requirements using the environment instructions above.

Configure your own AWS CLI profile once, if not already configured. Enter your
own access-key ID/secret at the local prompts, region `us-east-1`, output `json`.
The AWS console password is not an API access key. Skip configuration when your
existing profile already works; select its name in `AWS_PROFILE` instead.

```bash
aws configure --profile lantern
export AWS_PROFILE=lantern
aws sts get-caller-identity
aws s3 ls s3://lantern-team2-dvc-fall-2026/dvc/
source .venv/bin/activate
python -m src.handoff
```

`python -m src.handoff` runs `dvc pull data/handoff.dvc`, restores the compressed
public-document snapshot and synthetic caches, validates both JSONL examples,
and runs the fictional extraction/embedding replay with provider access blocked.
No OpenAI key or model download is needed for replay. Existing identical files
are reused; differing local files are reported rather than overwritten. Keep
about 2 GB free for the restored sources, plus room for the compressed download
and DVC cache. For a rerun without S3 access use `python -m src.handoff --local`.

Expected final line: **Handoff ready: source documents restored, JSONL valid,
model/embedding replay passed.** Send that result or the error message to the
team; never send credentials. Access confirmation is an ongoing teammate check,
not a condition for implementing their parts.

Where to start:

- `examples/cs2/records.jsonl`: cited document-block examples for Shravya.
- `examples/cs2/facts.jsonl`: normalized numeric examples for Gunna and Dhruvi.
- `examples/synthetic/kestrel_practice_memo.md`: invented development memo, not
  instructor Kestrel or Deal A/B.
- `data/edgar_comps/<run_id>/manifest.jsonl`: the ten companies' source filings.
- `data/earnings/<run_id>/manifest.jsonl`: selected 8-Ks and earnings exhibits.

`run_id` comes from `ingest.public.run_id` in `params.yaml`. Manifests contain
source paths and hashes. The downloads are raw source documents, not finished
CS2 extraction or a completed DuckDB fact store. Read [CONTRACTS.md](docs/CONTRACTS.md)
for the already defined record/fact fields and each owner's remaining interfaces.

DVC basics: Git carries code and `.dvc` pointers; DVC/S3 carries the dataset.
To download this handoff only: `dvc pull data/handoff.dvc`. A bare `dvc pull`
also requests inherited CS1 artifacts and is unnecessary for this handoff.
If a dataset pointer changes after a Git pull, pull the corresponding DVC target
again. `AccessDenied` means check the selected profile and bucket policy;
`Unable to locate credentials` means the shell has no usable AWS profile;
missing cache objects should be reported with the pointer/branch being used.

Maintainers updating the selected snapshot run `python -m src.handoff --pack`,
`dvc add data/handoff`, then `dvc push data/handoff.dvc`, and commit the updated
pointer with the matching code/configuration. The raw acquisition stage outputs
use `persist: true` and `cache: false`; the compressed handoff is the shared
DVC artifact, avoiding a second upload of the expanded sources. Do not run
`dvc gc` against the shared remote or change other teammates' data.

References: [AWS CLI profiles](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html),
[DVC pull](https://doc.dvc.org/command-reference/pull).
