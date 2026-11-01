---
name: infinite-memory
description: Full reference for `mem`, the persistent memory (notes, recall, summary tree, supersede, reflect, doctor). Use when unsure how to record, find, fix or summarize memories, when wake shows CONFLICT/RECURRING ERROR/NAP lines, or when memory looks wrong, stale or missing.
---

# Infinite memory (`mem`)

The source of truth is the append-only log at `~/.claude/infinite/data/log.jsonl`. The SQLite FTS5 index next to it is a cache: `mem rebuild` recreates it from the log. Never edit anything under `data/` by hand.

## What to record (and what not)
- Record what is not derivable from the code or git history: decisions with their reasons, user preferences, lessons, experiment verdicts, facts about external systems, and ideas.
- Don't record what the repo already says, or chit-chat. One fact per note, written so it makes sense alone in a year: name the thing and the project.
- Choose the scope:
  - Project scope is the default (the git root or the folder with CLAUDE.md).
  - Use `-g` for the user's identity and preferences, and for cross-project lessons.
- Importance (`-i 1-5`): 4-5 is a lasting rule or critical fact (lessons and prefs rated 4+ become RULES), 2 is normal, 1 is trivia.
- Anything inside `<private>…</private>` is stripped before storage.

## Commands
| Need | Command |
|---|---|
| Record | `mem note "..." -k decision -i 3` (kinds: fact decision lesson pref mistake idea todo experiment insight person project ref report) |
| Park an idea | `mem idea "..."` (memory + TASKS.md Queue) |
| Search | `mem recall words` · `-a` all projects · `-x regex` · `--history` includes superseded |
| Drill down | `mem get <id>` (full text + links) · `mem timeline <id>` (neighbours) · `mem zoom a-b` (open a summary) |
| Correct | `mem supersede <old> "new text"` or `mem supersede <old> --by <id>` · `mem forget <id>` · `mem restore <id>` |
| Promote | `mem pin <id>` (always shown) · `mem importance <id> 5` · `mem link <a> <b> causes` |
| Tree | `mem naps` · `mem nap a-b "one line"` · `mem unnap a-b` (drop a bad summary) |
| Health | `mem reflect` · `mem inbox` · `mem doctor [--fix]` · `mem stats` · `mem rules` · `mem view` |
| Graph | `mem graph` (mermaid: projects, tags, links) · `mem project list` |
| Tasks / KB | `mem task park\|start\|done "..."` · `mem kb new <area> "<title>" --verdict works --evidence ".."` |
| Config | `mem config wake_lines=80` (reading budget only; nothing is recomputed) |

## How it works
- **Wake** (SessionStart hook) prints these sections:
  - the RULES
  - the CONFLICT and RECURRING ERROR lines that need attention
  - the TASKS.md excerpt
  - global memory
  - project memory: recent notes verbatim, older ones as `@a-b` summaries (coarser with age, never lost)
  - at most one due NAP

  After a compaction, the user's verbatim requests are re-injected first.
- **Prompt recall** (UserPromptSubmit hook) injects the top relevant memories. It adds the anti-bias protocol for idea prompts, the parking-lot note for mid-task ideas, and a lesson nudge for corrections. `#fresh` turns injection off.
- **Harvest** (the Stop, PreCompact and SessionEnd hooks) scans the transcript for tool errors and user corrections and puts them in the inbox. Errors with the same signature are counted and reported as RECURRING.
- **Write decision:**
  - A near-duplicate is reinforced instead of added.
  - Similar notes are shown to you.
  - A negation mismatch becomes a CONFLICT.
  - Superseding invalidates the affected summaries, which get re-napped.

## Writing a NAP (summary) line
- One line, at most 280 chars. Keep the user's words, decisions, corrections, verdicts and their reasons close to verbatim. Drop process noise and invent nothing.
- Skip superseded or forgotten lines.
- Name things concretely ("parser: switched to lark because regex failed on nested quotes"), never "various improvements".

## When memory is wrong
1. Verify against the code, and the user if needed.
2. `mem supersede <id> "corrected fact"`. Never just add a contradicting note and leave both.
3. If a summary is wrong, run `mem unnap a-b` and nap it again.
4. If the index is corrupt or the counts mismatch, run `mem doctor --fix`.
