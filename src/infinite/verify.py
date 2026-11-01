"""Hallucination capture: check an agent's final message against the real repo.

Checks (cheap, no LLM):
- cited paths exist (`src/x.py`, src\\x.py, x.py:120) and cited line numbers are in range;
- cited code symbols (`foo()`, `Class.method`, `def foo`) occur somewhere in the source tree.
Lines that talk about creating/proposing/deleting things are skipped (those may
legitimately not exist). Results are *suspects*: the agent is asked to verify,
never silently "corrected".
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PATH = re.compile(r"(?<![\w/.@:-])((?:[A-Za-z]:)?(?:[\w.\-~]+[/\\])+[\w.\-]+\.[A-Za-z0-9]{1,6}|[\w\-]+\.(?:py|ts|tsx|js|jsx|go|rs|md|json|toml|yaml|yml|sh|c|h|cpp|java|rb|php|css|html))(?::(\d+))?(?![\w/])")
SYMBOL = re.compile(r"`(?:def |class |function |fn )?([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)?)\(\)?[^`]{0,40}`")
SKIP_LINE = re.compile(
    r"\b(creat|new file|add(ed|ing)? (a|an|the)? ?(new )?file|propos|would|should|could|plan|todo|suggest|next step"
    r"|delet|remov|renam|missing|not found|doesn'?t exist|does not exist|no longer|example|e\.g\.|placeholder"
    r"|criar|novo arquivo|sugest|remov|apag|exemplo)", re.I)
SRC_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".c", ".h", ".cpp", ".java", ".rb", ".php", ".swift",
           ".kt", ".cs", ".sh", ".lua", ".ex", ".exs", ".hs", ".ml", ".scala", ".vue", ".svelte"}
IGNORE = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", ".next", ".cache"}
COMMON = {"print", "len", "open", "range", "main", "run", "test", "init", "str", "int", "dict", "list", "set",
          "map", "filter", "sorted", "super", "isinstance", "getattr", "require", "import", "console.log", "fetch"}


def _source_blob(root: Path, max_files=4000, max_bytes=40_000_000) -> str:
    parts, total, n = [], 0, 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in IGNORE and not d.startswith(".")]
        for f in fn:
            if Path(f).suffix.lower() in SRC_EXT:
                p = Path(dp) / f
                try:
                    s = p.stat().st_size
                    if s > 2_000_000:
                        continue
                    parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
                total += s
                n += 1
                if n >= max_files or total >= max_bytes:
                    return "\n".join(parts)
    return "\n".join(parts)


def _resolve(raw: str, root: Path, extra_roots=()) -> Path | None:
    s = raw.replace("\\", "/")
    if s.startswith("~"):
        p = Path(os.path.expanduser(s))
        return p if p.exists() else None
    p = Path(s)
    if p.is_absolute() or re.match(r"^[A-Za-z]:/", s):
        return p if p.exists() else None
    claude_home = Path.home() / ".claude"
    for base in (root, root / ".claude", claude_home, Path.home(), *extra_roots):
        q = base / s
        if q.exists():
            return q
    if "/" not in s:  # bare filename: anywhere in the tree, incl. .claude/ and ~/.claude (bounded)
        for top in (root, claude_home):
            for i, (dp, dn, fn) in enumerate(os.walk(top)):
                dn[:] = [d for d in dn if d not in IGNORE and (not d.startswith(".") or d in (".claude", ".github"))
                         and not (top == claude_home and d in ("projects", "file-history", "paste-cache", "shell-snapshots"))]
                if s in fn:
                    return Path(dp) / s
                if i > 3000:
                    break
    return None


def check(text: str, root: str | Path, max_items=12) -> list[str]:
    root = Path(root)
    if not text or not root.exists():
        return []
    suspects: list[str] = []
    seen = set()
    code_lines = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or SKIP_LINE.search(line) or "http://" in line or "https://" in line:
            continue
        code_lines.append(line)
        for m in PATH.finditer(line):
            raw, ln = m.group(1), m.group(2)
            key = "%s:%s" % (raw, ln)
            if key in seen or "*" in raw or "<" in raw or raw.startswith(("e.g", "i.e")):
                continue
            seen.add(key)
            seen.add(Path(raw).stem)
            p = _resolve(raw, root)
            if p is None:
                suspects.append("path `%s` does not exist" % raw)
            elif ln and p.is_file():
                try:
                    with open(p, "rb") as fh:
                        n = sum(1 for _ in fh)
                except OSError:
                    n = 10 ** 9
                if int(ln) > n:
                    suspects.append("`%s:%s` but the file has only %d lines" % (raw, ln, n))
            if len(suspects) >= max_items:
                return suspects
    syms = []
    for line in code_lines:
        for m in SYMBOL.finditer(line):
            name = m.group(1)
            if name.lower() not in COMMON and len(name) > 3 and name not in seen:
                seen.add(name)
                syms.append(name)
    if syms and ((root / ".git").exists() or (root / "pyproject.toml").exists() or (root / "package.json").exists()):
        blob = _source_blob(root)
        if blob:
            for name in syms[:20]:
                last = name.split(".")[-1]
                if not re.search(r"\b%s\b" % re.escape(last), blob):
                    suspects.append("symbol `%s` not found in the source tree" % name)
                    if len(suspects) >= max_items:
                        break
    return suspects
