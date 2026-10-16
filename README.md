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
Models/prices are unset and paid budgets are zero until the team configures
them; no API key is required for the test suite. All downstream modules must
use this helper rather than direct provider calls.
