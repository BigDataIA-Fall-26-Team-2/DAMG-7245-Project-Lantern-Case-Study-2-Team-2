"""Adapted from the LANTERN Part 2 course client; see docs/llm_client.md."""

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import yaml
from filelock import FileLock


class CacheMiss(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class ConfigurationError(ValueError):
    pass


def cache_key(request):
    payload = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, allow_nan=False)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


class Client:
    def __init__(self, params_path=None):
        self.params_path = Path(params_path or Path(__file__).resolve().parents[2] / "params.yaml").resolve()
        self.root = self.params_path.parent
        self.params = yaml.safe_load(self.params_path.read_text())
        self.config = self.params["llm"]
        self.mode = os.getenv("LANTERN_LLM_MODE", self.config.get("mode", "replay"))
        if self.mode not in {"replay", "record", "live"}:
            raise ValueError("LLM mode must be replay, record or live")
        if self.config.get("provider") != "openai":
            raise ValueError("Only the configured OpenAI provider is implemented")
        self.ledger_path = self.root / self.config.get("ledger", "logs/cost_ledger.jsonl")
        self._sdk = None
        self._open_model = None

    def _identity(self, scope, stage, task_id):
        if scope not in {"public", "deal_a", "deal_b", "kestrel"}:
            raise ValueError("scope must be public, deal_a, deal_b or kestrel")
        if not isinstance(stage, str) or not stage.strip() or not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("stage and task_id must be nonempty strings")

    def _model(self, explicit, role):
        value = explicit or self.config.get("models", {}).get(role)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Configure a pinned model for {role}, or pass model explicitly")
        return value

    def _usd(self, model, tin, tout):
        prices = self.config.get("prices", {}).get(model)
        tier = self.config.get("long_context", {}).get(model)
        if tier is not None:
            threshold = _nonnegative(tier["above_input_tokens"], "context threshold")
            if tin > threshold:
                prices = tier["prices"]
        if not isinstance(prices, list) or len(prices) != 2:
            raise ValueError(f"Set verified [input, output] USD per million token prices for {model}")
        pin, pout = [_nonnegative(p, "price") for p in prices]
        return (tin * pin + tout * pout) / 1_000_000

    def _usage(self, usage):
        tin = getattr(usage, "prompt_tokens", None)
        tout = getattr(usage, "completion_tokens", 0)
        if not isinstance(tin, int) or isinstance(tin, bool) or tin < 0:
            raise ValueError("Provider response has no valid input-token usage")
        if not isinstance(tout, int) or isinstance(tout, bool) or tout < 0:
            raise ValueError("Provider response has no valid output-token usage")
        return tin, tout

    def _events(self):
        latest = {}
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text().splitlines():
                row = json.loads(line)
                _nonnegative(row["usd"], "ledger usd")
                latest[row["request_id"]] = row
        return list(latest.values())

    def _append(self, row):
        with self.ledger_path.open("a") as handle:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _cached(self, path, key, validate):
        payload = json.loads(path.read_text())
        if payload.get("key") != key:
            raise ValueError(f"Cache identity mismatch: {path}")
        return validate(payload["data"])

    def _run(self, request, stage, task_id, invoke, validate, tin_bound, tout_bound, local=False):
        scope, model = request["scope"], request["model"]
        self._identity(scope, stage, task_id)
        key = cache_key(request)
        folder = "data/embed_cache" if request["kind"] == "embedding" else "data/llm_cache"
        path = self.root / folder / scope / f"{key}.json"
        if self.mode != "live" and path.exists():
            return self._cached(path, key, validate)
        if self.mode == "replay":
            raise CacheMiss(f"{request['kind']} cache miss {key} in scope {scope}")
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize calls sharing this ledger so simultaneous workers cannot overspend it.
        with FileLock(str(self.ledger_path) + ".lock", timeout=self.config.get("timeout_s", 60) + 10):
            if self.mode == "record" and path.exists():
                return self._cached(path, key, validate)
            reserved = 0 if local else self._usd(model, tin_bound, tout_bound)
            if not local:
                budget = self.params["budget"]
                total = _nonnegative(budget["usd_cap_total"], "total budget")
                per_task = _nonnegative(budget["usd_cap_per_task"], "task budget")
                if total == 0 or per_task == 0:
                    raise BudgetExceeded("Paid calls disabled: configure positive total and per-task caps")
                rows = self._events()
                task_spend = sum(r["usd"] for r in rows if r["scope"] == scope and r["task_id"] == task_id)
                if sum(r["usd"] for r in rows) + reserved > total or task_spend + reserved > per_task:
                    raise BudgetExceeded("The estimated request exceeds the total or per-task budget")
            row = {"request_id": uuid.uuid4().hex, "cache_key": key, "kind": request["kind"],
                   "provider": request["provider"], "model": model, "scope": scope,
                   "stage": stage, "task_id": task_id, "mode": self.mode,
                   "status": "reserved", "usd": reserved, "estimated": True,
                   "in": None, "out": None, "elapsed_s": 0}
            self._append(row)
            started, usage = time.perf_counter(), None
            try:
                data, usage = invoke()
                result = validate(data)
                tin, tout = (None, None) if local else self._usage(usage)
                usd = 0 if local else self._usd(model, tin, tout)
                if self.mode == "record":
                    _write_json(path, {"key": key, "data": data})
            except Exception as exc:
                usage = usage or getattr(exc, "total_usage", None)
                try:
                    tin, tout = (0, 0) if isinstance(exc, ConfigurationError) else self._usage(usage) if not local else (None, None)
                    usd = 0 if local else self._usd(model, tin, tout)
                    estimated = False
                except (ValueError, TypeError):
                    tin, tout, usd, estimated = None, None, reserved, True
                self._append({**row, "status": "error", "in": tin, "out": tout,
                              "usd": usd, "estimated": estimated, "error_type": type(exc).__name__,
                              "elapsed_s": time.perf_counter() - started})
                raise
            self._append({**row, "status": "success", "in": tin, "out": tout,
                          "usd": usd, "estimated": False, "reservation_exceeded": usd > reserved,
                          "elapsed_s": time.perf_counter() - started})
            return result

    def usage_summary(self, *, scope=None, task_id=None):
        if scope is not None:
            self._identity(scope, "summary", task_id or "summary")
        if not self.ledger_path.exists():
            rows = []
        else:
            with FileLock(str(self.ledger_path) + ".lock", timeout=10):
                rows = self._events()
        rows = [r for r in rows if (scope is None or r["scope"] == scope)
                and (task_id is None or r["task_id"] == task_id)]
        return {"requests": len(rows), "usd": sum(r["usd"] for r in rows),
                "estimated_requests": sum(r["estimated"] for r in rows),
                "input_tokens": sum(r["in"] or 0 for r in rows),
                "output_tokens": sum(r["out"] or 0 for r in rows)}

    def _openai(self):
        if self._sdk is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise ConfigurationError("Set OPENAI_API_KEY in your environment before a paid call")
            from openai import OpenAI
            self._sdk = OpenAI(max_retries=0, timeout=self.config.get("timeout_s", 60))
        return self._sdk

    def _structured(self, response_model, messages, model, temperature, max_tokens):
        import instructor
        client = instructor.from_openai(self._openai(), mode=instructor.Mode.JSON_SCHEMA)
        kwargs = {"temperature": temperature} if temperature is not None else {}
        effort = self.config.get("reasoning_effort")
        if effort is not None:
            kwargs["reasoning_effort"] = effort
        out, raw = client.create_with_completion(
            response_model=response_model, messages=messages, model=model,
            max_completion_tokens=max_tokens, max_retries=0, **kwargs)
        return out.model_dump(mode="json"), raw.usage

    def structured(self, response_model, messages, model=None, *, scope, task_id,
                   stage="build", max_tokens=None, input_token_bound=None):
        model = self._model(model, "large")
        max_tokens = max_tokens if max_tokens is not None else self.config.get("max_tokens", 1024)
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        schema = response_model.model_json_schema()
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list")
        temperature = self.config.get("temperature", 0)
        request = {"version": 1, "kind": "structured", "provider": "openai", "scope": scope,
                   "model": model, "messages": messages, "schema": schema,
                   "temperature": temperature, "max_tokens": max_tokens,
                   "reasoning_effort": self.config.get("reasoning_effort")}
        # Bytes plus schema overhead conservatively estimates text; images need a supplied bound.
        if input_token_bound is None:
            if any(not isinstance(m.get("content"), str) for m in messages):
                raise ValueError("Supply input_token_bound for image/multimodal requests")
            input_token_bound = len(json.dumps(messages).encode()) + len(json.dumps(schema).encode()) + 1024
        if not isinstance(input_token_bound, int) or isinstance(input_token_bound, bool) or input_token_bound <= 0:
            raise ValueError("input_token_bound must be a positive integer")
        return self._run(request, stage, task_id,
                         lambda: self._structured(response_model, messages, model, temperature, max_tokens),
                         response_model.model_validate, input_token_bound, max_tokens)

    def _hosted_embeddings(self, texts, model):
        response = self._openai().embeddings.create(model=model, input=texts)
        indexed = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in indexed] != list(range(len(texts))):
            raise ValueError("Provider returned mismatched embedding indexes")
        return [item.embedding for item in indexed], response.usage

    def _open_embeddings(self, texts, model, revision):
        if self._open_model is None:
            from sentence_transformers import SentenceTransformer
            self._open_model = SentenceTransformer(model, revision=revision)
        return self._open_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def embed(self, texts, model=None, compute=None, *, scope, task_id, stage="embed"):
        self._identity(scope, stage, task_id)
        texts = list(texts)
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("texts must contain nonempty strings")
        config = self.config.get("embed", {})
        model = model or config.get("hosted")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Configure a pinned embedding model or pass model explicitly")
        local = model == config.get("open")
        revision = config.get("open_revision") if local else None
        if local and (not isinstance(revision, str) or not revision.strip()):
            raise ValueError("Configure the open embedding model's pinned revision")
        if compute is not None and not local:
            raise ValueError("compute callbacks are only allowed for the configured open model")
        vectors = []
        for text in texts:
            request = {"version": 1, "kind": "embedding", "provider": "open" if local else "openai",
                       "scope": scope, "model": model, "revision": revision, "text": text}
            def invoke():
                if not local:
                    return self._hosted_embeddings([text], model)
                values = compute([text]) if compute is not None else self._open_embeddings([text], model, revision)
                return np.asarray(values).tolist(), None
            def validate(data):
                array = np.asarray(data, dtype=np.float32)
                if array.ndim != 2 or array.shape[0] != 1 or array.shape[1] == 0 or not np.isfinite(array).all():
                    raise ValueError("Embedding must be one nonempty finite vector per text")
                return array[0]
            vector = self._run(request, stage, task_id, invoke, validate,
                               len(text.encode()) + 16, 0, local=local)
            vectors.append(vector)
        if len({len(v) for v in vectors}) != 1:
            raise ValueError("Embedding dimensions differ across the requested texts")
        return np.vstack(vectors)


def structured(response_model, messages, model=None, *, params_path=None, **kwargs):
    return Client(params_path).structured(response_model, messages, model, **kwargs)


def embed(texts, model=None, compute=None, *, params_path=None, **kwargs):
    return Client(params_path).embed(texts, model, compute, **kwargs)
