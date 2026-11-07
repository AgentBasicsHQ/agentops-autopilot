"""agent_loop_template.py — the battle-tested agent turn skeleton.

Wires all five AgentOps modules into the loop shape every agent framework
eventually grows: plan → step → verify → checkpoint. Copy this instead of
growing your own from scar tissue.
"""
import json, time
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from resilient_call import resilient_call
from turn_budget import TurnBudget
from context_pressure import ContextPressure
from failure_journal import FailureJournal

def run_turn(plan, call_llm, call_tools, window=128_000, total_s=280):
    budget = TurnBudget(total_s=total_s, reserve_s=20)
    ctx = ContextPressure(model_window=window, system_overhead=12_000)
    journal = FailureJournal("logs/failures.jsonl")
    run_id = time.strftime("%Y%m%d-%H%M%S")
    results = []

    for step in plan:
        step_s = step.get("est_s", 30)
        # 1. deadline discipline: never start a step you can't finish
        if not budget.can_afford(step_s, safety=1.0):
            budget.degrade("budget tight — shipping partial")
            budget.skip()
            continue
        # 2. context leading indicator: act BEFORE the API errors
        action = ctx.action()
        if action == "hard_stop_ship_partial":
            budget.degrade("context exhausted — shipping partial")
            break
        if action == "prune_old_tool_results":
            ctx.prune_tool_results(keep_last=4)
        if action == "summarize_oldest_turns":
            # fold oldest turns into a state block (your summarizer here)
            ctx.prune_tool_results(keep_last=2)

        r = resilient_call(
            lambda: call_tools(step),
            name=step["name"], timeout=step.get("timeout", 45),
            retries=3, budget_s=min(60, budget.usable),
            validate=step.get("validate"),
        )
        budget.step()
        if not r.ok:
            journal.record_call_result(run_id, step["name"], r,
                                       budget=budget, context=ctx)
            # anti-spin: same failure 3x today => stop attempting it
            if journal.same_failure_count_today(r.failure["kind"], step["name"]) >= 3:
                budget.degrade(f"spin guard: {step['name']} halted")
                continue
            results.append({"step": step["name"], "status": "failed",
                            "why": r.failure})
            continue
        results.append({"step": step["name"], "status": "ok", "value": r.value})
        ctx.add("tool", json.dumps(r.value)[:5000])

    # 4. verify-by-readback: never claim success without reading state back
    # 5. checkpoint: write results before the turn ends, always
    with open(f"logs/{run_id}-state.json", "w") as f:
        json.dump({"results": results, "budget": budget.summary(),
                   "context": ctx.summary()}, f, indent=2)
    return results, budget.status_note()
