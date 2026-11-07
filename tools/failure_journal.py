"""failure_journal.py — structured failure logging that makes agents debuggable.

Agents fail in ways that vanish: a retry "fixed" it, a catch block swallowed
it, a silent truncation became a hallucination three steps later. Six months
of production agent work says: the teams that win are the ones that can
*replay* why a turn died. This module writes one JSONL line per failure with
the full causal chain (attempt log, budget state, context pressure at time of
failure), and gives you a `top_failures()` rollup so you fix the top cause
instead of the loudest one.

Zero dependencies. Python 3.10+.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FailureJournal:
    path: Path

    def __post_init__(self):
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, run_id: str, step: str, failure: dict,
               budget: dict | None = None, context: dict | None = None,
               tags: list | None = None) -> None:
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_id": run_id, "step": step, "failure": failure,
            "budget": budget, "context": context, "tags": tags or [],
        }
        with self.path.open("a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def record_call_result(self, run_id: str, step: str, result,
                           budget=None, context=None) -> bool:
        """Convenience: pass a resilient_call.CallResult; logs iff failed.
        Returns True if it was logged (i.e. it failed)."""
        if result.ok:
            return False
        self.record(run_id=run_id, step=step, failure=result.failure,
                    budget=budget.summary() if hasattr(budget, "summary") else budget,
                    context=context.summary() if hasattr(context, "summary") else context,
                    tags=[f"attempts:{result.attempts}"])
        return True

    def entries(self, last: int = 1000) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()[-last:]
        return [json.loads(l) for l in lines if l.strip()]

    def top_failures(self, n: int = 10) -> list[tuple[str, int]]:
        c = Counter(f"{e['failure'].get('kind','?')}@{e['step']}"
                    for e in self.entries())
        return c.most_common(n)

    def same_failure_count_today(self, kind: str, step: str) -> int:
        """The anti-spin signal: if you've hit THIS failure N times today,
        stop retrying it. (3 = hard stop.)"""
        today = time.strftime("%Y-%m-%d")
        return sum(1 for e in self.entries()
                   if e["ts"].startswith(today)
                   and e["failure"].get("kind") == kind and e["step"] == step)
