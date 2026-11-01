"""Session state + transcript harvesting (no LLM calls; pure heuristics).

- Session state keeps the user's words verbatim, so an auto-compaction can never
  lose the actual request: PreCompact snapshots it, SessionStart(source=compact)
  re-injects it.
- Transcript harvest (incremental, by byte offset) finds tool errors and user
  corrections and queues them in the inbox; recurring ones surface at wake
  (Reflexion-style: failures turn into lessons).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import core

CORRECTION = re.compile(
    r"(^\s*(no|nope|wrong|incorrect|stop|don'?t|again|why did you|n[aã]o[,!. ]|errado|pare|para de|de novo)\b)"
    r"|\b(you forgot|i told you|i said|i asked|not what i|that'?s not|doesn'?t work|still (broken|wrong|failing)"
    r"|voc[eê] esqueceu|esqueceu|eu disse|j[aá] (disse|falei)|n[aã]o (funciona|era isso|foi isso)|est[aá] errado)\b",
    re.I)
IDEA = re.compile(
    r"\b(idea|ideas|brainstorm|what if|new project|startup|design|architecture|should (i|we)|which is better"
    r"|ideia|ideias|e se|novo projeto|criar um|qual (é )?melhor|devo|vale a pena|proposta|plano)\b", re.I)
ADDON = re.compile(r"^\s*(also|and |another|btw|by the way|oh and|plus|tamb[eé]m|e tamb[eé]m|outra coisa|ah[, ]|al[eé]m disso|mais uma)", re.I)
FRESH = re.compile(r"(^|\s)(#fresh|/fresh|fresh:)", re.I)
NOISE = ("<command-", "<local-command", "<system-reminder", "<task-notification", "[Request interrupted",
         "Caveat:", "<user-prompt-submit-hook")


def sessions_dir() -> Path:
    d = core.data_dir() / "sessions"
    d.mkdir(exist_ok=True)
    return d


def _sp(session: str) -> Path:
    return sessions_dir() / ("%s.json" % re.sub(r"[^\w\-]", "_", session or "unknown"))


def load_state(session: str) -> dict:
    p = _sp(session)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"session": session, "started": time.time(), "prompts": [], "first": None, "corrections": 0,
            "notes_at_start": None, "reflect_asked": False, "compactions": 0}


def save_state(st: dict):
    _sp(st["session"]).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def record_prompt(st: dict, prompt: str):
    p = core.clean(core.PRIVATE.sub("[private]", prompt))[:1500]
    if not p or p.startswith(NOISE):
        return
    if st["first"] is None:
        st["first"] = p
    st["prompts"].append({"ts": time.time(), "text": p})
    st["prompts"] = st["prompts"][-15:]


def is_correction(prompt: str) -> bool:
    return bool(CORRECTION.search(prompt[:400]))


def _text(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            if b.get("type") == "text":
                out.append(b.get("text", ""))
            elif b.get("type") == "tool_result":
                out.append(_text(b.get("content")))
        elif isinstance(b, str):
            out.append(b)
    return "\n".join(out)


def _sig(err: str) -> str:
    s = core.fold(err.splitlines()[0] if err.strip() else err)[:200]
    s = re.sub(r"[a-z]:[\\/][^\s'\"]*|/[\w./\-]+", "<path>", s)
    s = re.sub(r"\d+", "N", s)
    return "error:" + " ".join(s.split())[:140]


def harvest(transcript: str, scope: str, session: str, max_bytes: int = 4_000_000) -> dict:
    """Scan new transcript lines; queue tool errors and corrections. Returns counts."""
    p = Path(transcript or "")
    res = {"errors": 0, "corrections": 0}
    if not transcript or not p.exists():
        return res
    with core.db() as c:
        key = "off:" + str(p)
        off = int(core.meta_get(c, key, 0) or 0)
        size = p.stat().st_size
        if off > size:
            off = 0
        if size - off > max_bytes:
            off = size - max_bytes
        with open(p, "rb") as f:
            f.seek(off)
            data = f.read()
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            return res
        chunk, new_off = data[: last_nl + 1], off + last_nl + 1
        with core.tx(c):
            for raw in chunk.splitlines():
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                if ev.get("type") != "user" or ev.get("isMeta"):
                    continue
                content = (ev.get("message") or {}).get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                            t = _text(b.get("content")).strip()
                            head = t[:160].lower()
                            if t and "user doesn't want" not in head and "rejected" not in head[:80] \
                                    and not ("permission" in head and "denied" in head):
                                core.inbox_add(c, scope, "error", t[:400], sig=_sig(t), session=session)
                                res["errors"] += 1
                else:
                    t = _text(content).strip()
                    if t and not t.startswith(NOISE) and is_correction(t):
                        core.inbox_add(c, scope, "correction", t[:400], session=session)
                        res["corrections"] += 1
            core.meta_set(c, key, new_off)
    return res


def last_assistant_text(transcript: str, limit: int = 6000) -> str:
    p = Path(transcript or "")
    if not p.exists():
        return ""
    size = p.stat().st_size
    with open(p, "rb") as f:
        f.seek(max(0, size - 2_000_000))
        lines = f.read().splitlines()
    for raw in reversed(lines):
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        if ev.get("type") == "assistant":
            t = _text((ev.get("message") or {}).get("content")).strip()
            if t:
                return t[-limit:]
    return ""
