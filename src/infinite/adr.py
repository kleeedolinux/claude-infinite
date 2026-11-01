"""Architecture Decision Records in docs/adr/NNNN-slug.md (MADR-style), linked to code.

Each ADR names what it `affects` (paths and/or symbols); `mem adr check` flags links
that rotted (file deleted, symbol renamed), so decisions stay attached to real code."""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import core

TEMPLATE = """# {id}: {title}

- status: {status}
- date: {date}
- affects: {affects}
- supersedes: {supersedes}

## Context
{context}

## Decision
{decision}

## Alternatives considered
{alternatives}

## Consequences
{consequences}
"""
FILE_EXT = {".py", ".md", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".json", ".toml", ".yaml", ".yml", ".sh",
            ".c", ".h", ".cpp", ".java", ".rb", ".php", ".css", ".html", ".sql", ".txt"}
FIELD = re.compile(r"^- (status|date|affects|supersedes):\s*(.*)$", re.M)


def adr_dir(root: Path) -> Path:
    return Path(root) / "docs" / "adr"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", core.fold(s)).strip("-")[:60] or "decision"


def parse(p: Path) -> dict:
    t = p.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"#\s*(ADR-\d+):\s*(.*)", t)
    f = dict(FIELD.findall(t))
    sections = {}
    for name, body in re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", t, re.M | re.S):
        sections[name.strip().lower()] = body.strip()
    return {"id": m.group(1) if m else p.stem, "title": m.group(2).strip() if m else p.stem, "path": str(p),
            "file": p.name, "status": f.get("status", "?"), "date": f.get("date", ""),
            "affects": [a.strip() for a in f.get("affects", "").split(",") if a.strip() and a.strip() != "-"],
            "supersedes": f.get("supersedes", "").strip(), "sections": sections, "text": t}


def all_(root: Path) -> list[dict]:
    d = adr_dir(root)
    return [parse(p) for p in sorted(d.glob("[0-9][0-9][0-9][0-9]-*.md"))] if d.exists() else []


def new(root: Path, title: str, context="", decision="", alternatives="", consequences="", affects="",
        status="accepted", supersedes="") -> dict:
    d = adr_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    nums = [int(p.name[:4]) for p in d.glob("[0-9][0-9][0-9][0-9]-*.md")]
    n = max(nums or [0]) + 1  # chosen at write time: parallel agents don't collide on stale ids
    aid = "ADR-%04d" % n
    p = d / ("%04d-%s.md" % (n, _slug(title)))
    p.write_text(TEMPLATE.format(id=aid, title=title, status=status, date=time.strftime("%Y-%m-%d"),
                                 affects=affects or "-", supersedes=supersedes or "-",
                                 context=context or "TODO: forces at play, constraints, what prompted this.",
                                 decision=decision or "TODO: what we do, stated actively.",
                                 alternatives=alternatives or "TODO: options rejected and why (at least 2).",
                                 consequences=consequences or "TODO: what becomes easier/harder; follow-ups."),
                 encoding="utf-8")
    if supersedes:
        for a in all_(root):
            if a["id"] == supersedes.strip():
                t = Path(a["path"]).read_text(encoding="utf-8")
                t = re.sub(r"^- status:.*$", "- status: superseded by %s" % aid, t, count=1, flags=re.M)
                Path(a["path"]).write_text(t, encoding="utf-8")
    core.note("%s %s — %s" % (aid, title, (decision or "")[:250]), core.scope_key(root), kind="decision",
              importance=3, source="adr:" + p.name, force=True)
    _index(root)
    return {"id": aid, "path": str(p)}


def _index(root: Path):
    d = adr_dir(root)
    rows = ["# Architecture Decision Records", "", "| ADR | Title | Status | Date |", "|---|---|---|---|"]
    for a in all_(root):
        rows.append("| [%s](%s) | %s | %s | %s |" % (a["id"], a["file"], a["title"], a["status"], a["date"]))
    (d / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def related(root: Path, keys: list[str]) -> list[dict]:
    keys = [k for k in keys if k]
    out = []
    for a in all_(root):
        aff = " ".join(a["affects"])
        if any(k in aff or (len(k) > 4 and k in a["text"]) for k in keys):
            out.append(a)
    return out


def check(root: Path, scope: str) -> list[str]:
    from . import atlas
    probs = []
    have_atlas = atlas.exists(scope)
    for a in all_(root):
        if "TODO:" in a["text"]:
            probs.append("%s has unfilled TODO sections" % a["id"])
        for x in a["affects"]:
            looks_like_file = "/" in x or chr(92) in x or Path(x).suffix.lower() in FILE_EXT
            if looks_like_file:
                if not (Path(root) / x).exists():
                    probs.append("%s affects `%s`, which no longer exists" % (a["id"], x))
            elif have_atlas:
                with atlas.adb(scope) as c:
                    if not atlas.lookup(c, x):
                        probs.append("%s affects symbol `%s`, not found in the code index" % (a["id"], x))
    return probs
