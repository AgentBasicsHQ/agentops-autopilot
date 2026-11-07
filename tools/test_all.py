"""test_all.py — the toolkit's proof. Run: python3 test_all.py"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from resilient_call import resilient_call, RetriableHTTP
from json_repair import repair_json
from turn_budget import TurnBudget
from context_pressure import ContextPressure
from failure_journal import FailureJournal

PASS = 0
def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ok  {name}")

# --- resilient_call ---------------------------------------------------------
calls = {"n": 0}
def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError("flaked")
    return {"status": "ok"}
r = resilient_call(flaky, name="flaky", retries=3, backoff_base=0.01)
check("retries recover flaky call", r.ok and r.value["status"] == "ok" and r.attempts == 3)

def always_timeout():
    time.sleep(2)
    return 1
r = resilient_call(always_timeout, name="slow", timeout=0.2, retries=1, backoff_base=0.01)
check("timeout enforced", not r.ok and r.failure["kind"] == "TimeoutError")

def bad_shape():
    return {"status": "partial"}
r = resilient_call(bad_shape, name="shape", validate=lambda x: x["status"] == "ok",
                   retries=1, backoff_base=0.01)
check("validate rejects bad shape", not r.ok and "rejected" in r.failure["last_error"])

def http_429():
    raise RetriableHTTP(429, "rate limited")
r = resilient_call(http_429, name="rate", retries=2, backoff_base=0.01)
check("429 retried then fails with structured record", not r.ok and r.attempts == 3
      and r.failure["kind"] == "http")

def permanent():
    raise ValueError("bad input")
r = resilient_call(permanent, name="perm", retries=5, backoff_base=0.01)
check("permanent error not retried", not r.ok and r.attempts == 1)

r = resilient_call(lambda: '{"a": 1', name="strict", strict_json=True, retries=0)
check("strict_json catches truncated json", not r.ok)

# --- json_repair ------------------------------------------------------------
o, rep = repair_json('{"a": 1}')
check("clean passthrough", o == {"a": 1} and rep.rung == "clean")
o, rep = repair_json('Here is the JSON:\n```json\n{"a": [1,2,],}\n```\nDone!')
check("fence + trailing comma", o == {"a": [1, 2]} and rep.rung in ("fence", "tail"))
o, rep = repair_json('{"title": "hello world", "tags": ["a", "b"')
check("truncated doc recovered", o is not None and o["title"] == "hello world"
      and rep.rung == "truncation")
o, rep = repair_json("{'items': [1, 2, True, None]}")
check("python literals + single quotes", o == {"items": [1, 2, True, None]})
o, rep = repair_json("")
check("empty input handled", o is None and rep.rung == "empty")

# --- turn_budget ------------------------------------------------------------
b = TurnBudget(total_s=0.1, reserve_s=0.01)
time.sleep(0.12)
check("budget detects exhaustion", not b.can_afford(0.01) and b.summary()["status"] == "EXHAUSTED")
b2 = TurnBudget(total_s=100)
check("healthy budget affords steps", b2.can_afford(10) and b2.summary()["status"] == "healthy")

# --- context_pressure -------------------------------------------------------
cp = ContextPressure(model_window=1000, system_overhead=100)
for i in range(20):
    cp.add("tool", "x" * 400)
check("pressure rises", cp.pressure > 0.8)
check("action graduated", cp.action() in ("summarize_oldest_turns", "checkpoint_and_restart", "hard_stop_ship_partial"))
pruned = cp.prune_tool_results(keep_last=2)
check("prune reduces pressure", pruned > 0 and cp.pressure < 1.0)

# --- failure_journal --------------------------------------------------------
jf = FailureJournal("/tmp/agentops_test_journal.jsonl")
r = resilient_call(always_timeout, name="slow2", timeout=0.1, retries=0)
check("journal logs failures", jf.record_call_result("run1", "slow2", r, budget=b2))
check("anti-spin counter", jf.same_failure_count_today("TimeoutError", "slow2") == 1)
os.remove("/tmp/agentops_test_journal.jsonl")

print(f"\n{PASS}/21 checks passed")
