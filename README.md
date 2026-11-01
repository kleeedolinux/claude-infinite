# claudeinfinite

Infinite, self-correcting memory and project organization for **Claude Code**, on by default in every project. It is pure Python standard library: no dependencies, no server, no API calls from hooks.

```
python install.py            # install / update (idempotent; backs up settings.json)
python install.py --uninstall  # remove everything except your memories
mem help
```

## What you get

| Need | How |
|---|---|
| Never forget (sessions, compactions, models) | An append-only log (`~/.claude/infinite/data/log.jsonl`) is the truth. The SQLite FTS5 index is a rebuildable cache (`mem rebuild`). |
| Memory in every project, automatically | A `SessionStart` hook injects the wake document: rules, alerts, tasks, team chat, global and project memory. A `UserPromptSubmit` hook injects the top relevant memories for each prompt. |
| Survive auto-compaction | `UserPromptSubmit` stores your words verbatim. `PreCompact` snapshots them, `PostCompact` saves the summary, and `SessionStart(compact)` re-injects your original requests as the goal. |
| Huge memory, small context | A zoomable binary summary tree (from OptMem/uniichat): recent notes stay verbatim, older ones become coarser `@a-b` summaries, and `mem zoom` descends. Summaries ("naps") are lazy: they are only requested when the view needs them. |
| Auto-fix errors | Near-duplicates are reinforced instead of duplicated. Negation mismatches become a CONFLICT. `supersede` is bi-temporal: the old fact is hidden, never deleted, and affected summaries are rebuilt. `mem doctor --fix` repairs the index from the log and flags stale file references. |
| Learn from mistakes | Tool errors and your corrections ("no, you forgot…", "não, errado…") are harvested from transcripts into an inbox. Repeated errors become RECURRING ERROR alerts. A lesson reinforced twice becomes a RULE shown at every wake. If you corrected Claude and it recorded nothing, the Stop hook asks once for a lesson. The `reflect` skill turns the inbox into rules, skills or fixes. |
| Catch hallucinations | When any agent stops, the paths, line numbers and code symbols cited in its final message are checked against the repo. A subagent with false claims is sent back once to verify them. If they are still wrong, the compositor gets an `@main` blocker on `#plan` and the saved report is marked UNVERIFIED. |
| Ideas without bias or derailing | Idea prompts get an anti-bias protocol: 3 or more real options, a premortem, and memory labeled separately from fresh reasoning. `#fresh` turns memory injection off. A mid-task idea is parked with `mem idea` (memory plus the TASKS.md Queue), and work continues. `mem bias "<idea>"` lists anchors and past failures. |
| Big projects with many agents | `mem chat`: a per-project Slack-like board with channels, @mentions, unread cursors, file claims (overlaps refused) and a digest. Subagent reports are saved and posted to `#reports` automatically. The main agent acts as the compositor (see the `team` skill). |
| Organize projects | `mem project new` (python, uv monorepo, or generic), `scan`, `migrate` (never overwrites), `monorepo` (plan with git subtree moves), `import-claude` (pulls in Claude Code's own memory files), and `graph` (mermaid of projects, tags and links). |
| Continuity files | `.claude/TASKS.md` (In progress / Queue / Done) via `mem task`, and `docs/kb/` records with verdicts and supersedes, with IDs assigned at write time, via `mem kb`. |

## Installed pieces
- `~/.claude/infinite/`: the code (`mem.py`, `infinite/`), `config.json`, and `data/`: your memories, chat and reports. The installer never touches `data/`.
- `~/.claude/CLAUDE.md`: a short memory block between `infinite-memory` markers, in the style of OptMem's prompt.
- `~/.claude/settings.json`: 7 hooks plus permission to run `mem` without prompts.
- `~/.claude/skills/`: infinite-memory, new-project, migrate-project, monorepo, idea-lab, reflect, finish-task, team.
- `~/.claude/agents/`: memory-curator (the only subagent allowed to write memory), idea-critic, project-architect.
- `~/.local/bin/mem` and `mem.cmd`.

## Layout
```
src/infinite/
  core.py      event log + FTS5 index, write decisions, scoring, rules, inbox
  tree.py      summary tree: cover, lazy naps, zoom
  wake.py      wake document, per-prompt recall, anti-bias and parking-lot text
  harvest.py   session state (verbatim prompts), transcript error/correction harvest
  hooks.py     Claude Code hook entry points (always exit 0)
  verify.py    hallucination check (paths, line ranges, symbols)
  chat.py      agent team chat, claims, digest
  projects.py  scaffold / scan / migrate / monorepo plan / import / graph
  tasks.py     TASKS.md and docs/kb
  cli.py       `mem` command
skills/ agents/ claude/CLAUDE.global.md install.py tests/
```

## Config (`mem config key=value`)
| Key | Default | Meaning |
|---|---|---|
| `wake_lines` | 60 | Tree lines per scope at wake. This is a reading budget; nothing is recomputed. |
| `wake_chars` | 9000 | Cap on the SessionStart context. Claude Code caps it at 10k. |
| `prompt_chars` / `prompt_hits` | 1800 / 5 | Size of the per-prompt recall. |
| `rule_threshold` | 2 | Reinforcements before a lesson or pref becomes a RULE. |
| `stop_reflect` | true | Ask once for a lesson after uncorrected corrections. |
| `verify_claims` | true | Hallucination check at Stop and SubagentStop. |

`INFINITE_HOME` relocates everything, for example to a synced folder.

## Credits / ideas borrowed
- **OptMem** (VictorTaelin): append-only log, the binary summary tree and its `cover` algorithm, a short prompt.
- **uniichat**: a zoomable tree that "never rots", and compaction that keeps the user's words near-verbatim.
- **joaodavisn, "projetos grandes com Claude"**: task file loaded by a hook, KB with verdicts and supersedes, area skills with lessons, the closing checklist, saved subagent reports.
- **Others:** Zep/Graphiti (bi-temporal invalidation), mem0 (add/update/noop at write time), Generative Agents (recency + importance + relevance), Reflexion (lessons from failures), claude-mem (`<private>`, layered recall), A-MEM and Basic Memory (links and tags graph).

## Tests
`python -m unittest tests/test_mem.py` runs against a temporary `INFINITE_HOME`. `python tests/live_hooks.py <project>` exercises the installed hooks.
