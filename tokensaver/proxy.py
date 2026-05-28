
"""
Advanced AI proxy middleware.

Features:
- semantic prompt compression
- automatic message optimization
- history trimming
- request deduplication
- token tracking
- caching
- smart skipping
- dashboard analytics
- SDK wrapping

Works with:
- OpenAI
- Anthropic
- Ollama
- Local LLM SDKs
"""

from __future__ import annotations

import hashlib
import time

from dataclasses import dataclass, field
from functools import lru_cache

from .condenser import condense_local
from .tokens import (
    count_tokens,
    estimate_cost,
)
from .store import Store, Record


# ==========================================================
# Context limits
# ==========================================================
MODEL_CONTEXT_LIMITS = {
    "gpt4o": 128000,
    "claude": 200000,
    "llama3": 8192,
}


# ==========================================================
# Stats object
# ==========================================================
@dataclass
class ProxyStats:

    input_tokens: int
    output_tokens: int
    tokens_saved: int
    exec_ms: float
    cost_saved: float

    notes: list = field(default_factory=list)

    @property
    def percent_saved(self):

        if self.input_tokens == 0:
            return 0.0

        return (
            self.tokens_saved
            / self.input_tokens
            * 100.0
        )


# ==========================================================
# Dashboard recording
# ==========================================================
def _record(
    stats: ProxyStats,
    command: str,
    label: str = "",
):

    store = Store.load()

    store.add(
        Record(
            ts=time.time(),
            command=command,
            mode="proxy",
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            tokens_saved=stats.tokens_saved,
            exec_ms=stats.exec_ms,
            cost_saved=stats.cost_saved,
            label=label,
        )
    )


# ==========================================================
# Hashing
# ==========================================================
def _hash_text(text: str) -> str:

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ==========================================================
# Cached condensing
# ==========================================================
@lru_cache(maxsize=4096)
def _cached_condense(
    text: str,
    level: str,
    compress_logs: bool,
):

    return condense_local(
        text,
        level=level,
        compress_logs=compress_logs,
    )


# ==========================================================
# Extract text from content
# ==========================================================
def _text_of(content):

    if isinstance(content, str):
        return content

    if isinstance(content, list):

        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
        )

    return ""


# ==========================================================
# Smart skip logic
# ==========================================================
def _should_skip(text: str) -> bool:

    stripped = text.strip().lower()

    if len(stripped) < 12:
        return True

    trivial = {
        "ok",
        "yes",
        "no",
        "thanks",
        "thank you",
        "hi",
        "hello",
    }

    return stripped in trivial


# ==========================================================
# Prompt classification
# ==========================================================
def _classify_prompt(text: str) -> str:

    lower = text.lower()

    if (
        "exception" in lower
        or "stacktrace" in lower
        or "error" in lower
    ):
        return "debug"

    if (
        "optimize" in lower
        or "performance" in lower
        or "slow" in lower
    ):
        return "performance"

    if (
        "ai" in lower
        or "routing" in lower
    ):
        return "architecture"

    if (
        "log" in lower
        or "trace" in lower
    ):
        return "logs"

    return "general"


# ==========================================================
# Condense content
# ==========================================================
def _condense_content(
    content,
    *,
    level: str = "balanced",
    compress_logs: bool = False,
):

    if isinstance(content, str):

        if _should_skip(content):
            return content

        result = _cached_condense(
            content,
            level,
            compress_logs,
        )

        return result.condensed

    if isinstance(content, list):

        out = []

        for block in content:

            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):

                txt = block["text"]

                if _should_skip(txt):
                    out.append(block)
                    continue

                result = _cached_condense(
                    txt,
                    level,
                    compress_logs,
                )

                nb = dict(block)
                nb["text"] = result.condensed

                out.append(nb)

            else:
                out.append(block)

        return out

    return content


# ==========================================================
# Message deduplication
# ==========================================================
def _dedupe_messages(messages):

    seen = set()
    deduped = []

    for msg in messages:

        if not isinstance(msg, dict):
            deduped.append(msg)
            continue

        txt = _text_of(
            msg.get("content", "")
        ).strip().lower()

        if not txt:
            deduped.append(msg)
            continue

        h = _hash_text(txt)

        if h in seen:
            continue

        seen.add(h)
        deduped.append(msg)

    return deduped


# ==========================================================
# Condense text
# ==========================================================
def condense_text(
    text: str,
    *,
    level: str = "balanced",
    compress_logs: bool = False,
    track: bool = True,
    label: str = "",
):

    start = time.perf_counter()

    result = _cached_condense(
        text,
        level,
        compress_logs,
    )

    exec_ms = (
        time.perf_counter() - start
    ) * 1000.0

    in_tok = count_tokens(text)
    out_tok = count_tokens(result.condensed)

    saved = max(0, in_tok - out_tok)

    stats = ProxyStats(
        input_tokens=in_tok,
        output_tokens=out_tok,
        tokens_saved=saved,
        exec_ms=exec_ms,
        cost_saved=estimate_cost(
            saved,
            "input",
        ),
    )

    if track:
        _record(
            stats,
            command="proxy.text",
            label=label,
        )

    return result.condensed, stats


# ==========================================================
# Condense messages
# ==========================================================
def condense_messages(
    messages: list[dict],
    *,
    roles: tuple[str, ...] = (
        "user",
        "assistant",
    ),
    level: str = "balanced",
    compress_logs: bool = False,
    trim_history_turns: int | None = None,
    confirm_trim=None,
    track: bool = True,
    label: str = "",
):

    start = time.perf_counter()

    original_join = [
        _text_of(m.get("content", ""))
        for m in messages
        if isinstance(m, dict)
    ]

    working = list(messages)

    # ------------------------------------------------------
    # History trimming
    # ------------------------------------------------------
    trim_notes = []

    if trim_history_turns is not None:

        from .history import trim_history

        preview = trim_history(
            messages,
            keep_recent=trim_history_turns,
        )

        if preview.has_changes:

            if (
                confirm_trim is not None
                and bool(confirm_trim(preview))
            ):

                working = preview.apply()

                trim_notes.append(
                    f"history trimmed "
                    f"({preview.tokens_saved} tokens saved)"
                )

    # ------------------------------------------------------
    # Deduplicate
    # ------------------------------------------------------
    working = _dedupe_messages(working)

    # ------------------------------------------------------
    # Condense
    # ------------------------------------------------------
    new_messages = []

    for msg in working:

        if (
            isinstance(msg, dict)
            and msg.get("role") in roles
            and "content" in msg
        ):

            new_msg = dict(msg)

            new_msg["content"] = _condense_content(
                msg["content"],
                level=level,
                compress_logs=compress_logs,
            )

            new_messages.append(new_msg)

        else:
            new_messages.append(msg)

    exec_ms = (
        time.perf_counter() - start
    ) * 1000.0

    in_tok = count_tokens(
        "\n".join(original_join)
    )

    out_tok = count_tokens(
        "\n".join(
            _text_of(m.get("content", ""))
            for m in new_messages
            if isinstance(m, dict)
        )
    )

    saved = max(
        0,
        in_tok - out_tok,
    )

    stats = ProxyStats(
        input_tokens=in_tok,
        output_tokens=out_tok,
        tokens_saved=saved,
        exec_ms=exec_ms,
        cost_saved=estimate_cost(
            saved,
            "input",
        ),
    )

    stats.notes = trim_notes

    if track:

        _record(
            stats,
            command="proxy.messages",
            label=label,
        )

    return new_messages, stats


# ==========================================================
# Method proxy
# ==========================================================
class _MethodProxy:

    def __init__(
        self,
        target,
        opts,
    ):
        self._target = target
        self._opts = opts

    def __getattr__(self, name):

        attr = getattr(
            self._target,
            name,
        )

        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):

            if (
                "messages" in kwargs
                and isinstance(
                    kwargs["messages"],
                    list,
                )
            ):

                kwargs["messages"], _ = condense_messages(
                    kwargs["messages"],
                    **self._opts,
                )

            return attr(
                *args,
                **kwargs,
            )

        return wrapped


# ==========================================================
# Transparent client wrapper
# ==========================================================
class ProxyClient:

    def __init__(
        self,
        client,
        *,
        roles=("user", "assistant"),
        level="balanced",
        compress_logs=False,
        trim_history_turns=None,
        confirm_trim=None,
        track=True,
        label="",
    ):

        self._client = client

        self._opts = dict(
            roles=roles,
            level=level,
            compress_logs=compress_logs,
            trim_history_turns=trim_history_turns,
            confirm_trim=confirm_trim,
            track=track,
            label=label,
        )

    def __getattr__(self, name):

        attr = getattr(
            self._client,
            name,
        )

        if (
            hasattr(attr, "__dict__")
            or hasattr(type(attr), "__getattr__")
        ):

            return _MethodProxy(
                attr,
                self._opts,
            )

        return attr
