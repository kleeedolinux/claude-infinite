"""Code atlas: a real, queryable model of a codebase (not prose).

Index (per project, data/atlas/<scope>.db, incremental by mtime/size):
  files    path, lang, loc, module
  symbols  module/class/function/method: qualname, signature, docstring, lines, complexity
  imports  module -> module (resolved to internal modules when possible)
  calls    caller symbol -> callee name (resolved to an internal symbol when unambiguous)
Python is parsed exactly with `ast`; JS/TS/Go/Rust/others with conservative regexes
(marked approx). Everything printed is derived from the code and cites path:line.
"""
from __future__ import annotations

import ast
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from . import core

LANGS = {".py": "python", ".pyi": "python", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "ts",
         ".tsx": "ts", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".php": "php",
         ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".swift": "swift", ".lua": "lua",
         ".sh": "shell", ".ex": "elixir", ".hs": "haskell", ".scala": "scala", ".vue": "js", ".svelte": "js"}
IGNORE = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "target", ".next",
          ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "out", ".cache", ".turbo", "vendor", "third_party"}
MAX_FILE = 1_500_000

SCHEMA = """
create table if not exists files(path text primary key, mtime real, size integer, lang text, loc integer, module text);
create table if not exists symbols(id integer primary key, path text, module text, name text, qual text, kind text,
  line integer, end_line integer, sig text, doc text, complexity integer, parent integer, approx integer default 0);
create index if not exists sym_name on symbols(name);
create index if not exists sym_path on symbols(path);
create table if not exists imports(path text, module text, target text, name text, line integer, internal text);
create index if not exists imp_path on imports(path);
create table if not exists calls(caller integer, callee text, line integer, resolved integer, last text);
create index if not exists calls_caller on calls(caller);
create index if not exists calls_resolved on calls(resolved);
create virtual table if not exists sym_fts using fts5(name, qual, doc, sig, path, body,
  tokenize="porter unicode61 remove_diacritics 2");
create table if not exists meta(key text primary key, value text);
create table if not exists docs(path text primary key, mtime real, size integer);
create table if not exists chunks(id integer primary key, path text, heading text, line integer, end_line integer,
  text text);
create index if not exists chunks_path on chunks(path);
create virtual table if not exists chunk_fts using fts5(heading, text, path, tokenize="porter unicode61 remove_diacritics 2");
"""
SCHEMA_VERSION = "2"
WALK_DOT_DIRS = {".claude", ".github"}
DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".adoc"}
CHUNK_LINES = 60


def db_file(scope: str) -> Path:
    d = core.data_dir() / "atlas"
    d.mkdir(exist_ok=True)
    return d / ("%s.db" % scope[-120:])


@contextmanager
def adb(scope: str):
    c = sqlite3.connect(db_file(scope), timeout=30, isolation_level=None)
    c.execute("pragma journal_mode=wal")
    c.execute("pragma synchronous=normal")
    c.execute("pragma temp_store=memory")
    c.execute("pragma cache_size=-16000")
    c.executescript(SCHEMA)
    try:
        yield c
    finally:
        c.close()


def exists(scope: str) -> bool:
    return db_file(scope).exists()


# ------------------------------------------------------------------ parsing

def module_name(rel: str) -> str:
    p = Path(rel)
    parts = [x for x in p.with_suffix("").parts if x not in ("src", "lib")] or [p.stem]
    if parts and parts[-1] in ("__init__", "index", "mod"):
        parts = parts[:-1] or [p.parent.name or p.stem]
    return ".".join(parts) or p.stem


def _complexity(node) -> int:
    n = 1
    for x in ast.walk(node):
        if isinstance(x, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith,
                          ast.IfExp, ast.comprehension, ast.Assert)):
            n += 1
        elif isinstance(x, ast.BoolOp):
            n += len(x.values) - 1
        elif isinstance(x, ast.Match):
            n += len(x.cases)
    return n


def _callee(f) -> str | None:
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        base = f.value
        if isinstance(base, ast.Name):
            return "%s.%s" % (base.id, f.attr)
        return f.attr
    return None


def parse_python(src: str, rel: str):
    tree = ast.parse(src)
    mod = module_name(rel)
    syms, imps = [], []
    mdoc = ast.get_docstring(tree) or ""
    syms.append(dict(name=mod.split(".")[-1], qual=mod, kind="module", line=1, end=len(src.splitlines()) or 1,
                     sig="", doc=mdoc, complexity=0, parent=None, calls=[], body=""))

    def visit(node, parent_idx, prefix, cls):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_cls = isinstance(ch, ast.ClassDef)
                qual = "%s.%s" % (prefix, ch.name)
                if is_cls:
                    bases = ", ".join(ast.unparse(b) for b in ch.bases)
                    sig = "(%s)" % bases if bases else ""
                    kind = "class"
                else:
                    try:
                        sig = "(%s)" % ast.unparse(ch.args)
                        if ch.returns is not None:
                            sig += " -> " + ast.unparse(ch.returns)
                    except Exception:
                        sig = "(...)"
                    kind = "method" if cls else "function"
                    if isinstance(ch, ast.AsyncFunctionDef):
                        kind = "async " + kind
                calls = []
                if not is_cls:
                    for x in ast.walk(ch):
                        if isinstance(x, ast.Call):
                            n = _callee(x.func)
                            if n:
                                calls.append((n, x.lineno))
                body_ids = {x.id for x in ast.walk(ch) if isinstance(x, ast.Name)} | \
                    {x.attr for x in ast.walk(ch) if isinstance(x, ast.Attribute)}
                syms.append(dict(name=ch.name, qual=qual, kind=kind, line=ch.lineno,
                                 end=getattr(ch, "end_lineno", ch.lineno), sig=sig,
                                 doc=ast.get_docstring(ch) or "", complexity=0 if is_cls else _complexity(ch),
                                 parent=parent_idx, calls=calls, body=" ".join(sorted(body_ids))[:1500],
                                 cls=cls))
                visit(ch, len(syms) - 1, qual, ch.name if is_cls else cls)
            elif isinstance(ch, (ast.Import, ast.ImportFrom)):
                if isinstance(ch, ast.Import):
                    for a in ch.names:
                        imps.append((a.name, a.asname or a.name, ch.lineno))
                else:
                    base = ch.module or ""
                    if ch.level:
                        pkg = mod.split(".")
                        # a package's __init__ IS the package; a module's parent is one up
                        up = ch.level - (1 if rel.endswith("__init__.py") else 0)
                        pkg = pkg[: max(0, len(pkg) - up)] if up > 0 else pkg
                        base = ".".join(pkg + ([base] if base else []))
                    for a in ch.names:
                        imps.append((base, a.name, ch.lineno))
            elif isinstance(ch, (ast.If, ast.Try, ast.With)) and parent_idx == 0:
                visit(ch, parent_idx, prefix, cls)
    visit(tree, 0, mod, None)
    main_guard = bool(re.search(r"^if\s+__name__\s*==\s*['\"]__main__['\"]", src, re.M))
    return syms, imps, main_guard


RX = {
    "js": [(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*(\([^)]*\))", "function"),
           (r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", "function"),
           (r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)()", "class"),
           (r"^\s*(?:export\s+)?(?:interface|type)\s+([A-Za-z_$][\w$]*)()", "type"),
           (r"^\s+(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*([A-Za-z_$][\w$]*)\s*(\([^)]*\))\s*(?::\s*[^{]+)?\{\s*$", "method")],
    "go": [(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*(\([^)]*\)[^{]*)", "function"),
           (r"^type\s+([A-Za-z_]\w*)\s+(struct|interface)", "class")],
    "rust": [(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*(\([^)]*\)[^{;]*)", "function"),
             (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)()", "class")],
    "generic": [(r"^\s*(?:public|private|protected|static|final|def|function|func|fn|sub|proc)\s+[\w<>\[\], ]*?([A-Za-z_]\w*)\s*(\([^)]*\))", "function"),
                (r"^\s*(?:public\s+|final\s+|abstract\s+)*(?:class|struct|interface|module|enum)\s+([A-Za-z_]\w*)()", "class")],
}
RX["ts"] = RX["js"]
IMPORT_RX = {
    "js": r"""(?:import\s+(?:[^'"]+\s+from\s+)?|require\(\s*|import\(\s*)['"]([^'"]+)['"]""",
    "go": r"""^\s*(?:import\s+)?(?:\w+\s+)?"([^"]+)"\s*$""",
    "rust": r"^\s*use\s+([\w:]+)",
    "generic": r"""^\s*(?:import|#include|using|require)\s+[<"']?([\w./:\-]+)""",
}
IMPORT_RX["ts"] = IMPORT_RX["js"]
CALL_RX = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
KEYWORDS = set("if for while switch return function catch typeof sizeof new await yield match fn func def class".split())


def parse_regex(src: str, rel: str, lang: str):
    mod = module_name(rel)
    lines = src.splitlines()
    syms = [dict(name=mod.split(".")[-1], qual=mod, kind="module", line=1, end=len(lines) or 1, sig="", doc="",
                 complexity=0, parent=None, calls=[], body="")]
    pats = [(re.compile(p), k) for p, k in RX.get(lang, RX["generic"])]
    starts = []
    for i, line in enumerate(lines, 1):
        for rx, kind in pats:
            m = rx.match(line)
            if m and m.group(1) not in KEYWORDS:
                starts.append((i, m.group(1), (m.group(2) or "").strip()[:200], kind))
                break
    for j, (ln, name, sig, kind) in enumerate(starts):
        end = (starts[j + 1][0] - 1) if j + 1 < len(starts) else len(lines)
        body = "\n".join(lines[ln:end])
        doc = ""
        k = ln - 2
        com = []
        while k >= 0 and re.match(r"^\s*(//|\*|/\*\*|#|///)", lines[k]):
            com.insert(0, re.sub(r"^\s*(//+|/\*\*|\*/?|#|///)\s?", "", lines[k]).strip())
            k -= 1
        doc = " ".join(x for x in com if x)[:600]
        calls = [(m.group(1), ln + body[:m.start()].count("\n") + 1) for m in CALL_RX.finditer(body)
                 if m.group(1) not in KEYWORDS and m.group(1) != name][:200]
        syms.append(dict(name=name, qual="%s.%s" % (mod, name), kind=kind, line=ln, end=end, sig=sig, doc=doc,
                         complexity=1 + len(re.findall(r"\b(if|for|while|case|catch|&&|\|\|)\b", body)),
                         parent=0, calls=calls, body=" ".join(sorted(set(re.findall(r"[A-Za-z_]\w{2,}", body))))[:1500]))
    irx = re.compile(IMPORT_RX.get(lang, IMPORT_RX["generic"]), re.M)
    imps = [(m.group(1), m.group(1).split("/")[-1].split("::")[-1], src[:m.start()].count("\n") + 1)
            for m in irx.finditer(src)]
    main = bool(re.search(r"^func main\(|^fn main\(|^\s*public static void main", src, re.M))
    return syms, imps, main


# ------------------------------------------------------------------ indexing

def walk(root: Path, docs: bool = False):
    """Yield (path, rel, lang, mtime, size) using os.scandir; on Windows DirEntry.stat() is
    served from the directory listing, so no per-file syscall is needed."""
    root_s = str(root)
    cut = len(root_s.rstrip("/" + chr(92))) + 1
    stack = [root_s]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        subdirs = []
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in IGNORE and (not e.name.startswith(".") or e.name in WALK_DOT_DIRS):
                        subdirs.append(e.path)
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                lang = LANGS.get(ext) or ("doc" if docs and ext in DOC_EXT else None)
                if lang:
                    st = e.stat(follow_symlinks=False)
                    yield e.path, e.path[cut:].replace(chr(92), "/"), lang, st.st_mtime, st.st_size
            except OSError:
                continue
        stack.extend(reversed(subdirs))


def _parse_file(item):
    path, rel, lang, mtime, size = item
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        if lang == "python":
            try:
                syms, imps, main = parse_python(src, rel)
            except SyntaxError:
                syms, imps, main = parse_regex(src, rel, "generic")
        else:
            syms, imps, main = parse_regex(src, rel, lang)
        return item, src.count("\n") + 1, syms, imps, main
    except Exception:
        return None


def index(root: str | Path, scope: str | None = None, budget_s: float | None = None, full: bool = False) -> dict:
    root = Path(root).resolve()
    scope = scope or core.scope_key(root)
    t0 = time.time()
    stats = {"scanned": 0, "parsed": 0, "removed": 0, "errors": 0, "partial": False}
    with adb(scope) as c:
        if core.meta_get(c, "schema") != SCHEMA_VERSION:
            _reset(c)
            full = True
        known = {p: (m, s) for p, m, s in c.execute("select path, mtime, size from files")}
        seen = set()
        todo = []
        doc_items = []
        for path, rel, lang, mtime, size in walk(root, docs=True):  # ONE scandir pass for code + docs
            if lang == "doc":
                doc_items.append((path, rel, mtime, size))
                continue
            seen.add(rel)
            stats["scanned"] += 1
            if size <= MAX_FILE and (full or known.get(rel) != (mtime, size)):
                todo.append((path, rel, lang, mtime, size))
        # FORK: parse in parallel; JOIN: collect results in order
        results = _fork_join_parse(todo, t0, budget_s, stats)
        # REDUCE: fold all parse results into a few bulk batches (ids assigned up front)
        c.execute("begin")
        changed = [r[0][1] for r in results if r is not None]
        dropped_names = _drop_many(c, changed)
        next_id = (c.execute("select coalesce(max(id), 0) from symbols").fetchone()[0] or 0) + 1
        files_rows, sym_rows, fts_rows, call_rows, imp_rows = [], [], [], [], []
        for res in results:
            if res is None:
                stats["errors"] += 1
                continue
            (path, rel, lang, mtime, size), nlines, syms, imps, main = res
            mod = module_name(rel)
            files_rows.append((rel, mtime, size, lang, nlines, mod))
            ids = []
            for s in syms:
                sid = next_id
                next_id += 1
                parent = ids[s["parent"]] if s["parent"] is not None and s["parent"] < len(ids) else None
                ids.append(sid)
                kind, sig = s["kind"], s["sig"]
                if main and len(ids) == 1:
                    kind, sig = "module", "[entry point]"
                sym_rows.append((sid, rel, mod, s["name"], s["qual"], kind, s["line"], s["end"], sig,
                                 s["doc"][:2000], s["complexity"], parent, int(lang != "python")))
                fts_rows.append((sid, _split_ident(s["name"]), s["qual"], s["doc"][:2000], sig, rel, s.get("body", "")))
                for callee, line in s["calls"]:
                    if s.get("cls") and callee.startswith("self."):
                        callee = "%s.%s" % (s["cls"], callee[5:])
                    call_rows.append((sid, callee, line, None, callee.rsplit(".", 1)[-1]))
            imp_rows += [(rel, mod, target, name, line, None) for target, name, line in imps]
            stats["parsed"] += 1
        c.executemany("insert into files values(?,?,?,?,?,?)", files_rows)
        c.executemany("insert into symbols(id,path,module,name,qual,kind,line,end_line,sig,doc,complexity,parent,approx)"
                      " values(?,?,?,?,?,?,?,?,?,?,?,?,?)", sym_rows)
        c.executemany("insert into sym_fts(rowid,name,qual,doc,sig,path,body) values(?,?,?,?,?,?,?)", fts_rows)
        c.executemany("insert into calls(caller,callee,line,resolved,last) values(?,?,?,?,?)", call_rows)
        c.executemany("insert into imports values(?,?,?,?,?,?)", imp_rows)
        removed = sorted(set(known) - seen) if not stats["partial"] else []
        dropped_names |= _drop_many(c, removed)
        stats["removed"] = len(removed)
        if stats["parsed"] or stats["removed"]:
            # LAZY: full resolve only for a full index; otherwise just the calls this change can affect
            new_names = {r[3] for r in sym_rows}
            _resolve(c, None if full else (set(changed), new_names | dropped_names))
        if not stats["partial"]:
            stats["docs"] = _index_docs(c, doc_items, full)
        core.meta_set(c, "root", str(root))
        core.meta_set(c, "indexed_at", time.time())
        c.execute("commit")
    stats["seconds"] = round(time.time() - t0, 2)
    return stats


def _chunks(text: str):
    """Split a document at headings; long sections are cut every CHUNK_LINES lines."""
    lines = text.splitlines()
    out, head, start, buf = [], "", 1, []

    def flush(end):
        if any(l.strip() for l in buf):
            for k in range(0, len(buf), CHUNK_LINES):
                part = buf[k:k + CHUNK_LINES]
                out.append((head, start + k, start + k + len(part) - 1, "\n".join(part)))
    in_fence = False
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^#{1,4}\s+\S", l):
            flush(i - 1)
            head, start, buf = l.lstrip("#").strip(), i, [l]
        else:
            buf.append(l)
    flush(len(lines))
    return out


def _read_doc(item):
    path, rel, mtime, size = item
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return item, _chunks(f.read())
    except OSError:
        return None


def _index_docs(c, items, full=False) -> int:
    known = {p: (m, s) for p, m, s in c.execute("select path, mtime, size from docs")}
    seen = {it[1] for it in items}
    todo = [it for it in items if it[3] <= MAX_FILE and (full or known.get(it[1]) != (it[2], it[3]))]
    if len(todo) >= 8:  # fork/join the reads; chunking is cheap, so threads are enough
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as ex:
            res = [r for r in ex.map(_read_doc, todo) if r]
    else:
        res = [r for r in map(_read_doc, todo) if r]
    for (path, rel, mtime, size), _ in res:
        _drop_doc(c, rel)
    next_id = (c.execute("select coalesce(max(id), 0) from chunks").fetchone()[0] or 0) + 1
    rows, fts, docs = [], [], []
    for (path, rel, mtime, size), chunks in res:  # reduce into bulk inserts
        for head, a_, b_, body in chunks:
            rows.append((next_id, rel, head, a_, b_, body))
            fts.append((next_id, head, body, rel))
            next_id += 1
        docs.append((rel, mtime, size))
    c.executemany("insert into chunks(id,path,heading,line,end_line,text) values(?,?,?,?,?,?)", rows)
    c.executemany("insert into chunk_fts(rowid,heading,text,path) values(?,?,?,?)", fts)
    c.executemany("insert into docs values(?,?,?)", docs)
    for rel in set(known) - seen:
        _drop_doc(c, rel)
    return len(res)


def _drop_doc(c, rel):
    ids = [r[0] for r in c.execute("select id from chunks where path=?", (rel,))]
    if ids:
        c.execute("delete from chunk_fts where rowid in (%s)" % ",".join("?" * len(ids)), ids)
    c.execute("delete from chunks where path=?", (rel,))
    c.execute("delete from docs where path=?", (rel,))


def _split_ident(name: str) -> str:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ")
    return "%s %s" % (name, parts)


def _drop(c, rel):
    _drop_many(c, [rel])


def _drop_many(c, rels) -> set:
    """Delete everything derived from these files in bulk; returns the symbol names that disappeared
    (calls that pointed at them must be re-resolved). Calls into dropped ids are nulled lazily."""
    names = set()
    for k in range(0, len(rels), 400):
        part = rels[k:k + 400]
        q = ",".join("?" * len(part))
        ids = [r[0] for r in c.execute("select id from symbols where path in (%s)" % q, part)]
        names |= {r[0] for r in c.execute("select distinct name from symbols where path in (%s)" % q, part)}
        for j in range(0, len(ids), 800):
            sub = ids[j:j + 800]
            qi = ",".join("?" * len(sub))
            c.execute("delete from calls where caller in (%s)" % qi, sub)
            c.execute("update calls set resolved=null where resolved in (%s)" % qi, sub)
            c.execute("delete from sym_fts where rowid in (%s)" % qi, sub)
        c.execute("delete from symbols where path in (%s)" % q, part)
        c.execute("delete from imports where path in (%s)" % q, part)
        c.execute("delete from files where path in (%s)" % q, part)
    return names


def _parse_pool_kind(n: int, budget_s) -> str:
    # processes pay ~0.1-0.3s spawn on Windows: only worth it for big batches without a tight budget
    if n >= 250 and (budget_s is None or budget_s >= 10):
        return "procs"
    return "threads" if n >= 8 else "serial"


def _fork_join_parse(todo, t0, budget_s, stats):
    kind = _parse_pool_kind(len(todo), budget_s)
    if kind == "serial":
        return [_parse_file(i) for i in todo]
    workers = min(8, os.cpu_count() or 2)
    results = []
    try:
        if kind == "procs":
            from concurrent.futures import ProcessPoolExecutor
            ex = ProcessPoolExecutor(max_workers=workers)
            step, chunk = 256, max(4, min(32, len(todo) // (workers * 4) or 4))
        else:
            ex = ThreadPoolExecutor(max_workers=workers)
            step, chunk = 48, 1
        with ex:
            for k in range(0, len(todo), step):
                if budget_s and time.time() - t0 > budget_s:
                    stats["partial"] = True
                    break
                results.extend(ex.map(_parse_file, todo[k:k + step], chunksize=chunk))
    except Exception:  # e.g. process spawn not allowed: degrade to threads, never fail
        if kind != "procs":
            raise
        done = len(results)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results.extend(ex.map(_parse_file, todo[done:]))
    return results


def _reset(c):
    c.execute("begin")
    for t in ("files", "symbols", "imports", "calls", "sym_fts", "docs", "chunks", "chunk_fts"):
        c.execute("delete from %s" % t)
    c.execute("commit")
    try:
        c.execute("alter table calls add column last text")
    except sqlite3.OperationalError:
        pass
    c.execute("create index if not exists calls_last on calls(last)")
    core.meta_set(c, "schema", SCHEMA_VERSION)


def _resolve(c, delta=None):
    """Resolve imports to internal modules and calls to internal symbols.
    delta=None: everything. delta=(changed_paths, names): only calls made from changed files,
    plus unresolved calls whose name was (re)defined or removed by this change."""
    mods = {m: p for m, p in c.execute("select module, path from files")}
    suffix: dict[str, list] = {}  # every dotted suffix of every module -> modules (O(1) lookup)
    for m in mods:
        parts = m.split(".")
        for i in range(len(parts)):
            suffix.setdefault(".".join(parts[i:]), []).append(m)
    imp_upd = []
    for rowid, target, name, mod in c.execute("select rowid, target, name, module from imports").fetchall():
        hit = None
        for cand in (target + "." + name, target, target.replace("/", ".").lstrip(".")):
            if cand in mods:
                hit = cand
                break
        if not hit:  # relative JS import like ./util or ../core/x
            if target.startswith("."):
                base = mod.split(".")[:-1]
                for seg in target.split("/"):
                    if seg == "..":
                        base = base[:-1]
                    elif seg not in (".", ""):
                        base.append(seg.rsplit(".", 1)[0])
                cand = ".".join(base)
                hit = cand if cand in mods else None
            else:
                tail = suffix.get(target, [])
                hit = tail[0] if len(tail) == 1 else None
        imp_upd.append((hit, rowid))
    c.executemany("update imports set internal=? where rowid=?", imp_upd)
    by_name: dict[str, list] = {}
    by_qual = {}
    for sid, name, qual, mod, kind in c.execute("select id, name, qual, module, kind from symbols where kind!='module'"):
        by_name.setdefault(name, []).append((sid, mod, qual))
        by_qual[qual] = sid
    imported = {}
    for mod, name, internal in c.execute("select module, name, internal from imports where internal is not null"):
        imported.setdefault(mod, {})[name] = internal
    base_sql = "select calls.rowid, callee, s.module, s.qual from calls join symbols s on s.id = calls.caller"
    if delta is None:
        todo_calls = c.execute(base_sql).fetchall()
    else:
        paths, names = delta
        todo_calls = []
        paths, names = list(paths), list(names)
        for k in range(0, len(paths), 400):
            part = paths[k:k + 400]
            todo_calls += c.execute(base_sql + " where s.path in (%s)" % ",".join("?" * len(part)), part).fetchall()
        for k in range(0, len(names), 400):
            part = names[k:k + 400]
            todo_calls += c.execute(base_sql + " where calls.resolved is null and calls.last in (%s)"
                                    % ",".join("?" * len(part)), part).fetchall()
        todo_calls = list(dict.fromkeys(todo_calls))
    upd = []
    for rowid, callee, caller_mod, caller_qual in todo_calls:
        target = None
        last = callee.split(".")[-1]
        head = callee.split(".")[0] if "." in callee else None
        cls_q = caller_qual.rsplit(".", 2)[0] + "." + callee if "." in callee else None
        if cls_q and cls_q in by_qual:  # Class.method within same module (self.x rewritten)
            target = by_qual[cls_q]
        elif head and head in imported.get(caller_mod, {}):  # module alias: core.note
            target = by_qual.get("%s.%s" % (imported[caller_mod][head], last))
        elif not head and callee in imported.get(caller_mod, {}):  # from x import f
            target = by_qual.get("%s.%s" % (imported[caller_mod][callee], callee))
        if target is None and head and head not in ("self", "cls", "super"):
            # obj.method() on an unknown object (os.walk, p.exists, d.get): never guess by bare name
            upd.append((None, rowid))
            continue
        if target is None:
            cands = by_name.get(last, [])
            same = [s for s in cands if s[1] == caller_mod]
            if len(same) == 1:
                target = same[0][0]
            elif len(cands) == 1:
                target = cands[0][0]
        upd.append((target, rowid))
    c.executemany("update calls set resolved=? where rowid=?", upd)


# ------------------------------------------------------------------ queries

def _rows(c, sql, args=()):
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.row_factory = None


def find(scope, query, limit=15, kinds=None):
    q = core.fts_query(query, limit=10)
    if not q:
        return []
    with adb(scope) as c:
        sql = ("select s.*, bm25(sym_fts, 6.0, 3.0, 1.5, 1.0, 1.0, 0.4) as bm from sym_fts join symbols s on s.id = sym_fts.rowid"
               " where sym_fts match ?")
        args = [q]
        if kinds:
            sql += " and s.kind in (%s)" % ",".join("?" * len(kinds))
            args += kinds
        sql += " order by bm limit ?"
        args.append(limit)
        try:
            return _rows(c, sql, args)
        except sqlite3.OperationalError:
            return []


def search(scope, query, limit=12, graph=True) -> list[dict]:
    """One ranked index over code symbols + doc chunks, expanded through the call/import graph.

    Returns compact hits ({type, where, title, snippet, score}) so the agent reads only the
    exact line ranges it needs (index layer -> `mem code explain` / Read offset)."""
    q = core.fts_query(query, limit=10)
    if not q:
        return []
    hits = []
    with adb(scope) as c:
        try:
            syms = _rows(c, "select s.*, -bm25(sym_fts, 6.0, 3.0, 1.5, 1.0, 1.0, 0.4) as sc from sym_fts join symbols s"
                            " on s.id = sym_fts.rowid where sym_fts match ? order by sc desc limit 40", (q,))
        except sqlite3.OperationalError:
            syms = []
        try:
            chs = _rows(c, "select ch.*, -bm25(chunk_fts, 3.0, 1.0, 0.5) as sc,"
                           " snippet(chunk_fts, 1, '[', ']', ' … ', 14) as snip from chunk_fts join chunks ch"
                           " on ch.id = chunk_fts.rowid where chunk_fts match ? order by sc desc limit 25", (q,))
        except sqlite3.OperationalError:
            chs = []

        def norm(rows):
            if not rows:
                return
            hi = max(r["sc"] for r in rows) or 1
            for r in rows:
                r["n"] = r["sc"] / hi

        norm(syms)
        norm(chs)
        by_id = {s["id"]: s for s in syms}
        if graph and syms:
            # graph signal: a hit connected to other hits is more central to the query
            ids = list(by_id)
            ph = ",".join("?" * len(ids))
            for a, b in c.execute("select caller, resolved from calls where resolved is not null and caller in (%s)"
                                  " and resolved in (%s)" % (ph, ph), ids + ids):
                for k in (a, b):
                    by_id[k]["n"] += 0.15
            # expansion: neighbours of the top hits (what calls them / what they call)
            for s in sorted(syms, key=lambda r: -r["n"])[:3]:
                for nb in callers(c, s["id"])[:3] + [
                        r for r in (_rows(c, "select * from symbols where id=?", (x["id"],))[0]
                                    for x in callees(c, s["id"]) if x["id"])][:3]:
                    if nb["id"] not in by_id:
                        nb["n"] = s["n"] * 0.45
                        nb["via"] = s["qual"]
                        by_id[nb["id"]] = nb
        for s in by_id.values():
            kind_boost = 0.1 if s["kind"] in ("class", "function", "method", "async function") else 0
            doc = " ".join((s.get("doc") or "").split())[:110]
            hits.append({"type": "graph" if s.get("via") else "code", "where": loc(s), "score": s["n"] + kind_boost,
                         "title": "%s%s" % (s["qual"], (s["sig"] or "")[:70] if s["kind"] != "module" else " (module)"),
                         "snippet": ("via %s; " % s["via"] if s.get("via") else "") + doc})
        for ch in chs:
            hits.append({"type": "doc", "where": "%s:%d-%d" % (ch["path"], ch["line"], ch["end_line"]),
                         "score": ch["n"] * 0.95, "title": "# " + (ch["heading"] or Path(ch["path"]).name),
                         "snippet": " ".join(ch["snip"].split())[:160]})
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]


def format_hits(hits) -> str:
    return "\n".join("%-5s %-38s %s%s" % (h["type"], h["where"], h["title"],
                                         (" — " + h["snippet"]) if h["snippet"] else "") for h in hits)


def lookup(c, name):
    """Symbol by exact qualname, path:line, suffix of qualname, or bare name."""
    m = re.fullmatch(r"(.+?):(\d+)", name)
    if m:
        r = _rows(c, "select * from symbols where path like ? and line<=? and end_line>=? order by (end_line-line) limit 1",
                  ("%" + m.group(1).replace("\\", "/"), int(m.group(2)), int(m.group(2))))
        if r:
            return r
    for sql, arg in (("select * from symbols where qual=?", name),
                     ("select * from symbols where qual like ? order by length(qual)", "%." + name),
                     ("select * from symbols where name=? order by kind='module', length(qual)", name)):
        r = _rows(c, sql, (arg,))
        if r:
            return r
    return []


def loc(s) -> str:
    return "%s:%d" % (s["path"], s["line"]) + ("-%d" % s["end_line"] if s["end_line"] and s["end_line"] != s["line"] else "")


def callers(c, sid):
    """One row per calling symbol (first call site), with n = number of call sites."""
    return _rows(c, "select s.*, min(calls.line) as at, count(*) as n from calls join symbols s on s.id = calls.caller"
                    " where calls.resolved=? group by s.id order by s.path, at", (sid,))


def callees(c, sid):
    rows = _rows(c, "select calls.callee, calls.line as at, s.qual, s.path, s.line, s.end_line, s.id from calls"
                    " left join symbols s on s.id = calls.resolved where calls.caller=? order by calls.line", (sid,))
    seen, out = set(), []
    for r in rows:
        k = r["id"] or r["callee"]
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def source(root: Path, s, max_lines=60) -> str:
    p = root / s["path"]
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(source unavailable)"
    a, b = s["line"] - 1, min(s["end_line"] or s["line"], s["line"] - 1 + max_lines)
    body = lines[a:b]
    more = (s["end_line"] or 0) - s["line"] + 1 - len(body)
    width = len(str(b))
    out = ["%*d  %s" % (width, a + 1 + i, l) for i, l in enumerate(body)]
    if more > 0:
        out.append("… %d more lines (Read %s offset %d)" % (more, s["path"], b + 1))
    return "\n".join(out)


def root_of(scope) -> Path:
    with adb(scope) as c:
        r = core.meta_get(c, "root")
    return Path(r) if r else core.find_root()


def explain(scope, name, src_lines=60) -> str:
    root = root_of(scope)
    with adb(scope) as c:
        hits = lookup(c, name)
        if not hits:
            alt = [s["qual"] for s in find(scope, name, limit=8)]
            return "No symbol `%s`. Closest: %s" % (name, ", ".join(alt) or "(none — run `mem code index`)")
        s = hits[0]
        out = ["## %s  (%s)%s" % (s["qual"], s["kind"], "  [approx parse]" if s["approx"] else ""),
               "location: %s" % loc(s)]
        if len(hits) > 1:
            out.append("also named so: " + ", ".join("%s (%s)" % (h["qual"], loc(h)) for h in hits[1:6]))
        if s["sig"]:
            out.append("signature: %s%s" % (s["name"], s["sig"]) if s["kind"] != "module" else "signature: " + s["sig"])
        if s["doc"]:
            out.append("docstring: " + " ".join(s["doc"].split())[:700])
        if s["kind"] != "module":
            out.append("size: %d lines, complexity %d" % ((s["end_line"] or s["line"]) - s["line"] + 1, s["complexity"]))
        if s["kind"] == "module":
            members = _rows(c, "select * from symbols where path=? and kind!='module' and parent=? order by line",
                            (s["path"], s["id"]))
            out.append("defines (%d): %s" % (len(members), ", ".join("%s%s @%d" % (m["name"], "()" if "function" in m["kind"] else "", m["line"]) for m in members[:40])))
            imps = c.execute("select distinct coalesce(internal, target) , internal is not null from imports where path=?", (s["path"],)).fetchall()
            out.append("imports: " + ", ".join(("%s" if i else "%s (ext)") % t for t, i in imps[:30]))
            by = c.execute("select distinct module from imports where internal=?", (s["module"],)).fetchall()
            out.append("imported by: " + (", ".join(m for (m,) in by) or "(nothing internal)"))
        else:
            if s["kind"] == "class":
                members = _rows(c, "select * from symbols where parent=? order by line", (s["id"],))
                out.append("members: " + ", ".join("%s%s @%d" % (m["name"], m["sig"][:60], m["line"]) for m in members[:30]))
            cr = callers(c, s["id"])
            out.append("called by (%d): %s" % (len(cr), ", ".join("%s (%s:%d)" % (x["qual"], x["path"], x["at"]) for x in cr[:15]) or "nobody internal (entry point, callback, or dead code?)"))
            ce = callees(c, s["id"])
            internal = [x for x in ce if x["id"]]
            ext = [x["callee"] for x in ce if not x["id"]]
            out.append("calls (%d internal): %s" % (len(internal), ", ".join("%s (%s:%d)" % (x["qual"], x["path"], x["line"]) for x in internal[:20]) or "-"))
            if ext:
                out.append("calls (external/unresolved): " + ", ".join(ext[:25]))
            tests = [x for x in cr if "test" in x["path"].lower()]
            out.append("tested by: " + (", ".join("%s (%s:%d)" % (t["qual"], t["path"], t["at"]) for t in tests[:8]) or "no direct test call found"))
    try:
        from . import adr
        rel = adr.related(root, [s["path"], s["qual"], s["name"]])
        if rel:
            out.append("decisions: " + "; ".join("%s %s [%s]" % (a["id"], a["title"], a["status"]) for a in rel[:6]))
    except Exception:
        pass
    with core.db() as mc:
        mems = core.search(mc, "%s %s" % (s["name"], Path(s["path"]).stem), scopes=[scope], limit=4)
    mems = [m for m in mems if s["name"].lower() in m["text"].lower() or Path(s["path"]).name in m["text"]]
    if mems:
        out.append("memories: " + "; ".join(core.fmt(m, 140) for m in mems))
    out.append("\nsource:\n" + source(root, s, src_lines))
    return "\n".join(out)


def brief(scope, task: str, max_chars=2600) -> str:
    """Task-scoped context for a SUBAGENT: exact places to work, blast radius, tests,
    constraints. No glossary, no prose — every line is a fact with a location."""
    root = root_of(scope)
    hits = search(scope, task, limit=14)
    is_test = lambda h: "test" in h["where"].split(":")[0].lower()
    code = [h for h in hits if h["type"] in ("code", "graph") and not is_test(h) and not h["title"].endswith("(module)")]
    mods = [h for h in hits if h["title"].endswith("(module)") and not is_test(h)]
    tests_h = [h for h in hits if h["type"] in ("code", "graph") and is_test(h)]
    docs = [h for h in hits if h["type"] == "doc"][:3]
    out = ["Brief for: %s" % task, "Work here (read only these ranges):"]
    out += ["- %s  %s" % (h["where"], h["title"]) for h in code[:8]]
    if mods:
        out.append("Modules involved: " + ", ".join(h["where"].split(":")[0] for h in mods[:5]))
    if tests_h:
        out.append("Existing tests: " + ", ".join("%s %s" % (h["where"], h["title"].split("(")[0].split(".")[-1]) for h in tests_h[:5]))
    with adb(scope) as c:
        files = set()
        for h in code[:4]:
            name = h["title"].split("(")[0].strip()
            r = lookup(c, name)
            if not r:
                continue
            s = r[0]
            files.add(s["path"])
            cr = callers(c, s["id"])
            ce = [x for x in callees(c, s["id"]) if x["id"]]
            tests = [x for x in cr if "test" in x["path"].lower()]
            out.append("Blast radius of %s: %d callers%s; calls %s; tests: %s" % (
                s["name"], len(cr), (" (" + ", ".join("%s:%d" % (x["path"], x["at"]) for x in cr[:4] if x not in tests) + ")") if cr else "",
                ", ".join(x["qual"].split(".")[-1] for x in ce[:6]) or "-",
                ", ".join("%s:%d" % (t["path"], t["at"]) for t in tests[:3]) or "NONE (add one)"))
    if docs:
        out.append("Docs: " + "; ".join("%s %s" % (d["where"], d["title"]) for d in docs))
    try:
        from . import adr
        rel = adr.related(root, sorted(files))
        if rel:
            out.append("Constraints (ADRs): " + "; ".join("%s %s: %s" % (a["id"], a["title"], a["sections"].get("decision", "")[:140])
                                                      for a in rel[:4] if not a["status"].startswith("superseded")))
    except Exception:
        pass
    with core.db() as mc:
        rl = [r for r in core.rules(mc, scope, limit=8) if r["scope"] == scope][:5]
    if rl:
        out.append("Project rules: " + " | ".join(r["text"][:160] for r in rl))
    try:
        from . import chat
        w = chat.who(scope)
        if w:
            out.append("Claimed by others (do not edit): " + "; ".join(" ".join(x.split()[:2]) for x in w[:8]))
    except Exception:
        pass
    out.append("Look up more yourself: `mem code search <words>`, `mem code explain <symbol>`, `mem code flow <symbol>`.")
    text = "\n".join(out)
    return text[:max_chars]


def flow(scope, name, depth=3, max_nodes=60) -> tuple[str, str]:
    """Downward call tree (what really happens) as text + mermaid."""
    with adb(scope) as c:
        hits = lookup(c, name)
        if not hits:
            return "No symbol `%s`." % name, ""
        start = hits[0]
        lines, edges, seen = [], [], set()
        count = [0]

        def rec(s, d, pref):
            if count[0] >= max_nodes:
                return
            count[0] += 1
            mark = " (seen above)" if s["id"] in seen else ""
            lines.append("%s%s  %s%s" % (pref, s["qual"], loc(s), mark))
            if mark or d >= depth:
                return
            seen.add(s["id"])
            for x in callees(c, s["id"]):
                if x["id"]:
                    edges.append((s["qual"], x["qual"]))
                    sub = _rows(c, "select * from symbols where id=?", (x["id"],))[0]
                    rec(sub, d + 1, pref + "  ")
        rec(start, 0, "")
    ids = {}
    mm = ["```mermaid", "flowchart TD"]
    for a, b in dict.fromkeys(edges):
        for n in (a, b):
            ids.setdefault(n, "n%d" % len(ids))
        mm.append('  %s["%s"] --> %s["%s"]' % (ids[a], a.split(".")[-1], ids[b], b.split(".")[-1]))
    mm.append("```")
    return "\n".join(lines), "\n".join(mm) if edges else ""


def overview(scope, top=12) -> str:
    """Project map: modules, entry points, dependency edges, hotspots, untested."""
    with adb(scope) as c:
        files = _rows(c, "select * from files order by path")
        if not files:
            return "(no index — run `mem code index`)"
        nsym = c.execute("select count(*) from symbols where kind!='module'").fetchone()[0]
        langs = c.execute("select lang, count(*), sum(loc) from files group by lang order by 3 desc").fetchall()
        entries = _rows(c, "select * from symbols where sig='[entry point]' or (name in ('main','cli','app','run') and kind like '%function') order by path")
        deps = c.execute("select distinct module, internal from imports where internal is not null and internal!=module").fetchall()
        hot = c.execute("select s.qual, s.path, s.line, count(*) n from calls join symbols s on s.id=calls.resolved"
                        " group by s.id order by n desc limit ?", (top,)).fetchall()
        cx = _rows(c, "select * from symbols where kind like '%function' or kind like '%method' order by complexity desc limit ?", (top,))
        tested = {r[0] for r in c.execute("select distinct calls.resolved from calls join symbols s on s.id=calls.caller where s.path like '%test%'")}
        pub = _rows(c, "select * from symbols where (kind like '%function' or kind='class') and name not like '\\_%' escape '\\'"
                       " and path not like '%test%' order by path, line")
        untested = [s for s in pub if s["id"] not in tested]
        mods = _rows(c, "select f.path, f.module, f.loc, f.lang, (select count(*) from symbols s where s.path=f.path and s.kind!='module') n,"
                        " (select doc from symbols s where s.path=f.path and s.kind='module') doc from files f order by f.path")
    out = ["# Code map: %s" % root_of(scope).name,
           "%d files, %d symbols. Languages: %s" % (len(files), nsym, ", ".join("%s %d files/%d loc" % l for l in langs)),
           "", "## Modules"]
    for m in mods[:80]:
        d = (" — " + " ".join(m["doc"].split())[:110]) if m["doc"] else ""
        out.append("- `%s` (%s, %d loc, %d symbols)%s" % (m["path"], m["module"], m["loc"], m["n"], d))
    if len(mods) > 80:
        out.append("- … %d more (`mem code find`)" % (len(mods) - 80))
    out += ["", "## Entry points"] + (["- %s  %s" % (e["qual"], loc(e)) for e in entries[:15]] or ["- (none detected)"])
    out += ["", "## Internal dependencies (module -> module)"] + ["- %s -> %s" % d for d in deps[:60]]
    out += ["", "## Most-called (hubs)"] + ["- %s  %s:%d  (%d call sites)" % h for h in hot]
    out += ["", "## Most complex"] + ["- %s  %s  complexity %d" % (s["qual"], loc(s), s["complexity"]) for s in cx]
    out += ["", "## Public symbols with no direct test call (%d of %d)" % (len(untested), len(pub))]
    out += ["- %s  %s" % (s["qual"], loc(s)) for s in untested[:top]]
    return "\n".join(out)


def module_graph(scope) -> str:
    with adb(scope) as c:
        deps = c.execute("select distinct module, internal from imports where internal is not null and internal!=module").fetchall()
    ids = {}
    out = ["```mermaid", "graph LR"]
    for a, b in deps:
        for n in (a, b):
            ids.setdefault(n, "m%d" % len(ids))
        out.append('  %s["%s"] --> %s["%s"]' % (ids[a], a, ids[b], b))
    out.append("```")
    return "\n".join(out)


def export(scope) -> dict:
    """Everything the static site needs."""
    with adb(scope) as c:
        files = _rows(c, "select path, module, loc, lang from files order by path")
        syms = _rows(c, "select id, path, module, name, qual, kind, line, end_line, sig, doc, complexity, parent from symbols")
        calls = c.execute("select distinct caller, resolved from calls where resolved is not null").fetchall()
        deps = c.execute("select distinct module, internal from imports where internal is not null and internal!=module").fetchall()
        ext = c.execute("select module, target from imports where internal is null").fetchall()
    return {"files": files, "symbols": syms, "calls": calls, "deps": deps, "ext": ext}
