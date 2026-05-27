"""
Log / dump compression.

Pasted logs, stack traces and error dumps are some of the biggest token
sinks in a prompt. This module collapses them WITHOUT changing what they
mean: it removes exact duplicate lines, collapses runs of near-identical
lines, and trims the quiet middle of very long stack traces while always
keeping the start (where the error type is) and the end (where the actual
failure is).

It is conservative: if a block does not clearly look like log/dump output,
it is left completely untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# A line "looks like a log line" if it starts with a timestamp, a level
# tag, or a stack-frame marker.
_LOG_HINTS = re.compile(
    r"""^\s*(
        \d{4}-\d{2}-\d{2}            # 2026-05-25 date
      | \d{2}:\d{2}:\d{2}           # 18:42:01 time
      | \[(DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)\]
      | (DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)[:\s]
      | \s*(File|at)\s              # stack frame  "  File ..."  / "  at ..."
      | Traceback\s
    )""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class LogCompressResult:
    text: str
    lines_before: int
    lines_after: int
    changed: bool


def _looks_like_log_block(block: str, min_lines: int = 8) -> bool:
    """Decide whether a block is log/dump output worth compressing."""
    lines = block.splitlines()
    if len(lines) < min_lines:
        return False
    hits = sum(1 for ln in lines if _LOG_HINTS.search(ln))
    # At least a third of the lines must look log-ish.
    return hits >= max(3, len(lines) // 3)


def _normalize_for_dup(line: str) -> str:
    """Strip the volatile parts of a log line (timestamps, hex addrs, ids)
    so that lines which differ only in those count as duplicates."""
    s = line
    s = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?", "<TS>", s)
    s = re.sub(r"\b\d{2}:\d{2}:\d{2}(\.\d+)?\b", "<TS>", s)
    s = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", s)
    s = re.sub(r"\b[0-9a-fA-F]{8,}\b", "<HEX>", s)
    s = re.sub(r"\b\d+\b", "<N>", s)
    return s.strip()


def compress_log_block(block: str, *, keep_head: int = 6, keep_tail: int = 8) -> LogCompressResult:
    """Compress one log/dump block. Returns original if it doesn't qualify."""
    lines = block.splitlines()
    before = len(lines)

    if not _looks_like_log_block(block):
        return LogCompressResult(block, before, before, changed=False)

    # Pass 1: collapse consecutive runs of lines that are identical once
    # their volatile parts are normalized.
    collapsed: list[str] = []
    run_key: str | None = None
    run_count = 0
    run_first = ""

    def flush():
        nonlocal run_count, run_first
        if run_count == 1:
            collapsed.append(run_first)
        elif run_count > 1:
            collapsed.append(run_first)
            collapsed.append(f"    ... ({run_count - 1} more similar lines)")
        run_count = 0

    for ln in lines:
        key = _normalize_for_dup(ln)
        if key and key == run_key:
            run_count += 1
        else:
            flush()
            run_key = key
            run_first = ln
            run_count = 1
    flush()

    # Pass 2: if it's still long, keep head + tail, summarize the middle.
    if len(collapsed) > keep_head + keep_tail + 2:
        head = collapsed[:keep_head]
        tail = collapsed[-keep_tail:]
        omitted = len(collapsed) - keep_head - keep_tail
        middle = [f"    ... ({omitted} log lines omitted -- head & tail kept) ..."]
        collapsed = head + middle + tail

    result = "\n".join(collapsed)
    after = len(collapsed)
    return LogCompressResult(result, before, after, changed=(after < before))
