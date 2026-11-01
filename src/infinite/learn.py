"""Glossary + learner profile + explain packs.

The glossary explains what a thing IS (concept), not just the code:
  what (plain-language concept) / why (why this project needs it) / analogy /
  how-here (file:line or symbols that implement it) / see (related terms).
It lives in docs/GLOSSARY.md (human-readable, versioned) and is mirrored in memory.
The learner profile (data/learner.json) remembers which terms the user already knows,
so explanations define only what is new to them and get shorter over time.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import core

FIELDS = ("what", "why", "analogy", "how-here", "see")
QUESTION = re.compile(
    r"\b(how does|how do|how is|what is|what are|what does|why does|why is|explain|walk me through|understand"
    r"|como funciona|o que [eé]|o que s[aã]o|o que faz|por que|porque|explica|explique|entender|n[aã]o entendi)\b", re.I)


def gfile(root: Path) -> Path:
    return Path(root) / "docs" / "GLOSSARY.md"


def load(root: Path) -> dict:
    p = gfile(root)
    if not p.exists():
        return {}
    terms, cur = {}, None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1)
            terms[cur] = {}
            continue
        m = re.match(r"^- (what|why|analogy|how-here|see):\s*(.*)$", line)
        if cur and m:
            terms[cur][m.group(1)] = m.group(2).strip()
    return terms


def save(root: Path, terms: dict):
    p = gfile(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = ["# Glossary", "", "What each term IS (concept first), why this project needs it, and where it lives in the code.",
           "Maintained with `mem term add`. Sorted A-Z.", ""]
    for name in sorted(terms, key=str.lower):
        out.append("## %s" % name)
        for f in FIELDS:
            if terms[name].get(f):
                out.append("- %s: %s" % (f, terms[name][f]))
        out.append("")
    p.write_text("\n".join(out), encoding="utf-8")


def add(root: Path, name: str, what: str, why="", analogy="", how="", see="") -> str:
    terms = load(root)
    key = next((k for k in terms if k.lower() == name.lower()), name)
    existed = key in terms
    t = terms.setdefault(key, {})
    for f, v in (("what", what), ("why", why), ("analogy", analogy), ("how-here", how), ("see", see)):
        if v:
            t[f] = core.clean(v)
    save(root, terms)
    core.note("term %s: %s" % (key, t.get("what", "")[:300]), core.scope_key(root), kind="fact",
              importance=2, tags=["term"], source="glossary", force=False)
    return "glossary: %s %s" % ("updated" if existed else "added", key)


# ------------------------------------------------------------------ learner profile

def _lp() -> Path:
    return core.data_dir() / "learner.json"


def profile() -> dict:
    try:
        return json.loads(_lp().read_text(encoding="utf-8"))
    except Exception:
        return {"known": {}}


def mark_known(terms: list[str], level: str = "knows"):
    p = profile()
    for t in terms:
        p["known"][t.lower()] = {"level": level, "ts": time.time()}
    _lp().write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")


def known(term: str) -> str | None:
    k = profile()["known"].get(term.lower())
    return k["level"] if k else None


# ------------------------------------------------------------------ candidates + explain pack

ACRO = re.compile(r"\b([A-Z][A-Z0-9]{1,9}s?|[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)\b")
COMMON_ACRO = {"TODO", "OK", "API", "URL", "ID", "JSON", "HTTP", "CLI", "README", "NOTE", "FIXME", "PR", "UI", "OS",
               "IO", "MD", "YES", "NO", "AND", "OR", "NOT", "THE", "IF", "A", "I"}


def candidates(scope: str, root: Path, limit=25) -> list[tuple[str, int]]:
    """Domain terms used in the code/docs but not in the glossary (acronyms, CamelCase, class names)."""
    from . import atlas
    have = {k.lower() for k in load(root)}
    counts: dict[str, int] = {}
    if atlas.exists(scope):
        with atlas.adb(scope) as c:
            for (txt,) in c.execute("select text from chunks"):
                for m in ACRO.findall(txt):
                    counts[m] = counts.get(m, 0) + 1
            for (name, doc) in c.execute("select name, doc from symbols where kind='class'"):
                counts[name] = counts.get(name, 0) + 3
                for m in ACRO.findall(doc or ""):
                    counts[m] = counts.get(m, 0) + 1
    out = [(t, n) for t, n in counts.items() if t.lower() not in have and t.upper() not in COMMON_ACRO and len(t) > 2]
    out.sort(key=lambda x: -x[1])
    return out[:limit]


def terms_in(text: str, glossary: dict) -> list[str]:
    low = core.fold(text)
    return [k for k in glossary if re.search(r"\b%s\b" % re.escape(core.fold(k)), low)]


def pack(question: str, scope: str, root: Path, hits=8) -> str:
    """Grounded material for answering a 'how does X work / what is X' question at the user's level."""
    from . import adr, atlas
    gl = load(root)
    out = ["# Explain pack: %s" % question]
    found = atlas.search(scope, question, limit=hits) if atlas.exists(scope) else []
    blob = question + " " + " ".join(h["title"] + " " + h["snippet"] for h in found)
    tq = terms_in(blob, gl)
    if tq:
        out.append("\n## Glossary terms involved (concept first)")
        for t in tq[:10]:
            g = gl[t]
            lvl = known(t)
            out.append("- **%s** [%s]: %s%s%s%s" % (
                t, "user knows it: one line is enough" if lvl else "NEW to the user: define it",
                g.get("what", "(no definition yet)"), (" | why: " + g["why"]) if g.get("why") else "",
                (" | like: " + g["analogy"]) if g.get("analogy") else "", (" | code: " + g["how-here"]) if g.get("how-here") else ""))
    undefined = [t for t, _ in (atlas and candidates(scope, root, 60)) if re.search(r"\b%s\b" % re.escape(t), blob)][:8] \
        if atlas.exists(scope) else []
    if undefined:
        out.append("\nTerms in the material with NO glossary entry (define them, then `mem term add`): " + ", ".join(undefined))
    if found:
        out.append("\n## Where it lives (read only these ranges)")
        out.append(atlas.format_hits(found))
    elif not atlas.exists(scope):
        out.append("\n(no code index yet: run `mem code index` for code-grounded answers)")
    rel = adr.related(root, [h["where"].split(":")[0] for h in found if h["type"] != "doc"][:5])
    if rel:
        out.append("\n## Decisions (why it is this way)")
        out += ["- %s %s [%s]: %s" % (a["id"], a["title"], a["status"], a["sections"].get("decision", "")[:200]) for a in rel[:5]]
    with core.db() as c:
        mems = core.search(c, question, scopes=[scope, "global"], limit=4)
    if mems:
        out.append("\n## Memories")
        out += ["- " + core.fmt(m, 200) for m in mems]
    out.append("\n## How to answer\n" + EXPLAIN_ORDER)
    return "\n".join(out)


EXPLAIN_ORDER = (
    "1. WHAT it is: the concept in plain words + an analogy (no code yet).\n"
    "2. WHY it exists here: the problem it solves in this project (cite ADRs/memories).\n"
    "3. HOW it works here: walk the real flow step by step with file:line (use `mem code flow <symbol>` and read the ranges above).\n"
    "4. TERMS: define every NEW term once, briefly; skip ones the user knows.\n"
    "5. Close with a small diagram (mermaid) if there are 3+ moving parts, and what you did NOT verify.\n"
    "Afterwards: save new terms (`mem term add \"T\" --what .. --why .. --analogy .. --how ..`) and, if the user"
    " shows they got it, `mem learned T`.")
