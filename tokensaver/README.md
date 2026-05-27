# tokensaver

**Condense your AI prompts before you send them — and watch how much you save.**

`tokensaver` strips the filler and padding out of the text you send to an AI
(Claude, Claude Code, ChatGPT, anything), so you spend fewer tokens for the same
result. Useful when you're on a fixed plan and want every dollar to count.

It works two ways:

- **CLI** — pipe a prompt through it manually before sending.
- **Proxy library** — drop it into your Python code and prompts get condensed
  automatically before they hit the AI's API.

Both feed the same dashboard, so `tokensaver stats` shows everything you've saved.

Condensing is **100% local** — pure regex/heuristics, no network calls, no API
keys, no extra dependencies.

```
  ============================================================
  TOKENSAVER  -  AI CONTEXT CONDENSER  ::  DASHBOARD
  ============================================================

  Tracking since                              2026-05-25 18:34
  Total commands run                                        42
  ------------------------------------------------------------
  Input tokens (original)                               18,930
  Output tokens (condensed)                             11,205
  Tokens saved                                           7,725
  ------------------------------------------------------------
  Total exec time                                       128 ms
  Avg overhead / command                                  3 ms
  ------------------------------------------------------------
  Efficiency meter
    [############------------------]  40.8%
  ------------------------------------------------------------
  Estimated cost saved                                 $0.0231
  ------------------------------------------------------------
  Commands used
    condense                                               x30
    proxy.messages                                         x12
  ============================================================
```

## Install

```bash
pip install tokensaver
```

For accurate token counting (recommended):

```bash
pip install "tokensaver[accurate]"
```

Without `tiktoken`, token counts fall back to a chars/4 estimate — still useful,
just less precise.

## 1. CLI — manual use

Pipe your prompt through `condense`, then send the result to your AI:

```bash
echo "I would really like you to please help me refactor this code" | tokensaver condense
```

The condensed prompt prints to **stdout** (pipe or copy it). A short summary
prints to **stderr** so it never pollutes piped output:

```
tokensaver: 56 -> 15 tokens | saved 41 (73.2%) | ~$0.00012 | 2 ms [local]
```

### Clipboard one-liners

```bash
# macOS
pbpaste | tokensaver condense | pbcopy

# Linux
xclip -o | tokensaver condense | xclip -sel clip
```

### Shell helper

Add to `~/.bashrc` or `~/.zshrc`:

```bash
ask() { echo "$*" | tokensaver condense; }
```

Then `ask please help me debug this loop` prints the condensed version.

## 2. Proxy library — automatic use

If you call an AI from Python code, the proxy condenses prompts for you. No
manual piping.

### Wrap your client

`ProxyClient` is a transparent wrapper. Any call with a `messages=` argument
gets its user prompts condensed before being forwarded to the real client:

```python
from tokensaver import ProxyClient
import anthropic

client = ProxyClient(anthropic.Anthropic())   # wrap your real client

client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "please kindly help me ..."}],
)
# the prompt was condensed first; savings recorded to the dashboard
```

It works with the OpenAI SDK shape too (`client.chat.completions.create`).
The proxy never makes a network call itself — it only rewrites the arguments
and hands them to the client you gave it.

### Or condense manually in code

```python
from tokensaver import condense_text, condense_messages

text, stats = condense_text("please could you help me out, thank you!")
print(text, f"saved {stats.tokens_saved} tokens ({stats.percent_saved:.0f}%)")

messages, stats = condense_messages([
    {"role": "system", "content": "You are helpful."},   # left untouched
    {"role": "user",   "content": "I was wondering if ..."},  # condensed
])
```

By default only `user` messages are condensed — system prompts and prior
assistant turns are preserved. Pass `roles=("user", "system")` to change that.

## Saving levels

Every condense operation takes a `level`, and **both levels are lossless** --
they never change what your prompt means:

| Level | What it does |
|---|---|
| `safe` | Removes filler/padding & redundant whitespace |
| `balanced` *(default)* | Same as safe; reserved for future lossless heuristics |

Pasted logs, code blocks, quotes, paths and numbers are **kept exactly as-is**.
Repetitive-log compression exists but is **opt-in only** -- pass
`--compress-logs` (CLI) or `compress_logs=True` (library) if you want it.

## Where the real savings are: history trimming

Squeezing one prompt saves a little. The big cost in a long chat is the
**history** -- every request re-sends every earlier turn. By message 30 you
pay for messages 1-29 every single time.

`tokensaver trim` shrinks that, and it **always asks first**:

```
$ tokensaver trim conversation.json

History trim preview:
  turns total           : 29
  kept verbatim         : 5 (system + recent)
  older turns condensed : 24 (lossless -- none dropped)
  tokens                : 275 -> 197  (save 78, 28.4%)

Apply this trim and overwrite the file? [y/N]
```

- The system prompt and the most recent turns are **always kept verbatim**.
- Older turns are only **condensed** (filler removal) -- never dropped, never
  summarized. The trim is fully lossless.
- Nothing is written until you confirm. `--yes` skips the prompt;
  `--keep-recent N` sets how many recent turns to keep untouched.

`conversation.json` is just a JSON list of `{"role": ..., "content": ...}`
message dicts.

### In code

`trim_history()` returns a **preview**, not a finished list. You must call
`.apply()` to confirm -- so trimming can never happen silently:

```python
from tokensaver import trim_history

preview = trim_history(messages, keep_recent=6)
print(preview.describe())
if user_says_yes:
    trimmed = preview.apply()
```

The proxy enforces the same gate -- history trimming needs a `confirm_trim`
callback, or it is previewed and skipped:

```python
client = ProxyClient(
    anthropic.Anthropic(),
    trim_history_turns=6,
    confirm_trim=lambda preview: input(preview.describe() + "\nOK? ") == "y",
)
```

Without `confirm_trim`, the proxy condenses individual prompts but leaves
history fully intact.

## Commands

| Command | What it does |
|---|---|
| `tokensaver condense` | Read stdin, print a condensed prompt, record the run |
| `tokensaver trim FILE` | Trim a saved conversation's history (asks first) |
| `tokensaver stats` | Show the savings dashboard |
| `tokensaver reset` | Wipe all tracked history |
| `tokensaver hook` | Print integration tips for Claude Code & others |

`condense` accepts `--label TAG` to tag a run so you can recognize it later.

## How condensing works

It's **conservative on purpose**. It:

- removes politeness padding ("please", "kindly", "thank you so much")
- drops whole filler sentences ("I was wondering if...")
- swaps verbose phrases for short ones ("in order to" → "to")
- collapses redundant whitespace

It **never** touches code blocks, inline code, quoted strings, file paths, or
numbers. Repetitive-log compression is available but **off by default** — those are vaulted out before processing and restored afterward. If a
prompt is already terse, it's left mostly alone. That's correct behavior.

## Using it with Claude Code

`tokensaver` condenses *the text you send*. Run your prompt through the CLI,
then paste the result into Claude Code. Run `tokensaver hook` for copy-paste
snippets for every OS.

## Where your data lives

A single JSON file at `~/.tokensaver/stats.json`. Human-readable, easy to back
up, and `tokensaver reset` clears it. Set `TOKENSAVER_HOME` to change the
location.

## Notes on cost estimates

The dollar figures are **estimates** based on rough public list prices, meant to
show relative savings — not to match your bill exactly. Edit the pricing in
`tokensaver/tokens.py` if your plan differs.

## License

MIT — see [LICENSE](LICENSE).
