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
  color-scheme:light;
  --fg:#172033; --dim:#667085; --faint:#98a2b3; --line:#e6e9ef;
  --bg:#f7f8fb; --card:#fff; --soft:#fafbfc;
  --shadow:0 1px 2px rgba(16,24,40,.03),0 8px 24px rgba(16,24,40,.035);
  --good:#18a66a; --good-bg:#ecfdf3; --bad:#f04438; --bad-bg:#fff1f0;
  --warn:#e9a11b; --warn-bg:#fff8e8; --info:#5b5bd6; --info-bg:#f1f0ff;
  --gen:#2f80ed; --gen-bg:#eef6ff; --aud:#7759d7; --aud-bg:#f4f1ff;
  --radius:14px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
"Hiragino Sans GB",sans-serif;min-height:100vh;display:flex;flex-direction:column}

header{min-height:68px;display:flex;align-items:center;gap:12px;padding:12px 28px;
background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);flex-wrap:wrap;
box-shadow:0 1px 0 rgba(16,24,40,.02);z-index:3}
.brand{font-weight:750;letter-spacing:-.03em;font-size:17px;display:flex;
align-items:center;gap:9px;margin-right:5px}
.brand-mark{width:28px;height:28px;border-radius:9px;background:var(--fg);color:#fff;
display:inline-flex;align-items:center;justify-content:center;font-size:14px}
.crumb{min-height:38px;display:flex;align-items:center;gap:8px;padding:7px 12px;
border:1px solid var(--line);border-radius:9px;font-size:13px;color:var(--dim);
background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.03)}
.crumb b{color:var(--fg);font-weight:650}
.crumb.project:after{content:'⌄';color:var(--faint);margin-left:3px}
.spacer{margin-left:auto}
.pill{font-size:11.5px;padding:6px 10px;border-radius:8px;
border:1px solid var(--line);color:var(--dim);white-space:nowrap;background:#fff;
display:inline-flex;align-items:center;gap:6px}
.pill.good{color:var(--good);background:var(--good-bg);border-color:transparent}
.pill.warn{color:var(--warn);background:var(--warn-bg);border-color:transparent}
.pill.bad{color:var(--bad);background:var(--bad-bg);border-color:transparent}
.livedot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:none}
.livedot.on{background:var(--good)}

main{flex:1;padding:28px 28px 12px}
.shell{width:min(1480px,100%);margin:0 auto}
.overview-head{display:flex;align-items:flex-end;gap:18px;margin:0 0 20px}
.overview-head h1{font-size:26px;line-height:1.2;margin:0;letter-spacing:-.035em}
.overview-head p{margin:5px 0 0;color:var(--dim);font-size:13.5px}
.eyebrow{font-size:11px;color:var(--info);font-weight:700;text-transform:uppercase;
letter-spacing:.09em;margin-bottom:5px}
h2{font-size:15px;margin:0;font-weight:700;letter-spacing:-.015em}
.sub{font-size:12px;color:var(--dim)}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
box-shadow:var(--shadow)}
.card-head{min-height:54px;padding:16px 18px 12px;display:flex;align-items:center;gap:10px;
border-bottom:1px solid var(--line)}
.card-body{padding:16px 18px 18px}
.grid{display:grid;gap:16px}
.section-head{display:flex;align-items:baseline;gap:10px;margin:22px 0 10px}
.section-head h2{font-size:14px}.section-head .sub{margin-left:auto}

.command{margin-bottom:18px;overflow:hidden;border-color:#d8deea;
box-shadow:0 14px 34px rgba(30,64,175,.07)}
.command-top{display:flex;gap:18px;align-items:flex-start;padding:19px 20px 4px}
.command-icon{width:38px;height:38px;border-radius:11px;background:var(--info-bg);
color:var(--info);display:flex;align-items:center;justify-content:center;
font-size:18px;flex:none}
.command-copy h2{font-size:17px}.command-copy p{margin:3px 0 0;color:var(--dim);
font-size:12.5px}.command-shortcuts{margin-left:auto;font-size:11.5px;color:var(--faint);
white-space:nowrap;padding-top:4px}
form{padding:14px 20px 18px;display:grid;grid-template-columns:1fr auto;gap:10px;
align-items:stretch}
textarea{width:100%;min-height:76px;max-height:180px;resize:vertical;padding:13px 15px;
border:1px solid #d7dce5;border-radius:11px;background:var(--soft);color:var(--fg);
font:inherit;line-height:1.5;box-shadow:inset 0 1px 2px rgba(16,24,40,.025)}
textarea:focus{outline:3px solid rgba(47,128,237,.13);border-color:var(--gen)}
button{min-width:126px;padding:0 20px;border:0;border-radius:11px;background:var(--fg);
color:#fff;font:inherit;font-weight:700;cursor:pointer;display:flex;align-items:center;
justify-content:center;gap:9px;box-shadow:0 4px 10px rgba(23,32,51,.14)}
button:hover{background:#263149}button:disabled{opacity:.45;cursor:default;box-shadow:none}
.button-arrow{font-size:17px}
.form-meta{grid-column:1/-1;display:flex;gap:16px;align-items:center;color:var(--faint);
font-size:11.5px;margin-top:-2px}.form-meta b{color:var(--dim);font-weight:600}

.metrics{grid-template-columns:repeat(5,minmax(150px,1fr));margin-bottom:18px}
.metric{padding:17px 18px;min-height:142px;position:relative;overflow:hidden}
.metric:after{content:'';position:absolute;left:18px;right:18px;bottom:0;height:3px;
border-radius:3px 3px 0 0;background:var(--line)}
.metric.good:after{background:var(--good)}.metric.bad:after{background:var(--bad)}
.metric.warn:after{background:var(--warn)}.metric.neutral:after{background:var(--info)}
.metric .metric-top{display:flex;align-items:center;justify-content:space-between}
.metric .k{font-size:12.5px;color:var(--dim);font-weight:600}
.metric .metric-icon{width:33px;height:33px;border-radius:9px;display:flex;
align-items:center;justify-content:center;background:var(--info-bg);color:var(--info);
font-size:16px}.metric.good .metric-icon{background:var(--good-bg);color:var(--good)}
.metric.bad .metric-icon{background:var(--bad-bg);color:var(--bad)}
.metric.warn .metric-icon{background:var(--warn-bg);color:var(--warn)}
.metric .v{font-size:31px;font-weight:740;letter-spacing:-.04em;margin-top:9px;
display:flex;align-items:baseline;gap:8px}
.metric .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px}
.metric.good .badge{color:var(--good);background:var(--good-bg)}
.metric.bad .badge{color:var(--bad);background:var(--bad-bg)}
.metric.warn .badge{color:var(--warn);background:var(--warn-bg)}
.metric .n{font-size:11.5px;color:var(--faint);margin-top:5px}
.metric .v.none{font-size:18px;font-weight:500;color:var(--faint)}

.dashboard{display:grid;grid-template-columns:minmax(0,1.75fr) minmax(310px,.8fr);
gap:16px;margin-bottom:16px;align-items:start}
.side-stack{display:grid;gap:16px}
.pipe{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.pstep{border:1px solid var(--line);border-radius:11px;padding:13px 13px 14px;
background:var(--soft);min-height:126px;position:relative}
.pstep:not(:last-child):after{content:'→';position:absolute;right:-10px;top:50%;
transform:translate(50%,-50%);color:var(--faint);background:var(--card);z-index:1}
.pstep .n{font-size:11px;color:var(--faint)}
.pstep .t{font-weight:650;margin-top:8px;display:flex;align-items:center;gap:7px}
.pstep .d{font-size:11.5px;color:var(--dim);margin-top:9px;word-break:break-word}
.pstep.done{border-color:#ccebdc;background:#f7fdf9}
.pstep.failed{border-color:#ffd1cd;background:#fff9f8}
.pstep.current{border-color:#f4dda7;background:#fffcf5}
.pstep.pending{opacity:.6;border-style:dashed}
.mark{width:19px;height:19px;border-radius:50%;display:inline-flex;
align-items:center;justify-content:center;font-size:10px;color:#fff;flex:none}
.done .mark{background:var(--good)}.failed .mark{background:var(--bad)}
.current .mark{background:var(--warn)}.pending .mark{background:var(--faint)}

.stream{max-height:390px;overflow-y:auto;padding:0 18px 14px}
.msg{padding:12px 0;border-bottom:1px solid var(--line)}
.msg:last-child{border-bottom:0}
.who{font-size:11px;color:var(--dim);display:flex;gap:8px;align-items:baseline}
.who b{color:var(--fg);font-weight:600}
.when{margin-left:auto;color:var(--faint)}
.body{margin-top:3px;white-space:pre-wrap;word-break:break-word}
.files{margin-top:4px;font-size:11.5px;color:var(--dim);
white-space:pre-wrap;word-break:break-word;
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

.live{margin-bottom:18px;border-color:#bcd7fb;background:linear-gradient(90deg,#fff,#f8fbff)}
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

.warnbar{padding:10px 20px;background:var(--warn-bg);color:var(--warn);
font-size:12.5px;display:none;border-top:1px solid #f3dfac;border-bottom:1px solid #f3dfac}
.warnbar.on{display:block}
.route{padding:11px 20px;font-size:12.5px;color:var(--dim);display:none;
white-space:pre-wrap;word-break:break-word;
border-top:1px solid var(--line);background:var(--soft)}
.route.on{display:block}
.route b{color:var(--fg)}
.ask{color:var(--warn)}
footer{min-height:38px;padding:9px 28px;font-size:11.5px;color:var(--faint);
background:var(--card);border-top:1px solid var(--line);display:flex;gap:18px;
align-items:center;flex-wrap:wrap}
.foot-status{color:var(--good);font-weight:600}.foot-status:before{content:'✓';
display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;
border-radius:6px;background:var(--good-bg);margin-right:7px}

@media(max-width:1180px){
  .metrics{grid-template-columns:repeat(3,1fr)}
  .dashboard{grid-template-columns:1fr}
}
@media(max-width:900px){
  header{padding:10px 16px}.pill#tier-pill{display:none}
  main{padding:22px 16px 10px}.pipe{grid-template-columns:1fr 1fr}
  .pstep:not(:last-child):after{display:none}
}
@media(max-width:680px){
  .metrics{grid-template-columns:1fr 1fr}.overview-head{align-items:flex-start}
  .command-top{padding:16px 16px 2px}.command-shortcuts{display:none}
  form{grid-template-columns:1fr;padding:12px 16px 16px}
  button{min-height:48px}.form-meta{display:none}.pipe{grid-template-columns:1fr}
  .metric{min-height:132px}.crumb#rules-crumb{display:none}
}
@media(max-width:440px){.metrics{grid-template-columns:1fr}.spacer{display:none}}
</style>

<header>
  <span class="brand"><span class="brand-mark">◇</span>CrossAudit</span>
  <span class="crumb project"><b id="proj">…</b></span>
  <span class="crumb" id="rules-crumb">…</span>
  <span class="spacer"></span>
  <span class="pill"><span class="livedot" id="livedot"></span>
    <span id="conn-text">connecting</span></span>
  <span class="pill" id="pair-pill"></span>
  <span class="pill" id="tier-pill"></span>
</header>

<main>
 <div class="shell">
  <div class="overview-head">
    <div><div class="eyebrow">Supervised workspace</div><h1>Overview</h1>
      <p>System health, audit evidence, and the next instruction in one place.</p></div>
  </div>

  <section class="card command" aria-labelledby="command-title">
    <div class="command-top">
      <div class="command-icon">⌁</div>
      <div class="command-copy"><h2 id="command-title">Command center</h2>
        <p>Describe the work, amend a rule, dispute a finding, or ask where things stand.</p></div>
      <div class="command-shortcuts">One box · routed by intent · committed to git</div>
    </div>
    <div class="warnbar" id="interrupted"></div>
    <form id="f" autocomplete="off">
      <textarea id="say" rows="2"
        placeholder="Say what you want — CrossAudit decides who should handle it…"></textarea>
      <button id="send"><span>Run task</span><span class="button-arrow">→</span></button>
      <div class="form-meta"><span><b>Generator</b> writes and commits</span>
        <span><b>Auditor</b> reviews another vendor's work</span>
        <span><b>Enter</b> submits · Shift+Enter adds a line</span></div>
    </form>
    <div class="route" id="route"></div>
  </section>

  <div class="card live hidden" id="live">
    <div class="card-head"><span class="spin" id="spin"></span>
      <h2 id="live-task">…</h2><span class="sub" id="live-outcome"></span>
      <span class="spacer"></span><span class="sub" id="live-elapsed"></span></div>
    <div class="card-body"><div class="steps" id="steps"></div></div>
  </div>

  <div class="section-head"><h2>Audit summary</h2>
    <span class="sub">Every number below is derived from the local ledger.</span></div>
  <div class="grid metrics" id="metrics"></div>

  <div class="dashboard">
    <div class="card">
      <div class="card-head"><h2>Audit pipeline</h2>
        <span class="sub">latest cycle</span><span class="spacer"></span>
        <span class="sub" id="pipe-sub"></span></div>
      <div class="card-body"><div class="pipe" id="pipe"></div></div>
    </div>
    <div class="card">
      <div class="card-head"><span class="dot aud"></span><h2>Recent audits</h2>
        <span class="sub">model judgement</span>
        <span class="spacer"></span><span class="sub" id="aud-sub"></span></div>
      <div class="stream" id="aud"></div>
    </div>
  </div>

  <div class="dashboard">
    <div class="card">
      <div class="card-head"><span class="dot gen"></span><h2>Generator activity</h2>
        <span class="sub">commits and instructions</span>
        <span class="spacer"></span><span class="sub" id="gen-sub"></span></div>
      <div class="stream" id="gen"></div>
    </div>
    <div class="side-stack">
      <div class="card">
        <div class="card-head"><h2>Pending escalations</h2>
          <span class="spacer"></span><span class="sub">waiting on you</span></div>
        <div class="card-body" id="escalations"></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Findings by severity</h2>
          <span class="spacer"></span><span class="sub" id="findings-sub"></span></div>
        <div class="card-body" id="findings"></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Disputes</h2>
          <span class="spacer"></span><span class="sub">one reading each</span></div>
        <div class="card-body" id="disputes"></div>
      </div>
    </div>
  </div>
 </div>
</main>

<footer>
  <span class="foot-status">Local console operational</span>
  <span>Everything here comes from git and the controller's store.</span>
  <span class="spacer"></span><span>CrossAudit · local ledger</span>
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
  const icons = {'Audits':'▤','Passed':'✓','Blocked':'×',
                 'Waiting on you':'!','Admitted':'↳'};
  const val = (m.value === null || m.value === undefined)
    ? '<div class="v none">not measured</div>'
    : '<div class="v">' + esc(m.value)
      + (m.badge ? '<span class="badge">' + esc(m.badge) + '</span>' : '') + '</div>';
  return '<div class="card metric ' + esc(m.tone || '') + '">'
    + '<div class="metric-top"><div class="k">' + esc(m.label) + '</div>'
    + '<div class="metric-icon" aria-hidden="true">'
    + esc(icons[m.label] || '•') + '</div></div>' + val
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

say.addEventListener('keydown', ev => {
  if(ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing){
    ev.preventDefault();
    form.requestSubmit();
  }
});

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
