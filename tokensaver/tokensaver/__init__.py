"""tokensaver - condense AI prompts and track token & cost savings.

Public API:
    from tokensaver import condense_text, condense_messages, ProxyClient
    from tokensaver import trim_history
"""

__version__ = "0.4.0"

from .condenser import condense_local, CondenseResult
from .proxy import condense_text, condense_messages, ProxyClient, ProxyStats
from .history import trim_history, TrimPreview
from .logcompress import compress_log_block
from .tokens import count_tokens, estimate_cost

__all__ = [
    "condense_local",
    "CondenseResult",
    "condense_text",
    "condense_messages",
    "ProxyClient",
    "ProxyStats",
    "trim_history",
    "TrimPreview",
    "compress_log_block",
    "count_tokens",
    "estimate_cost",
]
