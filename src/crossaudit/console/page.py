"""The console page: two windows, one input, and the loop's state between them.

Layout follows what the work actually is. The generator is the main window
because that is where the project takes shape; the auditor is the side window
because judgement is a smaller, denser thing that you read rather than watch.
Between them sits the loop's state, so "where are we" never needs asking.

The single input at the bottom is the black box. The user types as they would to
any assistant; the router decides whether that sentence belongs to the work, the
standards, a contested finding, or a question — and the decision, with its
confidence, is shown right where it happened. A box whose sorting is invisible
would be asking for trust it has not earned.

Sending is the one write path, and it is deliberately narrow: it POSTs the
sentence and nothing else. Everything the console can cause is something the CLI
could already do, which is the console rule from the paper's roadmap.
"""
from __future__ import annotations

PAGE = """<!doctype html>
<meta charset="utf-8"><title>CrossAudit</title>
<style>
:root{color-scheme:light dark;--fg:#14171a;--dim:#6b7378;--faint:#9aa3a8;
--line:#e3e6e8;--bg:#fff;--panel:#fafbfc;--red:#c0392b;--green:#1e8449;
--amber:#b9770e;--blue:#2874a6;--gen:#2874a6;--aud:#7d3c98}
@media(prefers-color-scheme:dark){:root{--fg:#e8eaec;--dim:#9aa3a8;--faint:#6b7378;
--line:#2a2e31;--bg:#121416;--panel:#181b1e}}
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
"PingFang SC","Hiragino Sans GB",sans-serif;color:var(--fg);background:var(--bg);
height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{padding:10px 18px;border-bottom:1px solid var(--line);display:flex;
align-items:baseline;gap:14px;flex-wrap:wrap}
h1{font-size:14px;margin:0;font-weight:650;letter-spacing:-.01em}
.meta{color:var(--dim);font-size:12px}
.tier{margin-left:auto;font-size:11px;color:var(--dim);border:1px solid var(--line);
padding:2px 9px;border-radius:10px}
main{flex:1;display:grid;grid-template-columns:1fr 380px;min-height:0}
@media(max-width:900px){main{grid-template-columns:1fr}}
.pane{display:flex;flex-direction:column;min-height:0;min-width:0}
.pane+.pane{border-left:1px solid var(--line)}
.pane-head{padding:9px 18px;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:8px;background:var(--panel)}
.dot{width:7px;height:7px;border-radius:50%;flex:none}
.dot.gen{background:var(--gen)}.dot.aud{background:var(--aud)}
.pane-title{font-size:12px;font-weight:600;letter-spacing:.02em}
.pane-sub{font-size:11px;color:var(--faint);margin-left:auto;text-align:right}
.scroll{flex:1;overflow-y:auto;padding:14px 18px}
.msg{margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.msg:last-child{border-bottom:0}
.who{font-size:11px;color:var(--dim);margin-bottom:3px;display:flex;gap:8px;
align-items:baseline}
.who b{font-weight:600;color:var(--fg)}
.when{color:var(--faint);margin-left:auto;font-variant-numeric:tabular-nums}
.body{white-space:pre-wrap;word-break:break-word}
.files{margin-top:5px;font-size:12px;color:var(--dim);
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.f{display:block}
.verdict{font-weight:650}
.PASS,.PASSED,.CONSUMED,.WITHDRAWN{color:var(--green)}
.BLOCKED,.UPHELD{color:var(--red)}
.ESCALATED,.DCL_ONLY{color:var(--amber)}.OPEN{color:var(--blue)}
.finding{margin-top:7px;padding-left:10px;border-left:2px solid var(--line)}
.rule{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--dim)}
.state{padding:10px 18px;border-top:1px solid var(--line);background:var(--panel);
display:flex;gap:18px;flex-wrap:wrap;font-size:12px;align-items:center}
.chip{display:flex;gap:6px;align-items:baseline}
.chip .k{color:var(--faint);font-size:11px}
.chip .v{font-weight:600}
form{display:flex;gap:8px;padding:12px 18px;border-top:1px solid var(--line)}
input[type=text]{flex:1;padding:9px 12px;border:1px solid var(--line);border-radius:7px;
background:var(--bg);color:var(--fg);font:inherit}
input[type=text]:focus{outline:2px solid var(--gen);outline-offset:-1px}
button{padding:9px 16px;border:0;border-radius:7px;background:var(--fg);
color:var(--bg);font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.45;cursor:default}
.route{padding:8px 18px;font-size:12px;color:var(--dim);border-top:1px solid var(--line);
display:none}
.route.on{display:block}
.route b{color:var(--fg)}
.empty{color:var(--faint);font-style:italic}
.ask{color:var(--amber)}
/* live build */
.live{padding:10px 18px;border-top:1px solid var(--line);background:var(--panel);
display:none}
.live.on{display:block}
.live-head{display:flex;gap:10px;align-items:baseline;font-size:12px;margin-bottom:6px}
.live-head b{font-size:13px}
.spin{width:9px;height:9px;border-radius:50%;background:var(--gen);flex:none;
animation:pulse 1.1s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.25;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}
.spin.done{animation:none;background:var(--green)}
.spin.bad{animation:none;background:var(--red)}
.spin.warn{animation:none;background:var(--amber)}
.elapsed{margin-left:auto;color:var(--faint);font-variant-numeric:tabular-nums}
.steps{max-height:132px;overflow-y:auto;font-size:12px}
.step{display:flex;gap:9px;padding:2px 0;align-items:baseline}
.step .a{color:var(--dim);width:74px;flex:none;font-size:11px}
.step .a.generator{color:var(--gen)}.step .a.auditor{color:var(--aud)}
.step .d{color:var(--faint);margin-left:6px}
.step.round{border-top:1px solid var(--line);margin-top:4px;padding-top:5px;
color:var(--dim)}
</style>

<header>
  <h1>CrossAudit</h1>
  <span class="meta" id="meta">…</span>
  <span class="tier" id="tier"></span>
</header>

<main>
  <div class="pane">
    <div class="pane-head"><span class="dot gen"></span>
      <span class="pane-title">Generator — the work</span>
      <span class="pane-sub" id="gen-sub"></span></div>
    <div class="scroll" id="gen"></div>
  </div>
  <div class="pane">
    <div class="pane-head"><span class="dot aud"></span>
      <span class="pane-title">Auditor — the judgement</span>
      <span class="pane-sub" id="aud-sub"></span></div>
    <div class="scroll" id="aud"></div>
  </div>
</main>

<div class="live" id="live">
  <div class="live-head"><span class="spin" id="spin"></span>
    <b id="live-task">…</b><span id="live-outcome" class="empty"></span>
    <span class="elapsed" id="live-elapsed"></span></div>
  <div class="steps" id="steps"></div>
</div>
<div class="state" id="state"></div>
<div class="route" id="route"></div>
<form id="f" autocomplete="off">
  <input type="text" id="say" placeholder="Say what you want — the box decides who hears it…">
  <button id="send">Send</button>
</form>

<script>
const T = new URLSearchParams(location.search).get('t') || '';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const at = t => new Date(t*1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});

async function api(path, body){
  const opt = body
    ? {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(body)}
    : {};
  const r = await fetch(path + '?t=' + encodeURIComponent(T), opt);
  if(!r.ok) throw new Error(r.status + ' ' + await r.text());
  return r.json();
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
    '<div class="finding"><span class="rule ' + esc(f.severity) + '">['
    + esc(f.severity) + '] ' + esc(f.rule) + ' · ' + esc(f.artifact)
    + '</span><div>' + esc(f.observation) + '</div></div>').join('');
  return '<div class="msg"><div class="who"><b>auditor</b>'
    + '<span class="verdict ' + esc(m.verdict) + '">' + esc(m.verdict) + '</span>'
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

async function draw(){
  try{
    const d = await api('/api/state');
    document.getElementById('meta').textContent =
      d.project + ' · ' + d.rules + ' rules'
      + (d.skills.length ? ' · skills: ' + d.skills.join(', ') : '')
      + ' · generator ' + d.generator + ' · auditor ' + d.auditor;
    document.getElementById('tier').textContent = d.tier.tier + ' — ' + d.tier.means;

    const gen = d.generator_stream.map(m => m.kind === 'you' ? userMsg(m) : genMsg(m));
    document.getElementById('gen').innerHTML = gen.join('') ||
      '<div class="empty">Nothing yet. Say what you want built.</div>';
    document.getElementById('gen-sub').textContent =
      d.generator_stream.length + ' entries';

    document.getElementById('aud').innerHTML =
      d.auditor_stream.map(m => m.kind === 'you' ? userMsg(m) : audMsg(m)).join('') ||
      '<div class="empty">Nothing judged yet.</div>';
    document.getElementById('aud-sub').textContent =
      d.auditor_stream.length + ' entries';

    document.getElementById('state').innerHTML = (d.cycles.length
      ? d.cycles.slice(-4).map(c => '<span class="chip"><span class="k">'
          + esc(c.id.slice(0,8)) + '</span><span class="v ' + esc(c.status) + '">'
          + esc(c.status) + '</span><span class="k">r' + c.round + '</span></span>').join('')
      : '<span class="k">no cycles yet</span>')
      + (d.tier.shortfalls.length
         ? '<span class="chip" style="margin-left:auto"><span class="k">toward enforced: '
           + esc(d.tier.shortfalls[0]) + '</span></span>' : '');

    drawProgress(d.progress);
    for(const el of document.querySelectorAll('.scroll')) el.scrollTop = el.scrollHeight;
  }catch(e){
    document.getElementById('meta').textContent = 'disconnected — ' + e.message;
  }
}

let fast = false;
function drawProgress(p){
  const box = document.getElementById('live');
  if(!p){ box.className = 'live'; fast = false; return; }
  box.className = 'live on';
  fast = !p.finished;
  document.getElementById('live-task').textContent = p.task.replace(/\\s+/g, ' ').slice(0,70);
  const spin = document.getElementById('spin');
  spin.className = 'spin' + (!p.finished ? ''
    : p.outcome === 'passed' ? ' done'
    : p.outcome === 'escalated' ? ' warn' : ' bad');
  document.getElementById('live-outcome').textContent = p.finished
    ? (p.outcome + (p.error ? ' — ' + p.error : '')) : 'running…';
  document.getElementById('live-elapsed').textContent = p.elapsed + 's';
  document.getElementById('steps').innerHTML = p.steps.map(s => {
    const isRound = s.actor === 'loop' && s.text.startsWith('round ');
    return '<div class="step' + (isRound ? ' round' : '') + '">'
      + '<span class="a ' + esc(s.actor) + '">' + esc(s.actor) + '</span>'
      + '<span>' + esc(s.text)
      + (s.detail ? '<span class="d">' + esc(s.detail) + '</span>' : '')
      + '</span></div>';
  }).join('');
  const st = document.getElementById('steps');
  st.scrollTop = st.scrollHeight;
}

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
      route.innerHTML = '<b class="ask">not sure enough to act</b> — ' + esc(r.clarify)
        + ' <span class="k">(nothing was done; say it again with that settled)</span>';
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
  draw();
};

// While a build is in flight the page follows it closely; otherwise it idles,
// because polling a ledger that is not changing is just noise.
draw();
setInterval(() => draw(), 4000);
setInterval(() => { if(fast) draw(); }, 1200);
</script>
"""
