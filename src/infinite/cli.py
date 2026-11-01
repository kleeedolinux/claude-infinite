"""`mem` — infinite memory for Claude Code. Run `mem help`."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from . import core, harvest, projects, tasks, tree, wake

HELP = """mem — infinite memory for Claude Code (stdlib Python; hooks load it in every project)

remember   note "<fact>" [-k kind] [-i 1-5] [-g] [--pin]   kinds: %s
           idea "<idea>"            park an idea: memory + TASKS.md Queue, do not switch task
           supersede <old> "<new>"  | supersede <old> --by <id>   (old kept, hidden: bi-temporal)
           forget <id> | restore <id> | pin <id> | link <a> <b> [rel] | importance <id> <1-5>
find       recall <words> [-a] [-x regex] [--history]   ranked search (index layer)
           get <id...>   timeline <id>   zoom <lo-hi>   view   rules
tree       naps (list due)   nap <lo-hi> "<summary line>"   unnap <lo-hi>
improve    reflect (agenda: corrections, recurring errors, conflicts, naps)   inbox [done <id>|all]
           doctor [--fix]   rebuild   stats   bias "<idea>"   config [key=value]
projects   project new <path> [--kind python|monorepo|generic] [--purpose ..] [--areas a,b]
           project scan <path> | migrate <path> | monorepo <target> <src...> | list
           import-claude [--all]   graph [--json]
code       code index [--full] · code search <words> (code+docs, graph-expanded) · code find <words>
           code explain <symbol|path:line> · code flow <symbol> [--depth 3] · code map · code graph
           code brief "<task>" (compact grounded context for a subagent) · code site [outdir] · code docs
docs       adr new "<title>" --context .. --decision .. --alternatives .. --consequences .. --affects a,b
           adr list|check|show <id> · explain "<question>" (grounded pack: what/why/how + terms)
learning   term add "T" --what .. [--why .. --analogy .. --how ..] · term list|candidates · learned <terms>
team chat  chat post <#channel> "<msg>" --as <agent> [--kind decision|blocker|done|question]
           chat read [#channel] --as <agent> (unread + @mentions) · chat channels · chat digest
           chat claim <file|glob...> --as <agent> [--note ..] · chat release [..] · chat who
tasks      task park|start|done|drop "<text>" [--owner name] [--files ..] | task list
           kb new <area> "<title>" --verdict works|fails|open --evidence ".." [--repro ".."] [--supersedes KB-n]
           kb check
""" % ", ".join(core.KINDS)


def _scope(a) -> str:
    if getattr(a, "scope", None):
        return a.scope
    if getattr(a, "g", False):
        return "global"
    return core.current_scope()


def _range(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"[#@]?(\d+)-(\d+)", s.strip())
    if not m:
        raise SystemExit("range must look like 8-15")
    return int(m.group(1)), int(m.group(2))


def cmd_note(a):
    scope = _scope(a)
    r = core.note(" ".join(a.text), scope, kind=a.k, importance=a.i, tags=a.t.split(",") if a.t else None,
                  force=a.force, pinned=a.pin)
    print(r["message"], "[%s]" % core.scope_name(scope))
    for s in r.get("similar", []):
        print("  " + s)
    if r.get("similar"):
        print("  If the new note replaces one: mem supersede <old> --by %d" % r["id"])
    with core.db() as c:
        nap = tree.next_nap(c, scope)
    if nap:
        print("\n" + nap)


def cmd_idea(a):
    text = " ".join(a.text)
    scope = _scope(a)
    r = core.note(text, scope, kind="idea", importance=a.i)
    root = core.find_root()
    if scope != "global":
        print(tasks.op(root, "park", "idea: %s (#%d)" % (text, r["id"])))
    print(r["message"], "Continue the current task unless the user asked to switch.")


def cmd_recall(a):
    scopes = None if a.a else [_scope(a), "global"]
    with core.db() as c:
        if a.x:
            rx = re.compile(a.x, re.I)
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute("select * from notes order by id")]
            rows = [r for r in rows if rx.search(r["text"]) and (scopes is None or r["scope"] in scopes)
                    and (a.history or not r["invalid_at"])]
            rows = rows[-a.n:]
        else:
            rows = core.search(c, " ".join(a.words), scopes=scopes, limit=a.n, valid_only=not a.history)
        if not rows:
            print("nothing found. Try other words, -a (all projects), -x regex, or --history.")
            return
        core.get(c, [r["id"] for r in rows])
    for r in rows:
        where = "" if r["scope"] in (scopes or []) else "  {%s}" % core.scope_name(r["scope"])
        print(core.fmt(r, 200) + where)
    print("(full text: mem get <id>; context around one: mem timeline <id>)")


def cmd_get(a):
    with core.db() as c:
        rows = core.get(c, [int(i.lstrip("#")) for i in a.ids])
        for r in rows:
            print(core.fmt(r))
            print("   scope=%s pos=%s importance=%s hits=%s reinforced=%s source=%s tags=%s"
                  % (core.scope_name(r["scope"]), r["pos"], r["importance"], r["hits"], r["reinforced"],
                     r["source"], r["tags"]))
            for dst, rel in c.execute("select dst, rel from links where src=?", (r["id"],)):
                print("   -> %s #%d" % (rel, dst))
            for src, rel in c.execute("select src, rel from links where dst=?", (r["id"],)):
                print("   <- %s #%d" % (rel, src))


def cmd_timeline(a):
    nid = int(a.id.lstrip("#"))
    with core.db() as c:
        r = c.execute("select scope,pos from notes where id=?", (nid,)).fetchone()
        if not r:
            raise SystemExit("no #%d" % nid)
        for row in tree.leaves(c, r[0], r[1] - a.w, r[1] + a.w + 1):
            print(("> " if row["id"] == nid else "  ") + core.fmt(row, 220))


def cmd_zoom(a):
    lo, hi = _range(a.range)
    with core.db() as c:
        print("\n".join(tree.zoom(c, _scope(a), lo, hi)))


def cmd_view(a):
    print(wake.wake(_scope(a), core.find_root()))


def cmd_naps(a):
    scope = _scope(a)
    with core.db() as c:
        due = tree.pending(c, scope)
        print("%d naps due in %s" % (len(due), core.scope_name(scope)))
        nap = tree.next_nap(c, scope)
    if nap:
        print(nap)


def cmd_nap(a):
    lo, hi = _range(a.range)
    text = core.clean(" ".join(a.text))
    if len(text) > 400:
        raise SystemExit("summary too long (%d chars); one line, <=280 preferred" % len(text))
    scope = _scope(a)
    with core.db() as c:
        size = hi + 1 - lo
        if size & (size - 1) or lo % size:
            raise SystemExit("not a tree block: size must be a power of two and lo aligned")
        core.emit(c, {"op": "summary", "scope": scope, "lo": lo, "hi": hi + 1, "text": text})
        print("Saved summary @%d-%d." % (lo, hi))
        nap = tree.next_nap(c, scope)
    if nap:
        print("\n" + nap)


def cmd_unnap(a):
    lo, hi = _range(a.range)
    with core.db() as c:
        core.emit(c, {"op": "unsummary", "scope": _scope(a), "lo": lo, "hi": hi + 1})
    print("Dropped summary @%d-%d; the next nap rebuilds it." % (lo, hi))


def cmd_supersede(a):
    old = int(a.old.lstrip("#"))
    if a.by:
        print(core.supersede(old, None, None, new_id=int(a.by.lstrip("#"))))
    else:
        if not a.text:
            raise SystemExit("give the new text or --by <id>")
        print(core.supersede(old, " ".join(a.text), None, kind=a.k))


def _simple(op, **kw):
    def f(a):
        core.simple_event(op, int(a.id.lstrip("#")), **kw)
        print("%s #%s" % (op, a.id))
    return f


def cmd_importance(a):
    core.simple_event("importance", int(a.id.lstrip("#")), value=max(1, min(5, a.value)))
    print("ok")


def cmd_link(a):
    with core.db() as c:
        core.emit(c, {"op": "link", "uid": core._uid(c, int(a.a.lstrip("#"))),
                      "dst_uid": core._uid(c, int(a.b.lstrip("#"))), "rel": a.rel})
    print("linked #%s -[%s]-> #%s" % (a.a, a.rel, a.b))


def cmd_rules(a):
    with core.db() as c:
        for r in core.rules(c, _scope(a), limit=50):
            print(core.fmt(r))


def cmd_inbox(a):
    with core.db() as c:
        if a.action == "done":
            with core.tx(c):
                for i in a.ids:
                    c.execute("update inbox set status='done' where id=?", (int(i),))
            print("closed", " ".join(a.ids))
            return
        q = "select id, kind, count, text, scope from inbox where status='open'" + (
            "" if a.action == "all" else " and scope in (?, 'global')") + " order by kind, count desc, ts desc limit 60"
        rows = c.execute(q, () if a.action == "all" else (_scope(a),)).fetchall()
    for i, k, n, t, s in rows:
        print("[%d] %s x%d: %s" % (i, k, n, " ".join(t.split())[:240]))
    if not rows:
        print("inbox empty")


def cmd_reflect(a):
    """Self-improvement agenda. The agent works through it and records outcomes."""
    scope = _scope(a)
    with core.db() as c:
        rows = c.execute("select id, kind, count, text from inbox where status='open' and scope in (?, 'global')"
                         " order by count desc, ts desc limit 25", (scope,)).fetchall()
        due = tree.pending(c, scope)
        c.row_factory = sqlite3.Row
        stale = [dict(r) for r in c.execute(
            "select * from notes where scope=? and invalid_at is null and hits=0 and reinforced=0"
            " and ts < ? and pinned=0 order by ts limit 8", (scope, time.time() - 60 * 86400))]
        c.row_factory = None
    print("# Reflect — %s\n" % core.scope_name(scope))
    print("For each item: find the concrete cause, then do ONE of: `mem note -k lesson \"when X do Y because Z\"`,"
          " `mem supersede`, fix the code/skill, or dismiss. Then `mem inbox done <ids>`. Lessons must name a"
          " destination (a rule, an area skill, a script) — vague lessons are worse than none.\n")
    for i, k, n, t in rows:
        print("[%d] %s x%d: %s" % (i, k, n, " ".join(t.split())[:300]))
    if stale:
        print("\nPossibly stale (60+ days, never used) — verify against the code, then keep/supersede/forget:")
        for r in stale:
            print("  " + core.fmt(r, 200))
    if due:
        print("\n%d naps due (`mem naps`)." % len(due))
    if not rows and not stale and not due:
        print("Nothing to reflect on. Memory is clean.")


def cmd_stats(a):
    with core.db() as c:
        n = c.execute("select count(*), sum(invalid_at is null) from notes").fetchone()
        kinds = c.execute("select kind, count(*) from notes where invalid_at is null group by kind order by 2 desc").fetchall()
        scopes = c.execute("select scope, count(*) from notes group by scope order by 2 desc limit 15").fetchall()
        s = c.execute("select count(*) from summaries").fetchone()[0]
        ib = c.execute("select kind, count(*) from inbox where status='open' group by kind").fetchall()
    print("notes: %d total, %d valid; summaries: %d; log: %s (%.1f KB)" % (
        n[0], n[1] or 0, s, core.log_path(), core.log_path().stat().st_size / 1024 if core.log_path().exists() else 0))
    print("kinds:", ", ".join("%s=%d" % k for k in kinds))
    print("inbox:", ", ".join("%s=%d" % k for k in ib) or "empty")
    for sc, k in scopes:
        print("  %5d  %s" % (k, core.scope_name(sc)))


def cmd_doctor(a):
    problems = []
    try:
        with core.db() as c:
            ok = c.execute("pragma integrity_check").fetchone()[0]
            if ok != "ok":
                problems.append("index integrity: " + ok)
            n_db = c.execute("select count(*) from notes").fetchone()[0]
    except Exception as e:
        problems.append("index unreadable: %s" % e)
        n_db = -1
    n_log = 0
    if core.log_path().exists():
        with open(core.log_path(), encoding="utf-8") as f:
            n_log = sum(1 for l in f if '"op": "note"' in l)
    if n_db != n_log:
        problems.append("index has %d notes, log has %d" % (n_db, n_log))
    errlog = core.data_dir() / "hook-errors.log"
    if errlog.exists() and errlog.stat().st_size:
        tail = errlog.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
        problems.append("hook errors logged (%s):\n    %s" % (errlog, "\n    ".join(tail)))
    # stale file references: notes mentioning paths that no longer exist
    with core.db() as c:
        roots = dict(c.execute("select scope, path from projects"))
        for nid, scope, text in c.execute("select id, scope, text from notes where invalid_at is null"):
            for m in re.findall(r"`([\w./\\-]+\.\w{1,5})`", text):
                base = Path(roots.get(scope, "")) if scope in roots else None
                if base and base.exists() and not (base / m).exists() and not Path(m).exists():
                    problems.append("#%d mentions `%s`, which no longer exists in %s (stale? supersede it)" % (nid, m, base.name))
        dups = c.execute("select a.id, b.id from notes a join notes b on a.scope=b.scope and a.id<b.id and"
                         " a.text=b.text and a.invalid_at is null and b.invalid_at is null limit 20").fetchall()
        for x, y in dups:
            problems.append("exact duplicate #%d = #%d (mem supersede %d --by %d)" % (x, y, x, y))
    if a.fix:
        if any(p.startswith(("index", "index has")) for p in problems):
            print("rebuilt index from log: %d events" % core.rebuild())
        if errlog.exists():
            errlog.rename(errlog.with_suffix(".log.%d" % int(time.time())))
    print("\n".join("- " + p for p in problems) if problems else "healthy")


def cmd_rebuild(a):
    print("replayed %d events into a fresh index" % core.rebuild())


def cmd_bias(a):
    text = " ".join(a.text)
    scope = _scope(a)
    with core.db() as c:
        hits = core.search(c, text, scopes=[scope, "global"], limit=8)
        dec = core.search(c, text, scopes=None, limit=6, kinds=["decision", "mistake", "lesson", "experiment"])
    print("# Bias check: %s\n" % text)
    print("Anchors — past memories that may pull the answer (evidence, not constraints):")
    for r in hits:
        print("  " + core.fmt(r, 200))
    if dec:
        print("Past decisions / failures across ALL projects worth checking:")
        for r in dec:
            print("  " + core.fmt(r, 200) + "  {%s}" % core.scope_name(r["scope"]))
    print("\n" + wake.BIAS_PROTOCOL)
    print("\nTip: answer once WITHOUT the anchors above, then once with them; report where they differ.")


def cmd_config(a):
    if not a.kv:
        print(json.dumps(core.config(), indent=1))
        return
    for kv in a.kv:
        k, _, v = kv.partition("=")
        if k not in core.DEFAULTS:
            raise SystemExit("unknown key %s (known: %s)" % (k, ", ".join(core.DEFAULTS)))
        if v == "":
            core.set_config(k, None)
        else:
            d = core.DEFAULTS[k]
            core.set_config(k, (v.lower() in ("1", "true", "yes")) if isinstance(d, bool) else type(d)(v))
    print(json.dumps(core.config(), indent=1))


def cmd_project(a):
    if a.action == "new":
        out = projects.new(a.paths[0], kind=a.kind, purpose=a.purpose or "",
                           areas=[x for x in (a.areas or "").split(",") if x])
        print("created:\n  " + "\n  ".join(out))
    elif a.action == "scan":
        print(json.dumps(projects.scan(a.paths[0] if a.paths else "."), indent=1))
    elif a.action == "migrate":
        out = projects.migrate(a.paths[0] if a.paths else ".", purpose=a.purpose or "")
        print("added (nothing overwritten):\n  " + "\n  ".join(out))
    elif a.action == "monorepo":
        print(projects.monorepo_plan(a.paths[0], a.paths[1:]))
    elif a.action == "list":
        with core.db() as c:
            for scope, path, name, last, n in c.execute(
                    "select p.scope, p.path, p.name, p.last_seen, (select count(*) from notes where scope=p.scope)"
                    " from projects p order by last_seen desc"):
                print("%-24s %4d notes  last %s  %s" % (name, n, time.strftime("%Y-%m-%d", time.localtime(last or 0)), path))


def cmd_import(a):
    print("imported %d memories from ~/.claude/projects/*/memory" % projects.import_claude(
        only=None if a.all else core.current_scope()))


def cmd_graph(a):
    print(projects.graph("json" if a.json else "mermaid"))


def cmd_task(a):
    root = core.find_root()
    if a.action == "list":
        print(tasks.listing(root))
    else:
        print(tasks.op(root, a.action, " ".join(a.text), owner=a.owner, files=a.files or ""))


def cmd_kb(a):
    root = core.find_root()
    if a.action == "check":
        d = tasks.kb_check(root)
        print("duplicate ids: " + ", ".join(d) if d else "kb ids unique")
    else:
        if len(a.args) < 2:
            raise SystemExit('usage: mem kb new <area> "<title>" --verdict .. --evidence ..')
        kid = tasks.kb_new(root, a.args[0], " ".join(a.args[1:]), a.verdict, a.evidence or "", a.repro or "",
                           a.supersedes or "")
        core.note("%s %s: %s — verdict %s" % (kid, a.args[0], " ".join(a.args[1:]), a.verdict),
                  core.scope_key(root), kind="experiment", importance=3, force=True)
        print("wrote %s to docs/kb/README.md" % kid)


def cmd_chat(a):
    import os
    from . import chat
    scope = _scope(a)
    me = a.as_ or os.environ.get("MEM_AGENT") or "main"
    args = a.args
    if a.action == "post":
        if len(args) < 2:
            raise SystemExit('usage: mem chat post <channel> "text" --as <agent> [--kind decision|blocker|done|question]')
        i = chat.post(scope, args[0], me, " ".join(args[1:]), kind=a.kind)
        print("posted %d to #%s as %s" % (i, args[0].lstrip("#"), me))
    elif a.action == "read":
        lines = chat.read(scope, me, args[0] if args else None, all_=a.all)
        m = chat.mentions(scope, me)
        NL = chr(10)
        print(NL.join(lines) if lines else "(no unread messages)")
        if m:
            print(NL + "mentions of @%s:" % me + NL + NL.join(m))
    elif a.action == "mentions":
        print(chr(10).join(chat.mentions(scope, me)) or "(no new mentions)")
    elif a.action == "channels":
        print(chr(10).join(chat.channels(scope)) or "(no channels yet)")
    elif a.action == "claim":
        print(chr(10).join(chat.claim(scope, me, args, note=a.note or "")))
    elif a.action == "release":
        print("released %d" % chat.release(scope, me, args or None))
    elif a.action == "who":
        print(chr(10).join(chat.who(scope)) or "(no live claims)")
    elif a.action == "digest":
        print(chat.digest(scope) or "(quiet)")


def cmd_code(a):
    from . import atlas
    root = Path(a.path).resolve() if a.path else core.find_root()
    scope = core.scope_key(root) if a.path else _scope(a)
    q = " ".join(a.args)
    act = a.action
    if act != "index" and not atlas.exists(scope):
        print("indexing %s first…" % root)
        print(atlas.index(root, scope))
    if act == "index":
        if a.bg:  # detached background run from a hook: bounded, silent, always releases its lock
            try:
                for _ in range(20):  # up to ~20 x 15s slices, so huge repos converge in one go
                    st = atlas.index(root, scope, budget_s=15)
                    if not st.get("partial"):
                        break
            except Exception:
                import traceback
                with open(core.data_dir() / "hook-errors.log", "a", encoding="utf-8") as f:
                    f.write("%s bg-index %s\n%s\n" % (time.strftime("%F %T"), root, traceback.format_exc()))
            finally:
                if a.lock:
                    Path(a.lock).unlink(missing_ok=True)
            return
        print(atlas.index(root, scope, full=a.full))
    elif act == "find":
        for s in atlas.find(scope, q, limit=a.n):
            print("%-38s %s %s  %s" % (atlas.loc(s), s["kind"], s["qual"], (s["sig"] or "")[:80]))
    elif act == "search":
        print(atlas.format_hits(atlas.search(scope, q, limit=a.n)) or "nothing found")
    elif act == "explain":
        print(atlas.explain(scope, q, src_lines=a.lines))
    elif act == "flow":
        txt, mm = atlas.flow(scope, q, depth=a.depth)
        print(txt + ("\n\n" + mm if mm else ""))
    elif act == "map":
        print(atlas.overview(scope))
    elif act == "graph":
        print(atlas.module_graph(scope))
    elif act == "brief":
        print(atlas.brief(scope, q))
    elif act == "site":
        from . import site
        out = site.build(scope, atlas.root_of(scope), Path(q) if q else None)
        print("site written: %s (open it in a browser; offline, single file)" % out)
    elif act == "docs":
        print(write_arch_doc(scope))


GEN_BEGIN, GEN_END = "<!-- generated:begin (mem code docs) -->", "<!-- generated:end -->"


def write_arch_doc(scope) -> str:
    """docs/ARCHITECTURE.md: generated facts between markers; human text outside is preserved."""
    from . import atlas
    root = atlas.root_of(scope)
    p = root / "docs" / "ARCHITECTURE.md"
    gen = "%s\n_Generated from the code index on %s. Do not edit inside these markers._\n\n%s\n\n## Module graph\n%s\n%s" % (
        GEN_BEGIN, time.strftime("%Y-%m-%d"), atlas.overview(scope), atlas.module_graph(scope), GEN_END)
    if p.exists():
        cur = p.read_text(encoding="utf-8")
        if GEN_BEGIN in cur and GEN_END in cur:
            a_, b_ = cur.index(GEN_BEGIN), cur.index(GEN_END) + len(GEN_END)
            new = cur[:a_] + gen + cur[b_:]
        else:
            new = cur.rstrip() + "\n\n" + gen + "\n"
    else:
        new = ("# Architecture\n\n## Overview (human-written)\nTODO: the big picture in a few paragraphs: what the system does,"
               " the main flow, why it is shaped this way (link ADRs).\n\n" + gen + "\n")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new, encoding="utf-8")
    return "wrote %s" % p


def cmd_adr(a):
    from . import adr
    root = core.find_root()
    if a.action == "new":
        r = adr.new(root, " ".join(a.args), a.context or "", a.decision or "", a.alternatives or "",
                    a.consequences or "", a.affects or "", a.status, a.supersedes or "")
        print("wrote %s %s — fill any TODO sections" % (r["id"], r["path"]))
    elif a.action == "list":
        for x in adr.all_(root):
            print("%s [%s] %s  (%s)  affects: %s" % (x["id"], x["status"], x["title"], x["date"], ", ".join(x["affects"]) or "-"))
    elif a.action == "check":
        probs = adr.check(root, core.scope_key(root))
        print("\n".join("- " + p for p in probs) if probs else "ADRs consistent with the code")
    elif a.action == "show":
        for x in adr.all_(root):
            if x["id"].lower() == (a.args[0] if a.args else "").lower():
                print(x["text"])


def cmd_term(a):
    from . import learn
    root = core.find_root()
    if a.action == "add":
        if not a.args or not a.what:
            raise SystemExit('usage: mem term add "Term" --what ".." [--why ..] [--analogy ..] [--how file:line] [--see ..]')
        print(learn.add(root, " ".join(a.args), a.what, a.why or "", a.analogy or "", a.how or "", a.see or ""))
    elif a.action == "list":
        for t, g in sorted(learn.load(root).items()):
            print("%s%s: %s" % (t, " (known)" if learn.known(t) else "", g.get("what", "")))
    elif a.action == "candidates":
        for t, n in learn.candidates(core.current_scope(), root):
            print("%4d  %s" % (n, t))


def cmd_learned(a):
    from . import learn
    learn.mark_known(a.terms, level=a.level)
    print("learner profile: user %s %s" % (a.level, ", ".join(a.terms)))


def cmd_explain(a):
    from . import atlas, learn
    root = core.find_root()
    scope = core.scope_key(root)
    if not atlas.exists(scope):
        atlas.index(root, scope)
    print(learn.pack(" ".join(a.question), scope, root))


def cmd_hook(a):
    from . import hooks
    hooks.run(a.name)


def build():
    p = argparse.ArgumentParser(prog="mem", add_help=False)
    sub = p.add_subparsers(dest="cmd")

    def add(name, fn, *aliases):
        s = sub.add_parser(name, aliases=list(aliases), add_help=False)
        s.set_defaults(fn=fn)
        s.add_argument("--scope")
        s.add_argument("-g", action="store_true", help="global scope")
        return s

    s = add("note", cmd_note, "n", "remember")
    s.add_argument("text", nargs="+"); s.add_argument("-k", default="fact"); s.add_argument("-i", type=int, default=2)
    s.add_argument("-t"); s.add_argument("--force", action="store_true"); s.add_argument("--pin", action="store_true")
    s = add("idea", cmd_idea); s.add_argument("text", nargs="+"); s.add_argument("-i", type=int, default=2)
    s = add("recall", cmd_recall, "r", "search"); s.add_argument("words", nargs="*"); s.add_argument("-a", action="store_true")
    s.add_argument("-x"); s.add_argument("-n", type=int, default=12); s.add_argument("--history", action="store_true")
    s = add("get", cmd_get); s.add_argument("ids", nargs="+")
    s = add("timeline", cmd_timeline); s.add_argument("id"); s.add_argument("-w", type=int, default=4)
    s = add("zoom", cmd_zoom); s.add_argument("range")
    add("view", cmd_view, "wake")
    add("naps", cmd_naps)
    s = add("nap", cmd_nap); s.add_argument("range"); s.add_argument("text", nargs="+")
    s = add("unnap", cmd_unnap); s.add_argument("range")
    s = add("supersede", cmd_supersede); s.add_argument("old"); s.add_argument("text", nargs="*")
    s.add_argument("--by"); s.add_argument("-k")
    for op in ("forget", "restore", "pin"):
        s = add(op, _simple(op)); s.add_argument("id")
    s = add("unpin", _simple("pin", value=0)); s.add_argument("id")
    s = add("importance", cmd_importance); s.add_argument("id"); s.add_argument("value", type=int)
    s = add("link", cmd_link); s.add_argument("a"); s.add_argument("b"); s.add_argument("rel", nargs="?", default="related")
    add("rules", cmd_rules)
    s = add("inbox", cmd_inbox); s.add_argument("action", nargs="?", default="list"); s.add_argument("ids", nargs="*")
    add("reflect", cmd_reflect)
    add("stats", cmd_stats)
    s = add("doctor", cmd_doctor); s.add_argument("--fix", action="store_true")
    add("rebuild", cmd_rebuild)
    s = add("bias", cmd_bias); s.add_argument("text", nargs="+")
    s = add("config", cmd_config); s.add_argument("kv", nargs="*")
    s = add("project", cmd_project); s.add_argument("action", choices=["new", "scan", "migrate", "monorepo", "list"])
    s.add_argument("paths", nargs="*"); s.add_argument("--kind", default="python", choices=["python", "monorepo", "generic"])
    s.add_argument("--purpose"); s.add_argument("--areas")
    s = add("import-claude", cmd_import); s.add_argument("--all", action="store_true")
    s = add("graph", cmd_graph); s.add_argument("--json", action="store_true")
    s = add("task", cmd_task); s.add_argument("action", choices=["park", "start", "done", "drop", "list"])
    s.add_argument("text", nargs="*"); s.add_argument("--owner", default="main"); s.add_argument("--files")
    s = add("kb", cmd_kb); s.add_argument("action", choices=["new", "check"]); s.add_argument("args", nargs="*")
    s.add_argument("--verdict", default="open"); s.add_argument("--evidence"); s.add_argument("--repro")
    s.add_argument("--supersedes")
    s = add("chat", cmd_chat); s.add_argument("action", choices=["post", "read", "mentions", "channels", "claim",
                                                                "release", "who", "digest"])
    s.add_argument("args", nargs="*"); s.add_argument("--as", dest="as_"); s.add_argument("--kind", default="msg")
    s.add_argument("--all", action="store_true"); s.add_argument("--note")
    s = add("code", cmd_code); s.add_argument("action", choices=["index", "find", "search", "explain", "flow", "map",
                                                                "graph", "brief", "site", "docs"])
    s.add_argument("args", nargs="*"); s.add_argument("--path"); s.add_argument("--full", action="store_true")
    s.add_argument("-n", type=int, default=15); s.add_argument("--depth", type=int, default=3)
    s.add_argument("--lines", type=int, default=60)
    s.add_argument("--bg", action="store_true"); s.add_argument("--lock")
    s = add("adr", cmd_adr); s.add_argument("action", choices=["new", "list", "check", "show"]); s.add_argument("args", nargs="*")
    for f in ("context", "decision", "alternatives", "consequences", "affects", "supersedes"):
        s.add_argument("--" + f)
    s.add_argument("--status", default="accepted")
    s = add("term", cmd_term); s.add_argument("action", choices=["add", "list", "candidates"]); s.add_argument("args", nargs="*")
    for f in ("what", "why", "analogy", "how", "see"):
        s.add_argument("--" + f)
    s = add("learned", cmd_learned); s.add_argument("terms", nargs="+"); s.add_argument("--level", default="knows")
    s = add("explain", cmd_explain); s.add_argument("question", nargs="+")
    s = add("hook", cmd_hook); s.add_argument("name")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(HELP)
        return
    a = build().parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
