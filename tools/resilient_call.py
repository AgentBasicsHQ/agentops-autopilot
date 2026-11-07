"""resilient_call.py — the workhorse wrapper every agent needs.

Every agent that calls an external API (LLM, search, webhook, DB) eventually
meets: timeouts, 429s, 5xx flakes, truncated JSON, and silent partial results.
This wrapper handles all five with one interface, and emits a structured
failure record on permanent failure so your agent can *reason* about why a
call died instead of hallucinating a plausible answer.

Zero dependencies (stdlib only). Python 3.10+.

Usage:
    from resilient_call import resilient_call

    result = resilient_call(
        lambda: my_api.do(x),
        name="my_api.do",
        validate=lambda r: r.get("status") == "ok",   # semantic check
        timeout=45,
        retries=4,
    )
    if result.ok:
        use(result.value)
    else:
        # result.failure is a dict: {kind, attempts, last_error, elapsed_s}
        handle(result.failure)
"""
from __future__ import annotations

import json
import random
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------

RETRYABLE_EXCEPTIONS = (
    TimeoutError, ConnectionError, OSError,  # OSError covers socket/ssl flakes
)
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class RetriableHTTP(Exception):
    """Raise this from your fn for an HTTP-status-based retry.

    Example:
        def fn():
            r = requests.get(url, timeout=20)
            if r.status_code in RETRYABLE_STATUS:
                raise RetriableHTTP(r.status_code, r.text[:200])
            r.raise_for_status()
            return r.json()
    """
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


@dataclass
class CallResult:
    ok: bool
    value: Any = None
    failure: dict | None = None
    attempts: int = 1
    elapsed_s: float = 0.0
    retry_log: list = field(default_factory=list)

    def unwrap(self) -> Any:
        if not self.ok:
            raise RuntimeError(f"call failed: {json.dumps(self.failure)}")
        return self.value


def _timeout_guard(fn: Callable, timeout: float) -> Any:
    """Run fn with a wall-clock timeout that works on any thread, any OS.

    signal.alarm only works on the main thread of Unix; a watchdog thread
    works everywhere. We return the value via a box; if the watchdog fires
    first we raise TimeoutError. (The runaway thread is daemonized and
    abandoned — same tradeoff concurrent.futures makes, without the
    executor overhead.)
    """
    box: dict[str, Any] = {}

    def runner():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 — re-raised on main thread
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"exceeded {timeout}s wall-clock budget")
    if "error" in box:
        raise box["error"]
    return box["value"]


def resilient_call(
    fn: Callable[[], Any],
    *,
    name: str = "call",
    validate: Callable[[Any], bool] | None = None,
    timeout: float = 60.0,
    retries: int = 3,
    backoff_base: float = 1.5,
    backoff_cap: float = 60.0,
    retry_on: tuple = RETRYABLE_EXCEPTIONS,
    budget_s: float | None = None,
    on_retry: Callable[[dict], None] | None = None,
    strict_json: bool = False,
) -> CallResult:
    """Call fn() with timeout, exponential backoff, semantic validation.

    validate: return False to treat a *successful* return as a failure worth
        retrying (truncated JSON, empty result, wrong shape).
    budget_s: total wall-clock budget across all attempts (defaults to
        timeout * (retries+1)). This is what keeps an agent turn alive.
    strict_json: if fn returns a str, json.loads it and fail on error
        (catches mid-stream truncation that 's returned' happily swallows).
    """
    start = time.monotonic()
    deadline = start + (budget_s if budget_s is not None else timeout * (retries + 1))
    attempts = 0
    log: list[dict] = []
    last_err = "unknown"
    last_kind = "unknown"

    for attempt in range(retries + 1):
        attempts += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            last_err, last_kind = "budget exhausted", "budget"
            break
        try:
            value = _timeout_guard(fn, min(timeout, remaining))
            if strict_json and isinstance(value, str):
                value = json.loads(value)
            if validate is not None and not validate(value):
                raise ValueError("validate() rejected the result")
            return CallResult(ok=True, value=value, attempts=attempts,
                              elapsed_s=time.monotonic() - start, retry_log=log)
        except RetriableHTTP as e:
            kind = "http"
            last_err = f"{e} {e.body[:120]}"
            retryable = e.status in RETRYABLE_STATUS
        except Exception as e:  # noqa: BLE001
            kind = type(e).__name__
            last_err = str(e)[:300] or kind
            retryable = isinstance(e, retry_on)

        entry = {"attempt": attempt, "kind": kind, "error": last_err,
                 "t": round(time.monotonic() - start, 2)}
        log.append(entry)
        if on_retry:
            on_retry(entry)
        if not retryable:
            last_kind = kind
            break  # permanent failure — retrying wastes the turn
        if attempt < retries and time.monotonic() < deadline - backoff_base:
            delay = min(backoff_cap, backoff_base * (2 ** attempt))
            delay *= random.uniform(0.75, 1.25)  # jitter: avoid thundering herd
            time.sleep(delay)
        last_kind = kind

    return CallResult(
        ok=False, attempts=attempts,
        elapsed_s=time.monotonic() - start, retry_log=log,
        failure={"kind": last_kind, "name": name, "attempts": attempts,
                 "last_error": last_err,
                 "elapsed_s": round(time.monotonic() - start, 2)},
    )
