"""Static, offline, single-file docs site generated from the atlas + ADRs + glossary + memory.

`mem code site [outdir]` -> <outdir>/index.html (no CDN, no build step). Views:
overview (stats + force-directed module graph), modules, symbols (callers/callees graph),
ADRs, glossary, decisions timeline, and instant client-side search over everything.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from . import adr, atlas, core, learn


def build(scope: str, root: Path, outdir: Path | None = None) -> Path:
    root = Path(root)
    outdir = Path(outdir or root / "docs" / "site")
    outdir.mkdir(parents=True, exist_ok=True)
    data = atlas.export(scope) if atlas.exists(scope) else {"files": [], "symbols": [], "calls": [], "deps": [], "ext": []}
    for s in data["symbols"]:
        s["doc"] = " ".join((s.get("doc") or "").split())[:500]
    with atlas.adb(scope) as c:
        docs = [{"path": p, "heading": h, "line": l, "text": " ".join((t or "").split())[:240]}
                for p, h, l, t in c.execute("select path, heading, line, text from chunks order by path, line")] \
            if atlas.exists(scope) else []
    with core.db() as c:
        c.row_factory = sqlite3.Row
        mems = [{"id": r["id"], "kind": r["kind"], "text": r["text"], "date": time.strftime("%Y-%m-%d", time.localtime(r["ts"]))}
                for r in c.execute("select * from notes where scope=? and invalid_at is null and kind in"
                                   " ('decision','fact','lesson','experiment','idea','pref') order by ts desc limit 400", (scope,))]
    payload = {"project": root.name, "root": str(root), "generated": time.strftime("%Y-%m-%d %H:%M"),
               **data, "docs": docs[:3000],
               "adrs": [{k: a[k] for k in ("id", "title", "status", "date", "affects", "supersedes", "sections", "file")}
                        for a in adr.all_(root)],
               "glossary": learn.load(root), "memories": mems}
    js = json.dumps(payload, ensure_ascii=False).replace("</", "<" + chr(92) + "/")
    (outdir / "index.html").write_text(HTML.replace("__DATA__", js).replace("__TITLE__", root.name), encoding="utf-8")
    return outdir / "index.html"


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — atlas</title>
<style>
:root{--bg:#0f1115;--panel:#161a22;--line:#262c38;--fg:#e6e9ef;--mut:#8b93a7;--acc:#7aa2f7;--ok:#9ece6a;--warn:#e0af68;--bad:#f7768e}
@media (prefers-color-scheme: light){:root{--bg:#f7f7f9;--panel:#fff;--line:#e3e5ea;--fg:#1d2230;--mut:#5d6578;--acc:#2f5bd3;--ok:#2e7d32;--warn:#a66b00;--bad:#c62828}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);display:grid;grid-template-columns:280px 1fr;height:100vh}
aside{border-right:1px solid var(--line);overflow:auto;padding:12px;background:var(--panel)}main{overflow:auto;padding:20px 28px}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
input{width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
nav a{display:block;padding:3px 6px;border-radius:6px}nav a.on{background:var(--line)}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:22px 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.mut{color:var(--mut)}.pill{display:inline-block;padding:0 8px;border-radius:99px;border:1px solid var(--line);font-size:12px;margin-right:4px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:8px 0}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
code,pre{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}pre{white-space:pre-wrap;background:var(--bg);padding:10px;border-radius:8px;border:1px solid var(--line)}
svg{width:100%;height:520px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.k{font-weight:600}
.accepted{color:var(--ok)}.proposed{color:var(--warn)}.superseded,.deprecated{color:var(--bad)}
</style></head><body>
<aside><input id="q" placeholder="Search code, docs, ADRs, terms…  ( / )" autocomplete="off">
<nav id="nav"></nav></aside><main id="main"></main>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s), esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const S={};D.symbols.forEach(s=>S[s.id]=s);
const callersOf={},calleesOf={};D.calls.forEach(([a,b])=>{(callersOf[b]=callersOf[b]||[]).push(a);(calleesOf[a]=calleesOf[a]||[]).push(b)});
const mods={};D.files.forEach(f=>mods[f.module]=f);
const symsIn=m=>D.symbols.filter(s=>s.module===m&&s.kind!=="module").sort((a,b)=>a.line-b.line);
const modSym=m=>D.symbols.find(s=>s.module===m&&s.kind==="module");
const L=s=>`<a href="#/s/${s.id}">${esc(s.qual)}</a> <span class="mut">${esc(s.path)}:${s.line}</span>`;
function navHtml(cur){
 const items=[["#/","Overview"],["#/modules","Modules ("+D.files.length+")"],["#/adr","Decisions / ADRs ("+D.adrs.length+")"],
 ["#/glossary","Glossary ("+Object.keys(D.glossary).length+")"],["#/memory","Memory ("+D.memories.length+")"],["#/docs","Docs ("+new Set(D.docs.map(d=>d.path)).size+")"]];
 return items.map(([h,t])=>`<a href="${h}" class="${cur===h?"on":""}">${t}</a>`).join("")+
 `<h2>Modules</h2>`+D.files.map(f=>`<a href="#/m/${encodeURIComponent(f.module)}">${esc(f.module)}</a>`).join("");
}
function graph(nodes,edges,onclick){
 const W=1000,H=520,N=nodes.map((n,i)=>({...n,x:W/2+Math.cos(i)*200*Math.random(),y:H/2+Math.sin(i)*200*Math.random(),vx:0,vy:0}));
 const idx={};N.forEach((n,i)=>idx[n.id]=i);const E=edges.filter(([a,b])=>a in idx&&b in idx).map(([a,b])=>[idx[a],idx[b]]);
 for(let it=0;it<300;it++){for(let i=0;i<N.length;i++)for(let j=i+1;j<N.length;j++){let dx=N[i].x-N[j].x,dy=N[i].y-N[j].y,d=Math.max(1,dx*dx+dy*dy),f=2200/d;N[i].vx+=dx*f/40;N[i].vy+=dy*f/40;N[j].vx-=dx*f/40;N[j].vy-=dy*f/40}
  E.forEach(([a,b])=>{let dx=N[b].x-N[a].x,dy=N[b].y-N[a].y;N[a].vx+=dx*.004;N[a].vy+=dy*.004;N[b].vx-=dx*.004;N[b].vy-=dy*.004});
  N.forEach(n=>{n.vx+=(W/2-n.x)*.002;n.vy+=(H/2-n.y)*.002;n.x+=n.vx*.5;n.y+=n.vy*.5;n.vx*=.6;n.vy*=.6;n.x=Math.max(30,Math.min(W-30,n.x));n.y=Math.max(20,Math.min(H-20,n.y))})}
 const deg={};E.forEach(([a,b])=>{deg[a]=(deg[a]||0)+1;deg[b]=(deg[b]||0)+1});
 let s=`<svg viewBox="0 0 ${W} ${H}"><defs><marker id="ar" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="var(--mut)"/></marker></defs>`;
 E.forEach(([a,b])=>s+=`<line x1="${N[a].x}" y1="${N[a].y}" x2="${N[b].x}" y2="${N[b].y}" stroke="var(--line)" stroke-width="1.2" marker-end="url(#ar)"/>`);
 N.forEach((n,i)=>{const r=4+Math.min(10,(deg[i]||0));s+=`<g style="cursor:pointer" onclick="${onclick(n)}"><circle cx="${n.x}" cy="${n.y}" r="${r}" fill="var(--acc)" opacity=".85"/><text x="${n.x+r+3}" y="${n.y+4}" fill="var(--fg)" font-size="11">${esc(n.label)}</text></g>`});
 return s+"</svg>";
}
const V={
 "":()=>{const nsym=D.symbols.filter(s=>s.kind!=="module").length,loc=D.files.reduce((a,f)=>a+f.loc,0);
  const hubs=Object.entries(callersOf).map(([k,v])=>[S[k],new Set(v).size]).filter(x=>x[0]).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const entry=D.symbols.filter(s=>s.sig==="[entry point]");
  return `<h1>${esc(D.project)}</h1><div class="mut">${D.files.length} files · ${nsym} symbols · ${loc} lines · generated ${D.generated} from the code (not hand-written)</div>
  <h2>Module dependency graph</h2>${graph(D.files.map(f=>({id:f.module,label:f.module})),D.deps,n=>`location.hash='#/m/${encodeURIComponent(n.id)}'`)}
  <div class="cols"><div><h2>Entry points</h2>${entry.map(s=>`<div>${L(s)}</div>`).join("")||'<span class="mut">none detected</span>'}
  <h2>Hubs (most called)</h2>${hubs.map(([s,n])=>`<div>${L(s)} <span class="pill">${n} callers</span></div>`).join("")}</div>
  <div><h2>Recent decisions</h2>${D.adrs.slice(-6).reverse().map(a=>`<div><a href="#/adr/${a.id}">${a.id}</a> ${esc(a.title)} <span class="${a.status.split(" ")[0]}">${esc(a.status)}</span></div>`).join("")}
  ${D.memories.filter(m=>m.kind==="decision").slice(0,8).map(m=>`<div class="mut">#${m.id} ${m.date} ${esc(m.text)}</div>`).join("")}</div></div>`},
 modules:()=>`<h1>Modules</h1><table><tr><th>Module</th><th>File</th><th>Lines</th><th>Symbols</th><th>Summary (docstring)</th></tr>${D.files.map(f=>{const m=modSym(f.module);return `<tr><td><a href="#/m/${encodeURIComponent(f.module)}">${esc(f.module)}</a></td><td class="mut">${esc(f.path)}</td><td>${f.loc}</td><td>${symsIn(f.module).length}</td><td>${esc((m&&m.doc||"").slice(0,140))}</td></tr>`}).join("")}</table>`,
 m:(name)=>{name=decodeURIComponent(name);const f=mods[name],ms=modSym(name);if(!f)return"not found";
  const out=D.deps.filter(d=>d[0]===name).map(d=>d[1]),inn=D.deps.filter(d=>d[1]===name).map(d=>d[0]),ext=[...new Set(D.ext.filter(e=>e[0]===name).map(e=>e[1]))];
  const nodes=[name,...out,...inn].map(x=>({id:x,label:x}));
  return `<h1>${esc(name)}</h1><div class="mut">${esc(f.path)} · ${f.loc} lines · ${f.lang}</div>${ms&&ms.doc?`<div class="card">${esc(ms.doc)}</div>`:""}
  <div class="cols"><div><h2>Imports</h2>${out.map(x=>`<div><a href="#/m/${encodeURIComponent(x)}">${esc(x)}</a></div>`).join("")}<div class="mut">${esc(ext.join(", "))}</div></div>
  <div><h2>Imported by</h2>${inn.map(x=>`<div><a href="#/m/${encodeURIComponent(x)}">${esc(x)}</a></div>`).join("")||'<span class="mut">nothing internal</span>'}</div></div>
  <h2>Symbols</h2><table>${symsIn(name).map(s=>`<tr><td><a href="#/s/${s.id}">${esc(s.qual.slice(name.length+1))}</a><div class="mut"><code>${esc(s.sig)}</code></div></td><td>${esc(s.kind)}</td><td class="mut">:${s.line}</td><td>${esc(s.doc.slice(0,160))}</td></tr>`).join("")}</table>
  <h2>Neighbourhood</h2>${graph(nodes,D.deps.filter(d=>d[0]===name||d[1]===name),n=>`location.hash='#/m/${encodeURIComponent(n.id)}'`)}`},
 s:(id)=>{const s=S[id];if(!s)return"not found";const cr=[...new Set(callersOf[id]||[])].map(i=>S[i]).filter(Boolean),ce=[...new Set(calleesOf[id]||[])].map(i=>S[i]).filter(Boolean);
  const ad=D.adrs.filter(a=>a.affects.some(x=>x===s.path||x===s.qual||x===s.name));
  const g=graph([s,...cr,...ce].map(x=>({id:x.id,label:x.name})),[...cr.map(c=>[c.id,s.id]),...ce.map(c=>[s.id,c.id])],n=>`location.hash='#/s/${n.id}'`);
  return `<h1>${esc(s.qual)}</h1><div class="mut">${esc(s.kind)} · <code>${esc(s.path)}:${s.line}-${s.end_line}</code> · complexity ${s.complexity}</div>
  <pre>${esc(s.name+(s.sig||""))}</pre>${s.doc?`<div class="card">${esc(s.doc)}</div>`:'<div class="mut">no docstring</div>'}
  <div class="cols"><div><h2>Called by (${cr.length})</h2>${cr.map(x=>`<div>${L(x)}</div>`).join("")||'<span class="mut">nobody internal</span>'}</div>
  <div><h2>Calls (${ce.length})</h2>${ce.map(x=>`<div>${L(x)}</div>`).join("")||'<span class="mut">no internal calls</span>'}</div></div>
  ${ad.length?`<h2>Decisions</h2>${ad.map(a=>`<div><a href="#/adr/${a.id}">${a.id}</a> ${esc(a.title)}</div>`).join("")}`:""}<h2>Call graph</h2>${g}`},
 adr:(id)=>{if(!id)return `<h1>Architecture Decision Records</h1><table><tr><th>ADR</th><th>Title</th><th>Status</th><th>Date</th><th>Affects</th></tr>${D.adrs.map(a=>`<tr><td><a href="#/adr/${a.id}">${a.id}</a></td><td>${esc(a.title)}</td><td class="${a.status.split(" ")[0]}">${esc(a.status)}</td><td>${a.date}</td><td class="mut">${esc(a.affects.join(", "))}</td></tr>`).join("")}</table>`;
  const a=D.adrs.find(x=>x.id===id);if(!a)return"not found";
  return `<h1>${a.id}: ${esc(a.title)}</h1><div><span class="${a.status.split(" ")[0]}">${esc(a.status)}</span> · ${a.date} ${a.supersedes&&a.supersedes!=="-"?"· supersedes "+esc(a.supersedes):""}</div>
  <div class="mut">affects: ${a.affects.map(x=>{const s=D.symbols.find(y=>y.path===x&&y.kind==="module")||D.symbols.find(y=>y.qual===x||y.name===x);return s?`<a href="#/s/${s.id}">${esc(x)}</a>`:esc(x)}).join(", ")}</div>
  ${Object.entries(a.sections).map(([k,v])=>`<h2>${esc(k)}</h2><div class="card" style="white-space:pre-wrap">${esc(v)}</div>`).join("")}`},
 glossary:()=>`<h1>Glossary</h1><div class="mut">What each term IS, why it matters here, and where it lives in the code.</div>${Object.entries(D.glossary).sort().map(([t,g])=>`<div class="card" id="t-${esc(t)}"><div class="k">${esc(t)}</div>${["what","why","analogy","how-here","see"].filter(k=>g[k]).map(k=>`<div><span class="mut">${k}:</span> ${esc(g[k])}</div>`).join("")}</div>`).join("")||'<span class="mut">empty — mem term add</span>'}`,
 memory:()=>`<h1>Memory (this project)</h1>${D.memories.map(m=>`<div class="card"><span class="pill">${m.kind}</span><span class="mut">#${m.id} ${m.date}</span><div>${esc(m.text)}</div></div>`).join("")}`,
 docs:()=>{const by={};D.docs.forEach(d=>(by[d.path]=by[d.path]||[]).push(d));return `<h1>Docs</h1>${Object.entries(by).map(([p,cs])=>`<h2>${esc(p)}</h2>${cs.map(c=>`<div><span class="mut">:${c.line}</span> <b>${esc(c.heading||"")}</b> <span class="mut">${esc(c.text.slice(0,140))}</span></div>`).join("")}`).join("")}`},
 search:(q)=>{q=decodeURIComponent(q||"");const toks=q.toLowerCase().split(/[^a-z0-9_]+/).filter(t=>t.length>1);if(!toks.length)return"";
  const sc=t=>{t=t.toLowerCase();return toks.reduce((a,k)=>a+(t.includes(k)?1:0),0)};const R=[];
  D.symbols.forEach(s=>{const v=sc(s.qual)*3+sc(s.doc)+sc(s.sig);if(v)R.push([v+(callersOf[s.id]?.length?0.5:0),`<span class="pill">code</span>${L(s)} <span class="mut">${esc(s.doc.slice(0,100))}</span>`])});
  D.adrs.forEach(a=>{const v=sc(a.title)*3+sc(JSON.stringify(a.sections));if(v)R.push([v+1,`<span class="pill">adr</span><a href="#/adr/${a.id}">${a.id} ${esc(a.title)}</a>`])});
  Object.entries(D.glossary).forEach(([t,g])=>{const v=sc(t)*4+sc(JSON.stringify(g));if(v)R.push([v+1,`<span class="pill">term</span><a href="#/glossary">${esc(t)}</a> <span class="mut">${esc((g.what||"").slice(0,100))}</span>`])});
  D.docs.forEach(d=>{const v=sc(d.heading||"")*2+sc(d.text);if(v)R.push([v,`<span class="pill">doc</span>${esc(d.path)}:${d.line} <b>${esc(d.heading||"")}</b> <span class="mut">${esc(d.text.slice(0,100))}</span>`])});
  D.memories.forEach(m=>{const v=sc(m.text);if(v)R.push([v,`<span class="pill">${m.kind}</span><span class="mut">#${m.id}</span> ${esc(m.text.slice(0,140))}`])});
  R.sort((a,b)=>b[0]-a[0]);return `<h1>Search: ${esc(q)}</h1><div class="mut">${R.length} results</div>${R.slice(0,80).map(r=>`<div style="margin:4px 0">${r[1]}</div>`).join("")}`},
};
function route(){const h=location.hash.replace(/^#\/?/,"");const [v,...rest]=h.split("/");const arg=rest.join("/");
 $("#main").innerHTML=(V[v]||V[""])(arg);$("#nav").innerHTML=navHtml("#/"+(v||""));$("#main").scrollTop=0}
let t;$("#q").addEventListener("input",e=>{clearTimeout(t);t=setTimeout(()=>{location.hash="#/search/"+encodeURIComponent(e.target.value)},150)});
document.addEventListener("keydown",e=>{if(e.key==="/"&&document.activeElement!==$("#q")){e.preventDefault();$("#q").focus()}});
addEventListener("hashchange",route);route();
</script></body></html>
"""
