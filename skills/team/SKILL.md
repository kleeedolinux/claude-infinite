---
name: team
description: Run a team - user is lead, main agent is CTO, subagents are workers with limited rights - split work by disjoint file ownership, worktrees, frozen shared interfaces, saved reports, memory rules for subagents, and a task dependency graph. Use when work is large enough to parallelize, the user asks for agents/subagents/a team/parallel work, or several agents touch one checkout.
---

# Team of subagents

## Org chart and rights
| Role | Who | Decides | May | May not |
|---|---|---|---|---|
| **Lead** | the user | goals, taste, scope, priorities; anything irreversible, public, costly or security-relevant | everything | — |
| **CTO** | the main agent | architecture (ADRs), the task split, interfaces, who owns what, integration, what gets recorded in memory | plan, delegate, write memory/ADRs, integrate, run everything, commit if the lead wants commits | override the lead; take irreversible, public or costly actions without the lead's OK |
| **Worker** | `worker` agent (or general-purpose given the worker brief) | how to implement inside its claim | edit claimed files, run tests, read memory/code, post in chat | write memory, edit outside its claim, change APIs/architecture/dependencies/scope, commit/push, talk to the lead |
| **Reviewer** | `reviewer` agent | nothing (reports defects) | read, run tests | edit anything |
| **Specialists** | `project-architect`, `idea-critic` (read-only), `memory-curator` (memory only) | nothing | their narrow job | anything else |

**Escalation:** worker → CTO (`@main` in `#plan`, `--kind question`, with a recommended option) → lead, for the lead-level items above. The CTO answers what it can and batches the rest into one short question to the lead. Workers keep doing unblocked work instead of waiting.

## Before splitting
- Parallelize only independent work. Shared code is frozen and tested first, and function signatures are agreed in writing.
- Draw the task graph in TASKS.md: each task lists its owner, the files it touches and what it depends on (`mem task start "..." --owner agent-x --files src/x`). Tasks touching the same files are never in parallel.
- Subagents start blank, and a glossary or prose doesn't help them. For each subagent's task, run `mem code brief "<its task>"` and paste the result into the brief. It gives the exact line ranges to work in, the blast radius (callers), existing tests, ADR constraints, project rules and others' claims, in under 2.6k chars. Add the relevant `mem recall` facts.

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
- `worker`: implements one scoped task on claimed files, with the rights above.
- `reviewer`: independent read-only check of a worker's change before integration.
- `memory-curator`: consolidates memory. It is the only subagent allowed to write memory.
- `idea-critic`: independent devil's advocate for ideas and decisions. Give it options, not your conclusion.
- `project-architect`: scans projects and proposes structure, migration and monorepo plans. Read-only.
- Built-in `Explore` for broad searches, `Plan` for implementation plans, `general-purpose` for execution.

## Running
- Run independent agents in one message so they execute in parallel. Use `isolation: "worktree"` when they edit code.
- Reports are saved automatically to `~/.claude/infinite/data/reports/<project>/` by the SubagentStop hook. Cite them; don't re-ask.
- The main agent integrates the work, runs the full tests, records decisions and lessons (`mem note`), and updates TASKS.md.
- Their mistakes come back in the same confident tone as their findings, so verify claims that matter before relying on them.
