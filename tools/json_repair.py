"""json_repair.py — parse LLM output that is *almost* JSON.

LLMs emit broken JSON constantly: markdown fences, trailing commas,
single-quoted keys, unescaped newlines in strings, Python literals (True/None),
comment lines, and — the silent killer — output truncated mid-string by a
max_tokens cap. Standard json.loads fails on all of these; naive "fix it with
regex" hacks corrupt data.

This module is a deterministic repair ladder: it tries progressively more
aggressive fixes, stops at the first that parses, and reports which rung fixed
it so you can log how dirty the model's output really is.

Zero dependencies. Python 3.10+.

Usage:
    from json_repair import repair_json

    obj, report = repair_json(text)
    if obj is None:
        # truncated or hopeless — report.repaired_as tells you how far we got
        ...
    else:
        use(obj)          # report.rung == "clean" means it was valid already
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE = re.compile(r"```(?:json|python|)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class RepairReport:
    rung: str            # what fixed it: clean|fence|extract|tail|quotes|pyliterals|escape|truncation
    original_len: int
    repaired_len: int
    note: str = ""

    def __bool__(self):
        return True


def _strip_fences(s: str) -> str:
    m = _FENCE.search(s)
    return m.group(1).strip() if m else s


def _extract_balanced(s: str) -> str | None:
    """Grab the first balanced {...} or [...] span, string-aware."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        # unbalanced: return from opener to end (truncation candidate)
        return s[start:]
    return None


def _close_truncated(s: str) -> str:
    """Close an unterminated JSON document: strings, then brackets."""
    stack: list[str] = []
    in_str = False
    esc = False
    last_safe = 0
    for i, c in enumerate(s):
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack and stack[-1] == c:
                stack.pop()
                last_safe = i + 1
    if in_str:
        # unterminated string: cut back to before it, then close containers
        s = s[: last_safe] if last_safe else s
    # also drop a dangling key like  "title":
    s = re.sub(r'[,{]\s*"[^"]*"\s*:\s*$', "", s)
    s = _TRAILING_COMMA.sub(r"\1", s)
    return s + "".join(reversed(stack))


def repair_json(text: str) -> tuple[object | None, RepairReport]:
    """Return (parsed_object_or_None, RepairReport)."""
    report = RepairReport(rung="clean", original_len=len(text), repaired_len=len(text))
    if not text or not text.strip():
        report.rung, report.note = "empty", "input empty"
        return None, report

    rungs = []
    s = text

    # 1. clean
    rungs.append(("clean", s))
    # 2. strip markdown fences
    s2 = _strip_fences(s)
    if s2 != s:
        rungs.append(("fence", s2))
        s = s2
    # 3. extract first balanced JSON span (drops prose before/after)
    ext = _extract_balanced(s)
    if ext is not None and ext != s:
        rungs.append(("extract", ext))
        s = ext

    # Try the ladder in order of aggression.
    candidates = list(rungs)
    # 4. trailing commas + control chars + python literals
    fixed = s
    fixed = _TRAILING_COMMA.sub(r"\1", fixed)
    fixed = _CONTROL_CHARS.sub(" ", fixed)
    if fixed != s:
        candidates.append(("tail", fixed))
        s4 = fixed
    else:
        s4 = fixed
    # 5. python literals
    s5 = re.sub(r"\bTrue\b", "true", s4)
    s5 = re.sub(r"\bFalse\b", "false", s5)
    s5 = re.sub(r"\bNone\b", "null", s5)
    if s5 != s4:
        candidates.append(("pyliterals", s5))
    # 6. single-quoted strings (only if no double quotes present — else risky)
    if '"' not in s5 and "'" in s5:
        s6 = s5.replace("'", '"')
        candidates.append(("quotes", s6))
    # 7. truncation repair (last resort)
    s7 = _close_truncated(s5)
    if s7 != s5:
        candidates.append(("truncation", s7))

    for rung, cand in candidates:
        try:
            obj = json.loads(cand)
            report.rung = rung
            report.repaired_len = len(cand)
            if rung == "truncation":
                report.note = "document was cut off; partial data recovered"
            return obj, report
        except (json.JSONDecodeError, ValueError):
            continue
    report.rung = "unrepairable"
    return None, report
