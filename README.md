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
