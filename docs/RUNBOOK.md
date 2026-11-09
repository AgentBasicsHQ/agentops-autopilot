# The AgentOps Runbook — failure-mode playbook

The 12 failure modes that break production agents, how to detect each,
and the fix. (Pro/Team customers get this as a 30-page PDF; this is the
table of contents so you know what you're buying.)

1. **The wall-clock killer** — turn exceeds runtime timeout at step 41.
   Detect: TurnBudget. Fix: budget_s on every call + ship-partial policy.
2. **Silent API truncation** — "all results" → 10 results, no error.
   Detect: validate= on shape+count. Fix: re-request with pagination.
3. **Truncated JSON** — max_tokens cuts mid-string. Detect: strict_json.
   Fix: json_repair ladder, then re-ask with smaller scope.
4. **The retry spiral** — same failure retried N times. Detect:
   failure_journal.same_failure_count_today(). Fix: 3-strike hard stop.
5. **Context amnesia** — early instructions silently forgotten. Detect:
   ContextPressure leading indicator. Fix: graduated prune→summarize→checkpoint.
6. **429 thundering herd** — retry storms. Detect: retry_log. Fix: jittered
   exponential backoff + total budget.
7. **Permanent error retried** — ValueError retried 5×. Fix: retryable-class
   allowlist, not blanket except.
8. **Hallucinated success** — agent claims "uploaded" without reading back.
   Fix: verify-by-readback pattern (in templates).
9. **Timeout that doesn't work** — signal.alarm on worker threads. Fix:
   thread-watchdog timeout (resilient_call).
10. **Budget eaten by retries** — retries alone consume the turn. Fix:
    budget_s shared across attempts.
11. **The state-loss crash** — long job dies, work lost. Fix: checkpoint
    files + resume (templates).
12. **Un-debuggable production incident** — no record of why the turn died.
    Fix: FailureJournal causal chain + top_failures rollup.
13. **Partial success with a confident summary** — the run "completed", 4 of 11
    steps ran, the model wrote a fluent wrap-up anyway. Nothing errored, so no
    retry logic sees it. Detect: receipt_audit.StepAudit receipt diff.
    Fix: enforce_partial_honesty() stamps the receipt count onto the summary
    before the user ever reads it. (Named by the community, 2026-11-09; ships
    as `receipt_audit.py` in the MIT core.)
