"""
Proxy library.

Lets your code condense prompts automatically before they reach an AI API,
instead of piping through the CLI by hand. Two ways to use it:

1. condense_messages() / condense_text() -- plain functions you call yourself.
2. ProxyClient -- a transparent wrapper around an AI SDK client. Every call
   that passes `messages` gets the user-role text condensed first, and the
   savings are recorded to the same dashboard the CLI uses.

Everything is local-only: no network, no API keys, no extra dependencies.
The proxy never sends anything anywhere itself -- it only rewrites the
arguments and forwards them to the client you gave it.

Example
-------
    from tokensaver.proxy import ProxyClient
    import anthropic

    client = ProxyClient(anthropic.Anthropic())   # wraps your real client
    client.messages.create(                       # prompt is condensed first
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "please kindly help me ..."}],
    )

    # later:  tokensaver stats   -> savings show up on the dashboard
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .condenser import condense_local
from .tokens import count_tokens, estimate_cost
from .store import Store, Record


@dataclass
class ProxyStats:
    """Returned by condense helpers so callers can inspect the savings."""
    input_tokens: int
    output_tokens: int
    tokens_saved: int
    exec_ms: float
    cost_saved: float
    notes: list = field(default_factory=list)

    @property
    def percent_saved(self) -> float:
        if self.input_tokens == 0:
            return 0.0
        return self.tokens_saved / self.input_tokens * 100.0


def _record(stats: ProxyStats, command: str, label: str = "") -> None:
    """Append a run to the shared dashboard store."""
    store = Store.load()
    store.add(Record(
        ts=time.time(),
        command=command,
        mode="local",
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        tokens_saved=stats.tokens_saved,
        exec_ms=stats.exec_ms,
        cost_saved=stats.cost_saved,
        label=label,
    ))


def condense_text(
    text: str,
    *,
    level: str = "balanced",
    compress_logs: bool = False,
    track: bool = True,
    label: str = "",
) -> tuple[str, ProxyStats]:
    """Condense a single string. Returns (condensed_text, stats).

    level: "safe" or "balanced" (default). Both are lossless.
    compress_logs: collapse long pasted logs/stack traces.
    """
    start = time.perf_counter()
    result = condense_local(text, level=level, compress_logs=compress_logs)
    exec_ms = (time.perf_counter() - start) * 1000.0

    in_tok = count_tokens(text)
    out_tok = count_tokens(result.condensed)
    saved = max(0, in_tok - out_tok)
    stats = ProxyStats(
        input_tokens=in_tok,
        output_tokens=out_tok,
        tokens_saved=saved,
        exec_ms=exec_ms,
        cost_saved=estimate_cost(saved, "input"),
    )
    if track:
        _record(stats, command="proxy.text", label=label)
    return result.condensed, stats


def _condense_content(content, level: str = "balanced", compress_logs: bool = False):
    """Condense the `content` field of one chat message.

    Handles both the plain-string form and the list-of-blocks form
    (used by Anthropic / OpenAI vision-style messages). Only text is
    touched; image/other blocks pass through untouched.
    """
    if isinstance(content, str):
        return condense_local(content, level=level,
                              compress_logs=compress_logs).condensed

    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" \
                    and isinstance(block.get("text"), str):
                new = dict(block)
                new["text"] = condense_local(block["text"], level=level,
                                             compress_logs=compress_logs).condensed
                out.append(new)
            else:
                out.append(block)  # image, tool_result, etc -- leave alone
        return out

    return content  # unknown shape -- don't risk mangling it


def condense_messages(
    messages: list[dict],
    *,
    roles: tuple[str, ...] = ("user",),
    level: str = "balanced",
    compress_logs: bool = False,
    trim_history_turns: int | None = None,
    confirm_trim=None,
    track: bool = True,
    label: str = "",
) -> tuple[list[dict], ProxyStats]:
    """Condense the chat `messages` list used by Claude / OpenAI style APIs.

    Only messages whose role is in `roles` are condensed (default: just
    "user" -- system prompts and prior assistant turns are left intact).
    This per-message pass is lossless.

    level: "safe" or "balanced" (default). Both are lossless.
    compress_logs: opt-in collapsing of pasted logs. OFF by default --
        pasted blocks are kept exactly as-is.

    History trimming (re-sends of old turns are the big token sink) is
    OPT-IN and CONFIRMED -- it never happens silently:
      trim_history_turns: number of recent turns to keep verbatim. If None
          (default), history is NOT trimmed at all.
      confirm_trim: a callable taking a TrimPreview and returning True to
          proceed. If trim_history_turns is set but confirm_trim is None or
          returns False, the trim is SKIPPED and the untrimmed (but
          per-message condensed) list is returned.

    Returns (new_messages, aggregate_stats). stats.notes records what happened.
    """
    start = time.perf_counter()

    original_join = [
        _text_of(m.get("content", "")) if isinstance(m, dict) else ""
        for m in messages
    ]

    trim_notes: list[str] = []
    working = list(messages)

    # History trimming pass FIRST, on the original messages -- opt-in AND
    # confirmed. The trim losslessly condenses OLD turns; the per-message
    # pass below then condenses the remaining (recent) turns. Running trim
    # first avoids double-condensing and lets the preview report real savings.
    if trim_history_turns is not None:
        from .history import trim_history

        preview = trim_history(messages, keep_recent=trim_history_turns)

        if not preview.has_changes:
            trim_notes.append("history trim: nothing to trim")
        elif confirm_trim is None:
            trim_notes.append(
                "history trim available "
                f"(would save {preview.tokens_saved} tokens) -- skipped: "
                "no confirm_trim callback provided")
        else:
            if bool(confirm_trim(preview)):
                working = preview.apply()
                trim_notes.append(
                    f"history trimmed (confirmed): saved "
                    f"{preview.tokens_saved} tokens, "
                    f"{preview.turns_condensed} old turns condensed")
            else:
                trim_notes.append("history trim declined by user")

    # Per-message condensing pass (lossless). Old turns may already be
    # condensed by the trim; re-running on them is harmless (idempotent).
    new_messages = []
    for msg in working:
        if isinstance(msg, dict) and msg.get("role") in roles and "content" in msg:
            new_msg = dict(msg)
            new_msg["content"] = _condense_content(
                msg["content"], level=level, compress_logs=compress_logs)
            new_messages.append(new_msg)
        else:
            new_messages.append(msg)

    exec_ms = (time.perf_counter() - start) * 1000.0

    in_tok = count_tokens("\n".join(original_join))
    out_tok = count_tokens(
        "\n".join(_text_of(m.get("content", "")) for m in new_messages
                  if isinstance(m, dict)))
    saved = max(0, in_tok - out_tok)
    stats = ProxyStats(
        input_tokens=in_tok,
        output_tokens=out_tok,
        tokens_saved=saved,
        exec_ms=exec_ms,
        cost_saved=estimate_cost(saved, "input"),
    )
    stats.notes = trim_notes
    if track:
        _record(stats, command="proxy.messages", label=label)
    return new_messages, stats


def _text_of(content) -> str:
    """Extract just the text from a message content field, for token counting."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


# ----------------------------------------------------------------------
# Transparent client wrapper
# ----------------------------------------------------------------------

class _MethodProxy:
    """Wraps an SDK sub-object (e.g. client.messages) so that calls with a
    `messages=` kwarg get condensed first."""

    def __init__(self, target, opts):
        self._target = target
        self._opts = opts  # dict of condense options

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            if "messages" in kwargs and isinstance(kwargs["messages"], list):
                kwargs["messages"], _ = condense_messages(
                    kwargs["messages"], **self._opts)
            return attr(*args, **kwargs)

        return wrapped


class ProxyClient:
    """Transparent wrapper around an AI SDK client.

    Forwards every attribute to the wrapped client, but any sub-object whose
    methods take a `messages` kwarg (e.g. `.messages`, `.chat.completions`)
    gets its prompts condensed automatically.

    Works with the Anthropic SDK and OpenAI SDK shapes. Local-only: it never
    makes a network call itself -- it just rewrites arguments and hands them
    to the real client.

    Options:
      roles              roles to condense (default: ("user",))
      level              "safe" | "balanced" (default). Both lossless.
      compress_logs      opt-in log/stack-trace collapsing (default: False --
                         pasted blocks are kept exactly as-is)
      trim_history_turns if set, enable history trimming keeping this many
                         recent turns verbatim (default: None = no trimming)
      confirm_trim       REQUIRED to actually trim history. A callable taking
                         a TrimPreview and returning True/False. Without it,
                         history trimming is previewed but never applied --
                         trimming can never happen without your confirmation.
      track              record savings to the dashboard (default: True)
      label              optional tag for dashboard records
    """

    def __init__(
        self,
        client,
        *,
        roles: tuple[str, ...] = ("user",),
        level: str = "balanced",
        compress_logs: bool = False,
        trim_history_turns: int | None = None,
        confirm_trim=None,
        track: bool = True,
        label: str = "",
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
        attr = getattr(self._client, name)
        # Sub-objects (messages, chat, completions...) get proxied so we can
        # intercept their create()/etc calls. Primitives pass straight through.
        if hasattr(attr, "__dict__") or hasattr(type(attr), "__getattr__"):
            return _MethodProxy(attr, self._opts)
        return attr
