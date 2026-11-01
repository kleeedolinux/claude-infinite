---
name: migrate-project
description: Bring an existing project under the memory/organization system - scan it, add CLAUDE.md/TASKS.md/KB without overwriting, import old Claude memory files, write area skills, and propose a cleanup/reorganization plan. Use when the user asks to migrate, adopt, organize, clean up, document or "organizar" an existing project or folder.
---

# Migrate / organize an existing project

1. **Scan:** `mem project scan <path>` shows languages, manifests, top directories, nested git repos and large files. Read the README and manifests, using line ranges for big files.
2. **Search memory:** `mem recall <project name> -a` and the `home-projects` skill if it applies. Old sessions or memory may already explain the project.
3. **Migrate without overwriting:** `mem project migrate <path> --purpose "..."` adds CLAUDE.md, `.claude/TASKS.md` and `docs/kb/` only where they are missing. It also registers the project and imports `~/.claude/projects/<key>/memory/*.md`.
4. **Write the real CLAUDE.md map:** one line per top-level folder, plus build, test and run commands that you actually executed. Mark anything unverified as such. If a CLAUDE.md already exists, shorten it: move area detail into skills and keep the rules and pointers.
5. **Area skills:** one `.claude/skills/<area>/SKILL.md` per real area, covering where things are, rules, taste, how to verify, and lessons. The template comes from `mem project new --areas`. Only create one when there is content for it.
6. **Reorganization plan:** propose it, don't do it silently. List problems (duplication, dead code, mixed concerns, missing tests, secrets in the repo), a target layout, and the moves. For several related repos, use the monorepo skill. Get the user's OK before any mass move or delete. Use `git mv` so history is kept.
7. **Record:** `mem note -k fact "<project>: what it is, stack, entry points" -i 3`, plus decisions taken. Put the remaining work in TASKS.md Queue (`mem task park "..."`).
8. **Close:** run the tests and builds that existed before, confirm nothing broke (finish-task skill), then commit only your own files.
