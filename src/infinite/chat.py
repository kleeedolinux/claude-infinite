"""Team chat for agents (Slack-like), per project: channels, @mentions, per-agent
unread cursors, file claims (ownership locks), and a blackboard of shared decisions.

Subagents talk here instead of through the main agent's context, so a big project
can run many agents while the main agent (the "compositor") only reads summaries.
Separate DB (chat.db) so chatter never pollutes long-term memory.
"""
from __future__ import annotations

import fnmatch
import re
import sqlite3
import time
from contextlib import contextmanager

from . import core

SCHEMA = """
create table if not exists msgs(id integer primary key, ts real, scope text, channel text, author text,
  text text, kind text default 'msg');
create index if not exists msgs_ch on msgs(scope, channel, id);
create table if not exists cursors(scope text, agent text, channel text, last integer, primary key(scope, agent, channel));
create table if not exists claims(scope text, pattern text, agent text, ts real, note text, primary key(scope, pattern));
"""
MENTION = re.compile(r"@([\w\-]+)")
CLAIM_TTL = 4 * 3600


@contextmanager
def chatdb():
    c = sqlite3.connect(core.data_dir() / "chat.db", timeout=30, isolation_level=None)
    c.execute("pragma journal_mode=wal")
    c.executescript(SCHEMA)
    try:
        yield c
    finally:
        c.close()


def post(scope, channel, author, text, kind="msg") -> int:
    text = core.clean(text)[:4000]
    with chatdb() as c:
        return c.execute("insert into msgs(ts,scope,channel,author,text,kind) values(?,?,?,?,?,?)",
                         (time.time(), scope, channel.lstrip("#"), author, text, kind)).lastrowid


def _fmt(r) -> str:
    i, ts, ch, au, tx, kind = r
    tag = "" if kind == "msg" else "[%s] " % kind
    return "%d %s #%s <%s> %s%s" % (i, time.strftime("%H:%M", time.localtime(ts)), ch, au, tag, tx)


def read(scope, agent, channel=None, limit=40, all_=False) -> list[str]:
    """Unread messages for `agent` (and advance its cursor). channel=None: all channels + mentions."""
    with chatdb() as c:
        chans = [channel.lstrip("#")] if channel else [r[0] for r in c.execute(
            "select distinct channel from msgs where scope=?", (scope,))]
        out = []
        for ch in chans:
            last = 0 if all_ else (c.execute("select last from cursors where scope=? and agent=? and channel=?",
                                             (scope, agent, ch)).fetchone() or [0])[0]
            rows = c.execute("select id,ts,channel,author,text,kind from msgs where scope=? and channel=? and id>?"
                             " order by id desc limit ?", (scope, ch, last, limit)).fetchall()[::-1]
            if rows:
                out += rows
                c.execute("insert or replace into cursors values(?,?,?,?)", (scope, agent, ch, rows[-1][0]))
        out.sort()
        return [_fmt(r) for r in out[-limit:]]


def mentions(scope, agent, limit=30) -> list[str]:
    with chatdb() as c:
        last = (c.execute("select last from cursors where scope=? and agent=? and channel='@'", (scope, agent)).fetchone()
                or [0])[0]
        rows = c.execute("select id,ts,channel,author,text,kind from msgs where scope=? and id>? and text like ?"
                         " order by id limit ?", (scope, last, "%@" + agent + "%", limit)).fetchall()
        rows = [r for r in rows if agent in MENTION.findall(r[4]) or "all" in MENTION.findall(r[4])]
        if rows:
            c.execute("insert or replace into cursors values(?,?,?,?)", (scope, agent, "@", rows[-1][0]))
    return [_fmt(r) for r in rows]


def channels(scope) -> list[str]:
    with chatdb() as c:
        return ["#%s  %d msgs, last %s by %s" % (ch, n, time.strftime("%m-%d %H:%M", time.localtime(ts)), au)
                for ch, n, ts, au in c.execute(
                    "select channel, count(*), max(ts), (select author from msgs m2 where m2.scope=m.scope and"
                    " m2.channel=m.channel order by id desc limit 1) from msgs m where scope=? group by channel"
                    " order by max(ts) desc", (scope,))]


def claim(scope, agent, patterns: list[str], note="") -> list[str]:
    """Claim files/globs. Refuses overlaps with live claims of other agents."""
    now = time.time()
    msgs = []
    with chatdb() as c:
        c.execute("begin immediate")
        try:
            c.execute("delete from claims where ts < ?", (now - CLAIM_TTL,))
            live = c.execute("select pattern, agent from claims where scope=?", (scope,)).fetchall()
            for p in patterns:
                clash = [(q, a) for q, a in live if a != agent and (
                    fnmatch.fnmatch(p, q) or fnmatch.fnmatch(q, p) or p.startswith(q.rstrip("*")) or q.startswith(p.rstrip("*")))]
                if clash:
                    msgs.append("REFUSED %s: owned by %s" % (p, ", ".join("%s (%s)" % (a, q) for q, a in clash)))
                    continue
                c.execute("insert or replace into claims values(?,?,?,?,?)", (scope, p, agent, now, note))
                msgs.append("claimed %s" % p)
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise
    for m in msgs:
        if m.startswith("claimed"):
            post(scope, "claims", agent, m + ((" — " + note) if note else ""), kind="claim")
    return msgs


def release(scope, agent, patterns: list[str] | None = None) -> int:
    with chatdb() as c:
        if patterns:
            n = sum(c.execute("delete from claims where scope=? and agent=? and pattern=?", (scope, agent, p)).rowcount
                    for p in patterns)
        else:
            n = c.execute("delete from claims where scope=? and agent=?", (scope, agent)).rowcount
    post(scope, "claims", agent, "released %s" % (", ".join(patterns) if patterns else "all"), kind="claim")
    return n


def who(scope) -> list[str]:
    with chatdb() as c:
        c.execute("delete from claims where ts < ?", (time.time() - CLAIM_TTL,))
        return ["%-28s %-16s %s %s" % (p, a, time.strftime("%H:%M", time.localtime(ts)), n or "")
                for p, a, ts, n in c.execute("select pattern, agent, ts, note from claims where scope=? order by agent", (scope,))]


def digest(scope, limit=12) -> str:
    """Compact view for the compositor/wake: recent decisions + blockers + live claims."""
    with chatdb() as c:
        rows = c.execute("select id,ts,channel,author,text,kind from msgs where scope=? and ts > ? and"
                         " kind in ('decision','blocker','done','question') order by id desc limit ?",
                         (scope, time.time() - 3 * 86400, limit)).fetchall()[::-1]
    lines = [_fmt(r) for r in rows]
    w = who(scope)
    if w:
        lines.append("live claims: " + "; ".join(x.split()[0] + "=" + x.split()[1] for x in w[:10]))
    return "\n".join(lines)
