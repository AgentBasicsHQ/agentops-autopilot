"""context_pressure.py — know when your agent's context is about to die.

Context exhaustion fails two ways, both catastrophic: the API hard-errors
(token limit), or — worse — the agent silently forgets early instructions
and starts hallucinating. This module gives you the *leading indicator*:
a pressure reading you poll every loop iteration, with graduated actions
(summarize old tool results → drop oldest turns → force a state checkpoint)
before either failure mode.

Token math is heuristic (chars/4 for English, denser for code/CJK) — that's
the right tradeoff: you want a cheap, monotonic signal, not a tokenizer call
per iteration. Calibrate once per model with the calibrate() helper.

Zero dependencies. Python 3.10+.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# rough chars-per-token by content kind
_CPT = {"text": 4.0, "code": 3.2, "json": 2.8, "cjk": 1.6}


def estimate_tokens(content: str, kind: str = "auto") -> float:
    if kind == "auto":
        cjk = sum(1 for c in content if "\u4e00" <= c <= "\u9fff")
        if cjk / max(1, len(content)) > 0.15:
            kind = "cjk"
        elif any(line.lstrip().startswith(("{", "[", '"')) for line in content.splitlines()[:5]):
            kind = "json"
        elif any(ch in content for ch in ("def ", "function", "=>", "import ")):
            kind = "code"
        else:
            kind = "text"
    return len(content) / _CPT[kind]


@dataclass
class ContextPressure:
    model_window: int                  # e.g. 128_000
    system_overhead: int = 8_000       # system prompt + tools schema (calibrate!)
    messages: list = field(default_factory=list)   # (role, content, kind)
    calibrated: float = 1.0            # empirical correction from calibrate()

    def add(self, role: str, content: str, kind: str = "auto"):
        self.messages.append((role, content, kind))

    def tokens(self) -> float:
        t = self.system_overhead
        for _, content, kind in self.messages:
            t += estimate_tokens(content, kind)
        return t * self.calibrated

    @property
    def pressure(self) -> float:
        """0.0 = empty, 1.0 = window full. Act before 0.85."""
        return self.tokens() / self.model_window

    def action(self) -> str:
        p = self.pressure
        if p < 0.60:
            return "none"
        if p < 0.75:
            return "prune_old_tool_results"   # replace big tool outputs with 1-line summaries
        if p < 0.88:
            return "summarize_oldest_turns"   # fold oldest N turns into a state block
        if p < 0.95:
            return "checkpoint_and_restart"   # write state to files, start fresh session
        return "hard_stop_ship_partial"       # do not send this request; ship what exists

    def should_prune(self) -> bool:
        return self.pressure >= 0.60

    def prune_tool_results(self, keep_last: int = 4) -> int:
        """Replace all but the last `keep_last` tool outputs with stubs.
        Returns count pruned. This is the single highest-value context move:
        tool results are 70-90% of most agent contexts."""
        pruned = 0
        tool_idx = [i for i, (r, _, _) in enumerate(self.messages) if r == "tool"]
        for i in tool_idx[:-keep_last] if keep_last else tool_idx:
            role, content, kind = self.messages[i]
            stub = f"[tool result pruned: {len(content)} chars at {self.pressure:.0%} pressure; re-run the call if needed]"
            if len(content) > 200:
                self.messages[i] = (role, stub, kind)
                pruned += 1
        return pruned

    def calibrate(self, actual_prompt_tokens: int):
        """Feed a real usage number from an API response to correct the heuristic."""
        est = self.tokens()
        if est > 0:
            self.calibrated = actual_prompt_tokens / est

    def summary(self) -> dict:
        return {"pressure": round(self.pressure, 3), "tokens_est": int(self.tokens()),
                "window": self.model_window, "action": self.action()}
