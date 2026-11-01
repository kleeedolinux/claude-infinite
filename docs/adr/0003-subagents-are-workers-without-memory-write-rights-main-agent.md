# ADR-0003: Subagents are workers without memory-write rights; main agent is CTO, user is lead

- status: accepted
- date: 2026-11-01
- affects: src/infinite/chat.py,src/infinite/verify.py,infinite.hooks.subagent_stop,agents/worker.md
- supersedes: -

## Context
Parallel subagents writing memory duplicate and contradict notes; unchecked worker reports spread hallucinations; the user wants to stay in charge.

## Decision
Only the main agent (and memory-curator) write memory; workers claim files and coordinate via mem chat; SubagentStop verifies their reports against the repo and sends them back once; lead-level decisions escalate to the user.

## Alternatives considered
Let every agent write memory (rejected: duplicates, no judgment of what is known). No chat, everything through the main agent's context (rejected: context blow-up on big projects).

## Consequences
The CTO must record lasting facts from reports; workers can stall on questions, so they post them and continue unblocked work.
