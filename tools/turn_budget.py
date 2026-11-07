"""turn_budget.py — deadline discipline for agent turns.

The failure mode: an agent loop makes 40 tool calls, each "fast", and blows
past the runtime's hard timeout at call #41 — losing the ENTIRE turn's work.
The fix: a budget object the loop consults before every step. It knows the
total budget, elapsed, and whether a planned step still fits. When the budget
is tight, the agent *ships partial work with a status note* instead of dying
mid-sentence.

Zero dependencies. Python 3.10+.

Usage:
    from turn_budget import TurnBudget

    b = TurnBudget(total_s=280, reserve_s=20)   # 280s turn, keep 20s to write results

    for step in plan:
        if not b.can_afford(step.estimated_s):
            b.degrade("skipping optional steps")   # or ship partial
            break
        do(step)
    print(b.summary())   # {"elapsed": .., "remaining": .., "steps_run": ..}
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TurnBudget:
    total_s: float
    reserve_s: float = 15.0          # time reserved for writing out results
    start: float = field(default_factory=time.monotonic)
    steps_run: int = 0
    steps_skipped: int = 0
    degradations: list = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start

    @property
    def remaining(self) -> float:
        return self.total_s - self.elapsed

    @property
    def usable(self) -> float:
        # reserve is advisory: never let it alone make the whole turn unaffordable
        reserve = min(self.reserve_s, self.remaining * 0.5)
        return self.remaining - reserve

    def can_afford(self, step_s: float, safety: float = 1.3) -> bool:
        """Can we start a step estimated at step_s and still finish the turn?

        safety multiplies the estimate — step estimates are optimistic by
        construction (network), so 1.3x is the honest number.
        """
        return self.usable >= step_s * safety

    def degrade(self, note: str) -> None:
        self.degradations.append({"note": note, "at": round(self.elapsed, 1)})

    def skip(self) -> None:
        self.steps_skipped += 1

    def step(self) -> None:
        self.steps_run += 1

    def fraction_used(self) -> float:
        return min(1.0, self.elapsed / self.total_s)

    def summary(self) -> dict:
        return {
            "elapsed_s": round(self.elapsed, 1),
            "remaining_s": round(self.remaining, 1),
            "usable_s": round(self.usable, 1),
            "steps_run": self.steps_run,
            "steps_skipped": self.steps_skipped,
            "degradations": self.degradations,
            "status": ("healthy" if self.usable > self.total_s * 0.25 else
                       "tight" if self.usable > 0 else "EXHAUSTED"),
        }

    def status_note(self) -> str:
        """Paste this into your agent's output so partial work is honest."""
        if self.degradations:
            return (f"[partial: {self.steps_run} steps done, "
                    f"{self.steps_skipped} skipped, "
                    f"{self.elapsed:.0f}s elapsed — not a failure, budgeted]")
        return ""
