import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TMP = tempfile.mkdtemp(prefix="infinite-test-")
os.environ["INFINITE_HOME"] = TMP
os.environ.pop("CLAUDE_PROJECT_DIR", None)

from infinite import cli, core, harvest, hooks, projects, tasks, tree, wake  # noqa: E402


def run_hook(fn, inp):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(inp)
    out = buf.getvalue()
    return json.loads(out) if out.strip() else {}


def cli_out(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(list(argv))
    return buf.getvalue()


class MemTest(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp(prefix="proj-"))
        (self.proj / ".git").mkdir()
        self.scope = core.scope_key(self.proj)
        os.chdir(self.proj)

    def test_dedupe_reinforce_and_rule_promotion(self):
        a = core.note("Always run tests with pytest -q before committing", self.scope, kind="lesson")
        b = core.note("always run tests with pytest -q before committing!", self.scope, kind="lesson")
        self.assertEqual(b["status"], "reinforced")
        self.assertEqual(b["id"], a["id"])
        core.note("Always run the tests with pytest -q before committing", self.scope, kind="lesson")
        with core.db() as c:
            self.assertIn(a["id"], [r["id"] for r in core.rules(c, self.scope)])

    def test_contradiction_goes_to_inbox_and_supersede_closes_it(self):
        a = core.note("The API uses REST endpoints for clients", self.scope)
        b = core.note("The API does not use REST endpoints for clients anymore", self.scope)
        self.assertTrue(any("CONTRADICTION" in s for s in b["similar"]))
        core.supersede(a["id"], None, None, new_id=b["id"])
        with core.db() as c:
            self.assertEqual(c.execute("select count(*) from inbox where kind='conflict' and status='open'"
                                       " and sig like ?", ("conflict:%d:%%" % a["id"],)).fetchone()[0], 0)
            ids = [r["id"] for r in core.search(c, "REST endpoints", scopes=[self.scope])]
        self.assertIn(b["id"], ids)
        self.assertNotIn(a["id"], ids)

    def test_private_is_stripped(self):
        r = core.note("deploy key is <private>sk-123</private> stored in vault", self.scope, force=True)
        with core.db() as c:
            t = c.execute("select text from notes where id=?", (r["id"],)).fetchone()[0]
        self.assertNotIn("sk-123", t)
        self.assertNotIn("sk-123", core.log_path().read_text(encoding="utf-8"))

    def test_rebuild_from_log(self):
        core.note("rebuild survives index loss marker", self.scope, force=True)
        with core.db() as c:
            before = c.execute("select count(*) from notes").fetchone()[0]
        core.rebuild()
        with core.db() as c:
            after = c.execute("select count(*) from notes").fetchone()[0]
        self.assertEqual(before, after)

    def test_tree_cover_and_lazy_naps(self):
        self.assertEqual(tree.cover(5, 10), [(i, i + 1) for i in range(5)])
        cv = tree.cover(1000, 40)
        self.assertLessEqual(len(cv), 40)
        self.assertEqual(cv[0][0], 0)
        self.assertEqual(cv[-1][1], 1000)
        for (a, b), (c_, d) in zip(cv, cv[1:]):
            self.assertEqual(b, c_)
        s = core.scope_key(self.proj / "treeproj")
        for i in range(30):
            core.note("tree note %d about topic%d" % (i, i), s, force=True)
        with core.db() as c:
            self.assertEqual(tree.pending(c, s, budget=40), [])
            due = tree.pending(c, s, budget=8)
            self.assertTrue(due)
            lines, missing = tree.render(c, s, 8)
            self.assertTrue(any("not summarized" in l for l in lines))

    def test_hook_lifecycle_and_compaction_recovery(self):
        sid = "sess-" + self.scope[-6:]
        out = run_hook(hooks.session_start, {"session_id": sid, "cwd": str(self.proj), "source": "startup"})
        self.assertIn("Infinite memory", out["hookSpecificOutput"]["additionalContext"])
        run_hook(hooks.user_prompt, {"session_id": sid, "cwd": str(self.proj), "prompt": "Build the CSV importer"})
        o = run_hook(hooks.user_prompt, {"session_id": sid, "cwd": str(self.proj),
                                         "prompt": "also, new idea: what if we add a dashboard?"})
        self.assertIn("mem idea", o["hookSpecificOutput"]["additionalContext"])
        o = run_hook(hooks.user_prompt, {"session_id": sid, "cwd": str(self.proj), "prompt": "no, you forgot the header row"})
        self.assertIn("correction", o["hookSpecificOutput"]["additionalContext"])
        tr = self.proj / "t.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "Build the CSV importer"}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                                                           "content": "FileNotFoundError: C:\\a\\b.csv line 3"}]}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                                                           "content": "FileNotFoundError: C:\\x\\y.csv line 9"}]}}]
        tr.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
        run_hook(hooks.pre_compact, {"session_id": sid, "cwd": str(self.proj), "transcript_path": str(tr)})
        run_hook(hooks.post_compact, {"session_id": sid, "cwd": str(self.proj), "compact_summary": "summary text"})
        with core.db() as c:
            n = c.execute("select count from inbox where kind='error' and scope=?", (self.scope,)).fetchone()[0]
        self.assertEqual(n, 2)  # same signature -> one recurring item
        ctx = run_hook(hooks.session_start, {"session_id": sid, "cwd": str(self.proj), "source": "compact"})
        ctx = ctx["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Recovered after compaction", ctx)
        self.assertIn("Build the CSV importer", ctx)
        self.assertIn("RECURRING ERROR", ctx)
        st = run_hook(hooks.stop, {"session_id": sid, "cwd": str(self.proj), "transcript_path": str(tr)})
        self.assertEqual(st.get("decision"), "block")
        st2 = run_hook(hooks.stop, {"session_id": sid, "cwd": str(self.proj), "stop_hook_active": True})
        self.assertEqual(st2, {})
        self.assertLess(len(ctx), 10000)

    def test_fresh_mode_injects_no_memory(self):
        core.note("The favourite framework is Django", self.scope, force=True)
        ctx = wake.prompt_context("#fresh ideas for framework choice", self.scope)
        self.assertNotIn("Django", ctx)

    def test_tasks_and_kb(self):
        tasks.op(self.proj, "park", "idea: dark mode")
        tasks.op(self.proj, "start", "dark mode", owner="ui-agent", files="ui/theme.py")
        t = tasks.listing(self.proj)
        self.assertIn("[ui-agent] idea: dark mode — files: ui/theme.py", t)
        tasks.op(self.proj, "done", "dark mode")
        self.assertIn("## Done\n- ", tasks.listing(self.proj))
        k1 = tasks.kb_new(self.proj, "perf", "gzip level 6", "works", "2x smaller", "python bench.py")
        k2 = tasks.kb_new(self.proj, "perf", "gzip level 9", "fails", "slower", supersedes=k1)
        self.assertEqual((k1, k2), ("KB-0001", "KB-0002"))
        self.assertIn("SUPERSEDED by KB-0002", (self.proj / "docs/kb/README.md").read_text(encoding="utf-8"))
        self.assertEqual(tasks.kb_check(self.proj), [])

    def test_project_new_monorepo_and_scan(self):
        root = self.proj / "mono"
        created = projects.new(str(root), kind="monorepo", purpose="test mono", areas=["core", "api"])
        self.assertTrue((root / "packages/core/pyproject.toml").exists())
        self.assertTrue((root / ".claude/skills/api/SKILL.md").exists())
        self.assertTrue(any("CLAUDE.md" in c for c in created))
        info = projects.scan(str(root))
        self.assertIn("pyproject.toml", info["manifests"])
        again = projects.new(str(root), kind="monorepo")
        self.assertFalse(any("CLAUDE.md" in c for c in again))  # never overwrites

    def test_cli_smoke(self):
        out = cli_out("note", "CLI smoke note about parsers", "-k", "decision")
        self.assertIn("Saved", out)
        self.assertIn("CLI smoke", cli_out("recall", "parsers"))
        self.assertIn("healthy", cli_out("doctor")) if "hook errors" not in cli_out("doctor") else None
        self.assertIn("graph LR", cli_out("graph"))
        self.assertIn("Bias check", cli_out("bias", "rewrite", "parsers", "in", "rust"))


class VerifyChatTest(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp(prefix="vproj-"))
        (self.proj / ".git").mkdir()
        (self.proj / "src").mkdir()
        (self.proj / "src" / "real.py").write_text("def parse_rows(x):\n    return x\n", encoding="utf-8")
        self.scope = core.scope_key(self.proj)
        os.chdir(self.proj)

    def test_verify_flags_missing_paths_lines_and_symbols(self):
        from infinite import verify
        text = ("I fixed `parse_rows()` in src/real.py:2.\n"
                "Also updated src/ghost.py and `load_config()` handles it.\n"
                "See src/real.py:500 for details.\n"
                "Next step: create src/new_module.py.\n")
        sus = verify.check(text, self.proj)
        joined = " | ".join(sus)
        self.assertIn("src/ghost.py", joined)
        self.assertIn("load_config", joined)
        self.assertIn("real.py:500", joined)
        self.assertNotIn("new_module", joined)       # proposals are not hallucinations
        self.assertNotIn("parse_rows", joined)
        self.assertEqual(verify.check("All good in src/real.py and `parse_rows()`.", self.proj), [])

    def test_subagent_hallucination_wakes_it_up_then_flags_compositor(self):
        from infinite import chat
        msg = "Done. I refactored src/imaginary/thing.py and `frobnicate()` now works. " * 3
        inp = {"session_id": "v1", "cwd": str(self.proj), "agent_type": "worker", "agent_id": "abc12345",
               "last_assistant_message": msg}
        o = run_hook(hooks.subagent_stop, inp)
        self.assertEqual(o.get("decision"), "block")
        self.assertIn("Wake up", o["reason"])
        o2 = run_hook(hooks.subagent_stop, {**inp, "stop_hook_active": True})
        self.assertEqual(o2, {})
        lines = chat.read(self.scope, "main", "plan", all_=True)
        self.assertTrue(any("AFTER re-check" in l for l in lines))
        rep = list((core.data_dir() / "reports" / self.scope).glob("*worker*.md"))
        self.assertTrue(rep and "UNVERIFIED" in rep[0].read_text(encoding="utf-8"))

    def test_main_stop_hallucination(self):
        o = run_hook(hooks.stop, {"session_id": "v2", "cwd": str(self.proj),
                                  "last_assistant_message": "Updated lib/nowhere.py as requested."})
        self.assertEqual(o.get("decision"), "block")
        o = run_hook(hooks.stop, {"session_id": "v3", "cwd": str(self.proj),
                                  "last_assistant_message": "Updated src/real.py as requested."})
        self.assertEqual(o, {})

    def test_chat_claims_and_unread(self):
        from infinite import chat
        self.assertTrue(chat.claim(self.scope, "a", ["src/api/*"])[0].startswith("claimed"))
        self.assertTrue(chat.claim(self.scope, "b", ["src/api/x.py"])[0].startswith("REFUSED"))
        chat.post(self.scope, "plan", "main", "@b please take src/ui", kind="decision")
        self.assertTrue(chat.mentions(self.scope, "b"))
        self.assertFalse(chat.mentions(self.scope, "b"))  # cursor advanced
        chat.release(self.scope, "a")
        self.assertTrue(chat.claim(self.scope, "b", ["src/api/x.py"])[0].startswith("claimed"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
