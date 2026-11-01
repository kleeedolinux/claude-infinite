"""What the agent sees: the wake document and the per-prompt recall."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import core, tree

BIAS_PROTOCOL = """Idea mode (anti-bias protocol, active because this prompt asks for ideas/decisions):
- Memories are evidence, not constraints. Label what comes from memory (#id) vs. fresh reasoning.
- Give >=3 genuinely different options, including one that ignores or contradicts past choices and one the user probably has not considered.
- Premortem the favourite: assume it failed in a year; list the likeliest reasons.
- Check biases: anchoring on the first framing, sunk cost from older projects, confirmation of past decisions, recency, overconfidence.
- State what evidence would change the recommendation. For big calls, ask the idea-critic agent for an independent pass."""

FRESH_NOTE = ("Fresh mode (#fresh): no memories were injected for this prompt, to avoid anchoring. Reason from first "
              "principles; afterwards compare with memory (`mem recall <words>`) and say where they differ.")


def tasks_excerpt(root: Path, limit: int = 1600) -> str:
    for p in (root / ".claude" / "TASKS.md", root / "TASKS.md", root / "docs" / "TASKS.md"):
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ""
            keep, on = [], False
            for line in txt.splitlines():
                h = line.lower()
                if line.startswith("#"):
                    on = any(k in h for k in ("progress", "doing", "queue", "next", "todo", "andamento", "fila"))
                    if on:
                        keep.append(line)
                    continue
                if on and line.strip():
                    keep.append(line)
            out = "\n".join(keep) or txt
            rel = p.relative_to(root)
            return ("(from %s)\n" % rel) + (out[:limit] + ("\n…" if len(out) > limit else ""))
    return ""


def attention(c, scope) -> list[str]:
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "select * from inbox where status='open' and scope in (?, 'global') order by count desc, ts desc limit 40",
        (scope,))]
    c.row_factory = None
    out = []
    conflicts = [r for r in rows if r["kind"] == "conflict"]
    recurring = [r for r in rows if r["kind"] == "error" and r["count"] >= 2]
    corr = [r for r in rows if r["kind"] == "correction"]
    for r in conflicts[:3]:
        out.append("CONFLICT %s -> resolve: `mem supersede <old> --by <new>` or `mem inbox done %d`" % (r["text"][:220], r["id"]))
    for r in recurring[:4]:
        out.append("RECURRING ERROR x%d (inbox %d): %s" % (r["count"], r["id"], " ".join(r["text"].split())[:200]))
    if corr:
        out.append("%d unprocessed user correction(s) in inbox -> `mem reflect` turns them into lessons." % len(corr))
    return out


def wake(scope: str, root: Path, source: str = "startup", session: str | None = None) -> str:
    cfg = core.config()
    from . import harvest
    with core.db() as c:
        name = core.scope_name(scope)
        nproj = tree.count(c, scope)
        nglob = tree.count(c, "global")
        head = ["# Infinite memory — %s (%s)" % (name, root),
                "Tool: `mem` (= python ~/.claude/infinite/mem.py). %d project notes, %d global notes. "
                "Lines are `#id date [kind] text`; `@a-b` lines summarize the a-th..b-th notes of that scope (`mem zoom a-b` opens one)."
                % (nproj, nglob)]
        sections = []
        if source == "compact" and session:
            st = harvest.load_state(session)
            rec = ["## Recovered after compaction (verbatim user requests; these remain the goal)"]
            if st.get("first"):
                rec.append("Opening request: " + st["first"][:1200])
            for p in st.get("prompts", [])[-8:]:
                if p["text"] != st.get("first"):
                    rec.append("- " + time.strftime("%H:%M", time.localtime(p["ts"])) + " " + p["text"][:700])
            if st.get("compact_summary_path"):
                rec.append("Pre-compaction summary saved at: %s" % st["compact_summary_path"])
            sections.append(("recovered", "\n".join(rec)))
        rl = core.rules(c, scope)
        if rl:
            sections.append(("rules", "## Rules learned from past sessions (follow them)\n" +
                             "\n".join(core.fmt(r, 260) for r in rl)))
        att = attention(c, scope)
        if att:
            sections.append(("attention", "## Needs attention\n" + "\n".join(att)))
        if scope != "global":
            tx = tasks_excerpt(root)
            if tx:
                sections.append(("tasks", "## Tasks\n" + tx))
        try:
            from . import chat
            dg = chat.digest(scope) if scope != "global" else ""
        except Exception:
            dg = ""
        if dg:
            sections.append(("chat", "## Team chat (recent decisions/blockers/claims; `mem chat read`)\n" + dg))
        budget = cfg["wake_lines"]
        g_lines, g_miss = tree.render(c, "global", max(8, budget // 3), skip={r["id"] for r in rl})
        p_lines, p_miss = (tree.render(c, scope, budget, skip={r["id"] for r in rl}) if scope != "global" else ([], []))
        if g_lines:
            sections.append(("global", "## Global memory (you, the user, cross-project)\n" + "\n".join(g_lines)))
        if p_lines:
            sections.append(("project", "## Project memory (oldest first, coarser with age)\n" + "\n".join(p_lines)))
        elif scope != "global":
            sections.append(("project", "## Project memory\n(empty — record the first fact with `mem note \"...\"`)"))
        nap = tree.next_nap(c, scope) if scope != "global" else None
        nap = nap or tree.next_nap(c, "global")
        if nap:
            sections.append(("nap", nap))
    text = "\n".join(head) + "\n\n" + "\n\n".join(s for _, s in sections)
    limit = cfg["wake_chars"]
    if len(text) > limit:
        # trim the oldest tree lines first; the recovered/rules sections are never cut
        parts = dict(sections)
        for key in ("global", "project"):
            if key in parts:
                ls = parts[key].split("\n")
                while len("\n\n".join(parts.values())) + 400 > limit and len(ls) > 4:
                    del ls[1]
                parts[key] = ls[0] + "\n(older lines trimmed for size: `mem view`)\n" + "\n".join(ls[1:])
        text = "\n".join(head) + "\n\n" + "\n\n".join(parts.values())
        text = text[:limit]
    return text


PARKING = ("Working-style note: if this message adds a NEW idea unrelated to the task in progress, acknowledge it in one line,"
           " save it with `mem idea \"<idea>\"` (memory + TASKS.md Queue) and continue the current task — switch only if the"
           " user says so. If it refines the current task, integrate it. Never silently drop either one.")


def prompt_context(prompt: str, scope: str, ongoing: bool = False) -> str:
    cfg = core.config()
    from . import harvest
    out = []
    if harvest.FRESH.search(prompt):
        return FRESH_NOTE
    with core.db() as c:
        hits = core.search(c, prompt, scopes=[scope, "global"], limit=cfg["prompt_hits"])
        hits = [h for h in hits if h["score"] > 1.2]
        if hits:
            ids = {h["id"] for h in hits}
            extra = []
            for h in hits[:2]:
                for (dst,) in c.execute("select dst from links where src=? union select src from links where dst=?",
                                        (h["id"], h["id"])):
                    if dst not in ids:
                        ids.add(dst)
                        extra.append(dst)
            core.get(c, [h["id"] for h in hits])
            out.append("Relevant memories (verify against code before relying on them):")
            out += ["- " + core.fmt(h, 220) for h in hits]
            if extra:
                rows = [r for r in core.get(c, extra[:3]) if not r["invalid_at"]]
                out += ["- linked: " + core.fmt(r, 160) for r in rows]
    if harvest.IDEA.search(prompt):
        out.append(BIAS_PROTOCOL)
    if ongoing and (harvest.IDEA.search(prompt) or harvest.ADDON.search(prompt)):
        out.append(PARKING)
    if harvest.is_correction(prompt):
        out.append("This message reads like a correction. After fixing it, record the concrete cause as a lesson: "
                   "`mem note -k lesson \"<when X, do Y, because Z>\"` (repeats get reinforced into rules).")
    text = "\n".join(out)
    return text[: cfg["prompt_chars"]]
