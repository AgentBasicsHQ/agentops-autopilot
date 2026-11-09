
## Unreleased — 2026-11-09 (v0.2: mode #6 ships as code)
- NEW MODULE `receipt_audit.py` — failure mode #6 ("partial success with a
  confident summary", named by @ChanYop in our launch thread) now has a real
  defense: plan steps, collect receipts, audit the final summary against the
  receipt diff, and `enforce_partial_honesty()` stamps "PARTIAL (n/m receipts)"
  onto any summary that pretends otherwise. Verdict feeds `failure_journal`
  as a `partial_success` record. Credited to the community in README.
- Test suite: 18 -> 24 checks (6 new for receipt_audit). Harness denominator is
  computed from the harness itself, never hand-typed.
- README: module table + license count updated to 6 modules.

## Earlier — 2026-11-09
- README: added failure mode #6 — "partial success with a confident summary" —
  named by @ChanYop in our launch thread. Defense documented: planned-steps vs
  receipts diff; summaries untrusted until they cite their own evidence.
- README: pricing tiers updated to the live ladder ($19 / $49 / $199
  Done-With-You pairing session with money-back guarantee).
