---
name: new-project
description: Create a new project the right way (Python by default; single package or uv monorepo) with short CLAUDE.md, TASKS.md, knowledge base, area skills and memory registration. Use when the user wants to start/create/scaffold a new project, app, library, repo or "novo projeto".
---

# New project

1. **Clarify in one round, at most 3 questions:** purpose and audience; what done looks like; the kind (`python` package, `monorepo` with several packages and apps, or `generic`). If the user already said these, don't ask.
2. **Bias check the idea before building:** run `mem bias "<idea>"` and apply idea-lab briefly. Give 3 options for scope and stack, one premortem line, and a recommendation. Proceed with the user's choice.
3. **Scaffold** with `mem project new <path> --kind python|monorepo|generic --purpose "<1 paragraph>" --areas a,b`. It never overwrites, runs git init and registers the project in memory.
4. **Fill in CLAUDE.md** and keep it under about 60 lines: purpose, rules, a map (folder → what lives there), commands, pointers. Put detail in `.claude/skills/<area>/SKILL.md`, which loads only when needed. Long CLAUDE.md files get ignored.
5. **Seed `.claude/TASKS.md`:** first 3-7 tasks in Queue, smallest vertical slice first.
6. **Record:**
   - `mem note -k decision "<stack/structure chosen and why>" -i 3`
   - user taste as `-k pref`, with `-g` if it holds across projects.
7. **Verify** the toolchain: `uv sync` (or `uv sync --all-packages`), then `uv run pytest -q`. Commit "scaffold" if the user wants commits.

## Defaults (Python)
- `uv` for environments and lockfile, `src/` layout, pytest, ruff, Python 3.11 or newer.
- Monorepos:
  - `packages/*` holds libraries; `apps/*` holds deployables.
  - Apps depend on packages, never on each other.
  - `tools/` holds repo scripts.
- No dependency without a reason recorded as a decision.
- For a non-Python stack the user asks for, still create CLAUDE.md, TASKS.md and the KB (`--kind generic`) and add that stack's own scaffolding.
