#!/usr/bin/env python3
"""Install claudeinfinite globally for Claude Code (idempotent; rerun to update).

  python install.py              install / update
  python install.py --uninstall  remove hooks, skills, agents, CLAUDE.md block (memory data is kept)
  python install.py --dry-run    show what would change

Never touches ~/.claude/infinite/data (your memories)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
TARGET = CLAUDE / "infinite"
BEGIN, END = "<!-- infinite-memory:begin", "<!-- infinite-memory:end -->"
MARK = "infinite/mem.py\" hook"
SKILLS = sorted(p.name for p in (REPO / "skills").iterdir() if (p / "SKILL.md").exists())
AGENTS = sorted(p.name for p in (REPO / "agents").glob("*.md"))
EVENTS = {  # event -> (hook name, timeout seconds)
    "SessionStart": ("session-start", 20),
    "UserPromptSubmit": ("prompt", 10),
    "PreCompact": ("pre-compact", 30),
    "PostCompact": ("post-compact", 10),
    "Stop": ("stop", 20),
    "SubagentStop": ("subagent-stop", 10),
    "SessionEnd": ("session-end", 5),
}
PERMS = ["Bash(mem:*)", "Bash(python ~/.claude/infinite/mem.py:*)"]
DRY = "--dry-run" in sys.argv


def say(*a):
    print(("[dry] " if DRY else "") + " ".join(str(x) for x in a))


def py() -> str:
    return Path(sys.executable).as_posix()


def hook_cmd(name: str) -> str:
    return '"%s" "%s" hook %s' % (py(), (TARGET / "mem.py").as_posix(), name)


def copy_code():
    say("code ->", TARGET)
    if DRY:
        return
    TARGET.mkdir(parents=True, exist_ok=True)
    pkg = TARGET / "infinite"
    if pkg.exists():
        shutil.rmtree(pkg)
    shutil.copytree(REPO / "src" / "infinite", pkg, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(REPO / "mem.py", TARGET / "mem.py")
    (TARGET / "VERSION").write_text("%s installed %s from %s\n" % (
        _git_rev(), time.strftime("%F %T"), REPO), encoding="utf-8")


def _git_rev() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "nogit"


def copy_assets(remove=False):
    for s in SKILLS:
        dst = CLAUDE / "skills" / s
        say(("remove" if remove else "skill ->"), dst)
        if DRY:
            continue
        if dst.exists():
            if not (dst / ".claudeinfinite").exists() and not remove:
                bak = dst.with_name(dst.name + ".bak-%d" % time.time())
                say("  existing unmanaged skill moved to", bak)
                dst.rename(bak)
            else:
                shutil.rmtree(dst)
        if not remove:
            shutil.copytree(REPO / "skills" / s, dst)
            (dst / ".claudeinfinite").write_text("managed by claudeinfinite/install.py\n", encoding="utf-8")
    for a in AGENTS:
        dst = CLAUDE / "agents" / a
        say(("remove" if remove else "agent ->"), dst)
        if DRY:
            continue
        if remove:
            dst.unlink(missing_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / "agents" / a, dst)


def claude_md(remove=False):
    p = CLAUDE / "CLAUDE.md"
    cur = p.read_text(encoding="utf-8") if p.exists() else ""
    if BEGIN in cur and END in cur:
        a = cur.index(BEGIN)
        b = cur.index(END) + len(END)
        cur = (cur[:a] + cur[b:]).strip("\n")
    block = (REPO / "claude" / "CLAUDE.global.md").read_text(encoding="utf-8").strip()
    new = cur.strip() + "\n" if remove else block + ("\n\n" + cur.strip() + "\n" if cur.strip() else "\n")
    say(("strip block from" if remove else "memory block (top) ->"), p)
    if not DRY:
        p.write_text(new, encoding="utf-8")


def settings(remove=False):
    p = CLAUDE / "settings.json"
    raw = p.read_text(encoding="utf-8") if p.exists() else "{}"
    s = json.loads(raw or "{}")
    hooks = s.setdefault("hooks", {})
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            hs = [h for h in g.get("hooks", []) if MARK not in h.get("command", "")]
            if hs:
                groups.append({**g, "hooks": hs})
        if groups:
            hooks[ev] = groups
        else:
            del hooks[ev]
    perms = s.setdefault("permissions", {}).setdefault("allow", [])
    perms[:] = [x for x in perms if x not in PERMS]
    if not remove:
        for ev, (name, timeout) in EVENTS.items():
            hooks.setdefault(ev, []).append({"hooks": [{"type": "command", "command": hook_cmd(name), "timeout": timeout}]})
        perms.extend(PERMS)
    if not s["permissions"]["allow"]:
        del s["permissions"]["allow"]
    if not s["permissions"]:
        del s["permissions"]
    if not hooks:
        del s["hooks"]
    say(("remove hooks from" if remove else "hooks %s ->" % ",".join(EVENTS)), p)
    if DRY:
        return
    bdir = CLAUDE / "backups"
    bdir.mkdir(exist_ok=True)
    if p.exists():
        shutil.copy2(p, bdir / ("settings.json.claudeinfinite-%s" % time.strftime("%Y%m%d-%H%M%S")))
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))  # validate before replacing
    os.replace(tmp, p)


def shims(remove=False):
    bindir = Path.home() / ".local" / "bin"
    files = {bindir / "mem": '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (py(), (TARGET / "mem.py").as_posix()),
             bindir / "mem.cmd": '@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, TARGET / "mem.py")}
    for f, body in files.items():
        say(("remove" if remove else "shim ->"), f)
        if DRY:
            continue
        if remove:
            f.unlink(missing_ok=True)
        else:
            bindir.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8", newline="")
            try:
                f.chmod(0o755)
            except OSError:
                pass
    path = os.environ.get("PATH", "").lower().replace("\\", "/")
    if not remove and bindir.as_posix().lower() not in path and str(bindir).lower() not in path:
        print("note: %s is not on PATH; use `python ~/.claude/infinite/mem.py` or add it." % bindir)


def post_install():
    if DRY:
        return
    mem = [sys.executable, str(TARGET / "mem.py")]
    out = subprocess.run(mem + ["import-claude", "--all"], capture_output=True, text=True, encoding="utf-8")
    print(out.stdout.strip() or out.stderr.strip())
    out = subprocess.run(mem + ["doctor"], capture_output=True, text=True, encoding="utf-8")
    print("doctor:", out.stdout.strip() or out.stderr.strip())


def main():
    if "--uninstall" in sys.argv:
        settings(remove=True)
        claude_md(remove=True)
        copy_assets(remove=True)
        shims(remove=True)
        print("uninstalled (memory data kept in %s)" % (TARGET / "data"))
        return
    copy_code()
    copy_assets()
    claude_md()
    settings()
    shims()
    post_install()
    print("\ninstalled. Open any project with `claude`: memory loads automatically. Try: mem help")


if __name__ == "__main__":
    main()
