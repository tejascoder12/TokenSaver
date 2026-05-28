
from __future__ import annotations

DEFAULT_PRICING = {
    "input_per_1m": 3.00,
    "output_per_1m": 15.00,
}

MODEL_ENCODINGS = {
    "gpt": "cl100k_base",
    "gpt4": "cl100k_base",
    "gpt4o": "o200k_base",
}

DEFAULT_MODEL = "gpt4o"

_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder(model: str = DEFAULT_MODEL):

    global _ENCODER
    global _ENCODER_TRIED

    if _ENCODER_TRIED:
        return _ENCODER

    _ENCODER_TRIED = True

    try:
        import tiktoken

        encoding_name = MODEL_ENCODINGS.get(
            model,
            "cl100k_base"
        )

        _ENCODER = tiktoken.get_encoding(
            encoding_name
        )

    except Exception:
        _ENCODER = None

    return _ENCODER


def count_tokens(
    text: str,
    model: str = DEFAULT_MODEL,
) -> int:

    if not text:
        return 0

    enc = _get_encoder(model)

    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass

    return max(1, len(text) // 4)


def estimate_cost(
    tokens: int,
    kind: str = "input",
    pricing: dict | None = None,
) -> float:

    p = pricing or DEFAULT_PRICING

    rate = (
        p["output_per_1m"]
        if kind == "output"
        else p["input_per_1m"]
    )

    return (tokens / 1_000_000) * rate


def compression_ratio(
    before: int,
    after: int,
) -> float:

    if before <= 0:
        return 0.0

    return ((before - after) / before) * 100.0


def compare_token_efficiency(
    original: str,
    optimized: str,
    model: str = DEFAULT_MODEL,
):

    before = count_tokens(original, model)
    after = count_tokens(optimized, model)

    return {
        "before": before,
        "after": after,
        "saved": before - after,
        "ratio": compression_ratio(before, after),
    }


def encoder_is_accurate() -> bool:
    return _get_encoder() is not None
