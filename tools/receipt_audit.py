"""receipt_audit.py — catch failure mode #6: partial success with a confident summary.

The sixth killer never raises. The run "completed", every call *returned*, and
the model still wrote a fluent wrap-up of work it only partially did. Nothing
in a retry loop catches that, because nothing errored. The only defense is an
audit: diff the steps you PLANNED against the receipts your steps LEFT.

This module closes that gap with zero dependencies:

    audit = StepAudit(run_id="run-41")
    audit.plan(["fetch_rows", "summarize", "post_report"])
    ...each step does its work...
    audit.receipt("fetch_rows", detail="58/60 rows")   # partial step, own note
    audit.receipt("summarize")
    audit.final_claim("Report posted. All rows summarized.")

    verdict = audit.audit()
    # verdict.ok == False
    # verdict.missing  == ["post_report"]           planned, no receipt
    # verdict.unplanned == []                       receipts with no plan entry
    # verdict.claims_unsupported == True            summary sounds complete,
    #                                               2/3 steps have receipts

Rule the module enforces: a final summary is UNTRUSTED until it cites its own
evidence. Feed the verdict into your loop — if it isn't ok, the agent must
restate its answer as partial ("2/3 receipts — partial") before returning.

Zero dependencies. Python 3.10+. Named for @ChanYop, who named the failure
mode in our launch thread (see README, mode #6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Words that make a summary sound complete. Deliberately conservative: a
# claim only counts as "sounds complete" if it uses one of these AND the
# step diff doesn't support it.
_COMPLETE_WORDS = re.compile(
    r"\b(all|every|each|everything|complete(?:ly|d)?|fully|successfully?|"
    r"done|finished|no (errors|issues|problems)|successfully)\b",
    re.IGNORECASE,
)
# Explicit partiality markers — if the summary has one, we don't flag the tone.
_PARTIAL_WORDS = re.compile(
    r"\b(partial|incomplete|some|only|\d+\s*/\s*\d+|failed|missing|"
    r"couldn'?t|unable|not all|skipped)\b",
    re.IGNORECASE,
)


@dataclass
class AuditVerdict:
    ok: bool
    planned: list
    receipts: list
    missing: list          # planned steps with no receipt
    unplanned: list        # receipts that were never planned
    claims_unsupported: bool  # summary sounds complete but diff says partial
    detail: str = ""

    def as_failure(self) -> dict:
        """Failure record shaped for failure_journal.FailureJournal.record()."""
        return {
            "kind": "partial_success",
            "missing": self.missing,
            "unplanned": self.unplanned,
            "claims_unsupported": self.claims_unsupported,
            "receipts": f"{len(self.receipts)}/{len(self.planned)}",
        }


@dataclass
class StepAudit:
    run_id: str
    _planned: list = field(default_factory=list)
    _receipts: dict = field(default_factory=dict)  # step -> detail
    _final_claim: str = ""

    def plan(self, steps: list) -> None:
        """Declare the steps this run intends to perform (idempotent)."""
        for s in steps:
            if s not in self._planned:
                self._planned.append(s)

    def receipt(self, step: str, detail: str = "") -> None:
        """Mark a step as actually executed. Call it AFTER the work, with a
        note about what it really produced (e.g. "58/60 rows")."""
        self._receipts[step] = detail

    def final_claim(self, summary: str) -> None:
        """The summary the agent is about to return to the user."""
        self._final_claim = summary

    def audit(self) -> AuditVerdict:
        missing = [s for s in self._planned if s not in self._receipts]
        unplanned = [s for s in self._receipts if s not in self._planned]
        partial = bool(missing)  # a missing receipt = the run is partial

        claims_unsupported = False
        if partial and self._final_claim:
            sounds_complete = bool(_COMPLETE_WORDS.search(self._final_claim))
            admits_partial = bool(_PARTIAL_WORDS.search(self._final_claim))
            claims_unsupported = sounds_complete and not admits_partial

        n_done, n_plan = len(self._receipts), len(self._planned)
        ok = not missing and not unplanned and not claims_unsupported
        detail = (
            f"{n_done}/{n_plan} receipts"
            + (f"; missing: {missing}" if missing else "")
            + (f"; unplanned: {unplanned}" if unplanned else "")
            + ("; summary claims completeness but run is partial"
               if claims_unsupported else "")
        )
        return AuditVerdict(ok=ok, planned=list(self._planned),
                            receipts=list(self._receipts), missing=missing,
                            unplanned=unplanned,
                            claims_unsupported=claims_unsupported, detail=detail)


def enforce_partial_honesty(summary: str, verdict: AuditVerdict) -> str:
    """Return a summary the run is allowed to say out loud.

    If the verdict is ok, the summary passes through untouched. If the run was
    partial and the summary pretended otherwise, it gets a loud, honest prefix
    built from the verdict — the agent is never allowed to sound more complete
    than its receipts.
    """
    if verdict.ok:
        return summary
    prefix = f"PARTIAL ({len(verdict.receipts)}/{len(verdict.planned)} receipts"
    if verdict.missing:
        prefix += f"; not done: {', '.join(verdict.missing)}"
    prefix += "). "
    if verdict.claims_unsupported:
        return prefix + summary
    # Summary already admitted partiality; still stamp the numbers.
    return prefix + summary
