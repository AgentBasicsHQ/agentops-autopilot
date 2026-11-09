# AgentOps Autopilot

**The reliability layer every AI agent needs — 5 production-hardened Python
tools, zero dependencies, drop-in in 10 minutes.**

Every agent that calls external APIs eventually meets the same five killers:
timeouts, rate limits, truncated JSON, blown turn deadlines, and silent
context exhaustion. Most teams re-invent bad versions of these defenses per
project. This toolkit is the version you install once.

Built from real production failure modes (a 300s runtime timeout that killed
whole turns; an API that silently truncated "all 60 results" to 10; JSON cut
mid-string by max_tokens; identical failures retried 5 times until a hard
stop). Every module here exists because one of those hurt first.

## What's inside

| Module | Kills which failure |
|---|---|
| `resilient_call.py` | Timeouts, 429/5xx flakes, truncated JSON, bad-shape results — one wrapper, structured failure records, total-budget awareness so retries never eat your whole turn |
| `json_repair.py` | LLM output that's *almost* JSON: fences, trailing commas, Python literals, unterminated strings — deterministic repair ladder with a honesty report |
| `turn_budget.py` | The "worked 40 steps, died at step 41" failure — deadline discipline; ship partial work with a status note instead of losing everything |
| `context_pressure.py` | Silent context exhaustion — leading-indicator pressure gauge with graduated actions (prune tool results → summarize → checkpoint) |
| `failure_journal.py` | Un-debuggable agents — JSONL causal-chain logging + `top_failures()` rollup + anti-spin counter |

All stdlib-only. Python 3.10+. Tested: `python3 tools/test_all.py` → 18 checks.

## The sixth killer (named by the community)

Mode #6, credited to @ChanYop who named it better than we could in our launch
thread: **partial success with a confident summary**. The call *returned*, the
run completed, and the model wrote a confident paragraph — but only 4 of 11
steps actually executed. Nothing errored, so no retry logic ever sees it.

It's invisible unless you diff planned steps against executed steps. The
defense: treat a final summary as untrusted until it cites its own evidence —
every step leaves a receipt in the failure journal, and the answer must match
the receipt count. `failure_journal.py` + a planned-steps checklist turns
"found the issues" into "4/11 receipts — partial", said out loud.

## 10-minute install

```python
from resilient_call import resilient_call
from turn_budget import TurnBudget
from failure_journal import FailureJournal

budget = TurnBudget(total_s=280, reserve_s=20)
journal = FailureJournal("logs/failures.jsonl")

def my_llm_call(prompt): ...            # your existing call

r = resilient_call(lambda: my_llm_call(p), name="llm",
                   timeout=45, retries=3,
                   validate=lambda x: x.get("choices"),  # semantic check
                   budget_s=budget.usable)
if not r.ok:
    journal.record_call_result(run_id, "llm", r, budget=budget)
    # r.failure is a dict you can reason about — not a stack trace soup
```

## License tiers

- **MIT core (this repo):** all 5 modules, free for personal projects.
- **Pro ($49):** 4 production templates (agent loop, cron pipeline, API
  gateway wrapper, eval harness) + the AgentOps Runbook (failure-mode
  playbook) + quarterly module updates.
- **Done-With-You ($199):** a 1-hour live pairing session — we wire these
  modules into your pipeline together, verified against your own traffic.
  Full refund if it doesn't stick.

Templates and runbook are in the Pro/Team download. This repo is the proof
they're built from something real.
