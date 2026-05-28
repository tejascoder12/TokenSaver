
"""
Persistent stats store.

Stores:
- token savings
- execution metrics
- compression analytics
- cost estimates
- dashboard statistics

Data location:
~/.tokensaver/stats.json
"""

from __future__ import annotations

import json
import os
import time

from collections import defaultdict
from dataclasses import (
    dataclass,
    field,
    asdict,
)

from datetime import (
    datetime,
    timezone,
)


# ==========================================================
# Data directory
# ==========================================================
def _data_dir() -> str:

    base = (
        os.environ.get("TOKENSAVER_HOME")
        or os.path.join(
            os.path.expanduser("~"),
            ".tokensaver",
        )
    )

    os.makedirs(
        base,
        exist_ok=True,
    )

    return base


# ==========================================================
# Stats path
# ==========================================================
def stats_path() -> str:

    return os.path.join(
        _data_dir(),
        "stats.json",
    )


# ==========================================================
# Record
# ==========================================================
@dataclass
class Record:

    ts: float

    command: str

    mode: str

    input_tokens: int

    output_tokens: int

    tokens_saved: int

    exec_ms: float

    cost_saved: float

    label: str = ""


# ==========================================================
# Store
# ==========================================================
@dataclass
class Store:

    created: float = field(
        default_factory=time.time
    )

    records: list = field(
        default_factory=list
    )

    # ------------------------------------------------------
    # Load
    # ------------------------------------------------------
    @classmethod
    def load(cls) -> "Store":

        path = stats_path()

        if not os.path.exists(path):
            return cls()

        try:

            with open(
                path,
                "r",
                encoding="utf-8",
            ) as fh:

                raw = json.load(fh)

            store = cls(
                created=raw.get(
                    "created",
                    time.time(),
                )
            )

            store.records = [
                Record(**r)
                for r in raw.get(
                    "records",
                    [],
                )
            ]

            return store

        except Exception:

            try:
                os.rename(
                    path,
                    path + ".corrupt",
                )

            except OSError:
                pass

            return cls()

    # ------------------------------------------------------
    # Save
    # ------------------------------------------------------
    def save(self) -> None:

        path = stats_path()

        payload = {
            "created": self.created,
            "records": [
                asdict(r)
                for r in self.records
            ],
        }

        tmp = path + ".tmp"

        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as fh:

            json.dump(
                payload,
                fh,
                indent=2,
            )

        os.replace(
            tmp,
            path,
        )

    # ------------------------------------------------------
    # Add record
    # ------------------------------------------------------
    def add(
        self,
        rec: Record,
    ) -> None:

        self.records.append(rec)

        self.save()

    # ======================================================
    # Aggregates
    # ======================================================

    def total_commands(self) -> int:

        return len(self.records)

    def total_input(self) -> int:

        return sum(
            r.input_tokens
            for r in self.records
        )

    def total_output(self) -> int:

        return sum(
            r.output_tokens
            for r in self.records
        )

    def total_saved(self) -> int:

        return sum(
            r.tokens_saved
            for r in self.records
        )

    def total_exec_ms(self) -> float:

        return sum(
            r.exec_ms
            for r in self.records
        )

    def total_cost_saved(self) -> float:

        return sum(
            r.cost_saved
            for r in self.records
        )

    # ======================================================
    # Metrics
    # ======================================================

    def efficiency(self) -> float:

        ti = self.total_input()

        if ti == 0:
            return 0.0

        return (
            self.total_saved()
            / ti
            * 100.0
        )

    def avg_overhead_ms(self) -> float:

        if not self.records:
            return 0.0

        return (
            self.total_exec_ms()
            / len(self.records)
        )

    # ======================================================
    # Command breakdown
    # ======================================================

    def command_breakdown(self):

        out = defaultdict(int)

        for r in self.records:
            out[r.command] += 1

        return dict(out)

    # ======================================================
    # Top labels
    # ======================================================

    def top_labels(
        self,
        limit: int = 10,
    ):

        out = defaultdict(int)

        for r in self.records:

            if not r.label:
                continue

            out[r.label] += 1

        return sorted(
            out.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:limit]

    # ======================================================
    # Daily savings
    # ======================================================

    def daily_savings(self):

        out = defaultdict(int)

        for r in self.records:

            day = datetime.fromtimestamp(
                r.ts,
                tz=timezone.utc,
            ).strftime("%Y-%m-%d")

            out[day] += r.tokens_saved

        return dict(out)

    # ======================================================
    # Top token-saving runs
    # ======================================================

    def top_saving_runs(
        self,
        limit: int = 10,
    ):

        return sorted(
            self.records,
            key=lambda r: r.tokens_saved,
            reverse=True,
        )[:limit]

    # ======================================================
    # Average compression ratio
    # ======================================================

    def average_compression_ratio(self):

        if not self.records:
            return 0.0

        ratios = []

        for r in self.records:

            if r.input_tokens <= 0:
                continue

            ratio = (
                r.tokens_saved
                / r.input_tokens
            ) * 100.0

            ratios.append(ratio)

        if not ratios:
            return 0.0

        return sum(ratios) / len(ratios)

    # ======================================================
    # Tracking since
    # ======================================================

    def tracking_since(self) -> str:

        dt = datetime.fromtimestamp(
            self.created,
            tz=timezone.utc,
        ).astimezone()

        return dt.strftime(
            "%Y-%m-%d %H:%M"
        )

    # ======================================================
    # Reset stats
    # ======================================================

    def reset(self):

        self.records = []

        self.created = time.time()

        self.save()

    # ======================================================
    # Export
    # ======================================================

    def export_summary(self):

        return {
            "tracking_since": self.tracking_since(),
            "total_commands": self.total_commands(),
            "total_input_tokens": self.total_input(),
            "total_output_tokens": self.total_output(),
            "total_saved_tokens": self.total_saved(),
            "total_cost_saved": round(
                self.total_cost_saved(),
                4,
            ),
            "avg_compression_ratio": round(
                self.average_compression_ratio(),
                2,
            ),
            "avg_exec_ms": round(
                self.avg_overhead_ms(),
                2,
            ),
        }
