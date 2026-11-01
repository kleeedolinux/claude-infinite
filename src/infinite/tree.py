"""Summary tree per scope (OptMem / uniichat).

Leaves are notes in scope order (pos). Block [lo,hi) is an aligned power-of-two
range; its summary is one line the agent writes (`mem nap`). Wake tiles the past
with blocks whose size grows with age: recent = verbatim, old = coarse, nothing lost,
`mem zoom lo-hi` descends. Missing summaries never block: the view shows
"(not summarized yet: zoom it)" and a nap is offered.
"""
from __future__ import annotations

import sqlite3

from . import core


def _cover(T: int, alpha: float):
    root = 1
    while root < T:
        root *= 2
    out, stack = [], [(0, root)]
    while stack:
        lo, hi = stack.pop()
        if lo >= T:
            continue
        size = hi - lo
        if size > 1 and (hi > T or size > alpha * (T - lo)):
            mid = (lo + hi) // 2
            stack.append((mid, hi))
            stack.append((lo, mid))
        else:
            out.append((lo, hi))
    out.sort()
    return out


def cover(T: int, budget: int):
    """Adapted from OptMem `cover`: at most `budget` blocks, finest near T."""
    if T <= 0:
        return []
    if T <= budget:
        return [(i, i + 1) for i in range(T)]
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if len(_cover(T, mid)) > budget:
            lo = mid
        else:
            hi = mid
    out = _cover(T, hi)
    while len(out) < budget:
        i = max((i for i, b in enumerate(out) if b[1] - b[0] > 1), default=None)
        if i is None:
            break
        a, b = out[i]
        m = (a + b) // 2
        out[i:i + 1] = [(a, m), (m, b)]
    return out


def count(c, scope) -> int:
    return c.execute("select coalesce(max(pos),-1)+1 from notes where scope=?", (scope,)).fetchone()[0]


def leaf(c, scope, pos):
    c.row_factory = sqlite3.Row
    r = c.execute("select * from notes where scope=? and pos=?", (scope, pos)).fetchone()
    c.row_factory = None
    return dict(r) if r else None


def summary(c, scope, lo, hi):
    r = c.execute("select text from summaries where scope=? and lo=? and hi=?", (scope, lo, hi)).fetchone()
    return r[0] if r else None


def leaves(c, scope, lo, hi):
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "select * from notes where scope=? and pos>=? and pos<? order by pos", (scope, lo, hi))]
    c.row_factory = None
    return rows


def render(c, scope, budget: int, skip=frozenset()) -> tuple[list[str], list[tuple[int, int]]]:
    """Lines for wake + the blocks that were needed but missing (to nap first)."""
    T = count(c, scope)
    lines, missing = [], []
    for lo, hi in cover(T, budget):
        if hi - lo == 1:
            r = leaf(c, scope, lo)
            if r and not r["invalid_at"] and r["id"] not in skip:
                lines.append(core.fmt(r, 240))
            continue
        s = summary(c, scope, lo, hi)
        if s is None:
            missing.append((lo, hi))
            rows = [r for r in leaves(c, scope, lo, hi) if not r["invalid_at"]]
            top = max(rows, key=lambda r: (r["importance"], r["reinforced"]), default=None)
            hint = (" top: " + core.fmt(top, 120)) if top else ""
            lines.append("@%d-%d (not summarized yet: zoom it)%s" % (lo, hi - 1, hint))
        else:
            lines.append("@%d-%d %s" % (lo, hi - 1, s))
    return lines, missing


def pending(c, scope, limit=None, budget=None):
    """Lazy naps: only blocks the wake view actually needs (and the children
    those need), smallest first. Nothing is due until notes exceed the budget."""
    T = count(c, scope)
    budget = budget or core.config()["wake_lines"]
    have = {(lo, hi) for lo, hi in c.execute("select lo,hi from summaries where scope=?", (scope,))}
    need: set = set()

    def want(lo, hi):
        if hi - lo < 2 or (lo, hi) in have or (lo, hi) in need:
            return
        if hi - lo > 16:
            m = (lo + hi) // 2
            want(lo, m)
            want(m, hi)
        need.add((lo, hi))

    for lo, hi in cover(T, budget):
        want(lo, hi)
    todo = sorted(need, key=lambda b: (b[1] - b[0], b[0]))
    return todo[:limit] if limit else todo


def nap_prompt(c, scope, lo, hi, left=0) -> str:
    if hi - lo <= 16:
        body = "\n".join("  " + core.fmt(r, 300) for r in leaves(c, scope, lo, hi))
    else:
        m = (lo + hi) // 2
        body = "\n".join("  @%d-%d %s" % (a, b - 1, summary(c, scope, a, b)) for a, b in ((lo, m), (m, hi)))
    tail = "\n(%d more compressions due after this one)" % left if left else ""
    return ("NAP due for %s @%d-%d: compress into ONE line (<=280 chars). Keep user words, decisions,"
            " corrections, verdicts and their reasons near-verbatim; drop the rest; invent nothing;"
            " skip lines marked superseded/forgotten.\n%s%s\nRun: mem nap %d-%d \"<line>\"%s"
            % (core.scope_name(scope), lo, hi - 1, body, tail, lo, hi - 1,
               "" if scope == core.current_scope() else " --scope " + scope))


def next_nap(c, scope) -> str | None:
    todo = pending(c, scope)
    todo = [b for b in todo if b[1] - b[0] <= 16 or all(
        summary(c, scope, *h) for h in ((b[0], (b[0] + b[1]) // 2), ((b[0] + b[1]) // 2, b[1])))]
    if not todo:
        return None
    lo, hi = todo[0]
    return nap_prompt(c, scope, lo, hi, len(todo) - 1)


def zoom(c, scope, lo, hi) -> list[str]:
    hi += 1  # user gives inclusive
    if hi - lo <= 2 or hi - lo <= 16 and not summary(c, scope, lo, (lo + hi) // 2):
        return [core.fmt(r) for r in leaves(c, scope, lo, hi)]
    m = (lo + hi) // 2
    out = []
    for a, b in ((lo, m), (m, hi)):
        s = summary(c, scope, a, b)
        out.append("@%d-%d %s" % (a, b - 1, s if s else "(not summarized yet: zoom it)"))
    return out
