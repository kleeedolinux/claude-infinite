"""TASKS.md (In progress / Queue / Done) and docs/kb records, per joaodavisn's
"projetos grandes com Claude": continuity lives in files the next session reads."""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import projects

SECTIONS = ("In progress", "Queue", "Done")


def _file(root: Path) -> Path:
    p = root / ".claude" / "TASKS.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(projects.TASKS_MD, encoding="utf-8")
    return p


def _parse(text: str) -> dict:
    secs = {s: [] for s in SECTIONS}
    cur = None
    for line in text.splitlines():
        m = re.match(r"##\s+(.*)", line)
        if m:
            name = m.group(1).strip()
            cur = next((s for s in SECTIONS if s.lower() == name.lower()), None)
            continue
        if cur and line.strip().startswith("- "):
            secs[cur].append(line.strip())
    return secs


def _dump(secs: dict) -> str:
    out = ["# Tasks", ""]
    for s in SECTIONS:
        out.append("## " + s)
        out += secs[s]
        out.append("")
    return "\n".join(out)


def _take(lines: list[str], needle: str):
    n = needle.lower()
    for i, l in enumerate(lines):
        if n in l.lower():
            return lines.pop(i)
    return None


def _strip(line: str) -> str:
    return re.sub(r"^- (\[[^\]]*\] )?", "", line).strip()


def op(root: Path, action: str, text: str, owner: str = "main", files: str = "") -> str:
    p = _file(root)
    secs = _parse(p.read_text(encoding="utf-8"))
    day = time.strftime("%Y-%m-%d")
    if action == "park":
        secs["Queue"].append("- %s" % text)
        msg = "Parked in Queue: %s" % text
    elif action == "start":
        found = _take(secs["Queue"], text)
        t = _strip(found) if found else text
        secs["In progress"].append("- [%s] %s%s" % (owner, t, (" — files: " + files) if files else ""))
        msg = "Started: %s" % t
    elif action == "done":
        found = _take(secs["In progress"], text) or _take(secs["Queue"], text)
        t = _strip(found) if found else text
        t = re.sub(r" — files: .*$", "", t)
        secs["Done"].insert(0, "- %s %s" % (day, t))
        msg = "Done: %s" % t
    elif action == "drop":
        found = _take(secs["Queue"], text) or _take(secs["In progress"], text)
        msg = "Dropped: %s" % (found or "(not found)")
    else:
        raise SystemExit("task actions: park|start|done|drop|list")
    secs["Done"] = secs["Done"][:60]
    p.write_text(_dump(secs), encoding="utf-8")
    return msg


def listing(root: Path) -> str:
    return _file(root).read_text(encoding="utf-8")


# ------------------------------------------------------------------ knowledge base

KB_ID = re.compile(r"^###\s+KB-(\d{4,})\b", re.M)


def _kb(root: Path) -> Path:
    p = root / "docs" / "kb" / "README.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(projects.KB_MD, encoding="utf-8")
    return p


def kb_new(root: Path, area: str, title: str, verdict: str, evidence: str, reproduce: str = "",
           supersedes: str = "") -> str:
    """The id is chosen at write time (never at task start) so parallel agents don't collide."""
    p = _kb(root)
    text = p.read_text(encoding="utf-8")
    nxt = max([int(i) for i in KB_ID.findall(text)] or [0]) + 1
    kid = "KB-%04d" % nxt
    rec = ["", "### %s %s %s — %s" % (kid, time.strftime("%Y-%m-%d"), area, title),
           "verdict: %s%s" % (verdict, ("      supersedes: " + supersedes) if supersedes else ""),
           "evidence: %s" % evidence]
    if reproduce:
        rec.append("reproduce: `%s`" % reproduce)
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n".join(rec) + "\n")
    if supersedes:
        t2 = p.read_text(encoding="utf-8")
        t2 = re.sub(r"(###\s+%s\b[^\n]*)" % re.escape(supersedes), r"\1 [SUPERSEDED by %s]" % kid, t2, count=1)
        p.write_text(t2, encoding="utf-8")
    return kid


def kb_check(root: Path) -> list[str]:
    text = _kb(root).read_text(encoding="utf-8")
    seen, dup = set(), []
    for i in KB_ID.findall(text):
        if i in seen:
            dup.append("KB-" + i)
        seen.add(i)
    return dup
