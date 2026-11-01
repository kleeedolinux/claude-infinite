"""Projects: scaffold new ones, scan/migrate existing ones, plan monorepos,
import Claude Code's own memory files, and draw the knowledge graph."""
from __future__ import annotations

import collections
import json
import os
import re
import time
from pathlib import Path

from . import core

IGNORE = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "target", ".next",
          ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode", ".tox", "out", ".cache", ".turbo"}
MANIFESTS = ["pyproject.toml", "setup.py", "requirements.txt", "uv.lock", "poetry.lock", "package.json",
             "pnpm-workspace.yaml", "turbo.json", "nx.json", "Cargo.toml", "go.mod", "Makefile", "Dockerfile",
             "docker-compose.yml", "CMakeLists.txt", "pom.xml", "build.gradle", "Gemfile", "composer.json",
             "deno.json", "bun.lockb", "CLAUDE.md", "AGENTS.md", ".claude"]

# ------------------------------------------------------------------ templates

CLAUDE_MD = """# {name}

{purpose}

## Rules
- Memory: `mem` runs automatically (hooks). Record lasting facts/decisions/lessons with `mem note`; ideas that are not the current task go to `mem idea` (parking lot) — do not switch tasks unless asked.
- Tasks live in `.claude/TASKS.md` (In progress / Queue / Done). Update it when a task starts or ends.
- Search before writing: reuse existing code; extract shared logic on the second occurrence.
- Measure, don't assume. Reports state what was NOT verified.
{rules}
## Map
{map}
## Commands
{commands}
## Area skills
Detailed guidance lives in `.claude/skills/<area>/SKILL.md` (loaded on demand). Create one when an area collects 5+ lessons or the same correction happens twice.
"""

TASKS_MD = """# Tasks

## In progress
<!-- one line per task: [owner/agent] task — files touched -->

## Queue
<!-- ideas parked by `mem idea` land here -->

## Done
<!-- newest first: YYYY-MM-DD task — result (commit) -->
"""

KB_MD = """# Knowledge base

One record per finding. Never copy a number elsewhere: cite the record id.

```
### KB-NNNN YYYY-MM-DD <area> — <title>
verdict: works | fails | open      supersedes: KB-xxxx (optional)
evidence: <what was measured, where>
reproduce: `<command>`
```

Rules: check here (and `mem recall`) before measuring or trying anything; do not repeat a failed
experiment unless the hypothesis changed (say what changed); when a fact changes, mark the old
record superseded and link it.
"""

AREA_SKILL = """---
name: {slug}
description: Area guide for {area} in {project}: where things are, rules, taste, how to verify, lessons. Use when working on {area}.
---

# {area}

## Where things are
-

## Non-negotiable rules
-

## Taste (owner preferences)
-

## How to verify
-

## Lessons (newest first, dated, concrete cause -> rule)
-
"""

PY_PYPROJECT = """[project]
name = "{pkg}"
version = "0.1.0"
description = "{purpose}"
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 110

[tool.pytest.ini_options]
testpaths = ["tests"]
"""

MONO_ROOT = """[project]
name = "{pkg}-workspace"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = []

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*", "apps/*"]

[tool.ruff]
line-length = 110

[tool.pytest.ini_options]
testpaths = ["packages", "apps"]
"""

MONO_PKG = """[project]
name = "{pkg}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""

GITIGNORE = """__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
dist/
build/
.env
node_modules/
"""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", core.fold(s)).strip("-") or "project"


def _pkg(s: str) -> str:
    return _slug(s).replace("-", "_")


def _write(p: Path, text: str, created: list, overwrite=False):
    if p.exists() and not overwrite:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    created.append(str(p))


def register(root: Path, name: str | None = None):
    now = time.time()
    with core.db() as c:
        with core.tx(c):
            c.execute("insert into projects(scope,path,name,first_seen,last_seen,sessions) values(?,?,?,?,?,0)"
                      " on conflict(scope) do update set path=excluded.path, name=coalesce(?, name)",
                      (core.scope_key(root), str(root), name or root.name, now, now, name))


def new(path: str, kind: str = "python", purpose: str = "", areas: list[str] | None = None) -> list[str]:
    root = Path(path).resolve()
    name = root.name
    purpose = purpose or "TODO: one paragraph — what this is, for whom, what done looks like."
    created: list[str] = []
    pkg = _pkg(name)
    if kind == "python":
        _write(root / "pyproject.toml", PY_PYPROJECT.format(pkg=pkg, purpose=purpose.replace('"', "'")), created)
        _write(root / "src" / pkg / "__init__.py", '"""%s"""\n' % name, created)
        _write(root / "tests" / ("test_%s.py" % pkg), "import %s\n\n\ndef test_import():\n    assert %s\n" % (pkg, pkg), created)
        mp = "- `src/%s/` — package code\n- `tests/` — pytest\n- `docs/kb/` — knowledge base" % pkg
        cmds = "- setup: `uv sync`\n- test: `uv run pytest -q`\n- lint: `uv run ruff check .`"
    elif kind == "monorepo":
        _write(root / "pyproject.toml", MONO_ROOT.format(pkg=pkg), created)
        core_pkg = pkg + "_core"
        _write(root / "packages" / "core" / "pyproject.toml", MONO_PKG.format(pkg=core_pkg), created)
        _write(root / "packages" / "core" / "src" / core_pkg / "__init__.py", '"""Shared core."""\n', created)
        _write(root / "packages" / "core" / "tests" / "test_core.py",
               "import %s\n\n\ndef test_import():\n    assert %s\n" % (core_pkg, core_pkg), created)
        _write(root / "apps" / "README.md", "# apps\nDeployable things (CLIs, services, UIs). Each app is a uv workspace member.\n", created)
        _write(root / "tools" / "README.md", "# tools\nRepo scripts (codegen, release, measurement). Measurements become scripts with fixed criteria.\n", created)
        mp = ("- `packages/<name>/` — libraries (shared code; frozen + tested before parallel work)\n"
              "- `apps/<name>/` — deployables; depend on packages, never on each other\n"
              "- `tools/` — repo scripts\n- `docs/kb/` — knowledge base\n"
              "- Ownership: one agent per package/app at a time (see TASKS.md In progress)")
        cmds = ("- setup: `uv sync --all-packages`\n- test all: `uv run pytest -q`\n"
                "- test one: `uv run --package <name> pytest -q packages/<name>`\n- lint: `uv run ruff check .`\n"
                "- add package: `uv init --lib packages/<name>`")
        areas = areas or ["core"]
    else:
        mp = "- (fill in: top-level folders and what lives there)"
        cmds = "- (fill in: build / test / run)"
    _write(root / "CLAUDE.md", CLAUDE_MD.format(name=name, purpose=purpose, rules="", map=mp, commands=cmds), created)
    _write(root / ".claude" / "TASKS.md", TASKS_MD, created)
    _write(root / "docs" / "kb" / "README.md", KB_MD, created)
    _write(root / ".gitignore", GITIGNORE, created)
    for a in areas or []:
        _write(root / ".claude" / "skills" / _slug(a) / "SKILL.md",
               AREA_SKILL.format(slug=_slug(a), area=a, project=name), created)
    if not (root / ".git").exists():
        os.system('git init -q "%s"' % root)
    register(root, name)
    core.note("Project %s created (%s): %s" % (name, kind, purpose[:200]), core.scope_key(root), kind="project",
              importance=3, source="mem project new", force=True)
    return created


def scan(path: str, depth: int = 3) -> dict:
    root = Path(path).resolve()
    ext = collections.Counter()
    sizes = collections.Counter()
    top = collections.Counter()
    manifests, repos, big = [], [], []
    nfiles = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        lvl = len(rel.parts)
        if (Path(dirpath) / ".git").exists() and lvl > 0:
            repos.append(str(rel))
        dirnames[:] = [d for d in dirnames if d not in IGNORE and not d.startswith(".") or d == ".claude"]
        for f in filenames:
            nfiles += 1
            p = Path(dirpath) / f
            e = p.suffix.lower() or "(none)"
            ext[e] += 1
            try:
                s = p.stat().st_size
            except OSError:
                s = 0
            sizes[e] += s
            top[rel.parts[0] if rel.parts else "."] += 1
            if f in MANIFESTS and lvl <= depth:
                manifests.append(str(rel / f))
            if s > 1_000_000:
                big.append((s, str(rel / f)))
        if nfiles > 200_000:
            break
    big.sort(reverse=True)
    return {"root": str(root), "files": nfiles, "extensions": ext.most_common(15),
            "top_dirs": top.most_common(25), "manifests": manifests[:80], "nested_git_repos": repos[:50],
            "large_files": [(round(s / 1e6, 1), f) for s, f in big[:10]],
            "has_claude_md": (root / "CLAUDE.md").exists(), "has_tasks": (root / ".claude" / "TASKS.md").exists(),
            "memory_scope": core.scope_key(root)}


def migrate(path: str, purpose: str = "") -> list[str]:
    """Non-destructive: add missing scaffolding, register, import Claude memory. Never overwrites."""
    root = Path(path).resolve()
    info = scan(path)
    created: list[str] = []
    langs = ", ".join("%s(%d)" % e for e in info["extensions"][:6])
    mp = "\n".join("- `%s/` — %d files (describe)" % d for d in info["top_dirs"][:12] if d[0] != ".")
    if not (root / "CLAUDE.md").exists():
        _write(root / "CLAUDE.md", CLAUDE_MD.format(
            name=root.name, purpose=purpose or "TODO: purpose. Detected: " + langs, rules="", map=mp,
            commands="- (detected manifests: %s)" % ", ".join(info["manifests"][:8])), created)
    _write(root / ".claude" / "TASKS.md", TASKS_MD, created)
    _write(root / "docs" / "kb" / "README.md", KB_MD, created)
    register(root)
    n = import_claude(only=core.scope_key(root))
    created.append("(imported %d Claude memory files)" % n)
    return created


def monorepo_plan(target: str, sources: list[str]) -> str:
    out = ["# Monorepo plan -> %s (review before executing; nothing was moved)" % Path(target).resolve(), ""]
    for s in sources:
        p = Path(s).resolve()
        info = scan(s, depth=1)
        exts = dict(info["extensions"])
        is_app = any((p / f).exists() for f in ("main.py", "app.py", "manage.py", "Dockerfile", "index.html")) or \
            "package.json" in [Path(m).name for m in info["manifests"]]
        kind = "apps" if is_app else "packages"
        dest = "%s/%s" % (kind, _slug(p.name))
        hist = "git subtree add --prefix=%s %s HEAD  (keeps history)" % (dest, p) if (p / ".git").exists() \
            else "copy (no git history)"
        out.append("- %s -> `%s` [%s; %d files; top ext %s]\n    how: %s"
                   % (p.name, dest, kind[:-1], info["files"], next(iter(exts), "-"), hist))
    out += ["", "Then: root pyproject `[tool.uv.workspace] members = [\"packages/*\", \"apps/*\"]`, move shared code into",
            "packages/, replace cross-imports with workspace deps, one `.claude/skills/<area>` per package,",
            "run `uv sync --all-packages && uv run pytest -q`, then `mem project migrate <target>`."]
    return "\n".join(out)


# ------------------------------------------------------------------ Claude Code memory import

TYPE_KIND = {"user": "pref", "feedback": "lesson", "project": "fact", "reference": "ref"}


def _front(text: str) -> tuple[dict, str]:
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                m = re.match(r"\s*(\w+):\s*(.*)", line)
                if m:
                    meta[m.group(1)] = m.group(2).strip().strip('"')
            text = text[end + 4:]
    return meta, text.strip()


def import_claude(only: str | None = None) -> int:
    base = Path.home() / ".claude" / "projects"
    home_key = core.scope_key(Path.home())
    n = 0
    for mdir in sorted(base.glob("*/memory")):
        key = mdir.parent.name
        if only and key != only:
            continue
        scope = "global" if key == home_key else key
        for f in sorted(mdir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            meta, body = _front(f.read_text(encoding="utf-8", errors="replace"))
            first = next((l.strip() for l in body.splitlines() if l.strip() and not l.startswith("#")), "")
            desc = meta.get("description") or first
            text = "%s: %s" % (meta.get("name") or f.stem, desc)
            if first and first not in text:
                text += " — " + first
            text = core.clean(text)[:380] + " (src: %s)" % f.name
            kind = TYPE_KIND.get(meta.get("type", ""), "fact")
            r = core.note(text[:400], scope, kind=kind, importance=3, source="claude-memory:" + str(f))
            if r["status"] == "added":
                n += 1
    return n


# ------------------------------------------------------------------ graph

def graph(fmt: str = "mermaid", min_count: int = 2) -> str:
    with core.db() as c:
        names = {s: (n or s) for s, n in c.execute("select scope, name from projects")}
        rows = c.execute("select scope, tags, kind from notes where invalid_at is null").fetchall()
        links = c.execute("select l.src, l.dst, l.rel, a.scope, b.scope from links l join notes a on a.id=l.src"
                          " join notes b on b.id=l.dst").fetchall()
    tag_by_scope = collections.defaultdict(collections.Counter)
    counts = collections.Counter()
    for scope, tags, kind in rows:
        counts[scope] += 1
        for t in (tags or "").split():
            tag_by_scope[scope][t] += 1
    tag_scopes = collections.defaultdict(set)
    for s, cnt in tag_by_scope.items():
        for t, k in cnt.items():
            if k >= min_count or True:
                tag_scopes[t].add(s)
    label = lambda s: (names.get(s) or s.rsplit("-", 1)[-1]).replace('"', "'")
    nid = lambda s: "p" + re.sub(r"\W", "_", s)[-40:]
    if fmt == "json":
        return json.dumps({"projects": {label(s): n for s, n in counts.items()},
                           "tags": {t: sorted(label(s) for s in ss) for t, ss in tag_scopes.items()},
                           "links": [(a, b, r) for a, b, r, _, _ in links]}, indent=1)
    out = ["```mermaid", "graph LR"]
    for s, n in counts.most_common(40):
        out.append('  %s["%s (%d)"]' % (nid(s), label(s), n))
    for t, ss in sorted(tag_scopes.items(), key=lambda x: -len(x[1]))[:40]:
        tid = "t_" + re.sub(r"\W", "_", t)
        out.append('  %s(("#%s"))' % (tid, t))
        for s in ss:
            out.append("  %s --- %s" % (nid(s), tid))
    cross = collections.Counter((a, b) for _, _, _, a, b in links if a != b)
    for (a, b), k in cross.items():
        out.append("  %s -->|%d links| %s" % (nid(a), k, nid(b)))
    out.append("```")
    return "\n".join(out)
