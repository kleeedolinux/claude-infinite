---
name: team
description: Organize multiple subagents on one project - split work by disjoint file ownership, worktrees, frozen shared interfaces, saved reports, memory rules for subagents, and a task dependency graph. Use when work is large enough to parallelize, the user asks for agents/subagents/a team/parallel work, or several agents touch one checkout.
---

# Team of subagents

## Before splitting
- Parallelize only independent work. Shared code is frozen and tested first, and function signatures are agreed in writing.
- Draw the task graph in TASKS.md: each task lists its owner, the files it touches and what it depends on (`mem task start "..." --owner agent-x --files src/x`). Tasks touching the same files are never in parallel.
- Use `mem recall` to collect the facts each agent needs, and paste them into its brief. Subagents start blank.

## Team chat: agents talk to each other, not through you
`mem chat` is a per-project Slack-like board (`~/.claude/infinite/data/chat.db`, kept apart from memory). The main agent is the **compositor**: it posts the plan, spawns workers, reads only the digests, and integrates the results.
- **Channels:**
  - `#plan` holds the split, the frozen interfaces and decisions.
  - `#<area>` holds work talk.
  - `#reports` gets auto-posted when a subagent stops.
  - `#claims` gets auto-posted on claim and release.
- **Kinds:** `--kind decision|blocker|question|done|msg`. Decisions, blockers, questions and done messages appear in wake's "Team chat" section and in `mem chat digest`.
- **Ownership:**
  - `mem chat claim "src/api/*" --as api` before editing; overlapping claims are refused.
  - `mem chat release --as api` when finished (done automatically at SubagentStop).
  - `mem chat who` lists live claims.
- **Messaging:**
  - `mem chat read --as <me>` gives unread messages and @mentions; the cursor advances, so nothing is re-read.
  - `@name` pings an agent; `@all` pings everyone.
  - Use `@main` for questions only the compositor or user can answer. Don't stall: keep doing unblocked work.

## Brief template (every spawn)
```
Goal: <one sentence>. Done when: <check>.
Context: <facts + mem ids>. Already ruled out: <...>.
You are agent "<name>". You own ONLY: <files/dirs> — first run `mem chat claim "<glob>" --as <name>`.
Coordinate via team chat: `mem chat read --as <name>` at start and between steps; post decisions/blockers to #plan
(`mem chat post plan "..." --as <name> --kind decision|blocker|question`); ask peers with @their-name.
Verify with: <command>. Report: Done / How verified / NOT verified / Files changed.
You are a subagent: you may read memory (mem recall/get/zoom) and use mem chat, but do not write memory (no mem note).
```

## Big projects (compositor loop)
1. Post the plan to `#plan` as `decision`: areas, owners, frozen interfaces and the task graph. Mirror it in TASKS.md.
2. Spawn the independent workers in one message, in the background, with worktrees if they edit code.
3. While they work, handle `@main` mentions (`mem chat read --as main`) and answer in `#plan`.
4. As reports land (`#reports` and the saved files), integrate, run the full tests, and record the lasting decisions with `mem note`.
5. Spawn the next wave from the task graph. Finish with the finish-task skill.

## Roles (agents in ~/.claude/agents)
- `memory-curator`: consolidates memory. It is the only subagent allowed to write memory.
- `idea-critic`: independent devil's advocate for ideas and decisions. Give it options, not your conclusion.
- `project-architect`: scans projects and proposes structure, migration and monorepo plans. Read-only.
- Built-in `Explore` for broad searches, `Plan` for implementation plans, `general-purpose` for execution.

## Running
- Run independent agents in one message so they execute in parallel. Use `isolation: "worktree"` when they edit code.
- Reports are saved automatically to `~/.claude/infinite/data/reports/<project>/` by the SubagentStop hook. Cite them; don't re-ask.
- The main agent integrates the work, runs the full tests, records decisions and lessons (`mem note`), and updates TASKS.md.
- Their mistakes come back in the same confident tone as their findings, so verify claims that matter before relying on them.
