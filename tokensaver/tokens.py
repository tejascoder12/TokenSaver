"""
Token counting + cost estimation.

Uses tiktoken when available for accurate counts. Falls back to a
chars/4 heuristic if tiktoken or the encoding can't load (e.g. offline).
"""

from __future__ import annotations

# Approx USD per 1M tokens. Rough public list-price ballparks; used only
# to *estimate* savings, not for billing. Edit ~/.tokensaver/config if needed.
DEFAULT_PRICING = {
    "input_per_1m": 3.00,
    "output_per_1m": 15.00,
}

_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder():
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENCODER = None
    return _ENCODER


def count_tokens(text: str) -> int:
    """Return token count. Accurate if tiktoken is present, else estimated."""
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # Fallback heuristic: ~4 chars per token for English text.
    return max(1, len(text) // 4)


def estimate_cost(tokens: int, kind: str = "input", pricing: dict | None = None) -> float:
    """Estimate USD cost for a number of tokens."""
    p = pricing or DEFAULT_PRICING
    rate = p["output_per_1m"] if kind == "output" else p["input_per_1m"]
    return (tokens / 1_000_000) * rate


def encoder_is_accurate() -> bool:
    return _get_encoder() is not None
