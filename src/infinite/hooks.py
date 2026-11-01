"""Claude Code hook entry points. Every hook fails silent (exit 0) — memory must
never block a session. Errors go to data/hook-errors.log for `mem doctor`."""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path

from . import core, harvest, wake


def _out(event: str, context: str | None = None, **extra):
    o = dict(extra)
    if context:
        o["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": context}
    if o:
        sys.stdout.write(json.dumps(o, ensure_ascii=True))


def _register(scope: str, root: Path):
    now = time.time()
    with core.db() as c:
        with core.tx(c):
            c.execute("insert into projects(scope,path,name,first_seen,last_seen,sessions) values(?,?,?,?,?,1)"
                      " on conflict(scope) do update set last_seen=excluded.last_seen, sessions=sessions+1, path=excluded.path",
                      (scope, str(root), root.name or str(root), now, now))


def _max_note(c) -> int:
    return c.execute("select coalesce(max(id),0) from notes").fetchone()[0]


def session_start(inp: dict):
    root = core.find_root(inp.get("cwd"))
    scope = core.scope_key(root)
    source = inp.get("source", "startup")
    sid = inp.get("session_id", "")
    if source != "compact":
        _register(scope, root)
    st = harvest.load_state(sid)
    st["scope"] = scope
    if st.get("notes_at_start") is None:
        with core.db() as c:
            st["notes_at_start"] = _max_note(c)
    harvest.save_state(st)
    _out("SessionStart", wake.wake(scope, root, source=source, session=sid))


def user_prompt(inp: dict):
    prompt = inp.get("prompt") or ""
    scope = core.current_scope(inp.get("cwd"))
    sid = inp.get("session_id", "")
    st = harvest.load_state(sid)
    ongoing = len(st.get("prompts", [])) >= 1
    harvest.record_prompt(st, prompt)
    if harvest.is_correction(prompt):
        st["corrections"] = st.get("corrections", 0) + 1
        with core.db() as c:
            with core.tx(c):
                core.inbox_add(c, scope, "correction", core.clean(prompt)[:400], session=sid)
    harvest.save_state(st)
    if len(prompt.strip()) < 4 or prompt.lstrip().startswith("/"):
        return
    ctx = wake.prompt_context(prompt, scope, ongoing=ongoing)
    if ctx:
        _out("UserPromptSubmit", ctx)


def pre_compact(inp: dict):
    sid = inp.get("session_id", "")
    scope = core.current_scope(inp.get("cwd"))
    harvest.harvest(inp.get("transcript_path"), scope, sid)
    st = harvest.load_state(sid)
    st["compactions"] = st.get("compactions", 0) + 1
    st["last_compact"] = time.time()
    harvest.save_state(st)


def post_compact(inp: dict):
    sid = inp.get("session_id", "")
    summ = inp.get("compact_summary") or ""
    if not summ:
        return
    scope = core.current_scope(inp.get("cwd"))
    d = core.data_dir() / "reports" / scope
    d.mkdir(parents=True, exist_ok=True)
    st = harvest.load_state(sid)
    p = d / ("compact-%s-%s-%d.md" % (time.strftime("%Y%m%d-%H%M"), sid[:8], st.get("compactions", 1)))
    p.write_text(summ, encoding="utf-8")
    st["compact_summary_path"] = str(p)
    harvest.save_state(st)


NL = chr(10)
WAKE_UP = ("Hallucination check: your final message cites things that do not exist in %s:" + NL + "%s" + NL +
           "Wake up and verify each one with tools (Glob/Grep/Read). Correct or remove wrong claims, and mark anything "
           "you could not verify as NOT verified. Then give the corrected final message.")


def _hallucinations(text: str, inp: dict) -> list[str]:
    if not core.config().get("verify_claims", True):
        return []
    from . import verify
    try:
        return verify.check(text, core.find_root(inp.get("cwd")))
    except Exception:
        return []


def _flag(scope: str, who: str, suspects: list[str], session: str, final: bool):
    with core.db() as c:
        with core.tx(c):
            core.inbox_add(c, scope, "hallucination", "%s: %s" % (who, "; ".join(suspects))[:500], session=session)
    try:
        from . import chat
        chat.post(scope, "plan", who, "@main %s report has %d unverified claim(s)%s: %s" % (
            who, len(suspects), " AFTER re-check — do not trust it" if final else " (sent back to verify)",
            "; ".join(suspects)[:600]), kind="blocker")
    except Exception:
        pass


def stop(inp: dict):
    sid = inp.get("session_id", "")
    scope = core.current_scope(inp.get("cwd"))
    harvest.harvest(inp.get("transcript_path"), scope, sid)
    cfg = core.config()
    text = inp.get("last_assistant_message") or ""
    if not inp.get("stop_hook_active") and text:
        sus = _hallucinations(text, inp)
        if sus:
            _flag(scope, "main", sus, sid, final=False)
            root = core.find_root(inp.get("cwd"))
            _out("Stop", None, decision="block", reason=WAKE_UP % (root, NL.join("- " + x for x in sus)))
            return
    if not cfg.get("stop_reflect") or inp.get("stop_hook_active"):
        return
    st = harvest.load_state(sid)
    if st.get("reflect_asked") or not st.get("corrections"):
        return
    with core.db() as c:
        wrote = _max_note(c) > (st.get("notes_at_start") or 0)
    if wrote:
        return
    st["reflect_asked"] = True
    harvest.save_state(st)
    _out("Stop", None, decision="block", reason=(
        "Memory check: the user corrected you %d time(s) this session and no memory was recorded. "
        "Record 1-3 concrete lessons (`mem note -k lesson \"when X, do Y, because Z\"`), then finish. "
        "If nothing is worth keeping, just finish." % st["corrections"]))


def subagent_stop(inp: dict):
    text = inp.get("last_assistant_message") or harvest.last_assistant_text(inp.get("agent_transcript_path"))
    if not text or len(text) < 80:
        return
    scope = core.current_scope(inp.get("cwd"))
    who = inp.get("agent_type") or "agent"
    sus = _hallucinations(text, inp)
    if sus:
        final = bool(inp.get("stop_hook_active"))
        _flag(scope, who, sus, inp.get("session_id", ""), final=final)
        if not final:  # wake the subagent up once to verify its own claims
            root = core.find_root(inp.get("cwd"))
            _out("SubagentStop", None, decision="block", reason=WAKE_UP % (root, NL.join("- " + x for x in sus)))
            return
    d = core.data_dir() / "reports" / scope
    d.mkdir(parents=True, exist_ok=True)
    name = "%s-%s-%s.md" % (time.strftime("%Y%m%d-%H%M%S"), who, (inp.get("agent_id") or "")[:8])
    body = text
    if sus:
        body = ("> UNVERIFIED CLAIMS (hallucination check failed after re-check):" + NL +
                NL.join("> - " + x for x in sus) + NL + NL + text)
    (d / name).write_text(body, encoding="utf-8")
    try:
        from . import chat
        first = " ".join(text.split())[:300]
        chat.post(scope, "reports", who, "%s%s … (full: %s)" % ("[UNVERIFIED] " if sus else "", first, d / name),
                  kind="done")
        chat.release(scope, who)
    except Exception:
        pass


def session_end(inp: dict):
    scope = core.current_scope(inp.get("cwd"))
    harvest.harvest(inp.get("transcript_path"), scope, inp.get("session_id", ""))


HOOKS = {"session-start": session_start, "prompt": user_prompt, "pre-compact": pre_compact,
         "post-compact": post_compact, "stop": stop, "subagent-stop": subagent_stop, "session-end": session_end}


def run(name: str):
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace") if not sys.stdin.isatty() else ""
        try:
            inp = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:  # tolerate unescaped Windows backslashes
            bs = chr(92)
            inp = json.loads(re.sub(bs * 2 + '(?![' + bs * 2 + '"/bfnrtu])', bs * 4, raw))
        HOOKS[name](inp)
    except Exception:
        try:
            with open(core.data_dir() / "hook-errors.log", "a", encoding="utf-8") as f:
                f.write("%s %s\n%s\n" % (time.strftime("%F %T"), name, traceback.format_exc()))
        except Exception:
            pass
    sys.exit(0)
