"""Live check of the INSTALLED hooks (~/.claude/infinite), as Claude Code runs them.
Usage: python tests/live_hooks.py [project_dir]   (read-mostly: registers the project, records prompts)"""
import json
import subprocess
import sys
import time
from pathlib import Path

PY = sys.executable
MEM = str(Path.home() / ".claude" / "infinite" / "mem.py")
cwd = sys.argv[1] if len(sys.argv) > 1 else str(Path.cwd())
sid = "live-check-%d" % time.time()


def hook(name, d, raw=None):
    t = time.time()
    r = subprocess.run([PY, MEM, "hook", name], input=raw if raw is not None else json.dumps(d),
                       capture_output=True, text=True, encoding="utf-8")
    return r, round(time.time() - t, 2)


r, t = hook("session-start", {"session_id": sid, "cwd": cwd, "source": "startup"})
ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
print("session-start: %.2fs, %d chars (limit 10000)" % (t, len(ctx)))
print(ctx[:2000])
r, t = hook("prompt", {"session_id": sid, "cwd": cwd, "prompt": "what did we decide about the build and budget?"})
print("\nprompt: %.2fs" % t)
print(json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else "(no context)")
bs = chr(92)
bad = '{"session_id":"%s","cwd":"C:%sUsers%sklee","prompt":"hello there friend"}' % (sid, bs, bs)
r, t = hook("prompt", None, raw=bad)
print("\nunescaped-backslash input: rc=%d %.2fs" % (r.returncode, t))
r, t = hook("stop", {"session_id": sid, "cwd": cwd, "stop_hook_active": False, "last_assistant_message": "ok"})
print("stop: rc=%d %.2fs out=%r" % (r.returncode, t, r.stdout[:200]))
