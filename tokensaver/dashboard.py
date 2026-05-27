"""
Dashboard rendering.

Pure-stdlib ANSI output. No external deps so it stays trivial to install.
Colors auto-disable when stdout isn't a TTY or NO_COLOR is set.
"""

from __future__ import annotations

import os
import sys

from .store import Store

_USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


DIM = lambda s: _c("2", s)
BOLD = lambda s: _c("1", s)
GREEN = lambda s: _c("32", s)
CYAN = lambda s: _c("36", s)
YELLOW = lambda s: _c("33", s)
MAGENTA = lambda s: _c("35", s)

_W = 60  # inner content width


def _line(left: str, right: str = "") -> str:
    # account for invisible ANSI codes when padding
    visible = len(_strip(left)) + len(_strip(right))
    pad = max(1, _W - visible)
    return f"  {left}{' ' * pad}{right}  "


def _strip(s: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _rule() -> str:
    return "  " + DIM("-" * _W) + "  "


def _meter(pct: float, width: int = 30) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round((pct / 100.0) * width))
    bar = "#" * filled + "-" * (width - filled)
    if pct >= 50:
        bar = GREEN(bar)
    elif pct >= 20:
        bar = YELLOW(bar)
    else:
        bar = MAGENTA(bar)
    return f"[{bar}] {pct:5.1f}%"


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_dur(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.2f} s"


def render_dashboard(store: Store) -> str:
    lines: list[str] = []
    top = "  " + BOLD(CYAN("+" + "=" * _W + "+")).replace("+", "")
    lines.append("")
    lines.append("  " + CYAN("=" * _W))
    title = BOLD("  TOKENSAVER  -  AI CONTEXT CONDENSER  ::  DASHBOARD")
    lines.append(title)
    lines.append("  " + CYAN("=" * _W))
    lines.append("")

    eff = store.efficiency()
    saved_tok = store.total_saved()
    saved_usd = store.total_cost_saved()

    lines.append(_line(DIM("Tracking since"), BOLD(store.tracking_since())))
    lines.append(_line(DIM("Total commands run"),
                       BOLD(_fmt_int(store.total_commands()))))
    lines.append(_rule())

    lines.append(_line(DIM("Input tokens (original)"),
                       _fmt_int(store.total_input())))
    lines.append(_line(DIM("Output tokens (condensed)"),
                       _fmt_int(store.total_output())))
    lines.append(_line(BOLD("Tokens saved"),
                       GREEN(BOLD(_fmt_int(saved_tok)))))
    lines.append(_rule())

    lines.append(_line(DIM("Total exec time"),
                       _fmt_dur(store.total_exec_ms())))
    lines.append(_line(DIM("Avg overhead / command"),
                       _fmt_dur(store.avg_overhead_ms())))
    lines.append(_rule())

    lines.append(_line(BOLD("Efficiency meter")))
    lines.append(_line("  " + _meter(eff)))
    lines.append(_rule())

    lines.append(_line(BOLD("Estimated cost saved"),
                       GREEN(BOLD(f"${saved_usd:,.4f}"))))
    lines.append(_rule())

    # command breakdown
    bd = store.command_breakdown()
    lines.append(_line(BOLD("Commands used")))
    if bd:
        for cmd, cnt in sorted(bd.items(), key=lambda x: -x[1]):
            lines.append(_line("  " + CYAN(cmd), DIM(f"x{cnt}")))
    else:
        lines.append(_line("  " + DIM("(none yet)")))

    lines.append("")
    lines.append("  " + CYAN("=" * _W))

    if store.total_commands() == 0:
        lines.append("")
        lines.append("  " + DIM("No runs yet. Try:"))
        lines.append("  " + YELLOW('  echo "your long prompt" | tokensaver condense'))

    lines.append("")
    return "\n".join(lines)
