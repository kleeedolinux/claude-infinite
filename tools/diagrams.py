"""Generate the README diagrams (docs/img/*.svg). Diagrams are code: rerun after design changes.

    python tools/diagrams.py

Style: minimal, explanatory figures — thin strokes, monospace labels, one accent, and
automatic light/dark via prefers-color-scheme (works in GitHub's <img> rendering).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from infinite.tree import cover  # noqa: E402  (the real algorithm draws the tree figure)

OUT = ROOT / "docs" / "img"

MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
STYLE = """<style>
.h{font:600 15px %(sans)s;fill:#111}
.sub{font:13px %(sans)s;fill:#666}
.t{font:12.5px %(mono)s;fill:#111}
.tb{font:600 12.5px %(mono)s;fill:#111}
.s{font:12px %(sans)s;fill:#555}
.m{font:11px %(mono)s;fill:#888}
.ta{font:600 12.5px %(mono)s;fill:#3451d1}
.box{fill:#fbfbfb;stroke:#d4d4d4;stroke-width:1.1}
.acc{fill:#f1f4ff;stroke:#3451d1;stroke-width:1.2}
.warn{fill:#fff6ee;stroke:#d9480f;stroke-width:1.2}
.tw{font:600 12.5px %(mono)s;fill:#d9480f}
.ln{stroke:#a3a3a3;stroke-width:1.1;fill:none}
.la{stroke:#3451d1;stroke-width:1.3;fill:none}
.lw{stroke:#d9480f;stroke-width:1.3;fill:none}
.dash{stroke:#c4c4c4;stroke-width:1;fill:none;stroke-dasharray:3 4}
.dot{fill:#111}.dota{fill:#3451d1}
.cell{fill:#e9e9e9}.cella{fill:#3451d1}
.ah{fill:#a3a3a3}.aha{fill:#3451d1}.ahw{fill:#d9480f}
@media (prefers-color-scheme: dark){
.h,.t,.tb{fill:#ececec}.sub{fill:#a0a0a0}.s{fill:#b0b0b0}.m{fill:#8a8a8a}
.ta{fill:#8aa4ff}.tw{fill:#ff8a4c}
.box{fill:#141414;stroke:#3a3a3a}.acc{fill:#121a33;stroke:#8aa4ff}.warn{fill:#2a1709;stroke:#ff8a4c}
.ln{stroke:#6a6a6a}.la{stroke:#8aa4ff}.lw{stroke:#ff8a4c}.dash{stroke:#444}
.dot{fill:#ececec}.dota{fill:#8aa4ff}.cell{fill:#2c2c2c}.cella{fill:#8aa4ff}
.ah{fill:#6a6a6a}.aha{fill:#8aa4ff}.ahw{fill:#ff8a4c}}
</style>""" % {"mono": MONO, "sans": SANS}
DEFS = """<defs>
<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" class="ah"/></marker>
<marker id="aa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" class="aha"/></marker>
<marker id="aw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" class="ahw"/></marker>
</defs>"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h, self.parts = w, h, []
        self.title = title

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, cls="t", anchor="start"):
        self.add('<text x="%g" y="%g" class="%s" text-anchor="%s">%s</text>' % (x, y, cls, anchor, esc(s)))

    def box(self, x, y, w, h, cls="box", r=7):
        self.add('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" class="%s"/>' % (x, y, w, h, r, cls))

    def line(self, pts, cls="ln", arrow="a"):
        d = "M" + " L".join("%g,%g" % p for p in pts)
        m = (' marker-end="url(#%s)"' % arrow) if arrow else ""
        self.add('<path d="%s" class="%s"%s/>' % (d, cls, m))

    def card(self, x, y, w, h, head, lines, cls="box", head_cls="tb", line_cls="s", gap=17):
        self.box(x, y, w, h, cls)
        self.text(x + 12, y + 22, head, head_cls)
        for i, ln in enumerate(lines):
            self.text(x + 12, y + 42 + i * gap, ln, line_cls)

    def save(self, name):
        body = "\n".join(self.parts)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
               'aria-label="%s">\n<title>%s</title>\n%s\n%s\n%s\n</svg>\n' % (
                   self.w, self.h, self.w, self.h, esc(self.title), esc(self.title), STYLE, DEFS, body))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text(svg, encoding="utf-8")
        return OUT / name


# ------------------------------------------------------------------ 1. a session, start to finish

def session():
    s = Svg(900, 440, "How claude-infinite runs inside one Claude Code session")
    s.text(28, 36, "One session, start to finish", "h")
    s.text(28, 58, "Claude Code fires hooks; each one is a ~0.1s call to mem. Nothing ever blocks the session.", "sub")
    xs = [110, 285, 460, 635, 800]
    events = ["SessionStart", "UserPromptSubmit", "PreCompact", "Stop", "SessionEnd"]
    s.line([(40, 104), (870, 104)], "ln", "a")
    for x, e in zip(xs, events):
        s.add('<circle cx="%g" cy="104" r="5" class="%s"/>' % (x, "dota" if e != "SessionEnd" else "dot"))
        s.text(x, 90, e, "ta" if e != "SessionEnd" else "tb", "middle")
    s.text(460, 124, "+ PostCompact", "m", "middle")
    s.text(635, 124, "+ SubagentStop", "m", "middle")
    cards = [
        ("inject the wake", ["rules learned so far", "conflicts · recurring errors", "tasks · team chat", "memory tree (fits budget)", "spawn background indexer"]),
        ("per prompt", ["store your words verbatim", "relevant memories", "relevant code path:line", "idea / explain / fix modes", "#fresh = no memory"]),
        ("around compaction", ["snapshot your requests", "save the summary", "after it: re-inject the", "original goal, verbatim", ""]),
        ("when an agent stops", ["harvest errors and", "corrections -> inbox", "check cited paths/symbols", "wrong? wake it up", "refresh code index"]),
        ("last call", ["final harvest", "(1.5s budget)", "", "", ""]),
    ]
    for x, (head, lines) in zip(xs, cards):
        w = 160 if x != 800 else 120
        s.card(x - w / 2, 140, w, 128, head, [l for l in lines if l] or [""])
        s.line([(x, 268), (x, 300)], "dash", None)
    s.line([(110, 300), (800, 300)], "dash", None)
    stores = [
        (28, "log.jsonl", ["append-only truth", "every event, forever"], "acc"),
        (200, "index.db", ["FTS5 search cache", "rebuilt from the log"], "box"),
        (372, "atlas/*.db", ["code index per project", "symbols · calls · docs"], "box"),
        (544, "chat.db", ["team board, claims", "subagent reports"], "box"),
        (716, "sessions/", ["verbatim prompts", "per session"], "box"),
    ]
    for x, head, lines, cls in stores:
        s.card(x, 330, 156, 78, head, lines, cls, "ta" if cls == "acc" else "tb")
        s.line([(x + 78, 300), (x + 78, 328)], "ln", "a")
    s.line([(184, 369), (198, 369)], "la", "aa")
    s.text(450, 432, "~/.claude/infinite/data  —  the installer never touches it", "m", "middle")
    return s.save("session.svg")


# ------------------------------------------------------------------ 2. the memory tree

def tree():
    T, budget = 32, 12
    blocks = cover(T, budget)
    s = Svg(900, 470, "The memory tree: recent memories verbatim, older ones summarized, nothing lost")
    s.text(28, 36, "Infinite memory, fixed reading budget", "h")
    s.text(28, 58, "%d memories, a budget of %d lines. Detail fades with age; every summary can be zoomed back open." % (T, budget), "sub")
    x0, cw, gap, y = 70, 21, 4, 250
    def cx(i):
        return x0 + i * (cw + gap)
    # leaves
    for i in range(T):
        recent = blocks[[k for k, b in enumerate(blocks) if b[0] <= i < b[1]][0]][1] - \
            blocks[[k for k, b in enumerate(blocks) if b[0] <= i < b[1]][0]][0] == 1
        s.add('<rect x="%g" y="%g" width="%g" height="%g" rx="3" class="%s"/>' % (cx(i), y, cw, cw, "cella" if recent else "cell"))
        if i % 4 == 0 or i == T - 1:
            s.text(cx(i) + cw / 2, y + 40, "#%d" % i, "m", "middle")
    s.text(x0 - 12, y + 15, "notes", "m", "end")
    s.line([(cx(0), y + 58), (cx(T - 1) + cw, y + 58)], "ln", "a")
    s.text(cx(0), y + 74, "older", "m")
    s.text(cx(T - 1) + cw, y + 74, "now", "m", "end")
    # the cover (what wake prints), drawn as a row of bars above the leaves
    by = 168
    for lo, hi in blocks:
        x, w = cx(lo), cx(hi - 1) + cw - cx(lo)
        leaf = hi - lo == 1
        s.box(x, by, w, 36, "acc" if leaf else "box", 5)
        label = ("#%d" % lo) if leaf else ("@%d-%d" % (lo, hi - 1))
        cls = ("ta" if leaf else "t") if w >= 60 else "m"
        if w >= 40:
            s.text(x + w / 2, by + 23, label, cls, "middle")
        else:  # too narrow: label above the bar
            s.text(x + w / 2, by - 6, label, "m", "middle")
        s.line([(x + w / 2, by + 36), (x + w / 2, y - 4)], "dash", None)
    s.text(x0 - 12, by + 23, "wake", "m", "end")
    # zoom: show the first block opening into its halves
    lo, hi = blocks[0]
    m = (lo + hi) // 2
    zx, zw = cx(lo), cx(hi - 1) + cw - cx(lo)
    s.box(zx, 92, zw / 2 - 3, 30, "box", 5)
    s.box(zx + zw / 2 + 3, 92, zw / 2 - 3, 30, "box", 5)
    s.text(zx + zw / 4, 112, "@%d-%d" % (lo, m - 1), "t", "middle")
    s.text(zx + zw * 3 / 4, 112, "@%d-%d" % (m, hi - 1), "t", "middle")
    s.line([(zx + zw / 2, by - 2), (zx + zw / 2, 126)], "la", "aa")
    s.text(zx + zw + 14, 112, "mem zoom %d-%d  opens a summary into its two halves, down to the raw notes" % (lo, hi - 1), "s")
    # what Claude reads
    s.box(28, 352, 844, 100, "box")
    s.text(44, 374, "what Claude reads at session start (one line per bar)", "m")
    rows = ["@0-7    set up repo; chose uv workspaces because pip broke on editable installs; user wants stdlib only",
            "@8-11   parser: switched regex -> lark after nested quotes failed (#9 verdict: works)",
            "...",
            "#31     user: \"don't push to main, open a PR\" (lesson, reinforced x2 -> RULE)"]
    for i, r in enumerate(rows):
        s.text(44, 396 + i * 17, r, "t" if not r.startswith("#") else "ta")
    return s.save("memory-tree.svg")


# ------------------------------------------------------------------ 3. self-correction

def correct():
    s = Svg(900, 430, "How memory fixes itself: write-time checks and the learning loop")
    s.text(28, 36, "Memory that fixes itself", "h")
    s.text(28, 58, "Left: every write is checked against what is already known. Right: mistakes become rules.", "sub")
    # left: write decision
    s.card(40, 90, 200, 56, "mem note \"...\"", ["a new fact, decision, lesson"], "acc", "ta")
    s.line([(140, 146), (140, 176)], "ln", "a")
    s.card(40, 178, 200, 56, "search similar", ["FTS5 + word overlap"], "box")
    s.line([(140, 234), (140, 268)], "ln", "a")
    s.add('<rect x="40" y="270" width="200" height="140" rx="7" class="box"/>')
    s.text(54, 292, "≥85% same  -> reinforce", "t")
    s.text(54, 312, "            (count +1)", "m")
    s.text(54, 338, "opposite   -> CONFLICT", "tw")
    s.text(54, 358, "            supersede old", "m")
    s.text(54, 384, "new        -> add", "t")
    s.text(54, 402, "            hidden, never deleted", "m")
    # right: learning loop
    nodes = [(330, 92, "transcripts", ["tool errors", "your corrections"], "box", "tb"),
             (560, 92, "inbox", ["deduped by signature", "x3 = RECURRING ERROR"], "warn", "tw"),
             (560, 222, "reflect", ["concrete cause ->", "one destination"], "box", "tb"),
             (330, 222, "lesson", ["\"when X, do Y,", "because Z\""], "box", "tb"),
             (330, 340, "RULE", ["reinforced twice", "shown every session"], "acc", "ta"),
             (560, 340, "next session", ["follows the rule", "fewer corrections"], "box", "tb")]
    for x, y, head, lines, cls, hc in nodes:
        s.card(x, y, 190, 72, head, lines, cls, hc)
    s.line([(520, 128), (558, 128)], "ln", "a")
    s.line([(655, 164), (655, 220)], "lw", "aw")
    s.line([(558, 258), (522, 258)], "ln", "a")
    s.line([(425, 294), (425, 338)], "la", "aa")
    s.line([(520, 376), (558, 376)], "la", "aa")
    s.line([(750, 376), (800, 376), (800, 60 + 68), (752, 128)], "dash", None)
    s.text(812, 250, "loop", "m")
    s.text(330, 82, "harvested by Stop / PreCompact / SessionEnd hooks", "m")
    return s.save("self-correct.svg")


# ------------------------------------------------------------------ 4. code atlas

def atlas():
    s = Svg(900, 360, "The code atlas: from files to grounded answers")
    s.text(28, 36, "A real map of the code, not summaries", "h")
    s.text(28, 58, "Built in the background; every answer points at path:line. fork / join / reduce / lazy.", "sub")
    s.card(28, 96, 140, 92, "repo", ["*.py ast (exact)", "*.ts *.go *.rs", "*.md docs"], "box")
    s.line([(168, 142), (196, 142)], "ln", "a")
    s.card(198, 96, 128, 92, "one scandir", ["code + docs", "no extra stat()", "skip unchanged"], "box")
    s.line([(326, 142), (354, 142)], "ln", "a")
    # fork
    for i in range(4):
        s.box(366, 88 + i * 27, 98, 22, "acc", 4)
        s.text(415, 103 + i * 27, "parse %d" % (i + 1), "ta", "middle")
        s.line([(356, 142), (364, 99 + i * 27)], "ln", None)
        s.line([(464, 99 + i * 27), (474, 142)], "ln", None)
    s.text(415, 82, "fork", "m", "middle")
    s.line([(476, 142), (500, 142)], "ln", "a")
    s.text(488, 132, "join", "m", "middle")
    s.card(502, 96, 136, 92, "reduce", ["bulk writes", "lazy: re-resolve", "only what changed"], "box")
    s.line([(638, 142), (666, 142)], "la", "aa")
    s.card(668, 82, 204, 120, "atlas.db", ["symbols · signatures · docs", "calls (resolved graph)", "imports · tests", "doc chunks", "FTS5 + porter stemming"], "acc", "ta")
    qs = [("search", "words -> path:line"), ("explain", "callers, tests, ADRs"), ("flow", "what really happens"),
          ("brief", "context for a worker"), ("site", "offline docs + graphs")]
    for i, (q, d) in enumerate(qs):
        x = 28 + i * 171
        s.card(x, 252, 160, 62, "mem code " + q, [d], "box")
        s.line([(770, 202), (770, 226), (x + 80, 226), (x + 80, 250)], "ln", "a")
    s.text(450, 346, "measured: 518 files -> full 1.2s · no-op 0.03s · one changed file 0.08s · search ~10ms", "m", "middle")
    return s.save("atlas.svg")


# ------------------------------------------------------------------ 5. the team

def team():
    s = Svg(900, 430, "Lead, CTO and workers: how agents coordinate")
    s.text(28, 36, "You lead. Claude is the CTO. Subagents are workers.", "h")
    s.text(28, 58, "Workers talk on a shared board instead of flooding the CTO's context; every report is checked against the repo.", "sub")
    s.card(350, 80, 200, 62, "you  ·  lead", ["goals, taste, scope, irreversible"], "acc", "ta")
    s.line([(450, 142), (450, 170)], "la", "aa")
    s.card(320, 172, 260, 62, "main agent  ·  CTO", ["plans, ADRs, delegates, integrates"], "box")
    for i, (name, d) in enumerate([("worker api", "claims src/api/*"), ("worker ui", "claims src/ui/*"), ("reviewer", "read-only check")]):
        x = 110 + i * 250
        s.card(x, 330, 190, 62, name, [d], "box")
        s.line([(450, 234), (450, 300), (x + 95, 300), (x + 95, 328)], "ln", "a")
    s.box(28, 172, 230, 104, "box")
    s.text(42, 194, "mem chat", "tb")
    for i, (ch, d) in enumerate([("#plan", "decisions, @main ?"), ("#claims", "who owns which files"), ("#reports", "auto-posted on stop")]):
        s.text(42, 214 + i * 18, ch, "ta")
        s.text(112, 214 + i * 18, d, "s")
    s.text(42, 268, "overlapping claims are refused", "m")
    s.line([(258, 224), (318, 204)], "dash", None)
    s.box(642, 172, 230, 104, "warn")
    s.text(656, 194, "hallucination check", "tw")
    s.text(656, 214, "report cites a file, line or", "s")
    s.text(656, 232, "symbol that doesn't exist?", "s")
    s.text(656, 250, "-> worker is sent back once", "s")
    s.text(656, 268, "-> then @main gets a blocker", "s")
    s.line([(757, 328), (757, 278)], "lw", "aw")
    s.text(450, 420, "workers: edit only claimed files · no memory writes · no architecture calls · escalate with @main", "m", "middle")
    return s.save("team.svg")


if __name__ == "__main__":
    for f in (session, tree, correct, atlas, team):
        print("wrote", f())
