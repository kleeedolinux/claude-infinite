# ADR-0001: Append-only log is the source of truth; SQLite is a rebuildable cache

- status: accepted
- date: 2026-11-01
- affects: src/infinite/core.py,infinite.core.emit,infinite.core.apply,infinite.core.rebuild
- supersedes: -

## Context
Memory must never be lost across sessions, crashes, schema changes or index corruption; agents and hooks write concurrently.

## Decision
Every state change is an event appended to data/log.jsonl via core.emit; core.apply replays events into index.db; mem rebuild / doctor --fix recreate the index from the log.

## Alternatives considered
SQLite as the only store (rejected: corruption or a bad migration loses memory). Markdown files per memory like Claude Code auto-memory (rejected: no ranking, slow search, hard to dedupe at scale).

## Consequences
Index can always be rebuilt; inbox, chat and session state are not in the log and are treated as ephemeral; log grows forever (fine: ~200 bytes per note).
