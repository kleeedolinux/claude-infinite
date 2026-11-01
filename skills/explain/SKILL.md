---
name: explain
description: Explain a project, feature, function or concept to the user so they actually learn it - what it IS (concept), why it exists here, how it really works (grounded in code with file:line and call flow), defining only terms new to them, and remembering what they learned. Use when the user asks how something works, what something is, why it is built this way, to walk through code, or says they don't understand ("como funciona", "o que é", "explica", "não entendi").
---

# Explain (teach, grounded in the real code)

## 1. Gather facts, not vibes
- `mem explain "<question>"` gives a grounded pack: glossary terms (marked new or known to this user), code and doc locations, ADRs and memories.
- For a function or flow:
  - `mem code explain <symbol>`: signature, docstring, callers, callees, tests, decisions, source.
  - `mem code flow <symbol> --depth 3`: what really happens, call by call.
- For the whole project: `mem code map` (modules, entry points, dependencies, hubs, untested code).
- Read only the line ranges these give you. Never explain code you have not read.

## 2. Answer in layers (stop where the user's question stops)
1. **What it is:** the concept in plain words, with no code. Add one everyday analogy. If it is a general CS or industry concept (FTS5, BM25, ADR, monorepo, bi-temporal), explain the concept itself first. Implementation comes later.
2. **Why it exists here:** the problem it solves in this project. Cite the ADR, memory or commit, or say "reason not recorded".
3. **How it works here:** the real flow as numbered steps. Each step is one sentence plus its `file:line`. Add a mermaid diagram when there are 3 or more moving parts (`mem code flow` prints one).
4. **Terms:** define every term that is new to this user, once and briefly. Skip terms marked as known.
5. **Limits:** what you did not verify, and edge cases you noticed.

Use the user's language. No filler, no "in summary".

## 3. Remember, so the next explanation is better
- New concept: `mem term add "<Term>" --what "<concept, plain>" --why "<why here>" --analogy "<..>" --how "<file:line or symbols>"`. This writes `docs/GLOSSARY.md` and memory.
- When the user shows they understood (they use it correctly, or say so): `mem learned <Term>`. Later explanations then skip it.
- A missing reason that you found ("why is it like this?"): record it as an ADR (docs skill) or `mem note -k decision`.
- `mem term candidates` lists project terms that are still undefined. Offer to define the important ones.
