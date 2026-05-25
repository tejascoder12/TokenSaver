"""
Conversation history trimming.

The biggest token sink in a long chat is the history itself: every request
re-sends every previous turn. This module shrinks the history while keeping
the conversation usable.

Safety model -- trimming is LOSSLESS and CONFIRMED:
  * The system prompt is ALWAYS kept verbatim.
  * The most recent `keep_recent` turns are ALWAYS kept verbatim.
  * Older turns are only *condensed* (filler/padding removal) -- never
    dropped, never summarized. Meaning is preserved.
  * trim_history() does NOT return a ready-to-send message list. It returns
    a TrimPreview describing what *would* change. The caller must explicitly
    call preview.apply() to get the trimmed messages. This makes silent
    trimming impossible -- a confirmation step is structurally required.

There is only one trimming behavior (lossless condensing of old turns).
There is no aggressive/summarizing mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .condenser import condense_local
from .tokens import count_tokens


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _condense_content(content):
    """Condense a message's content (string or block list). Lossless."""
    if isinstance(content, str):
        return condense_local(content, level="balanced").condensed
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" \
                    and isinstance(block.get("text"), str):
                nb = dict(block)
                nb["text"] = condense_local(block["text"], level="balanced").condensed
                out.append(nb)
            else:
                out.append(block)
        return out
    return content


@dataclass
class TrimPreview:
    """The result of planning a history trim.

    This is a PREVIEW, not a finished message list. Call .apply() to get the
    trimmed messages -- that explicit step is the confirmation gate.
    """
    turns_total: int
    turns_kept_verbatim: int
    turns_condensed: int
    tokens_before: int
    tokens_after: int
    # the proposed trimmed list -- only handed out via apply()
    _proposed: list = field(default_factory=list, repr=False)
    applied: bool = False

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def percent_saved(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return self.tokens_saved / self.tokens_before * 100.0

    @property
    def has_changes(self) -> bool:
        return self.turns_condensed > 0 and self.tokens_saved > 0

    def describe(self) -> str:
        """Human-readable confirmation prompt text."""
        if not self.has_changes:
            return ("History trim: nothing to do "
                    f"({self.turns_total} turns, already compact).")
        return (
            f"History trim preview:\n"
            f"  turns total           : {self.turns_total}\n"
            f"  kept verbatim         : {self.turns_kept_verbatim} "
            f"(system + recent)\n"
            f"  older turns condensed : {self.turns_condensed} "
            f"(lossless -- none dropped)\n"
            f"  tokens                : {self.tokens_before} -> "
            f"{self.tokens_after}  (save {self.tokens_saved}, "
            f"{self.percent_saved:.1f}%)\n"
            f"  -> call .apply() to use the trimmed history."
        )

    def apply(self) -> list:
        """Confirm the trim and return the trimmed message list.

        This is the explicit confirmation step. Until this is called, the
        original conversation is untouched.
        """
        self.applied = True
        return list(self._proposed)


def trim_history(
    messages: list[dict],
    *,
    keep_recent: int = 6,
) -> TrimPreview:
    """Plan a lossless history trim.

    keep_recent: number of most-recent non-system turns kept fully verbatim.

    Returns a TrimPreview. Nothing is changed until you call preview.apply().
    Older turns are only condensed (filler removal) -- never dropped or
    summarized, so meaning is preserved.
    """
    tokens_before = count_tokens(
        "\n".join(_content_text(m.get("content", "")) for m in messages)
    )

    system_msgs = [m for m in messages if m.get("role") == "system"]
    dialogue = [m for m in messages if m.get("role") != "system"]

    if len(dialogue) <= keep_recent:
        # Nothing old enough to trim -- preview reports a no-op.
        return TrimPreview(
            turns_total=len(messages),
            turns_kept_verbatim=len(messages),
            turns_condensed=0,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            _proposed=list(messages),
        )

    recent = dialogue[-keep_recent:]
    older = dialogue[:-keep_recent]

    new_older = []
    for m in older:
        nm = dict(m)
        nm["content"] = _condense_content(m.get("content", ""))
        new_older.append(nm)

    proposed = system_msgs + new_older + recent
    tokens_after = count_tokens(
        "\n".join(_content_text(m.get("content", "")) for m in proposed)
    )

    return TrimPreview(
        turns_total=len(messages),
        turns_kept_verbatim=len(system_msgs) + len(recent),
        turns_condensed=len(older),
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        _proposed=proposed,
    )
