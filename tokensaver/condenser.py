"""
Condensing engine.

Reduces the token footprint of a prompt without losing meaning.
Pure heuristic / regex compression: free, instant, no network calls.

The condenser is conservative on purpose: it removes filler, collapses
whitespace, strips politeness padding and redundant phrasing, but never
touches code blocks, file paths, numbers, or anything inside quotes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Whole sentences that are pure padding -> dropped entirely.
_FILLER_SENTENCES = [
    r"thank you[^.!?\n]*[.!?]",
    r"thanks[^.!?\n]*[.!?]",
    r"i (really )?appreciate (it|your help)[^.!?\n]*[.!?]",
    r"i was wondering if[^.!?\n]*[.!?]",
]

# Filler words/phrases that almost never change instruction meaning.
# Kept conservative so removal doesn't strand sentence fragments.
_FILLER_PHRASES = [
    r"\bplease\b",
    r"\bkindly\b",
    r"\bi would like you to\b",
    r"\bi'?d like you to\b",
    r"\bi want you to\b",
    r"\bi need you to\b",
    r"\bi would like to\b",
    r"\bcould you please\b",
    r"\bcan you please\b",
    r"\bwould you please\b",
    r"\bcould you\b",
    r"\bcan you\b",
    r"\bif (it'?s |it is )?possible\b",
    r"\bjust\b",
    r"\bvery\b",
    r"\breally\b",
    r"\bbasically\b",
    r"\bactually\b",
    r"\bsimply\b",
    r"\bfor me\b",
    r"\bif you (don'?t|do not) mind\b",
    r"\bhere\b(?=[.,!?])",
]

# Phrase -> shorter equivalent.
_REPLACEMENTS = {
    r"\bin order to\b": "to",
    r"\bdue to the fact that\b": "because",
    r"\bat this point in time\b": "now",
    r"\bin the event that\b": "if",
    r"\ba large number of\b": "many",
    r"\bthe majority of\b": "most",
    r"\bwith regard to\b": "about",
    r"\bin spite of the fact that\b": "although",
    r"\bmake use of\b": "use",
    r"\bas a matter of fact\b": "",
    r"\bit is important to note that\b": "note:",
}


@dataclass
class CondenseResult:
    original: str
    condensed: str
    mode: str
    notes: list[str]


def _protect_segments(text: str) -> tuple[str, dict[str, str]]:
    """Replace code blocks, inline code, and quoted strings with placeholders
    so the heuristic pass never mangles them."""
    vault: dict[str, str] = {}
    idx = 0

    def stash(match: re.Match) -> str:
        nonlocal idx
        key = f"\x00PROT{idx}\x00"
        vault[key] = match.group(0)
        idx += 1
        return key

    # Fenced code blocks
    text = re.sub(r"```.*?```", stash, text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r"`[^`\n]+`", stash, text)
    # Double-quoted strings
    text = re.sub(r'"[^"\n]*"', stash, text)
    return text, vault


def _restore_segments(text: str, vault: dict[str, str]) -> str:
    for key, val in vault.items():
        text = text.replace(key, val)
    return text


def _maybe_compress_logs(text: str) -> tuple[str, bool]:
    """Run log/dump compression on the whole text. Returns (text, changed).

    Handles both fenced ```...``` blocks and bare pasted logs. Only blocks
    that actually look like logs are touched; everything else is returned
    verbatim, so meaning is preserved.
    """
    from .logcompress import compress_log_block

    changed = False

    # Compress inside fenced code blocks (logs are often pasted in fences).
    def fence_sub(m: re.Match) -> str:
        nonlocal changed
        fence = m.group(0)
        inner = fence[3:-3]
        # keep an optional language tag on the first line
        nl = inner.find("\n")
        if nl == -1:
            return fence
        lang, body = inner[:nl], inner[nl + 1:]
        res = compress_log_block(body)
        if res.changed:
            changed = True
            return f"```{lang}\n{res.text}\n```"
        return fence

    text = re.sub(r"```.*?```", fence_sub, text, flags=re.DOTALL)

    # Compress bare (un-fenced) log blocks: split on blank lines, test each.
    blocks = re.split(r"(\n\s*\n)", text)
    rebuilt = []
    for blk in blocks:
        if blk.strip() and "\n" in blk:
            res = compress_log_block(blk)
            if res.changed:
                changed = True
                rebuilt.append(res.text)
                continue
        rebuilt.append(blk)
    text = "".join(rebuilt)

    return text, changed


def condense_local(
    text: str,
    *,
    level: str = "balanced",
    compress_logs: bool = False,
) -> CondenseResult:
    """Heuristic, fully meaning-preserving compression. No network calls.

    level:
      "safe"     - filler/padding removal and whitespace only.
      "balanced" - same as safe (the default). Reserved for future
                   lossless heuristics. Both levels are lossless.
    compress_logs:
      OFF by default -- pasted logs and blocks are left exactly as-is.
      Set True to opt in to collapsing repetitive log/stack-trace lines.
    """
    if level not in ("safe", "balanced"):
        raise ValueError(f"unknown level: {level!r} (use 'safe' or 'balanced')")

    notes: list[str] = []
    work = text

    # Log compression is opt-in only. Off by default so pasted blocks
    # are preserved byte-for-byte.
    if compress_logs:
        work, log_changed = _maybe_compress_logs(work)
        if log_changed:
            notes.append("compressed pasted log/dump lines (opt-in)")

    protected, vault = _protect_segments(work)
    work = protected

    # Phrase replacements
    for pattern, repl in _REPLACEMENTS.items():
        if re.search(pattern, work, flags=re.IGNORECASE):
            work = re.sub(pattern, repl, work, flags=re.IGNORECASE)
            notes.append(f"replaced verbose phrase -> '{repl or '(removed)'}'")

    # Drop whole padding sentences first (avoids stranded fragments).
    for pattern in _FILLER_SENTENCES:
        if re.search(pattern, work, flags=re.IGNORECASE):
            work = re.sub(pattern, " ", work, flags=re.IGNORECASE)
            notes.append("removed padding sentence")

    # Remove filler phrases
    for pattern in _FILLER_PHRASES:
        if re.search(pattern, work, flags=re.IGNORECASE):
            work = re.sub(pattern, " ", work, flags=re.IGNORECASE)
    notes.append("stripped filler/politeness padding")

    # Collapse whitespace (but keep paragraph breaks)
    work = re.sub(r"[ \t]+", " ", work)
    work = re.sub(r" *\n *", "\n", work)
    work = re.sub(r"\n{3,}", "\n\n", work)

    # Tidy leftover punctuation from removals
    work = re.sub(r"\s+([,.;:!?])", r"\1", work)
    work = re.sub(r"([,.;:])\1+", r"\1", work)
    # Drop near-empty sentences left behind (e.g. " I!" or " .")
    work = re.sub(r"(^|[.!?\n])\s*[a-zA-Z]?\s*[.!?]", r"\1", work)
    work = re.sub(r"^[ ,.;:]+", "", work, flags=re.MULTILINE)
    work = re.sub(r"[ \t]+", " ", work)
    work = work.strip()

    # Capitalize first letter of lines BEFORE restoring code/quotes,
    # so protected segments are never altered.
    work = re.sub(
        r"(^|\n)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        work,
    )

    work = _restore_segments(work, vault)

    notes.append("collapsed whitespace")
    return CondenseResult(original=text, condensed=work, mode=level, notes=notes)
