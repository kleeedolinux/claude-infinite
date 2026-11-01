# Knowledge base

One record per finding. Never copy a number elsewhere: cite the record id.

```
### KB-NNNN YYYY-MM-DD <area> — <title>
verdict: works | fails | open      supersedes: KB-xxxx (optional)
evidence: <what was measured, where>
reproduce: `<command>`
```

Rules: check here (and `mem recall`) before measuring or trying anything; do not repeat a failed
experiment unless the hypothesis changed (say what changed); when a fact changes, mark the old
record superseded and link it.

### KB-0001 2026-11-01 perf — Atlas indexing: fork/join parse, reduce to bulk writes, lazy incremental resolve
verdict: works
evidence: WOLOS 518 files: full 1.71s->1.17s; noop 0.093s->0.033s; 1 changed 0.44s->0.084s; hook stop 0.13s->0.07s; hooks import 44ms->22ms; session-start 0.34s->0.16s (background indexer). Processes only >=250 files (spawn ~0.1-0.3s on Windows).
reproduce: `python tests/bench_atlas.py <repo>`
