# ADR-0002: Stdlib-only Python, hooks always exit 0 and stay under ~1s

- status: accepted
- date: 2026-11-01
- affects: src/infinite/hooks.py,infinite.hooks.run,infinite.hooks._auto_index
- supersedes: -

## Context
The system runs in every Claude Code session on any machine; a broken or slow hook would block or annoy every session.

## Decision
No third-party dependencies; every hook wraps its work in hooks.run, logs failures to hook-errors.log and exits 0; indexing in hooks is time-boxed (2s start, 1.5s stop) and incremental.

## Alternatives considered
Use a vector DB or embeddings for recall (rejected for now: dependency + model download; FTS5 with porter stemming plus the graph covers recall; revisit if recall misses). Background daemon (rejected: more moving parts on Windows).

## Consequences
Recall is lexical plus graph-based, not semantic; large repos finish indexing over a few sessions.
