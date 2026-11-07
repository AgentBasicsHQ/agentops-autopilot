"""llm_gateway_template.py — wrap ANY LLM API with the full stack.

One class that gives any OpenAI-compatible or custom LLM endpoint:
timeout+retry discipline, JSON repair on structured outputs, context
pressure tracking, and failure journaling. Swap `chat()` for your client.
"""
import json
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from resilient_call import resilient_call, RetriableHTTP
from json_repair import repair_json
from context_pressure import ContextPressure
from failure_journal import FailureJournal

class LLMSafe:
    def __init__(self, chat_fn, model_window=128_000, name="llm"):
        """chat_fn(messages) -> raw response string (or dict). Raise
        RetriableHTTP(status) for 429/5xx inside your client."""
        self.chat_fn = chat_fn
        self.name = name
        self.ctx = ContextPressure(model_window=model_window)
        self.journal = FailureJournal("logs/llm-failures.jsonl")
        self.run_id = "gateway"

    def ask(self, messages, *, want_json=False, timeout=60, retries=3):
        # pressure gate: refuse to send a request that will hard-error
        if self.ctx.action() == "hard_stop_ship_partial":
            return {"ok": False, "why": "context_pressure_stop",
                    "context": self.ctx.summary()}
        r = resilient_call(
            lambda: self.chat_fn(messages),
            name=self.name, timeout=timeout, retries=retries,
        )
        for m in messages:
            self.ctx.add(m.get("role", "user"), m.get("content", ""))
        if not r.ok:
            self.journal.record_call_result(self.run_id, self.name, r,
                                            context=self.ctx)
            return {"ok": False, "why": r.failure}
        value = r.value
        if want_json and isinstance(value, str):
            obj, report = repair_json(value)
            if obj is None:
                self.journal.record(run_id=self.run_id, step="json",
                                    failure={"kind": "unrepairable_json",
                                             "note": report.note,
                                             "sample": value[:200]})
                return {"ok": False, "why": "unrepairable_json", "raw": value[:500]}
            value = obj
        self.ctx.add("assistant", str(value))
        return {"ok": True, "value": value}

    def ask_json(self, messages, **kw):
        return self.ask(messages, want_json=True, **kw)
