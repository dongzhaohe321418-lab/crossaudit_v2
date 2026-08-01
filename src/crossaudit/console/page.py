"""The console page: an overview you can read at a glance, and one place to talk.

The layout answers a person's questions in the order they ask them. A band of
figures for "how is it going", the five steps of the loop for "where is this
increment", then the two conversations, what is waiting on me, and what the
rules have actually caught. The input stays at the bottom throughout: one box,
and the program decides who hears it.

Updates are pushed. The page opens a stream and the server sends a snapshot the
moment anything changes, so a build's rounds appear as they happen; polling
remains as a fallback, because a dashboard that shows nothing when one transport
is unavailable is worse than one that is a second late.

Three things this refuses to do, because a supervision dashboard that does them
is worse than no dashboard. It never shows a figure the ledger cannot support —
absent evidence renders as absent, not as zero. It never colours a step green
before it happened: a step nobody reached is pending, which is not the same as
passing. And it never implies the console acted on its own; every action runs a
CLI verb.
"""
from __future__ import annotations

PAGE = r"""<!doctype html>
<meta charset="utf-8"><title>CrossAudit</title>
<style>
:root{
  color-scheme:light dark;
  --fg:#0f172a; --dim:#64748b; --faint:#94a3b8; --line:#e2e8f0;
  --bg:#f8fafc; --card:#fff; --shadow:0 1px 2px rgba(15,23,42,.06);
  --good:#16a34a; --good-bg:#f0fdf4; --bad:#dc2626; --bad-bg:#fef2f2;
  --warn:#d97706; --warn-bg:#fffbeb; --info:#4f46e5; --info-bg:#eef2ff;
  --gen:#2563eb; --aud:#7c3aed;
}
@media(prefers-color-scheme:dark){:root{
  --fg:#e2e8f0; --dim:#94a3b8; --faint:#64748b; --line:#1e293b;
  --bg:#0b1120; --card:#111827; --shadow:none;
  --good-bg:#052e16; --bad-bg:#2a0d0d; --warn-bg:#2a1e05; --info-bg:#1e1b4b;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
"Hiragino Sans GB",sans-serif;height:100vh;display:flex;flex-direction:column;
overflow:hidden}

header{display:flex;align-items:center;gap:12px;padding:12px 22px;
background:var(--card);border-bottom:1px solid var(--line);flex-wrap:wrap}
.brand{font-weight:700;letter-spacing:-.02em}
.crumb{display:flex;align-items:center;gap:7px;padding:5px 11px;
border:1px solid var(--line);border-radius:8px;font-size:13px;color:var(--dim)}
.crumb b{color:var(--fg);font-weight:600}
.spacer{margin-left:auto}
.pill{font-size:11px;padding:3px 10px;border-radius:999px;
border:1px solid var(--line);color:var(--dim);white-space:nowrap;
display:inline-flex;align-items:center;gap:6px}
.pill.good{color:var(--good);background:var(--good-bg);border-color:transparent}
.pill.warn{color:var(--warn);background:var(--warn-bg);border-color:transparent}
.pill.bad{color:var(--bad);background:var(--bad-bg);border-color:transparent}
.livedot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:none}
.livedot.on{background:var(--good)}

main{flex:1;overflow-y:auto;padding:20px 22px 8px}
h2{font-size:15px;margin:0;font-weight:650;letter-spacing:-.01em}
.sub{font-size:12px;color:var(--dim)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
box-shadow:var(--shadow)}
.card-head{padding:14px 16px 10px;display:flex;align-items:baseline;gap:10px}
.card-body{padding:0 16px 15px}
.grid{display:grid;gap:14px}

.metrics{grid-template-columns:repeat(auto-fit,minmax(168px,1fr));margin-bottom:16px}
.metric{padding:14px 16px}
.metric .k{font-size:12px;color:var(--dim)}
.metric .v{font-size:30px;font-weight:700;letter-spacing:-.03em;margin-top:5px;
display:flex;align-items:baseline;gap:8px}
.metric .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px}
.metric.good .badge{color:var(--good);background:var(--good-bg)}
.metric.bad .badge{color:var(--bad);background:var(--bad-bg)}
.metric.warn .badge{color:var(--warn);background:var(--warn-bg)}
.metric .n{font-size:11px;color:var(--faint);margin-top:4px}
.metric .v.none{font-size:18px;font-weight:500;color:var(--faint)}

.pipe{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
@media(max-width:900px){.pipe{grid-template-columns:1fr}}
.pstep{border:1px solid var(--line);border-radius:10px;padding:11px 12px;
background:var(--card)}
.pstep .n{font-size:11px;color:var(--faint)}
.pstep .t{font-weight:600;margin-top:3px;display:flex;align-items:center;gap:6px}
.pstep .d{font-size:11.5px;color:var(--dim);margin-top:4px;word-break:break-word}
.pstep.done{border-color:var(--good);background:var(--good-bg)}
.pstep.failed{border-color:var(--bad);background:var(--bad-bg)}
.pstep.current{border-color:var(--warn);background:var(--warn-bg)}
.pstep.pending{opacity:.6;border-style:dashed}
.mark{width:16px;height:16px;border-radius:50%;display:inline-flex;
align-items:center;justify-content:center;font-size:10px;color:#fff;flex:none}
.done .mark{background:var(--good)}.failed .mark{background:var(--bad)}
.current .mark{background:var(--warn)}.pending .mark{background:var(--faint)}

.talk{grid-template-columns:1fr 1fr}
@media(max-width:980px){.talk{grid-template-columns:1fr}}
.stream{max-height:290px;overflow-y:auto;padding:0 16px 14px}
.msg{padding:10px 0;border-bottom:1px solid var(--line)}
.msg:last-child{border-bottom:0}
.who{font-size:11px;color:var(--dim);display:flex;gap:8px;align-items:baseline}
.who b{color:var(--fg);font-weight:600}
.when{margin-left:auto;color:var(--faint)}
.body{margin-top:3px;white-space:pre-wrap;word-break:break-word}
.files{margin-top:4px;font-size:11.5px;color:var(--dim);
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.f{display:block}
.dot{width:8px;height:8px;border-radius:50%;flex:none}
.dot.gen{background:var(--gen)}.dot.aud{background:var(--aud)}
.finding{margin-top:6px;padding-left:10px;border-left:2px solid var(--line)}
.rule{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--dim)}
.PASS,.PASSED,.CONSUMED,.WITHDRAWN{color:var(--good);font-weight:650}
.BLOCKED,.UPHELD{color:var(--bad);font-weight:650}
.ESCALATED,.ESCALATE,.DCL_ONLY{color:var(--warn);font-weight:650}
.OPEN{color:var(--info);font-weight:650}

.lower{grid-template-columns:1fr 1fr 1fr}
@media(max-width:1100px){.lower{grid-template-columns:1fr 1fr}}
@media(max-width:760px){.lower{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:9px;padding:5px 0;font-size:13px}
.bar .lab{width:78px;flex:none;color:var(--dim);font-size:12px}
.bar .track{flex:1;height:7px;border-radius:4px;background:var(--line);
overflow:hidden}
.bar .fill{height:100%;border-radius:4px}
.bar .num{width:52px;text-align:right;color:var(--dim);font-size:12px}
.fill.BLOCKER{background:var(--bad)}.fill.ADVISORY{background:var(--warn)}
.fill.other{background:var(--info)}
.item{padding:9px 0;border-bottom:1px solid var(--line)}
.item:last-child{border-bottom:0}
.item .h{display:flex;gap:8px;align-items:baseline}
.item .w{font-size:12px;color:var(--dim);margin-top:2px}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.empty{color:var(--faint);font-style:italic;font-size:13px;padding:6px 0}
.cmd{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--dim);
background:var(--bg);border:1px solid var(--line);border-radius:6px;
padding:2px 7px;display:inline-block;margin-top:5px}

.live{margin-bottom:16px;border-color:var(--gen)}
.live.hidden{display:none}
.spin{width:9px;height:9px;border-radius:50%;background:var(--gen);
animation:pulse 1.1s ease-in-out infinite;flex:none}
@keyframes pulse{0%,100%{opacity:.25;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}
.spin.done{animation:none;background:var(--good)}
.spin.bad{animation:none;background:var(--bad)}
.spin.warn{animation:none;background:var(--warn)}
.steps{max-height:120px;overflow-y:auto;font-size:12px;margin-top:6px}
.st{display:flex;gap:9px;padding:2px 0}
.st .a{color:var(--dim);width:74px;flex:none;font-size:11px}
.st .a.generator{color:var(--gen)}.st .a.auditor{color:var(--aud)}
.st .d{color:var(--faint);margin-left:6px}
.st.round{border-top:1px solid var(--line);margin-top:4px;padding-top:5px;
color:var(--dim)}

.warnbar{padding:9px 22px;background:var(--warn-bg);color:var(--warn);
font-size:12.5px;display:none;border-top:1px solid var(--line)}
.warnbar.on{display:block}
.route{padding:8px 22px;font-size:12.5px;color:var(--dim);display:none;
border-top:1px solid var(--line);background:var(--card)}
.route.on{display:block}
.route b{color:var(--fg)}
.ask{color:var(--warn)}
form{display:flex;gap:9px;padding:12px 22px;background:var(--card);
border-top:1px solid var(--line)}
input[type=text]{flex:1;padding:10px 13px;border:1px solid var(--line);
border-radius:9px;background:var(--bg);color:var(--fg);font:inherit}
input[type=text]:focus{outline:2px solid var(--gen);outline-offset:-1px}
button{padding:10px 18px;border:0;border-radius:9px;background:var(--fg);
color:var(--card);font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.45;cursor:default}
footer{padding:7px 22px;font-size:11px;color:var(--faint);background:var(--card);
border-top:1px solid var(--line);display:flex;gap:14px;flex-wrap:wrap}
</style>

<header>
  <span class="brand">CrossAudit</span>
  <span class="crumb"><b id="proj">…</b></span>
  <span class="crumb" id="rules-crumb">…</span>
  <span class="spacer"></span>
  <span class="pill"><span class="livedot" id="livedot"></span>
    <span id="conn-text">connecting</span></span>
  <span class="pill" id="pair-pill"></span>
  <span class="pill" id="tier-pill"></span>
</header>

<main>
  <div class="grid metrics" id="metrics"></div>

  <div class="card live hidden" id="live">
    <div class="card-head"><span class="spin" id="spin"></span>
      <h2 id="live-task">…</h2><span class="sub" id="live-outcome"></span>
      <span class="spacer"></span><span class="sub" id="live-elapsed"></span></div>
    <div class="card-body"><div class="steps" id="steps"></div></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-head"><h2>The loop</h2>
      <span class="sub" id="pipe-sub"></span></div>
    <div class="card-body"><div class="pipe" id="pipe"></div></div>
  </div>

  <div class="grid talk" style="margin-bottom:16px">
    <div class="card">
      <div class="card-head"><span class="dot gen"></span><h2>Generator</h2>
        <span class="sub">the work</span>
        <span class="spacer"></span><span class="sub" id="gen-sub"></span></div>
      <div class="stream" id="gen"></div>
    </div>
    <div class="card">
      <div class="card-head"><span class="dot aud"></span><h2>Auditor</h2>
        <span class="sub">the judgement</span>
        <span class="spacer"></span><span class="sub" id="aud-sub"></span></div>
      <div class="stream" id="aud"></div>
    </div>
  </div>

  <div class="grid lower" style="margin-bottom:16px">
    <div class="card">
      <div class="card-head"><h2>Waiting on you</h2>
        <span class="sub">escalations</span></div>
      <div class="card-body" id="escalations"></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>What the rules caught</h2>
        <span class="sub" id="findings-sub"></span></div>
      <div class="card-body" id="findings"></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>Disputes</h2>
        <span class="sub">one reading each</span></div>
      <div class="card-body" id="disputes"></div>
    </div>
  </div>
</main>

<div class="warnbar" id="interrupted"></div>
<div class="route" id="route"></div>
<form id="f" autocomplete="off">
  <input type="text" id="say"
         placeholder="Say what you want — the box decides who hears it…">
  <button id="send">Send</button>
</form>
<footer>
  <span>Everything here comes from git and the controller's store.</span>
  <span>Actions run the same CLI verbs; this window writes nothing of its own.</span>
</footer>

<script>
const T = new URLSearchParams(location.search).get('t') || '';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const at = t => new Date(t*1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
const MARK = {done:'✓', failed:'✕', current:'●', pending:'·'};

async function api(path, body){
  const opt = body
    ? {method:'POST', headers:{'content-type':'application/json'},
       body:JSON.stringify(body)}
    : {};
  const r = await fetch(path + '?t=' + encodeURIComponent(T), opt);
  if(!r.ok) throw new Error(r.status + ' ' + await r.text());
  return r.json();
}

function metricCard(m){
  const val = (m.value === null || m.value === undefined)
    ? '<div class="v none">not measured</div>'
    : '<div class="v">' + esc(m.value)
      + (m.badge ? '<span class="badge">' + esc(m.badge) + '</span>' : '') + '</div>';
  return '<div class="card metric ' + esc(m.tone || '') + '">'
    + '<div class="k">' + esc(m.label) + '</div>' + val
    + '<div class="n">' + esc(m.note || '') + '</div></div>';
}

function stepCard(s, i){
  return '<div class="pstep ' + esc(s.state) + '">'
    + '<div class="n">step ' + (i+1) + '</div>'
    + '<div class="t"><span class="mark">' + MARK[s.state] + '</span>'
    + esc(s.title) + '</div>'
    + '<div class="d">' + esc(s.detail) + '</div></div>';
}

function genMsg(m){
  const files = (m.files||[]).map(f => '<span class="f">' + esc(f) + '</span>').join('');
  return '<div class="msg"><div class="who"><b>generator</b>'
    + (m.round ? '<span>round ' + m.round + '</span>' : '')
    + '<span class="when">' + at(m.t) + '</span></div>'
    + '<div class="body">' + esc(m.summary) + '</div>'
    + (files ? '<div class="files">' + files + '</div>' : '')
    + (m.notes ? '<div class="files">note: ' + esc(m.notes) + '</div>' : '')
    + '</div>';
}
function audMsg(m){
  const findings = (m.findings||[]).map(f =>
    '<div class="finding"><span class="rule">[' + esc(f.severity) + '] '
    + esc(f.rule) + ' · ' + esc(f.artifact) + '</span><div>'
    + esc(f.observation) + '</div></div>').join('');
  return '<div class="msg"><div class="who"><b>auditor</b>'
    + '<span class="' + esc(m.verdict) + '">' + esc(m.verdict) + '</span>'
    + '<span class="when">' + at(m.t) + '</span></div>'
    + (findings || '<div class="empty">no findings</div>') + '</div>';
}
function userMsg(m){
  return '<div class="msg"><div class="who"><b>you</b><span>→ ' + esc(m.lane)
    + ' · ' + Math.round(m.confidence*100) + '%</span>'
    + '<span class="when">' + at(m.t) + '</span></div>'
    + '<div class="body">' + esc(m.utterance) + '</div>'
    + '<div class="files">→ ' + esc(m.executed) + '</div></div>';
}

function drawProgress(p){
  const box = document.getElementById('live');
  if(!p){ box.className = 'card live hidden'; return; }
  box.className = 'card live';
  document.getElementById('live-task').textContent =
    p.task.replace(/\s+/g, ' ').slice(0,70);
  document.getElementById('spin').className = 'spin' + (!p.finished ? ''
    : p.outcome === 'passed' ? ' done'
    : p.outcome === 'escalated' ? ' warn' : ' bad');
  document.getElementById('live-outcome').textContent = p.finished
    ? (p.outcome + (p.error ? ' — ' + p.error : '')) : 'running…';
  document.getElementById('live-elapsed').textContent = p.elapsed + 's';
  document.getElementById('steps').innerHTML = p.steps.map(s => {
    const isRound = s.actor === 'loop' && s.text.startsWith('round ');
    return '<div class="st' + (isRound ? ' round' : '') + '">'
      + '<span class="a ' + esc(s.actor) + '">' + esc(s.actor) + '</span>'
      + '<span>' + esc(s.text)
      + (s.detail ? '<span class="d">' + esc(s.detail) + '</span>' : '')
      + '</span></div>';
  }).join('');
  const st = document.getElementById('steps');
  st.scrollTop = st.scrollHeight;
}

function render(d){
  document.getElementById('proj').textContent = d.project;
  document.getElementById('rules-crumb').innerHTML =
    d.rules + ' rules' + (d.skills.length
      ? ' · <b>' + esc(d.skills.join(', ')) + '</b>' : '');
  const tp = document.getElementById('tier-pill');
  tp.textContent = d.tier.tier + ' — ' + d.tier.means;
  tp.className = 'pill ' + (d.tier.tier === 'enforced' ? 'good' : 'warn');
  const pp = document.getElementById('pair-pill');
  pp.textContent = d.generator + ' → ' + d.auditor
    + (d.key_present ? '' : ' · key missing');
  pp.className = 'pill' + (d.key_present ? '' : ' bad');

  document.getElementById('metrics').innerHTML = d.metrics.map(metricCard).join('');
  document.getElementById('pipe').innerHTML = d.pipeline.map(stepCard).join('');
  document.getElementById('pipe-sub').textContent = d.cycles.length
    ? 'latest increment' : 'nothing audited yet';

  document.getElementById('gen').innerHTML =
    d.generator_stream.map(m => m.kind === 'you' ? userMsg(m) : genMsg(m)).join('')
    || '<div class="empty">Nothing yet. Say what you want built.</div>';
  document.getElementById('aud').innerHTML =
    d.auditor_stream.map(m => m.kind === 'you' ? userMsg(m) : audMsg(m)).join('')
    || '<div class="empty">Nothing judged yet.</div>';
  document.getElementById('gen-sub').textContent = d.generator_stream.length;
  document.getElementById('aud-sub').textContent = d.auditor_stream.length;

  document.getElementById('escalations').innerHTML = d.escalations.length
    ? d.escalations.map(e => '<div class="item"><div class="h">'
        + '<span class="mono">' + esc(e.sha) + '</span>'
        + '<span class="ESCALATED">round ' + e.round + '</span></div>'
        + '<div class="w">' + esc(e.why) + '</div>'
        + '<div class="cmd">say what should happen — it routes to resolve</div>'
        + '</div>').join('')
    : '<div class="empty">Nothing is waiting on you.</div>';

  const fb = d.findings;
  document.getElementById('findings-sub').textContent =
    fb.total ? fb.total + ' findings' : '';
  document.getElementById('findings').innerHTML = (fb.total
    ? fb.rows.map(r => '<div class="bar"><span class="lab">'
        + esc(r.severity.toLowerCase()) + '</span><span class="track">'
        + '<span class="fill ' + (r.severity === 'BLOCKER' ? 'BLOCKER'
            : r.severity === 'ADVISORY' ? 'ADVISORY' : 'other')
        + '" style="width:' + Math.round(r.share*100) + '%"></span></span>'
        + '<span class="num">' + r.count + '</span></div>').join('')
      + (d.top_rules.length
         ? '<div class="w" style="margin-top:9px;font-size:12px;color:var(--dim)">'
           + d.top_rules.map(t => esc(t.rule) + ' ×' + t.count).join(' · ')
           + '</div>' : '')
    : '<div class="empty">No findings recorded yet.</div>');

  document.getElementById('disputes').innerHTML = d.disputes.length
    ? d.disputes.map(x => '<div class="item"><div class="h">'
        + '<span class="mono">' + esc(x.rule) + '</span>'
        + '<span class="' + esc(x.ruling) + '">' + esc(x.ruling) + '</span></div>'
        + '<div class="w">' + esc(x.reasoning) + '</div></div>').join('')
    : '<div class="empty">No finding has been contested.</div>';

  const iv = document.getElementById('interrupted');
  if(d.interrupted && !(d.progress && !d.progress.finished)){
    iv.className = 'warnbar on';
    iv.textContent = 'A build was interrupted: "'
      + d.interrupted.task.replace(/\s+/g, ' ').slice(0,60)
      + '". The rounds it committed are below; the one it was in the middle of '
      + 'is not. Say it again to carry on.';
  }else{ iv.className = 'warnbar'; }

  drawProgress(d.progress);
}

/* Pushed updates, with polling as the fallback: a dashboard that shows nothing
   when one transport is unavailable is worse than one that is a second late. */
function connected(on, why){
  document.getElementById('livedot').className = 'livedot' + (on ? ' on' : '');
  document.getElementById('conn-text').textContent = why;
}

let poller = null;
function startPolling(why){
  connected(false, why);
  if(poller) return;
  poller = setInterval(async () => {
    try{ render(await api('/api/state')); connected(true, 'polling'); }
    catch(e){ connected(false, 'disconnected'); }
  }, 2000);
}

function startStream(){
  let source;
  try{ source = new EventSource('/api/stream?t=' + encodeURIComponent(T)); }
  catch(e){ startPolling('polling'); return; }
  source.onopen = () => {
    connected(true, 'live');
    if(poller){ clearInterval(poller); poller = null; }
  };
  source.onmessage = ev => {
    try{ render(JSON.parse(ev.data)); connected(true, 'live'); }
    catch(e){ /* one malformed frame is no reason to blank the page */ }
  };
  source.onerror = () => startPolling('reconnecting');
}

api('/api/state').then(render).catch(e => {
  document.getElementById('proj').textContent = 'disconnected — ' + e.message;
});
startStream();

const form = document.getElementById('f');
const say = document.getElementById('say');
const send = document.getElementById('send');
const route = document.getElementById('route');

form.onsubmit = async ev => {
  ev.preventDefault();
  const text = say.value.trim();
  if(!text) return;
  send.disabled = true; say.disabled = true;
  route.className = 'route on';
  route.innerHTML = 'routing…';
  try{
    const r = await api('/api/say', {text});
    if(r.asked){
      route.innerHTML = '<b class="ask">not sure enough to act</b> — '
        + esc(r.clarify) + ' (nothing was done)';
      say.value = text;
    }else{
      route.innerHTML = '→ <b>' + esc(r.lane) + '</b> ('
        + Math.round(r.confidence*100) + '% sure) — ' + esc(r.reasoning)
        + '<br>' + esc(r.executed);
      say.value = '';
    }
  }catch(e){
    route.innerHTML = '<b>refused</b> — ' + esc(e.message);
  }
  send.disabled = false; say.disabled = false; say.focus();
};
</script>
"""
