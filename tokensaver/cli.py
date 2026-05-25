"""
tokensaver CLI.

Usage:
  tokensaver condense [--label TAG]   read stdin, print condensed prompt
  tokensaver trim FILE                trim a saved conversation (confirmed)
  tokensaver stats                    show the dashboard
  tokensaver reset                    wipe history
  tokensaver hook                     print Claude Code integration help

Examples:
  echo "please could you kindly help me ..." | tokensaver condense
  pbpaste | tokensaver condense | pbcopy
  cat prompt.txt | tokensaver condense --label refactor
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from .condenser import condense_local
from .tokens import count_tokens, estimate_cost, encoder_is_accurate, DEFAULT_PRICING
from .store import Store, Record
from .dashboard import render_dashboard


def _read_stdin() -> str:
    if sys.stdin.isatty():
        sys.stderr.write(
            "tokensaver: no input. Pipe text in, e.g.\n"
            '  echo "your prompt" | tokensaver condense\n'
        )
        sys.exit(2)
    return sys.stdin.read()


def cmd_condense(args) -> int:
    text = _read_stdin()
    start = time.perf_counter()

    result = condense_local(
        text, level=args.level, compress_logs=args.compress_logs)

    exec_ms = (time.perf_counter() - start) * 1000.0

    in_tok = count_tokens(result.original)
    out_tok = count_tokens(result.condensed)
    saved = max(0, in_tok - out_tok)
    cost_saved = estimate_cost(saved, "input")

    # The condensed prompt goes to stdout so it can be piped/copied.
    sys.stdout.write(result.condensed)
    if not result.condensed.endswith("\n"):
        sys.stdout.write("\n")

    # Record it.
    store = Store.load()
    store.add(Record(
        ts=time.time(),
        command="condense",
        mode=result.mode,
        input_tokens=in_tok,
        output_tokens=out_tok,
        tokens_saved=saved,
        exec_ms=exec_ms,
        cost_saved=cost_saved,
        label=args.label or "",
    ))

    # Human-readable summary on stderr so it doesn't pollute piped output.
    pct = (saved / in_tok * 100.0) if in_tok else 0.0
    acc = "" if encoder_is_accurate() else " (estimated)"
    sys.stderr.write(
        f"\ntokensaver: {in_tok} -> {out_tok} tokens"
        f" | saved {saved} ({pct:.1f}%){acc}"
        f" | ~${cost_saved:.5f} | {exec_ms:.0f} ms [{result.mode}]\n"
    )
    return 0


def cmd_stats(args) -> int:
    store = Store.load()
    sys.stdout.write(render_dashboard(store))
    return 0


def cmd_trim(args) -> int:
    """Trim a saved conversation's history. Always confirms before writing."""
    import json
    from .history import trim_history
    from .store import Store as _Store, Record as _Record

    if not os.path.exists(args.file):
        sys.stderr.write(f"tokensaver: file not found: {args.file}\n")
        return 2
    try:
        with open(args.file, "r", encoding="utf-8") as fh:
            messages = json.load(fh)
        if not isinstance(messages, list):
            raise ValueError("JSON root must be a list of message dicts")
    except Exception as exc:
        sys.stderr.write(f"tokensaver: could not read conversation: {exc}\n")
        return 2

    start = time.perf_counter()
    preview = trim_history(messages, keep_recent=args.keep_recent)
    exec_ms = (time.perf_counter() - start) * 1000.0

    # Show the preview -- this is the confirmation gate.
    sys.stdout.write("\n" + preview.describe() + "\n\n")

    if not preview.has_changes:
        return 0

    # Confirm before writing anything.
    if not args.yes:
        try:
            answer = input("Apply this trim and overwrite the file? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            sys.stdout.write("tokensaver: trim cancelled, file unchanged.\n")
            return 0

    trimmed = preview.apply()
    with open(args.file, "w", encoding="utf-8") as fh:
        json.dump(trimmed, fh, indent=2)

    # Record it on the dashboard.
    store = _Store.load()
    store.add(_Record(
        ts=time.time(),
        command="trim",
        mode="balanced",
        input_tokens=preview.tokens_before,
        output_tokens=preview.tokens_after,
        tokens_saved=preview.tokens_saved,
        exec_ms=exec_ms,
        cost_saved=estimate_cost(preview.tokens_saved, "input"),
        label=os.path.basename(args.file),
    ))
    sys.stdout.write(
        f"tokensaver: trimmed and saved. Saved {preview.tokens_saved} tokens.\n")
    return 0


def cmd_reset(args) -> int:
    from .store import stats_path

    path = stats_path()
    if os.path.exists(path):
        os.remove(path)
        sys.stdout.write("tokensaver: history cleared.\n")
    else:
        sys.stdout.write("tokensaver: nothing to clear.\n")
    return 0


def cmd_hook(args) -> int:
    sys.stdout.write(_HOOK_HELP)
    return 0


_HOOK_HELP = """\
Using tokensaver with Claude Code (and other terminal AIs)
==========================================================

tokensaver condenses the *text you send*. Pipe your prompt through it,
then hand the condensed result to the AI.

Saving levels (--level):
  safe      filler/padding removal. Lossless.
  balanced  default. Also lossless. (Log compression is opt-in: --compress-logs)

All condensing is lossless -- it never changes the meaning of your prompt.
Pasted logs/code blocks are kept exactly as-is unless you pass --compress-logs.

1. Quick manual use (any AI, any OS):

     echo "your long prompt" | tokensaver condense
     # copy the printed result, paste into Claude Code / ChatGPT

2. Clipboard one-liner:

     macOS:   pbpaste | tokensaver condense | pbcopy
     Linux:   xclip -o | tokensaver condense | xclip -sel clip
     Windows: powershell -c "Get-Clipboard | tokensaver condense | Set-Clipboard"

3. Shell function (add to ~/.bashrc or ~/.zshrc):

     ask() { echo "$*" | tokensaver condense; }
     # then:  ask please could you refactor this function for me

4. From a file (great for pasted logs):

     cat error_dump.txt | tokensaver condense --label debug

For long conversations, the biggest savings come from history trimming.
The history is what really eats tokens -- every request re-sends every old
turn. Trim a saved conversation (a JSON list of {role, content} messages):

     tokensaver trim conversation.json

It always shows a preview and asks before changing anything. Old turns are
only condensed losslessly -- never dropped or summarized.

Check what you've saved any time with:

     tokensaver stats
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokensaver",
        description="Condense prompts before sending them to an AI, and "
                    "track how many tokens (and dollars) you save.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("condense", help="condense text read from stdin")
    c.add_argument("--level", choices=["safe", "balanced"],
                   default="balanced",
                   help="safe or balanced (default). Both are lossless.")
    c.add_argument("--compress-logs", action="store_true",
                   help="opt in to collapsing repetitive pasted log lines "
                        "(off by default -- pasted blocks kept as-is)")
    c.add_argument("--label", default="", help="optional tag for this run")
    c.set_defaults(func=cmd_condense)

    t = sub.add_parser("trim",
                       help="trim a saved conversation's history (JSON file)")
    t.add_argument("file", help="path to a JSON file: a list of "
                                "{role, content} message dicts")
    t.add_argument("--keep-recent", type=int, default=6,
                   help="recent turns to keep verbatim (default: 6)")
    t.add_argument("--yes", action="store_true",
                   help="skip the confirmation prompt")
    t.set_defaults(func=cmd_trim)

    # "stats" plus "status" alias -- both show the dashboard.
    s = sub.add_parser("stats", aliases=["status"],
                       help="show the savings dashboard")
    s.set_defaults(func=cmd_stats)

    r = sub.add_parser("reset", help="clear all tracked history")
    r.set_defaults(func=cmd_reset)

    h = sub.add_parser("hook", help="how to wire this into Claude Code etc.")
    h.set_defaults(func=cmd_hook)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


# Short-form entry point: `tokensave`.
#   prompt | tokensave           -> condense (default)
#   tokensave status             -> dashboard
#   tokensave <anything-else>    -> delegate to the full tokensaver parser
def main_short(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # No args + piped input -> condense by default.
    if not argv and not sys.stdin.isatty():
        argv = ["condense"]

    # `status` -> dashboard. (Also accept `stats` for symmetry.)
    if argv and argv[0] in ("status", "stats"):
        argv = ["stats", *argv[1:]]

    # No args, no pipe -> show the dashboard so the user sees something useful.
    if not argv:
        argv = ["stats"]

    return main(argv)


if __name__ == "__main__":
    sys.exit(main())
