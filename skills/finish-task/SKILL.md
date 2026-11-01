---
name: finish-task
description: Closing checklist for any non-trivial task - tests, compatibility, warnings, duplication review, records, TASKS.md, report with unverified items, lesson, scoped commit. Use before saying a task is done, when the user says "finish/wrap up/close/terminar", or before committing.
---

# Finish a task (never skip steps; say which ones don't apply)

1. **Tests:** run the relevant suite and report the result. Add a test for the bug or feature if missing.
2. **Compatibility:** for serialized data, configs, APIs or CLIs, check that old data and callers still work.
3. **No new warnings** from the build, linter or type checker.
4. **UI changes:** look at them (screenshot or run). Check every supported language and theme.
5. **Duplication review:** search for code that already did this and reuse it. Extract shared logic on the second occurrence.
6. **Records:**
   - `mem note` for decisions and facts.
   - `mem kb new <area> "<title>" --verdict works|fails --evidence ".." --repro ".."` for measurements.
   - Supersede anything the task made outdated.
7. **TASKS.md:** `mem task done "<task>"`. New follow-ups go in with `mem task park "..."`.
8. **Report** in fixed sections: Done / How verified / NOT verified / Follow-ups. Unverified claims must be labeled, or they become "facts" later.
9. **Lesson:** if anything went wrong or was corrected, record one concrete lesson (see the reflect skill).
10. **Commit** (if the user wants commits) only this task's files: stage them by path (no `git add -A` on a shared checkout), check `git diff --cached --stat`, then commit.
