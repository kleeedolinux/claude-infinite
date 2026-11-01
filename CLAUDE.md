# claudeinfinite

Source of the global memory system installed at `~/.claude/infinite`. Edit here, then `python install.py`. Never edit the installed copy.

## Rules
- Stdlib-only Python 3.11+. Hooks must stay fast (well under 1s) and always exit 0 (`hooks.run`). Failures go to `~/.claude/infinite/data/hook-errors.log`.
- The log (`log.jsonl`) is the truth. Every state change that matters is an event that goes through `core.emit` and is replayed by `core.apply`. Inbox, chat and session state are derived or ephemeral.
- Hook context is written as plain facts (prompt-injection defenses dislike imperative "system" text) and stays under 10k chars.
- Writing Python that contains backslash escapes via bash heredocs breaks here: `\\n` arrives as a real newline. Use the Write/Edit tools, or `chr(10)`/`chr(92)`.
- Run `python -m unittest tests/test_mem.py` before installing. Run `python tests/live_hooks.py <project>` after.

## Map
- `src/infinite/`: core (store), tree (summaries), wake (context), harvest (transcripts), hooks, verify (hallucinations), chat (agents), projects, tasks, cli
- `skills/`, `agents/`: copied to `~/.claude/skills` and `~/.claude/agents` by install.py
- `claude/CLAUDE.global.md`: the block inserted at the top of `~/.claude/CLAUDE.md`
- `../claudeinfinite-refs/`: read-only clones of OptMem and uniichat (reference only; never run their code)
