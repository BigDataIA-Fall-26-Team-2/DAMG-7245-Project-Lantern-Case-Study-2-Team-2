# Shravya AI Engineering Log

## 2026-10-19 — CS2 environment setup (Python 3.11)

- **Tool/model:** Claude Opus 5.5 (claude.ai).
- **Contribution:** Step-by-step setup guidance: conda environment `lantern` (Python 3.11.17), install of the frozen `requirements.txt`, and a workaround for a pikepdf build failure.
- **Verification:** `pip install -r requirements.txt` completed; LLM client and model-selector tests passed; full `pytest -q` passed 205 tests, 18 skipped.
- **Failure/fix:** pip had to build pikepdf 10.16.0 from source on macOS 14 arm64 and failed (missing qpdf headers). Homebrew no longer provides bottles for macOS 14, so pikepdf 10.16.0 was installed from conda-forge instead, and pip kept it. One Streamlit AppTest timed out at 3 s on the first cold run and passed on rerun.
- **Limits:** macOS arm64 only; no Linux clean-room run. pikepdf comes from conda-forge locally rather than pip, so this environment differs slightly from the graders' `venv` + `pip` path.
- **Confidence/responsibility:** High for the local macOS setup: I ran each step and checked its output myself. Linux and clean `venv` reproduction remain unverified. I have reviewed this entry and can explain, modify, test, and defend the setup choices, including the conda-forge pikepdf workaround.

## 2026-10-19 — P3: synthetic deal-isolation fixture

- **Tool/model:** Claude Opus 5.5 (claude.ai).
- **Contribution:** Proposed the fixture design (two toy deals sharing topics, one planted canary each, one public block) and wrote `build_fixture.py` and the fixture README.
- **Final deliverables:** `tests/fixtures/isolation/build_fixture.py`, `records.jsonl`, `canaries.json`, `README.md`.
- **Verification:** Ran the builder (7 records). A scripted check confirmed exactly one canary block per deal and none in the public block. Full `pytest -q` passed 205, skipped 18. SHA-256 hashes recorded in the fixture README.
- **Failure/fix:** README code fences came out with four backticks when copied, which would not have rendered; fixed with `sed` and rechecked with `grep`.
- **Limits:** Records are not validated yet, because `src/schema.py` is still lantern/1.0. `citation` and `lineage` shapes are unconfirmed. `sha256` hashes the block text since there is no source file. The isolation test itself is not written yet.
- **Confidence/responsibility:** Moderate. The fixture structure and canary placement are checked, but the records cannot be validated until the lantern/2.0 schema lands, and the fixture is unused until the isolation test exists. I have reviewed the builder script and README and can explain, modify, test, and defend them.
