
from __future__ import annotations

from dataclasses import dataclass, field

from .condenser import condense_local
from .tokens import count_tokens


def _content_text(content):

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict)
            and b.get("type") == "text"
        )

    return ""


def _condense_content(content):

    if isinstance(content, str):
        return condense_local(
            content,
            level="balanced",
        ).condensed

    if isinstance(content, list):

        out = []

        for block in content:

            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):

                nb = dict(block)

                nb["text"] = condense_local(
                    block["text"],
                    level="balanced",
                ).condensed

                out.append(nb)

            else:
                out.append(block)

        return out

    return content


@dataclass
class TrimPreview:

    turns_total: int
    turns_kept_verbatim: int
    turns_condensed: int
    tokens_before: int
    tokens_after: int

    memory_summary: str = ""

    _proposed: list = field(
        default_factory=list,
        repr=False,
    )

    applied: bool = False

    @property
    def tokens_saved(self):
        return max(
            0,
            self.tokens_before - self.tokens_after,
        )

    @property
    def percent_saved(self):

        if self.tokens_before == 0:
            return 0.0

        return (
            self.tokens_saved
            / self.tokens_before
            * 100.0
        )

    @property
    def has_changes(self):
        return (
            self.turns_condensed > 0
            and self.tokens_saved > 0
        )

    def describe(self):

        return (
            f"History trim preview:\n"
            f"Turns total: {self.turns_total}\n"
            f"Kept verbatim: {self.turns_kept_verbatim}\n"
            f"Condensed: {self.turns_condensed}\n"
            f"Tokens: {self.tokens_before} -> {self.tokens_after}\n"
            f"Saved: {self.tokens_saved} "
            f"({self.percent_saved:.1f}%)"
        )

    def apply(self):
        self.applied = True
        return list(self._proposed)


def _build_memory_summary(messages):

    topics = set()

    joined = " ".join(
        _content_text(m.get("content", ""))
        for m in messages
    ).lower()

    keywords = {
        "asp.net": "ASP.NET",
        "ai": "AI",
        "token": "token optimization",
        "cache": "caching",
        "routing": "AI routing",
        "backend": "backend API",
    }

    for k, v in keywords.items():
        if k in joined:
            topics.add(v)

    if not topics:
        return ""

    return (
        "Conversation Memory: "
        + ", ".join(sorted(topics))
    )


def trim_history(
    messages: list[dict],
    *,
    keep_recent: int = 6,
):

    tokens_before = count_tokens(
        "\n".join(
            _content_text(m.get("content", ""))
            for m in messages
        )
    )

    system_msgs = [
        m for m in messages
        if m.get("role") == "system"
    ]

    dialogue = [
        m for m in messages
        if m.get("role") != "system"
    ]

    if len(dialogue) <= keep_recent:

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

        nm["content"] = _condense_content(
            m.get("content", "")
        )

        new_older.append(nm)

    memory_summary = _build_memory_summary(
        older
    )

    proposed = []

    proposed.extend(system_msgs)

    if memory_summary:
        proposed.append({
            "role": "system",
            "content": memory_summary,
        })

    proposed.extend(new_older)
    proposed.extend(recent)

    tokens_after = count_tokens(
        "\n".join(
            _content_text(m.get("content", ""))
            for m in proposed
        )
    )

    return TrimPreview(
        turns_total=len(messages),
        turns_kept_verbatim=len(system_msgs)
        + len(recent),
        turns_condensed=len(older),
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        memory_summary=memory_summary,
        _proposed=proposed,
    )
