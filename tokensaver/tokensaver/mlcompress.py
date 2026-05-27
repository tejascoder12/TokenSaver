"""
Optional ML-based prompt compression via LLMLingua-2.

Lossy: a small LM scores each token and drops the lowest-information ones.
Much more aggressive than the heuristic condenser, but meaning is preserved
only approximately. Use for long prompts where saving 30-50% matters more
than byte-for-byte fidelity.

LLMLingua is an optional dependency. Install with:
    pip install tokensaver[ml]
First run downloads a ~700MB model. CPU-only is fine for short prompts;
GPU is faster for long ones.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# A small multilingual encoder model — small enough to run on CPU,
# good general-purpose compressor for prompts.
_DEFAULT_MODEL = (
    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"
)

_COMPRESSOR = None  # cached PromptCompressor instance


@dataclass
class MLCompressResult:
    original: str
    compressed: str
    rate: float
    model: str


class MLUnavailable(RuntimeError):
    """Raised when LLMLingua isn't installed."""


def _load_compressor():
    """Lazy-load LLMLingua so importing this module is cheap."""
    global _COMPRESSOR
    if _COMPRESSOR is not None:
        return _COMPRESSOR
    try:
        from llmlingua import PromptCompressor  # type: ignore
    except ImportError as exc:
        raise MLUnavailable(
            "ML compression requires the optional 'llmlingua' package.\n"
            "Install with:\n"
            "    pip install tokensaver[ml]\n"
            "or directly:\n"
            "    pip install llmlingua\n"
            "(first run will download a ~700MB model)"
        ) from exc

    sys.stderr.write(
        "tokensave: loading ML model (first run downloads ~700MB)...\n"
    )
    sys.stderr.flush()
    _COMPRESSOR = PromptCompressor(
        model_name=_DEFAULT_MODEL,
        use_llmlingua2=True,
    )
    return _COMPRESSOR


def ml_compress(text: str, rate: float = 0.5) -> MLCompressResult:
    """Compress text with LLMLingua-2.

    rate: target keep-ratio. 0.5 = keep ~half the tokens.
          Smaller = more aggressive; larger = more conservative.
    """
    if not (0.05 <= rate <= 0.95):
        raise ValueError(f"rate must be between 0.05 and 0.95 (got {rate})")
    compressor = _load_compressor()
    out = compressor.compress_prompt(text, rate=rate, force_tokens=["\n"])
    return MLCompressResult(
        original=text,
        compressed=out["compressed_prompt"],
        rate=rate,
        model="llmlingua-2-bert-base",
    )
