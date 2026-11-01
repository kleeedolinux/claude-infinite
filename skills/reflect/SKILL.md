---
name: reflect
description: Self-improvement loop - turn corrections, recurring errors, conflicts and stale memories into concrete lessons, rules, skill updates or tool fixes; consolidate memory. Use when wake shows unprocessed corrections/recurring errors/conflicts, at the end of a big task, when the user says "learn from this"/"improve yourself"/"aprenda", or periodically.
---

# Reflect (get better every session)

1. `mem reflect` prints the agenda: inbox (user corrections, recurring tool errors, conflicts), stale memories and due naps.
2. **For each item, find the concrete cause.** Not "I was careless" but "I assumed uv because #12 said so; #12 was outdated".
3. **Pick exactly one destination:**
   - **Lesson:** `mem note -k lesson "when X, do Y, because Z" -i 3`. Repeats get reinforced into RULES shown at every wake.
   - **Correction of memory:** `mem supersede <id> "..."`.
   - **Area skill:** add a dated line under `## Lessons` in `.claude/skills/<area>/SKILL.md`, newest first. Create the skill when an area has 5 or more lessons or the same correction happened twice.
   - **Tool or script:** if the same error recurs (RECURRING ERROR x3 or more), fix the root cause with a script, a check or a config change, then record it.
   - **Global behaviour:** a lesson true in every project goes in with `-g`. If it changes how memory works, propose an edit to the `claudeinfinite` repo (`~/Documents/claudeinfinite`, then `python install.py`) instead of patching around it.
   - **Dismiss:** if it is noise, close it with `mem inbox done <id>`.
4. Close the handled items: `mem inbox done <ids>`.
5. **Consolidate:**
   - Run due naps.
   - Supersede duplicates `mem doctor` reports.
   - Verify stale notes against the code (keep, supersede or forget).
6. **Report** in 3-6 lines: what was learned, where it went, and what is still unverified. Vague lessons are worse than none: every lesson names a trigger and an action.

For a large backlog, delegate to the `memory-curator` agent. It is the only subagent allowed to write memory, and it reports what it changed.
