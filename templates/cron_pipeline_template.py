"""cron_pipeline_template.py — durable scheduled agent jobs.

The shape for any agent that runs on a schedule (daily briefings, monitors,
scrapers): checkpoint-resume so a crash at step 40 costs you step 40, not
the whole run; failure journaling so week-4 regressions are visible; and a
dead-man's switch so silence itself is an alert.
"""
import json, time
from pathlib import Path
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from resilient_call import resilient_call
from failure_journal import FailureJournal

STATE = Path("state/pipeline.json")

def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"done": [], "run": 0}

def save_state(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

def run_pipeline(items, process_fn):
    """items: list of work units. process_fn(item) -> result. Resumable."""
    state = load_state()
    state["run"] += 1
    journal = FailureJournal("logs/pipeline-failures.jsonl")
    for item in items:
        key = item["id"]
        if key in state["done"]:
            continue                       # checkpoint-resume: skip finished work
        r = resilient_call(lambda: process_fn(item), name=f"process:{key}",
                           timeout=120, retries=3)
        if r.ok:
            state["done"].append(key)
            save_state(state)              # checkpoint after EVERY unit
        else:
            journal.record_call_result(f"run{state['run']}", key, r)
            if journal.same_failure_count_today(r.failure["kind"], key) >= 3:
                state.setdefault("halted", []).append(key)   # anti-spin
                save_state(state)
    # dead-man's switch: write heartbeat; external monitor alerts if stale
    Path("state/heartbeat").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))
    return state
