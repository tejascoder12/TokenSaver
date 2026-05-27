"""
Persistent stats store.

Everything the dashboard needs lives in a single JSON file at
~/.tokensaver/stats.json . Each condense run appends one record.
Dead simple, human-readable, easy to back up or wipe.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _data_dir() -> str:
    base = os.environ.get("TOKENSAVER_HOME") or os.path.join(
        os.path.expanduser("~"), ".tokensaver"
    )
    os.makedirs(base, exist_ok=True)
    return base


def stats_path() -> str:
    return os.path.join(_data_dir(), "stats.json")


@dataclass
class Record:
    ts: float                      # unix time of the run
    command: str                   # the subcommand used, e.g. "condense"
    mode: str                      # "local" or "ai"
    input_tokens: int              # tokens of the ORIGINAL prompt
    output_tokens: int             # tokens of the CONDENSED prompt
    tokens_saved: int              # input - output
    exec_ms: float                 # how long the run took
    cost_saved: float              # estimated USD saved
    label: str = ""                # optional user tag


@dataclass
class Store:
    created: float = field(default_factory=time.time)
    records: list = field(default_factory=list)

    @classmethod
    def load(cls) -> "Store":
        path = stats_path()
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            store = cls(created=raw.get("created", time.time()))
            store.records = [Record(**r) for r in raw.get("records", [])]
            return store
        except Exception:
            # Corrupt file: don't crash the user's workflow, start fresh
            # but keep the broken file aside for inspection.
            try:
                os.rename(path, path + ".corrupt")
            except OSError:
                pass
            return cls()

    def save(self) -> None:
        path = stats_path()
        payload = {
            "created": self.created,
            "records": [asdict(r) for r in self.records],
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)  # atomic write

    def add(self, rec: Record) -> None:
        self.records.append(rec)
        self.save()

    # ----- aggregates used by the dashboard -----------------------------

    def total_commands(self) -> int:
        return len(self.records)

    def total_input(self) -> int:
        return sum(r.input_tokens for r in self.records)

    def total_output(self) -> int:
        return sum(r.output_tokens for r in self.records)

    def total_saved(self) -> int:
        return sum(r.tokens_saved for r in self.records)

    def total_exec_ms(self) -> float:
        return sum(r.exec_ms for r in self.records)

    def total_cost_saved(self) -> float:
        return sum(r.cost_saved for r in self.records)

    def efficiency(self) -> float:
        """Average % of input tokens removed. 0..100."""
        ti = self.total_input()
        if ti == 0:
            return 0.0
        return (self.total_saved() / ti) * 100.0

    def avg_overhead_ms(self) -> float:
        if not self.records:
            return 0.0
        return self.total_exec_ms() / len(self.records)

    def command_breakdown(self) -> dict:
        out: dict[str, int] = {}
        for r in self.records:
            out[r.command] = out.get(r.command, 0) + 1
        return out

    def tracking_since(self) -> str:
        dt = datetime.fromtimestamp(self.created, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
