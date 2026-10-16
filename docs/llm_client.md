# Shared model and embedding client

Use `src/llm/client.py` for every hosted model call and embedding operation.
It adapts the course client's `structured` / `embed` interfaces while adding
explicit configuration, scoped cache keys, atomic writes and task accounting.
No classroom documents, fixtures or recorded responses were copied.

## Try it without an API key

Activate the Python 3.11 environment, then run:

```bash
python -m pytest tests/test_llm_client.py -q
```

These tests use temporary synthetic data and an in-memory HTTP transport.
They exercise the installed OpenAI SDK and Instructor without connecting to
OpenAI, downloading model weights, or using the classroom/graded documents.
This proves the helper behavior, not extraction accuracy or live model access.

## Configure a real run

The shared `params.yaml` defaults to replay. The approved initial local-ledger
budgets are $1 total and $0.05 per task.
Text roles `large` and `small` initially use the low-cost `gpt-6-luna` model;
judge/vision and embeddings are still unset. The role names do not imply that
we have benchmarked two different model sizes. Importing the module does not read configuration, create
folders, import provider SDKs, load model weights or connect to a service.
Constructing `Client()` reads the repository's params file; an explicit params
path resolves cache/ledger paths relative to that file, not the working folder.

Before recording real requests:

1. Choose pinned provider model IDs for the roles you use (`large`, `small`,
   `judge`, `vision`) and hosted/open embeddings. Set an immutable model revision
   for the open embedding model. Explicit `model=` overrides are allowed, but a
   paid model still requires a configured price.
2. Enter verified, dated model rates in `llm.prices`: model ID mapped to
   `[USD per million input tokens, USD per million output tokens]`. Embeddings
   use an output rate of zero. These are ordinary list-price estimates; caching
   discounts and other provider billing adjustments are not inferred.
3. Review `budget.usd_cap_total` and `budget.usd_cap_per_task` before recording.
   Initial approved caps are $1 total and $0.05 per task for this local ledger;
   provider billing alerts remain a separate setup task.
4. Supply `OPENAI_API_KEY` through your local environment or deployment secrets.
   Do not put it in params, code, cache metadata, screenshots or Git. The helper
   reads only `OPENAI_API_KEY` from the local `.env` next to the selected params
   file, and only when a provider connection is needed. Existing environment
   variables take precedence; replay never reads the key file. It does not
   export file values into the process environment.
5. Set `LANTERN_LLM_MODE=record` explicitly. The environment variable overrides
   `llm.mode` when a new Client is constructed. Use `temperature: null` if the
   selected model does not support a temperature option. Model/API capability
   compatibility must be checked before a real run.

## Structured responses

```python
from pydantic import BaseModel
from src.llm.client import Client

class ExtractedValue(BaseModel):
    value: float

client = Client()
result = client.structured(
    ExtractedValue,
    [{"role": "user", "content": "Return the number in this synthetic example: 42."}],
    scope="public",
    task_id="connectivity-check",
    stage="extract_profile",
)
print(result.value)
print(client.usage_summary(scope="public", task_id="connectivity-check"))
```

This example requires the model/pricing/budget setup above and a record-mode
call to populate its cache. In replay, an unrecorded request raises `CacheMiss`.
For a judge or vision request, pass its configured model explicitly. For image
or other multimodal messages also supply a conservative `input_token_bound`
that includes image tokens. The helper validates response shape; fact lookup,
numeric grounding, trust labels and citation verification belong to the
answering/extraction/calculator layers, not this connectivity example.

The supported backend uses Instructor's JSON Schema mode over OpenAI Chat
Completions, with `max_completion_tokens`. SDK and Instructor retries are both
zero: caller-controlled regeneration/retries must go back through this helper
with the same task ID so task spending accumulates.

## Embeddings

```python
vectors = client.embed(
    ["First source block", "Second source block"],
    scope="deal_a",
    task_id="deal-a-index-build",
)
```

This uses `llm.embed.hosted`. To use the configured open model, pass
`model=client.config["embed"]["open"]`. On an uncached record/live request, the
open adapter lazily loads SentenceTransformer with `open_revision`; initial
weight download requires network. Local compute is recorded with zero provider
USD and unknown token counts, not fake token usage. Measure its runtime/compute
cost separately for economics.

An optional course-compatible `compute(texts)` callback is permitted only for
the configured open model. It must implement that exact pinned model/revision;
changing preprocessing/model weights requires a different versioned identity.
The callback cannot substitute for hosted embeddings or bypass their accounting.

Embeddings are cached per text and scope, including model/revision in the key.
Vectors must be finite, nonempty and dimensionally consistent. Replay never
calls the callback or loads SentenceTransformer weights. Prefer reusing a
Client instance for batches so loaded local weights are reused too.

## Modes, isolation and DVC

| Mode | Matching cache | Cache miss | Writes response cache |
|---|---|---|---|
| `replay` | Validate and return | Raise `CacheMiss`; no network/weights | No |
| `record` | Validate and return | Call backend within configured budget | Yes |
| `live` | Ignore | Always call backend within configured budget | No |

Both module functions (`structured`, `embed`) and Client methods require
`scope` and `task_id`. Valid scopes are `public`, `deal_a`, `deal_b`, `kestrel`.
Use the actual scope of the request's evidence; do not label private inputs as
public. Identical private content under another scope cannot reuse its cache.
Public evidence included in a deal request stays under that deal request's key.
These cache boundaries do not replace retrieval/API authorization.

Cache keys include provider, model, scope, response schema and generation
settings or embedding revision/content. Caches live under
`data/llm_cache/<scope>/` and `data/embed_cache/<scope>/` as JSON envelopes;
the payload format extends the tutorial and does not reuse its flat caches.
Changed inputs/settings/schema invalidate the matching request. Corrupt or
schema-invalid cached values raise errors rather than trigger a paid fallback.

After recording actual assignment requests, track both cache roots with DVC
and include them in the appropriate stage dependencies. Do not copy the
classroom caches, commit confidential payloads to Git, or upload new CS2 data
to the inherited S3 remote incidentally; its setup is a separate task.
Preparing real DVC caches and their offline reproduction remains pending.

## Cost ledger and budget boundaries

`logs/cost_ledger.jsonl` is ignored by Git. It contains request IDs/hashes,
model/provider, scope, stage/task IDs, mode/status, usage, estimated USD and
elapsed time. Prompt/response text, credentials and exception messages are not
written to it. Avoid putting confidential content in your task IDs.

Each backend attempt writes a reservation before calling, then a settlement.
**Use `client.usage_summary()` or the last event per request ID; do not sum all
ledger lines.** An interrupted request leaves its reservation counted. If usage
is known after failure it is billed from those tokens; a failure with unknown
usage retains its conservative reservation and `estimated: true`. Reconcile
unknown costs against provider records rather than treating failures as free.

Input bounds for plain text are conservative byte/schema estimates, not model
specific token counts. A caller can supply an explicit bound (required for
images). Output reservation uses `max_tokens`. Actual provider usage replaces
the estimate and `reservation_exceeded` flags a larger-than-estimated cost.
Estimates cannot guarantee the final provider bill; account-side controls and
billing alerts remain necessary. Cache hits make no new provider call and do
not append ledger entries; replay compute/storage still have costs.

A file lock serializes backend attempts sharing one local ledger, preventing
workers from simultaneously passing the same budget check. Caps cover this
ledger's lifetime, and per-task totals include all stages with the same scope
and task ID. Separate laptops/ledgers do not enforce one combined team budget;
coordinate provider-level limits and reconcile team usage. This helper is not
a distributed billing service. Replay reads only cache files and does not
write locks or the ledger.

## Sources

- Course source: Lab 2 starter kit, `src/llm/client.py`, LANTERN Tool Tutorial
  Part 2 orientation. Reused design/interfaces; no course sample data copied.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- [OpenAI embedding response usage](https://developers.openai.com/api/reference/resources/embeddings/methods/create).

## Initial low-cost selection (checked October 16, 2026)

The text default is `gpt-6-luna` using the existing direct OpenAI adapter.
This requires an OpenAI API key; the current client does not configure an
OpenRouter endpoint/key. No API key was accessed and no paid call was made
when setting these defaults. Account access still needs verification.

The [model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
lists standard short-context input/output rates of $0.10/$0.50 per million
tokens. Above 272,000 input tokens, full-request input/output rates become
$0.20/$0.75. `llm.long_context` applies that threshold to reservations and
actual reported input usage. Cached-input/cache-write adjustments and regional
premiums remain outside these baseline list-price estimates.

For illustration, 10,000 input + 1,000 output tokens costs $0.0015 at those
short-context rates, before other charges. This is arithmetic, not a measured
project bill or a guarantee of token counts. Initial local-ledger caps are $1 total and $0.05 per task.

`reasoning_effort: none` and omitted temperature keep the initial Chat
Completions request simple; the reasoning setting is part of the cache key.
The official page currently documents the `gpt-6-luna` alias rather than a
separate dated snapshot, so saved response caches provide replay stability;
do not claim independent live requests are immutable.

The [deprecation schedule](https://developers.openai.com/api/docs/deprecations)
lists GPT-4.1 nano shutdown on October 23, 2026 and GPT-4.1 shutdown on
January 14, 2027; they are avoided for this new setup. Final extraction/judge
quality still requires measured evaluation before choosing more capable roles.

## Streamlit model dropdown

Run `python -m streamlit run app/app.py -- --params params.yaml`. The sidebar
Model dropdown reads `llm.model_choices`, uses the configured large-role default
initially, and shows the selected model's standard input/output rates. Luna is
the default; the configured GPT-5.4 mini snapshot is an alternative. Add another
supported model and verified prices to configuration rather than editing the UI.
Generation settings must also be compatible with any newly approved model.

Selection lives in the current Streamlit session, not in a YAML write or shared
mutable global. `session_llm_client(params_path)` forwards it as the Client's
allowlisted `default_model`; explicit per-call models still override it for
purpose-specific work such as judging. A new session starts from the configured
default, and removing a selected model from the config resets to a valid choice.

The selector performs no inference. The inherited explorer still displays
existing pipeline outputs and has no connected Q&A form yet. Future request
handlers must use the session factory; model ID is already part of response
cache identity. Existing key/budget/replay restrictions continue to apply.

## Local key file

```bash
cp -n .env.example .env
```

Open `.env` locally and fill `OPENAI_API_KEY=` with your real key. Keep it out
of chat, screenshots, logs and Git. The example contains no key and is safe to
share. The helper checks the environment first, then this local file; file
values do not overwrite exported variables or mutate other sessions.

Only the API key is read from this file. Mode, models and budgets remain in
params (or the explicit mode environment override). Copying the example does
not enable paid calls: replay remains the default mode. An empty
or missing key produces a clear configuration error on a provider attempt.

### Initial live verification — 2026-10-16

One synthetic structured request to `gpt-6-luna` returned the validated value
42 and unit USD. Provider-reported usage was 77 input and 16 output tokens,
with an estimated model cost of $0.0000157 at configured rates. Replay returned
the same result while provider initialization and socket connections were
blocked, and left the usage ledger unchanged. This verifies the helper only;
real document recordings and full pipeline replay remain pending.
