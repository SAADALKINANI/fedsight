import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("FEDSIGHT_DATA_DIR", ROOT / "data"))
    index_dir: Path = Path(os.getenv("FEDSIGHT_INDEX_DIR", ROOT / ".index"))

    answer_model: str = os.getenv("FEDSIGHT_ANSWER_MODEL", "claude-sonnet-5-5")
    judge_model: str = os.getenv("FEDSIGHT_JUDGE_MODEL", "claude-haiku-5-5")
    embed_model: str = "snowflake/snowflake-arctic-embed-xs"
    # this model family expects queries (not documents) to start with an instruction
    embed_query_prefix: str = "Represent this sentence for searching relevant passages: "
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    top_k: int = 6
    candidates: int = 40
    max_chunks_per_doc: int = 3
    min_rerank_score: float = -4.0   # below this a passage is treated as irrelevant

    max_agent_steps: int = 5
    max_answer_tokens: int = 1500

    # cost protection for the public demo
    rate_limit_per_hour: int = _env_int("FEDSIGHT_RATE_LIMIT", 20)
    daily_question_cap: int = _env_int("FEDSIGHT_DAILY_CAP", 300)
    max_question_chars: int = 600

    sources: tuple = field(default=("gao", "fema", "cdc"))


settings = Settings()

# USD per million tokens (input, output). Used for the cost shown in the UI and eval report.
PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, (2.0, 10.0))
    return (input_tokens * pin + output_tokens * pout) / 1_000_000
