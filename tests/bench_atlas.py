"""Phase timing for the atlas indexer. Usage: python tests/bench_atlas.py <repo>"""
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["INFINITE_HOME"] = tempfile.mkdtemp(prefix="bench-")
from infinite import atlas, core  # noqa: E402


def main():
    root = Path(sys.argv[1]).resolve()
    t = time.perf_counter()
    items = list(atlas.walk(root))
    print("walk      %6.3fs  %d files" % (time.perf_counter() - t, len(items)))
    for name, ex in (("serial", None), ("threads", ThreadPoolExecutor(8)), ("procs", ProcessPoolExecutor(os.cpu_count()))):
        t = time.perf_counter()
        if ex is None:
            res = [atlas._parse_file(i) for i in items]
        else:
            with ex:
                res = list(ex.map(atlas._parse_file, items, chunksize=16) if name == "procs" else ex.map(atlas._parse_file, items))
        print("parse %-7s %6.3fs" % (name, time.perf_counter() - t))
    t = time.perf_counter()
    st = atlas.index(root, core.scope_key(root), full=True)
    print("index(full) %6.3fs  %s" % (time.perf_counter() - t, st))
    t = time.perf_counter()
    st = atlas.index(root, core.scope_key(root))
    print("index(noop) %6.3fs" % (time.perf_counter() - t))
    one = next(i for i in items if i[2] == "python" or True)
    os.utime(one[0])
    t = time.perf_counter()
    st = atlas.index(root, core.scope_key(root))
    print("index(1 changed) %6.3fs  %s" % (time.perf_counter() - t, st))


if __name__ == "__main__":
    main()
