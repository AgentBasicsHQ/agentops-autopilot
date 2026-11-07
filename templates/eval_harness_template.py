"""eval_harness_template.py — measure reliability, not vibes.

Before you ship an agent change, run it against the failure gauntlet:
inject each of the 12 runbook failure modes and score recovery. This is
how you prove your stack works instead of hoping.
"""
import json, random, time
from collections import Counter
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from resilient_call import resilient_call, RetriableHTTP

def make_chaos_fn(fail_kinds, seed=0):
    """Return a call fn that fails in the requested ways, then succeeds."""
    rng = random.Random(seed)
    state = {"n": 0}
    def fn():
        state["n"] += 1
        kind = fail_kinds[state["n"] - 1] if state["n"] <= len(fail_kinds) else None
        if kind == "timeout": time.sleep(0.5); return "late"
        if kind == "429": raise RetriableHTTP(429)
        if kind == "5xx": raise RetriableHTTP(503)
        if kind == "conn": raise ConnectionError("reset")
        if kind == "badjson": return '{"a": 1, "b": [1,2'
        if kind == "empties": return {}
        return {"status": "ok", "n": state["n"]}
    return fn

GAUNTLET = {
    "flaky_429":      (["429", "429"], True),
    "conn_reset":     (["conn", "conn", "conn"], True),
    "one_timeout":    (["timeout"], True),
    "truncated_json": (["badjson"], False),   # resilient_call alone can't fix; json_repair can
    "hopeless":       (["conn"] * 6, False),  # exhausts retries -> must fail
}

def run_gauntlet():
    scores = Counter()
    for name, (kinds, should_recover) in GAUNTLET.items():
        fn = make_chaos_fn(kinds)
        r = resilient_call(fn, name=name, timeout=0.1, retries=4, backoff_base=0.01,
                           validate=lambda x: x.get("status") == "ok")
        recovered = r.ok
        scores["pass" if recovered == should_recover else "misjudge"] += 1
        print(f"{name:16s} recovered={recovered} expected={should_recover}")
    print(f"\n{scores['pass']}/{sum(scores.values())} gauntlet cases judged correctly")
    return scores

if __name__ == "__main__":
    run_gauntlet()
