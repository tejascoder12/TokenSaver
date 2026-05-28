
from __future__ import annotations

import re

from dataclasses import dataclass

from .logcompress import compress_log_block


# ==========================================================
# Filler cleanup
# ==========================================================
_FILLER_SENTENCES = [
    r"thank you[^.!?\n]*[.!?]",
    r"thanks[^.!?\n]*[.!?]",
    r"i (really )?appreciate (it|your help)[^.!?\n]*[.!?]",
]

_FILLER_PHRASES = [
    r"\bplease\b",
    r"\bkindly\b",
    r"\bcould you\b",
    r"\bcan you\b",
    r"\bwould you\b",
    r"\bjust\b",
    r"\bvery\b",
    r"\breally\b",
    r"\bbasically\b",
    r"\bactually\b",
]


# ==========================================================
# Replacements
# ==========================================================
_REPLACEMENTS = {
    r"\bin order to\b": "to",
    r"\bdue to the fact that\b": "because",
    r"\bat this point in time\b": "now",
    r"\bbackend api\b": "backend API",
    r"\bai req\b": "AI requests",
}


# ==========================================================
# Result
# ==========================================================
@dataclass
class CondenseResult:

    original: str

    condensed: str

    mode: str

    notes: list[str]


# ==========================================================
# Protect code blocks
# ==========================================================
def _protect_segments(text: str):

    vault = {}

    idx = 0

    def stash(match):

        nonlocal idx

        key = f"\x00PROT{idx}\x00"

        vault[key] = match.group(0)

        idx += 1

        return key

    text = re.sub(
        r"```.*?```",
        stash,
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"`[^`\n]+`",
        stash,
        text,
    )

    return text, vault


# ==========================================================
# Restore protected blocks
# ==========================================================
def _restore_segments(text, vault):

    for k, v in vault.items():
        text = text.replace(k, v)

    return text


# ==========================================================
# Smart skip logic
# ==========================================================
def _should_skip(text: str):

    stripped = text.strip().lower()

    trivial = {
        "ok",
        "yes",
        "no",
        "thanks",
        "thank you",
        "hi",
        "hello",
    }

    if stripped in trivial:
        return True

    if len(stripped) < 10:
        return True

    return False


# ==========================================================
# Semantic compression
# ==========================================================
def _semantic_compress(text: str):

    lower = text.lower()

    sections = []

    # ------------------------------------------------------
    # AI Routing
    # ------------------------------------------------------
    if (
        "ai" in lower
        and (
            "backend" in lower
            or "request" in lower
            or "routing" in lower
        )
    ):

        sections.append(
            "Task: Build hybrid AI routing in backend API"
        )

    # ------------------------------------------------------
    # Non-AI operations
    # ------------------------------------------------------
    simple_ops = []

    if any(
        x in lower
        for x in [
            "log",
            "workout",
            "meal",
            "track",
            "ran",
        ]
    ):

        simple_ops.extend([
            "CRUD operations",
            "activity logging",
            "tracking requests",
        ])

    if simple_ops:

        sections.append(
            "Handle without AI:\n"
            + "\n".join(
                f"- {x}"
                for x in sorted(set(simple_ops))
            )
        )

    # ------------------------------------------------------
    # Performance optimization
    # ------------------------------------------------------
    if (
        "slow" in lower
        or "performance" in lower
        or "database queries" in lower
        or "repeated queries" in lower
    ):

        sections.append(
            "Optimize backend/API performance:\n"
            "- reduce repeated DB queries\n"
            "- improve execution speed\n"
            "- optimize repository access"
        )

    # ------------------------------------------------------
    # Debugging
    # ------------------------------------------------------
    if (
        "exception" in lower
        or "null reference" in lower
        or "error" in lower
        or "stacktrace" in lower
    ):

        sections.append(
            "Debug issue:\n"
            "- null reference exception\n"
            "- repository/service layer failure"
        )

    # ------------------------------------------------------
    # AI features
    # ------------------------------------------------------
    ai_features = []

    if (
        "predict" in lower
        or "prediction" in lower
    ):
        ai_features.append("forecasts")

    if (
        "recommend" in lower
        or "recommendation" in lower
    ):
        ai_features.append("advice")

    if (
        "summary" in lower
        or "summaries" in lower
    ):
        ai_features.append("summaries")

    if (
        "reason" in lower
        or "reasoning" in lower
    ):
        ai_features.append("reasoning")

    if ai_features:

        sections.append(
            "AI:\n"
            + "\n".join(
                f"- {x}"
                for x in sorted(set(ai_features))
            )
        )

    # ------------------------------------------------------
    # Optimizations
    # ------------------------------------------------------
    opts = []

    if "cache" in lower:
        opts.append("response caching")

    if "token" in lower:
        opts.append("token optimization")

    if "intent" in lower:
        opts.append("intent classification")

    if "filter" in lower:
        opts.append("request filtering")

    if opts:

        sections.append(
            "Optimizations:\n"
            + "\n".join(
                f"- {x}"
                for x in sorted(set(opts))
            )
        )

    # ------------------------------------------------------
    # Goals
    # ------------------------------------------------------
    goals = []

    if "cost" in lower:
        goals.append("reduce API cost")

    if "token" in lower:
        goals.append("reduce token usage")

    if (
        "response" in lower
        or "latency" in lower
    ):
        goals.append("reduce response time")

    if (
        "burden" in lower
        or "load" in lower
    ):
        goals.append("reduce AI load")

    if goals:

        sections.append(
            "Goals:\n"
            + "\n".join(
                f"- {x}"
                for x in sorted(set(goals))
            )
        )

    # ------------------------------------------------------
    # Fallback
    # ------------------------------------------------------
    if not sections:
        return text

    return "\n\n".join(sections)


# ==========================================================
# Main condenser
# ==========================================================
def condense_local(
    text: str,
    *,
    level: str = "balanced",
    compress_logs: bool = False,
):

    if _should_skip(text):

        return CondenseResult(
            original=text,
            condensed=text,
            mode=level,
            notes=["skipped trivial prompt"],
        )

    notes = []

    protected, vault = _protect_segments(text)

    work = protected

    # ------------------------------------------------------
    # Replacements
    # ------------------------------------------------------
    for pattern, repl in _REPLACEMENTS.items():

        work = re.sub(
            pattern,
            repl,
            work,
            flags=re.IGNORECASE,
        )

    # ------------------------------------------------------
    # Remove filler sentences
    # ------------------------------------------------------
    for pattern in _FILLER_SENTENCES:

        work = re.sub(
            pattern,
            " ",
            work,
            flags=re.IGNORECASE,
        )

    # ------------------------------------------------------
    # Remove filler phrases
    # ------------------------------------------------------
    for pattern in _FILLER_PHRASES:

        work = re.sub(
            pattern,
            " ",
            work,
            flags=re.IGNORECASE,
        )

    # ------------------------------------------------------
    # Log compression
    # ------------------------------------------------------
    if compress_logs:

        log_result = compress_log_block(work)

        if log_result.changed:

            work = log_result.text

            notes.append(
                f"log compression saved "
                f"{log_result.lines_before - log_result.lines_after} lines"
            )

    # ------------------------------------------------------
    # Cleanup spacing
    # ------------------------------------------------------
    work = re.sub(
        r"[ \t]+",
        " ",
        work,
    )

    work = re.sub(
        r"\n{3,}",
        "\n\n",
        work,
    )

    # ------------------------------------------------------
    # Semantic compression
    # ------------------------------------------------------
    # Skip the semantic template pass when the caller is in log-compression
    # mode -- they're sending raw logs and want exact (templated) collapse,
    # not domain-specific rewrites.
    if level == "balanced" and not compress_logs:

        work = _semantic_compress(work)

        notes.append(
            "semantic compression enabled"
        )

    # ------------------------------------------------------
    # Restore code blocks
    # ------------------------------------------------------
    work = _restore_segments(
        work,
        vault,
    )

    # ------------------------------------------------------
    # Final cleanup
    # ------------------------------------------------------
    work = work.strip()

    return CondenseResult(
        original=text,
        condensed=work,
        mode=level,
        notes=notes,
    )
