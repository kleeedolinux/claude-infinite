---
name: monorepo
description: Plan and execute consolidating several projects into one optimized monorepo (Python uv workspace by default; JS via pnpm/turbo), with packages/apps/tools layout, shared code extraction and per-package ownership for parallel agents. Use when the user wants a monorepo, to merge repos, or to restructure a large codebase.
---

# Monorepo

## Plan (always first, read-only)
1. `mem project monorepo <target> <src1> <src2> ...` prints a proposed mapping (apps vs packages) and how each one moves (git subtree keeps history).
2. For each source, run `mem project scan`. Find shared code: the same modules duplicated across repos become `packages/<name>`.
3. Present the plan:
   - target tree
   - moves
   - which shared code is extracted
   - dependency direction (apps → packages, packages → lower packages, no cycles)
   - risks
4. Wait for approval.

## Execute
1. `mem project new <target> --kind monorepo` (skip if the target exists).
2. Import each repo with history: `git subtree add --prefix=packages/<name> <path-or-url> <branch>`. Without git, copy it.
3. Give each member its own `pyproject.toml`. Workspace dependencies: `[tool.uv.sources] core = { workspace = true }` plus `dependencies = ["core"]`.
4. `uv sync --all-packages && uv run pytest -q`, until green.
5. Extract duplicates on the second occurrence and update both call sites.
6. Give each package or app one area skill (`.claude/skills/<pkg>/SKILL.md`) and one line in the root CLAUDE.md map.
7. Record the decisions: `mem note -k decision "monorepo: ... because ..."`. Then `mem project migrate <target>`.

## Optimized for agents
- Freeze and test shared packages before splitting parallel work. Agree on function signatures first.
- One agent per package at a time. Owners go in TASKS.md In progress (`mem task start "..." --owner agent-x --files packages/x`).
- Use one git worktree per parallel agent (Agent tool `isolation: "worktree"`).
- Fast feedback: `uv run --package <name> pytest -q packages/<name>` tests only what changed.
- JS or TS parts: pnpm workspaces plus turbo, under `apps/web` and `packages/ui`. Keep Python and JS tooling separate at the root.
