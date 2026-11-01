"""Core store: append-only event log (truth) + SQLite FTS5 index (rebuildable cache).

Design (borrowed and merged):
- OptMem: append-only log is ground truth; everything else is a cache.
- Zep/Graphiti: bi-temporal facts -- superseding never deletes, it invalidates.
- mem0: write-time ADD / REINFORCE (noop) / SIMILAR (suggest supersede) decision.
- Generative Agents: score = recency + importance + relevance (+ heat).
- A-MEM / Basic Memory: [[#id]] links and #tags form a graph.
- claude-mem: <private>...</private> is stripped before anything is stored.
"""
from __future__ import annotations

import atexit
import json
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path

# ------------------------------------------------------------------ paths

def home() -> Path:
    p = Path(os.environ.get("INFINITE_HOME") or Path.home() / ".claude" / "infinite")
    return p


def data_dir() -> Path:
    d = home() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path() -> Path:
    return data_dir() / "log.jsonl"


def db_path() -> Path:
    return data_dir() / "index.db"


DEFAULTS = {
    "wake_lines": 60,          # tree lines per scope printed at wake (reading budget)
    "wake_chars": 9000,        # hard cap for SessionStart context (Claude caps at 10k)
    "prompt_chars": 1800,      # cap for per-prompt recall context
    "prompt_hits": 5,
    "note_chars": 400,
    "rule_threshold": 2,       # reinforcements before a lesson/pref becomes a RULE
    "stop_reflect": True,      # Stop hook asks once per session to record lessons after corrections
    "nap_min": 2,              # smallest block that gets summarized
    "verify_claims": True,     # Stop/SubagentStop: check cited paths/symbols exist; wake the agent up if not
    "auto_index": True,        # SessionStart/Stop keep the code atlas fresh (time-boxed, incremental)
    "prompt_code_hits": 4,     # code/doc locations injected per prompt (0 = off)
}


def config() -> dict:
    cfg = dict(DEFAULTS)
    p = home() / "config.json"
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def set_config(key: str, value):
    p = home() / "config.json"
    cur = {}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    if value is None:
        cur.pop(key, None)
    else:
        cur[key] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ text

STOP = set("""a an and are as at be but by for from has have i if in into is it its of on or
that the their then there these this to was we were will with you your not no yes do does
o a os as um uma de da do das dos e em no na nos nas para por com que se ao aos é ser ter
mais mas como já foi são está isso esse essa este esta eu voce você ele ela""".split())

NEG = re.compile(r"\b(not|never|no longer|don'?t|doesn'?t|isn'?t|aren'?t|won'?t|stop|avoid|não|nao|nunca|jamais|evite|evitar|pare)\b", re.I)
PRIVATE = re.compile(r"<private>.*?</private>", re.S | re.I)
TAG = re.compile(r"(?<![\w#])#([A-Za-z][\w\-/]{1,40})")
LINK = re.compile(r"\[\[#?(\d+)\]\]")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]{2,}", fold(s)) if t not in STOP]


def jaccard(a: str, b: str) -> float:
    A, B = set(tokens(a)), set(tokens(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def clean(text: str) -> str:
    text = PRIVATE.sub("[private]", text)
    return " ".join(text.split())


def fts_query(text: str, limit: int = 12) -> str:
    seen, out = set(), []
    for t in tokens(text):
        if t not in seen and not t.isdigit():
            seen.add(t)
            out.append('"%s"' % t)
        if len(out) >= limit:
            break
    return " OR ".join(out)


# ------------------------------------------------------------------ scope

def scope_key(path: str | os.PathLike) -> str:
    """Same scheme Claude Code uses for ~/.claude/projects/<key>."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def find_root(start: str | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and not start:
        return Path(env).resolve()
    p = Path(start or os.getcwd()).resolve()
    known = set()
    try:
        with db() as c:
            known = {r[0] for r in c.execute("select path from projects")}
    except Exception:
        pass
    for q in [p, *p.parents]:
        if str(q) in known or (q / ".git").exists() or (q / "CLAUDE.md").exists():
            if q == Path.home():
                break
            return q
    return p


def current_scope(cwd: str | None = None) -> str:
    return scope_key(find_root(cwd))


# ------------------------------------------------------------------ db

SCHEMA = """
create table if not exists notes(
  id integer primary key, uid text unique, ts real, scope text, pos integer,
  kind text, text text, tags text, importance integer default 2,
  valid_from real, invalid_at real, superseded_by integer,
  hits integer default 0, last_hit real, reinforced integer default 0,
  pinned integer default 0, source text);
create index if not exists notes_scope on notes(scope, pos);
create virtual table if not exists notes_fts using fts5(text, tags, tokenize="unicode61 remove_diacritics 2");
create table if not exists summaries(scope text, lo integer, hi integer, text text, ts real,
  primary key(scope, lo, hi));
create table if not exists links(src integer, dst integer, rel text, primary key(src, dst, rel));
create table if not exists inbox(id integer primary key, ts real, scope text, kind text,
  text text, sig text, count integer default 1, status text default 'open', session text);
create index if not exists inbox_sig on inbox(sig);
create table if not exists projects(scope text primary key, path text, name text,
  first_seen real, last_seen real, sessions integer default 0);
create table if not exists meta(key text primary key, value text);
"""


def _connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, timeout=30, isolation_level=None)
    c.execute("pragma journal_mode=wal")
    c.execute("pragma synchronous=normal")
    c.execute("pragma temp_store=memory")
    c.execute("pragma cache_size=-8000")
    c.executescript(SCHEMA)
    return c


_local = threading.local()
atexit.register(lambda: close_all())


@contextmanager
def db():
    """Per-thread cached connection: schema/pragmas run once per process, not per call."""
    path = db_path()
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    c = cache.get(path)
    if c is None:
        c = cache[path] = _connect(path)
    try:
        yield c
    finally:
        c.row_factory = None
        if c.in_transaction:
            c.execute("rollback")


def close_all():
    for c in getattr(_local, "conns", {}).values():
        try:
            c.close()
        except Exception:
            pass
    _local.conns = {}


@contextmanager
def tx(c: sqlite3.Connection):
    c.execute("begin immediate")
    try:
        yield c
        c.execute("commit")
    except BaseException:
        c.execute("rollback")
        raise


def meta_get(c, key, default=None):
    r = c.execute("select value from meta where key=?", (key,)).fetchone()
    return r[0] if r else default


def meta_set(c, key, value):
    c.execute("insert or replace into meta values(?,?)", (key, str(value)))


# ------------------------------------------------------------------ events
# Every mutation that matters is an event in log.jsonl; apply() replays it.
# rebuild() = delete index.db, replay the log. That is the self-repair path.

def _append(ev: dict):
    with open(log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def apply(c, ev: dict):
    op = ev["op"]
    if op == "note":
        pos = c.execute("select coalesce(max(pos),-1)+1 from notes where scope=?", (ev["scope"],)).fetchone()[0]
        cur = c.execute(
            "insert into notes(uid,ts,scope,pos,kind,text,tags,importance,valid_from,source,pinned)"
            " values(?,?,?,?,?,?,?,?,?,?,?)",
            (ev["uid"], ev["ts"], ev["scope"], pos, ev["kind"], ev["text"], ev.get("tags", ""),
             ev.get("importance", 2), ev["ts"], ev.get("source", ""), ev.get("pinned", 0)))
        nid = cur.lastrowid
        c.execute("insert into notes_fts(rowid,text,tags) values(?,?,?)", (nid, ev["text"], ev.get("tags", "")))
        for dst in LINK.findall(ev["text"]):
            c.execute("insert or ignore into links values(?,?,?)", (nid, int(dst), "mentions"))
        return nid
    nid = _id(c, ev.get("uid"))
    if op == "supersede":
        new = _id(c, ev["new_uid"])
        c.execute("update notes set invalid_at=?, superseded_by=? where id=?", (ev["ts"], new, nid))
        c.execute("insert or ignore into links values(?,?,?)", (new, nid, "supersedes"))
        _invalidate_summaries(c, nid)
    elif op == "forget":
        c.execute("update notes set invalid_at=? where id=?", (ev["ts"], nid))
        _invalidate_summaries(c, nid)
    elif op == "restore":
        c.execute("update notes set invalid_at=null, superseded_by=null where id=?", (nid,))
        _invalidate_summaries(c, nid)
    elif op == "reinforce":
        c.execute("update notes set reinforced=reinforced+1, last_hit=? where id=?", (ev["ts"], nid))
    elif op == "pin":
        c.execute("update notes set pinned=? where id=?", (ev.get("value", 1), nid))
    elif op == "importance":
        c.execute("update notes set importance=? where id=?", (ev["value"], nid))
    elif op == "link":
        c.execute("insert or ignore into links values(?,?,?)", (nid, _id(c, ev["dst_uid"]), ev.get("rel", "related")))
    elif op == "summary":
        c.execute("insert or replace into summaries values(?,?,?,?,?)",
                  (ev["scope"], ev["lo"], ev["hi"], ev["text"], ev["ts"]))
    elif op == "unsummary":
        c.execute("delete from summaries where scope=? and lo=? and hi=?", (ev["scope"], ev["lo"], ev["hi"]))
    return nid


def _id(c, uid):
    if uid is None:
        return None
    r = c.execute("select id from notes where uid=?", (uid,)).fetchone()
    if not r:
        raise KeyError(uid)
    return r[0]


def _uid(c, nid: int) -> str:
    r = c.execute("select uid from notes where id=?", (nid,)).fetchone()
    if not r:
        raise SystemExit("no memory #%s" % nid)
    return r[0]


def _invalidate_summaries(c, nid):
    r = c.execute("select scope,pos from notes where id=?", (nid,)).fetchone()
    if r:
        c.execute("delete from summaries where scope=? and lo<=? and hi>?", (r[0], r[1], r[1]))


def emit(c, ev: dict):
    """Apply and log atomically (under the sqlite write lock)."""
    ev.setdefault("ts", time.time())
    with tx(c):
        out = apply(c, ev)
        _append(ev)
    return out


def rebuild() -> int:
    """Replay the log into a fresh index. Deletes the file when possible (fixes real corruption);
    if another connection holds it (Windows), resets the tables in place instead."""
    close_all()
    p = db_path()
    try:
        for suffix in ("", "-wal", "-shm"):
            q = Path(str(p) + suffix)
            if q.exists():
                q.unlink()
    except PermissionError:
        with db() as c:
            with tx(c):
                for t in ("notes", "notes_fts", "summaries", "links"):
                    c.execute("delete from %s" % t)
    n = 0
    with db() as c:
        with tx(c):
            if log_path().exists():
                with open(log_path(), encoding="utf-8") as f:
                    lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        apply(c, json.loads(line))
                        n += 1
                    except Exception:
                        continue  # a torn/corrupt line is skipped, never fatal
    return n


# ------------------------------------------------------------------ notes

KINDS = ("fact", "decision", "lesson", "pref", "mistake", "idea", "todo", "experiment",
         "insight", "person", "project", "ref", "report")
RULE_KINDS = ("lesson", "pref", "mistake")


def note(text: str, scope: str, kind: str = "fact", importance: int = 2, source: str = "agent",
         tags: list[str] | None = None, force: bool = False, pinned: bool = False) -> dict:
    """mem0-style write decision: NOOP/REINFORCE duplicates, flag near-duplicates and
    likely contradictions, otherwise ADD."""
    cfg = config()
    text = clean(text)
    if not text:
        raise SystemExit("empty memory")
    if len(text) > cfg["note_chars"]:
        raise SystemExit("memory is %d chars; max %d. One fact per note: split or tighten it."
                         % (len(text), cfg["note_chars"]))
    tags = sorted(set((tags or []) + [t.lower() for t in TAG.findall(text)]))
    with db() as c:
        similar = []
        if not force:
            for row in search(c, text, scopes=[scope, "global"], limit=6, valid_only=True):
                s = jaccard(text, row["text"])
                if s >= 0.30:
                    similar.append((s, row))
            similar.sort(key=lambda x: -x[0])
            if similar and similar[0][0] >= 0.85:
                row = similar[0][1]
                emit(c, {"op": "reinforce", "uid": row["uid"]})
                n = row["reinforced"] + 1
                msg = "Already known as #%d (reinforced x%d)." % (row["id"], n)
                if row["kind"] in RULE_KINDS and n == cfg["rule_threshold"]:
                    msg += " It is now a RULE shown at every wake."
                return {"status": "reinforced", "id": row["id"], "message": msg}
        uid = uuid.uuid4().hex[:12]
        nid = emit(c, {"op": "note", "uid": uid, "scope": scope, "kind": kind, "text": text,
                       "tags": " ".join(tags), "importance": max(1, min(5, importance)),
                       "source": source, "pinned": int(pinned)})
        out = {"status": "added", "id": nid, "message": "Saved #%d." % nid, "similar": []}
        for s, row in similar[:3]:
            contra = bool(NEG.search(text)) != bool(NEG.search(row["text"]))
            label = "possible CONTRADICTION" if contra else "similar"
            out["similar"].append("%s #%d (%.0f%%): %s" % (label, row["id"], s * 100, row["text"][:140]))
            if contra:
                inbox_add(c, scope, "conflict", "#%d vs #%d: %s | %s" % (nid, row["id"], text[:120], row["text"][:120]),
                          sig="conflict:%d:%d" % (min(nid, row["id"]), max(nid, row["id"])))
        return out


def supersede(old: int, new_text: str | None, scope: str, kind: str | None = None, new_id: int | None = None) -> str:
    with db() as c:
        r = c.execute("select kind, importance, scope from notes where id=?", (old,)).fetchone()
        if not r:
            raise SystemExit("no memory #%d" % old)
        if new_id is None:
            uid = uuid.uuid4().hex[:12]
            new_id = emit(c, {"op": "note", "uid": uid, "scope": r[2] if scope is None else scope,
                              "kind": kind or r[0], "text": clean(new_text), "importance": r[1],
                              "source": "supersede"})
        emit(c, {"op": "supersede", "uid": _uid(c, old), "new_uid": _uid(c, new_id)})
        with tx(c):
            c.execute("update inbox set status='done' where status='open' and kind='conflict' and"
                      " (sig like ? or sig like ?)", ("conflict:%d:%%" % old, "conflict:%%:%d" % old))
        return "#%d superseded by #%d (old kept in history, hidden from wake)." % (old, new_id)


def simple_event(op: str, nid: int, **kw) -> None:
    with db() as c:
        emit(c, {"op": op, "uid": _uid(c, nid), **kw})


def get(c, ids):
    q = "select * from notes where id in (%s)" % ",".join("?" * len(ids))
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(q, list(ids))]
    c.row_factory = None
    now = time.time()
    with tx(c):
        c.executemany("update notes set hits=hits+1, last_hit=? where id=?", [(now, r["id"]) for r in rows])
    return rows


def score(row: dict, rel: float, now: float) -> float:
    """Generative-Agents style: recency + importance + relevance, plus heat and rule boosts."""
    last = max(row["ts"], row.get("last_hit") or 0)
    hours = max(0.0, (now - last) / 3600)
    recency = 0.995 ** hours
    importance = (row["importance"] or 2) / 5
    heat = 1 - math.exp(-((row["hits"] or 0) + 2 * (row["reinforced"] or 0)) / 5)
    return rel + 0.6 * recency + 0.8 * importance + 0.4 * heat + (0.5 if row["pinned"] else 0)


def search(c, query: str, scopes: list[str] | None = None, limit: int = 10, valid_only: bool = True,
           kinds: list[str] | None = None) -> list[dict]:
    q = fts_query(query)
    if not q:
        return []
    sql = ("select n.*, bm25(notes_fts, 1.0, 0.5) as bm from notes_fts join notes n on n.id = notes_fts.rowid"
           " where notes_fts match ?")
    args: list = [q]
    if scopes:
        sql += " and n.scope in (%s)" % ",".join("?" * len(scopes))
        args += scopes
    if valid_only:
        sql += " and n.invalid_at is null"
    if kinds:
        sql += " and n.kind in (%s)" % ",".join("?" * len(kinds))
        args += kinds
    sql += " order by bm limit ?"
    args.append(limit * 4)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(sql, args)]
    except sqlite3.OperationalError:
        rows = []
    finally:
        c.row_factory = None
    if not rows:
        return []
    bms = [-r["bm"] for r in rows]
    lo, hi = min(bms), max(bms)
    now = time.time()
    for r, b in zip(rows, bms):
        rel = 1.0 if hi == lo else (b - lo) / (hi - lo)
        r["score"] = score(r, 1.5 * rel, now)
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def rules(c, scope: str, limit: int = 15) -> list[dict]:
    th = config()["rule_threshold"]
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "select * from notes where invalid_at is null and scope in (?, 'global') and"
        " (pinned=1 or (kind in ('lesson','pref','mistake') and (reinforced>=? or importance>=4)))"
        " order by pinned desc, importance desc, reinforced desc, ts desc limit ?", (scope, th, limit))]
    c.row_factory = None
    return rows


# ------------------------------------------------------------------ inbox (auto-harvested candidates)

def inbox_add(c, scope, kind, text, sig=None, session=None):
    sig = sig or "%s:%s" % (kind, " ".join(sorted(set(tokens(text))))[:160])
    r = c.execute("select id from inbox where sig=? and status='open'", (sig,)).fetchone()
    if r:
        c.execute("update inbox set count=count+1, ts=? where id=?", (time.time(), r[0]))
        return r[0]
    return c.execute("insert into inbox(ts,scope,kind,text,sig,session) values(?,?,?,?,?,?)",
                     (time.time(), scope, kind, text[:500], sig, session)).lastrowid


def fmt(row: dict, width: int = 0) -> str:
    t = row["text"]
    if width and len(t) > width:
        t = t[: width - 1] + "…"
    flag = ""
    if row.get("invalid_at"):
        flag = " (superseded by #%s)" % row["superseded_by"] if row.get("superseded_by") else " (forgotten)"
    day = time.strftime("%Y-%m-%d", time.localtime(row["ts"]))
    return "#%d %s [%s] %s%s" % (row["id"], day, row["kind"], t, flag)


def scope_name(scope: str) -> str:
    if scope == "global":
        return "global"
    with db() as c:
        r = c.execute("select name from projects where scope=?", (scope,)).fetchone()
    return r[0] if r else scope.rsplit("-", 1)[-1]
