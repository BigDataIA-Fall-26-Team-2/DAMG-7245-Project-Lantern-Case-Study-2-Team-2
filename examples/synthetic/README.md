# Synthetic development inputs

These files are wholly fictional practice inputs created to unblock pipeline
development before the instructor distributes the graded variant. They are not
Deal A, Deal B, Kestrel, public-company filings, evaluation answers, or evidence
for the final report. Do not copy them into the instructor DVC input paths.

`kestrel_practice_memo.md` is a tiny source for exercising the shared structured
LLM client and local open-embedding cache. Use the `kestrel` cache scope only
with the explicitly named `synthetic-kestrel-practice-v1` task. Its task ID and
prompt content keep this practice call distinct from future instructor data.

The configured open embedding is `BAAI/bge-small-en-v1.5`, pinned to revision
`5e62ea33e012fda8c02802b906664c915ebd1bb1`. Its model card documents local
Sentence Transformers usage and the repository is MIT licensed:
https://huggingface.co/BAAI/bge-small-en-v1.5/tree/5e62ea33e012fda8c02802b906664c915ebd1bb1

Use record mode explicitly for a first run. Replay must use the identical
prompt, model, schema and embedding revision. Replay is offline and raises a
cache miss rather than calling a provider or downloading model weights.

From the repository root, run the structured call and one-document open
embedding together:

```bash
LANTERN_LLM_MODE=record python -m examples.synthetic.run_profile
LANTERN_LLM_MODE=replay python -m examples.synthetic.run_profile
```

The first command reuses the existing recorded response if its request identity
matches, otherwise it makes one budget-checked model call. The open embedding
is local and cached. The second command must run without provider access or
model downloads; if either cache entry is absent it fails clearly.


For teammates, use `python -m src.handoff` from the repository root. It restores
the shared response/embedding caches before replaying this runner. The new
runner's request was recorded on 2026-10-19: 325 input and 64 output tokens,
estimated model cost USD 0.0000645 at the configured rates. One locally computed
384-dimensional embedding is cached for this memo. These are practice checks,
not instructor-variant evaluation results.
