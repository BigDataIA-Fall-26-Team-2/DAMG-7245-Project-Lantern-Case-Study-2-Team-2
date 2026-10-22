"""Record or replay a structured extraction from the fictional Kestrel memo."""

from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from src.llm.client import Client


class PracticeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str
    revenue_usd_m: float = Field(ge=0)
    ebitda_usd_m: float = Field(ge=0)
    revenue_growth_pct: float
    net_revenue_retention_pct: float
    top_customer_share_pct: float = Field(ge=0, le=100)
    enterprise_value_usd_m: float = Field(ge=0)


def main() -> None:
    memo = Path(__file__).with_name("kestrel_practice_memo.md").read_text()
    client = Client()
    profile = client.structured(
        PracticeProfile,
        [{"role": "user", "content": f"Extract the stated company metrics.\n\n{memo}"}],
        scope="kestrel",
        task_id="synthetic-kestrel-practice-v1",
        stage="extract_profile",
    )
    expected = dict(company_name="Kestrel Analytics", revenue_usd_m=48,
                    ebitda_usd_m=8, revenue_growth_pct=26,
                    net_revenue_retention_pct=118, top_customer_share_pct=14,
                    enterprise_value_usd_m=136)
    if profile.model_dump() != expected:
        raise ValueError("Synthetic extraction differs from the stated practice memo")
    print(profile.model_dump_json(indent=2))
    print(client.usage_summary(scope="kestrel", task_id="synthetic-kestrel-practice-v1"))
    started = perf_counter()
    vectors = client.embed(
        [memo],
        scope="kestrel",
        task_id="synthetic-kestrel-practice-v1",
        model=client.config["embed"]["open"],
    )
    if vectors.shape != (1, 384):
        raise ValueError(f"Unexpected practice embedding shape: {vectors.shape}")
    elapsed = perf_counter() - started
    print(f"Open embeddings: {len(vectors)} vector(s), {len(vectors[0])} dimensions")
    print(f"Embedding call elapsed: {elapsed:.3f}s (cache hit or local inference)")


if __name__ == "__main__":
    main()
