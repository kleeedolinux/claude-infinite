---
name: docs
description: Real project documentation instead of summary slop - code atlas (index, graphs), ADRs (architecture decision records) linked to code, generated ARCHITECTURE.md, glossary, and a static visual docs site. Use when the user wants docs, architecture docs, decision records/ADRs, diagrams/graphs of the project, a docs website, or to document why something was decided.
---

# Docs that stay true

**Rule: generated facts and written reasoning are kept apart, and both stay tied to the code.** The facts are tables and graphs derived from the code index. The reasoning lives in ADRs and the human-written overview. Never write prose that restates what the index already shows.

## The pieces
| Piece | Command | Where |
|---|---|---|
| Code index (symbols, calls, imports, docs chunks) | `mem code index` (automatic on session start and stop) | `~/.claude/infinite/data/atlas/` |
| Search code and docs (graph-expanded) | `mem code search <words>` | index layer: path:line plus title |
| Overview | `mem code map` · `mem code graph` (mermaid) | stdout |
| Architecture doc | `mem code docs` | `docs/ARCHITECTURE.md`: generated block between markers, human overview outside them |
| Decisions | `mem adr new "<title>" --context .. --decision .. --alternatives .. --consequences .. --affects path,symbol` | `docs/adr/NNNN-*.md`, plus an index in `docs/adr/README.md` |
| Glossary | `mem term add` | `docs/GLOSSARY.md` |
| Visual site | `mem code site` | `docs/site/index.html`: offline, single file, with module graph, call graphs, search, ADRs, glossary and memory |

## When to write an ADR
Write one when the decision is hard to reverse, people will ask "why is it like this?", alternatives were seriously considered, or the user stated a constraint.
- Give at least 2 real alternatives, each with the reason it was rejected.
- The consequences cover what gets harder, not only the benefits.
- `--affects` names files and symbols, so ADRs show up in `mem code explain` and subagent briefs.
- A changed decision gets a new ADR with `--supersedes ADR-000N`. Never edit history away.
- Run `mem adr check` after refactors. It flags ADRs whose files or symbols are gone, and unfilled TODO sections.

## Documenting a project
1. `mem code index`, then `mem code map`. Read the entry points and hubs with `mem code explain`.
2. Write the human overview at the top of `docs/ARCHITECTURE.md`, about 1-3 paragraphs: what the system does, the main flow, why it is shaped this way (link the ADRs). Every claim cites `file:line`. Mark guesses as NOT verified.
3. Turn existing decisions found in memory and git history (`mem recall decision -a`, `git log`) into ADRs.
4. `mem code docs`, then `mem code site`. Tell the user the path of `docs/site/index.html`.
5. Rerun `mem code docs` and `mem code site` after big changes. They only regenerate the generated parts.
