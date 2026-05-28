
"""
Advanced log compression engine.

Optimized for:
- AI prompt reduction
- debugging prompts
- stacktraces
- backend logs
- CI/CD logs
- API dumps

Features:
- duplicate collapse
- semantic dedupe
- stacktrace grouping
- head/tail preservation
- aggressive INFO compression
- ERROR preservation
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ==========================================================
# Log detection
# ==========================================================
_LOG_HINTS = re.compile(
    r"""^\s*(
        \d{4}-\d{2}-\d{2}
      | \d{2}:\d{2}:\d{2}
      | \[(DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)\]
      | (DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)[:\s]
      | \s*(File|at)\s
      | Traceback\s
    )""",
    re.IGNORECASE | re.VERBOSE,
)


IMPORTANT_PATTERNS = [
    "ERROR",
    "FATAL",
    "EXCEPTION",
    "Traceback",
]


# ==========================================================
# Result
# ==========================================================
@dataclass
class LogCompressResult:
    text: str
    lines_before: int
    lines_after: int
    changed: bool


# ==========================================================
# Detect log blocks
# ==========================================================
def _looks_like_log_block(
    block: str,
    min_lines: int = 3,
):

    lines = block.splitlines()

    if len(lines) < min_lines:
        return False

    hits = sum(
        1
        for ln in lines
        if _LOG_HINTS.search(ln)
    )

    return hits >= max(
        2,
        len(lines) // 3,
    )


# ==========================================================
# Normalize lines
# ==========================================================
def _normalize_for_dup(
    line: str,
):

    s = line

    s = re.sub(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?",
        "<TS>",
        s,
    )

    s = re.sub(
        r"\b\d{2}:\d{2}:\d{2}(\.\d+)?\b",
        "<TS>",
        s,
    )

    s = re.sub(
        r"0x[0-9a-fA-F]+",
        "<ADDR>",
        s,
    )

    s = re.sub(
        r"\b[0-9a-fA-F]{8,}\b",
        "<HEX>",
        s,
    )

    s = re.sub(
        r"\b\d+\b",
        "<N>",
        s,
    )

    return s.strip()


# ==========================================================
# Important line detection
# ==========================================================
def _is_important(
    line: str,
):

    upper = line.upper()

    return any(
        p in upper
        for p in IMPORTANT_PATTERNS
    )


# ==========================================================
# Compress log block
# ==========================================================
def compress_log_block(
    block: str,
    *,
    keep_head: int = 6,
    keep_tail: int = 8,
):

    lines = block.splitlines()

    before = len(lines)

    if not _looks_like_log_block(block):

        return LogCompressResult(
            block,
            before,
            before,
            changed=False,
        )

    collapsed = []

    run_key = None
    run_count = 0
    run_first = ""

    # ------------------------------------------------------
    # Flush repeated runs
    # ------------------------------------------------------
    def flush():

        nonlocal run_count
        nonlocal run_first

        if run_count == 1:

            collapsed.append(run_first)

        elif run_count > 1:

            display = _normalize_for_dup(
                run_first
            )

            collapsed.append(
                f"{display} (x{run_count})"
            )

        run_count = 0

    # ------------------------------------------------------
    # Main compression loop
    # ------------------------------------------------------
    for ln in lines:

        key = _normalize_for_dup(ln)

        # Important lines are preserved
        if _is_important(ln):

            flush()

            collapsed.append(ln)

            run_key = None
            run_count = 0

            continue

        if key and key == run_key:

            run_count += 1

        else:

            flush()

            run_key = key
            run_first = ln
            run_count = 1

    flush()

    # ------------------------------------------------------
    # Stacktrace grouping
    # ------------------------------------------------------
    stack_lines = []

    final_output = []

    for line in collapsed:

        stripped = line.strip()

        if (
            stripped.startswith("at ")
            or stripped.startswith("File ")
        ):

            stack_lines.append(stripped)

        else:

            if stack_lines:

                unique = list(
                    dict.fromkeys(stack_lines)
                )

                final_output.append(
                    "Stacktrace:"
                )

                for s in unique[:6]:
                    final_output.append(
                        f"  {s}"
                    )

                if len(unique) > 6:
                    final_output.append(
                        f"  ... ({len(unique)-6} more frames)"
                    )

                stack_lines.clear()

            final_output.append(line)

    if stack_lines:

        unique = list(
            dict.fromkeys(stack_lines)
        )

        final_output.append(
            "Stacktrace:"
        )

        for s in unique[:6]:
            final_output.append(
                f"  {s}"
            )

    collapsed = final_output

    # ------------------------------------------------------
    # Head/tail preservation
    # ------------------------------------------------------
    if len(collapsed) > keep_head + keep_tail + 3:

        head = collapsed[:keep_head]

        tail = collapsed[-keep_tail:]

        omitted = (
            len(collapsed)
            - keep_head
            - keep_tail
        )

        middle = [
            f"... ({omitted} log lines omitted)"
        ]

        collapsed = (
            head
            + middle
            + tail
        )

    result = "\n".join(collapsed)

    after = len(collapsed)

    return LogCompressResult(
        result,
        before,
        after,
        changed=(after < before),
    )
