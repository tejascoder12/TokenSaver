"""
tokensaver CLI.

Two entry points:
  tokensaver  -- full command, all subcommands and flags
  tokensave   -- short form for everyday use:
                 * `tokensave`            interactive: type your prompt,
                                          finish with a blank line, result
                                          prints and is copied to clipboard
                 * `prompt | tokensave`   condense piped input
                 * `tokensave status`     show the savings dashboard

Full tokensaver subcommands:
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
import subprocess
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


def _copy_to_clipboard(text: str) -> bool:
    """Best-effort clipboard copy across platforms. Returns True on success."""
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text, text=True,
                           check=True, timeout=5,
                           encoding="utf-8", errors="replace")
            return True
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True,
                           check=True, timeout=5)
            return True
        for cmd in (["xclip", "-selection", "clipboard"],
                    ["wl-copy"],
                    ["xsel", "--clipboard", "--input"]):
            try:
                subprocess.run(cmd, input=text, text=True,
                               check=True, timeout=5)
                return True
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    except Exception:
        pass
    return False


def _read_clipboard() -> str | None:
    """Best-effort clipboard read. Returns None if no tool / empty."""
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                return r.stdout.rstrip("\r\n")
            return None
        if sys.platform == "darwin":
            r = subprocess.run(["pbpaste"], capture_output=True,
                               text=True, timeout=5)
            return r.stdout if r.returncode == 0 else None
        for cmd in (["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"],
                    ["wl-paste"]):
            try:
                r = subprocess.run(cmd, capture_output=True,
                                   text=True, timeout=5)
                if r.returncode == 0:
                    return r.stdout
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return None


def _read_interactive() -> str:
    """Read a prompt from the user line-by-line. Ends on blank line or EOF."""
    sys.stderr.write(
        "tokensave: type or paste your prompt below.\n"
        "  finish with an empty line (press Enter twice)\n"
        "  or Ctrl+Z then Enter on Windows / Ctrl+D on macOS+Linux.\n"
        "----------------------------------------------------------\n"
    )
    sys.stderr.flush()

    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        except KeyboardInterrupt:
            sys.stderr.write("\ntokensave: cancelled.\n")
            sys.exit(130)
        if line == "" and lines:
            # blank line after some content -> done
            break
        if line == "" and not lines:
            # leading blank line — ignore, wait for real content
            continue
        lines.append(line)
    return "\n".join(lines)


def cmd_condense(args) -> int:
    text = _read_stdin()
    return _run_condense(text, level=args.level,
                         compress_logs=args.compress_logs,
                         label=args.label or "",
                         auto_clip=False,
                         use_ml=getattr(args, "ml", False),
                         rate=getattr(args, "rate", 0.5))


def _run_condense(text: str, *, level: str, compress_logs: bool,
                  label: str, auto_clip: bool,
                  use_ml: bool = False, rate: float = 0.5) -> int:
    start = time.perf_counter()
    result = condense_local(text, level=level, compress_logs=compress_logs)

    final_text = result.condensed
    mode = result.mode
    ml_note = ""

    if use_ml:
        try:
            from .mlcompress import ml_compress, MLUnavailable
            ml_out = ml_compress(final_text, rate=rate)
            final_text = ml_out.compressed
            mode = f"{result.mode}+ml({rate})"
        except MLUnavailable as exc:
            sys.stderr.write(f"\ntokensave: {exc}\n")
            sys.stderr.write("falling back to heuristic-only output.\n")
        except Exception as exc:
            sys.stderr.write(
                f"\ntokensave: ML compression failed ({exc}). "
                "falling back to heuristic output.\n"
            )

    exec_ms = (time.perf_counter() - start) * 1000.0

    in_tok = count_tokens(text)
    out_tok = count_tokens(final_text)
    saved = max(0, in_tok - out_tok)
    cost_saved = estimate_cost(saved, "input")

    sys.stdout.write(final_text)
    if not final_text.endswith("\n"):
        sys.stdout.write("\n")

    clipped = _copy_to_clipboard(final_text) if auto_clip else False

    store = Store.load()
    store.add(Record(
        ts=time.time(),
        command="condense",
        mode=mode,
        input_tokens=in_tok,
        output_tokens=out_tok,
        tokens_saved=saved,
        exec_ms=exec_ms,
        cost_saved=cost_saved,
        label=label,
    ))

    pct = (saved / in_tok * 100.0) if in_tok else 0.0
    acc = "" if encoder_is_accurate() else " (estimated)"
    sys.stderr.write(
        f"\ntokensaver: {in_tok} -> {out_tok} tokens"
        f" | saved {saved} ({pct:.1f}%){acc}"
        f" | ~${cost_saved:.5f} | {exec_ms:.0f} ms [{mode}]{ml_note}\n"
    )
    if auto_clip:
        sys.stderr.write(
            "(copied to clipboard — Ctrl+V to paste)\n"
            if clipped else
            "(clipboard tool unavailable — output is above)\n"
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
    c.add_argument("--ml", action="store_true",
                   help="also run LLMLingua-2 ML compression on the result "
                        "(lossy; requires `pip install tokensaver[ml]`)")
    c.add_argument("--rate", type=float, default=0.5,
                   help="ML keep-ratio: 0.5 keeps ~half (default). "
                        "Smaller = more aggressive.")
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
#   tokensave                    -> interactive: type your prompt, auto-clip
#   tokensave -c                 -> read clipboard, condense, write clipboard
#   prompt | tokensave           -> condense piped input
#   tokensave --ml [--rate 0.5]  -> add ML compression (any mode)
#   tokensave status             -> dashboard
#   tokensave <anything-else>    -> delegate to the full tokensaver parser
def main_short(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Pull short-form flags out so they work alongside any input mode.
    use_clipboard = False
    for flag in ("-c", "--clip", "--clipboard"):
        while flag in argv:
            argv.remove(flag)
            use_clipboard = True

    use_ml = False
    rate = 0.5
    if "--ml" in argv:
        argv.remove("--ml")
        use_ml = True
    if "--rate" in argv:
        i = argv.index("--rate")
        if i + 1 < len(argv):
            try:
                rate = float(argv[i + 1])
            except ValueError:
                sys.stderr.write("tokensave: --rate needs a number, e.g. 0.5\n")
                return 2
            del argv[i:i + 2]

    # `status` -> dashboard. (Also accept `stats` for symmetry.)
    if argv and argv[0] in ("status", "stats"):
        return main(["stats", *argv[1:]])

    # Clipboard mode: read clipboard, condense, write back to clipboard.
    if use_clipboard and not argv:
        text = _read_clipboard()
        if text is None:
            sys.stderr.write(
                "tokensave: couldn't read the clipboard. "
                "Copy your prompt first, then run `tokensave -c`.\n"
            )
            return 2
        if not text.strip():
            sys.stderr.write("tokensave: clipboard is empty, nothing to do.\n")
            return 0
        sys.stderr.write(
            f"tokensave: read {len(text)} chars from clipboard.\n"
        )
        return _run_condense(text, level="balanced", compress_logs=False,
                             label="clipboard", auto_clip=True,
                             use_ml=use_ml, rate=rate)

    # Piped input -> condense the pipe.
    if not argv and not sys.stdin.isatty():
        text = sys.stdin.read()
        return _run_condense(text, level="balanced", compress_logs=False,
                             label="", auto_clip=False,
                             use_ml=use_ml, rate=rate)

    # No args + TTY -> interactive prompt mode.
    if not argv:
        text = _read_interactive()
        if not text.strip():
            sys.stderr.write("tokensave: empty input, nothing to do.\n")
            return 0
        return _run_condense(text, level="balanced", compress_logs=False,
                             label="interactive", auto_clip=True,
                             use_ml=use_ml, rate=rate)

    return main(argv)


if __name__ == "__main__":
    sys.exit(main())
