"""Settings page HTML generator — imported by oak_bridge.py."""

CATEGORY_ORDER = [
    ("People",      "people",      "#4ade80"),
    ("Animals",     "animals",     "#fb923c"),
    ("Vehicles",    "vehicles",    "#60a5fa"),
    ("Food",        "food",        "#34d399"),
    ("Kitchen",     "kitchen",     "#a78bfa"),
    ("Furniture",   "furniture",   "#f472b6"),
    ("Electronics", "electronics", "#facc15"),
    ("Sports",      "sports",      "#e879f9"),
    ("Accessories", "accessories", "#2dd4bf"),
    ("Outdoor",     "outdoor",     "#f87171"),
]

CATEGORY_CLASSES = {
    "people":      ["person"],
    "animals":     ["bird","cat","dog","horse","sheep","cow","elephant","bear","zebra","giraffe"],
    "vehicles":    ["bicycle","car","motorcycle","airplane","bus","train","truck","boat"],
    "food":        ["banana","apple","sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake"],
    "kitchen":     ["bottle","wine glass","cup","fork","knife","spoon","bowl","microwave","oven","toaster","sink","refrigerator"],
    "furniture":   ["chair","couch","potted plant","bed","dining table","toilet","clock","vase","scissors","teddy bear"],
    "electronics": ["tv","laptop","mouse","remote","keyboard","cell phone"],
    "sports":      ["frisbee","skis","snowboard","sports ball","kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket"],
    "accessories": ["backpack","umbrella","handbag","tie","suitcase","book","hair drier","toothbrush"],
    "outdoor":     ["traffic light","fire hydrant","stop sign","parking meter","bench"],
}

def build_settings_html():
    sections_html = ""
    for (display_name, cat_key, accent) in CATEGORY_ORDER:
        classes = CATEGORY_CLASSES[cat_key]
        rows = ""
        for cls in sorted(classes):
            safe_id = cls.replace(" ", "_")
            rows += f"""
              <div class="obj-row" data-class="{cls}">
                <span class="obj-name">{cls.title()}</span>
                <div class="obj-controls">
                  <span class="conf-label">Confidence</span>
                  <input type="number" class="conf-input" id="conf_{safe_id}"
                         data-class="{cls}" min="0.01" max="1.0" step="0.01" value="0.50">
                  <button class="toggle-btn enabled" id="tog_{safe_id}"
                          data-class="{cls}" onclick="toggleObject(this)">ON</button>
                </div>
              </div>"""
        sections_html += f"""
          <section class="category" data-cat="{cat_key}">
            <div class="cat-header" style="--accent:{accent}">
              <h2>{display_name}</h2>
              <div class="cat-actions">
                <button class="cat-all-btn" onclick="setCatAll('{cat_key}',true)">All On</button>
                <button class="cat-all-btn" onclick="setCatAll('{cat_key}',false)">All Off</button>
              </div>
            </div>
            <div class="obj-list">{rows}</div>
          </section>"""

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OAK Camera</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0f1117;--surface:#171b26;--border:#2a2f3d;--text:#e2e8f0;--muted:#64748b;--on:#22c55e;--off:#475569;--inp:#1e2330}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'IBM Plex Sans',sans-serif;font-size:14px}
.topbar{position:sticky;top:0;z-index:100;background:var(--surface);border-bottom:1px solid var(--border);padding:8px 16px;display:flex;align-items:center;justify-content:space-between}
.topbar h1{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;letter-spacing:.05em}
.topbar-actions{display:flex;gap:6px;align-items:center}
.btn{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;border:none;border-radius:4px;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.8}
.btn-save{background:#3b82f6;color:#fff;padding:6px 16px}
.btn-reset{background:transparent;border:1px solid var(--border);color:var(--muted);padding:6px 10px}.btn-download{background:transparent;border:1px solid var(--border);color:var(--muted);padding:6px 10px}
.btn-reload{background:var(--border);color:var(--muted);padding:6px 10px}
#status{display:none;padding:7px 16px;font-family:'IBM Plex Mono',monospace;font-size:11px;border-bottom:1px solid var(--border)}
#status.ok{background:#052e16;color:#4ade80}
#status.err{background:#2d0a0a;color:#f87171}

/* ── Live feed ─────────────────────── */
.feed-section{background:#000;position:relative;width:100%;aspect-ratio:16/9;overflow:hidden}
.feed-section img{width:100%;height:100%;object-fit:contain;display:block}
.feed-offline{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--muted);font-family:'IBM Plex Mono',monospace;font-size:12px}
.feed-dot{width:8px;height:8px;border-radius:50%;background:var(--on);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* ── Settings toggle ───────────────── */
.settings-toggle{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:var(--surface);border-bottom:1px solid var(--border);cursor:pointer;user-select:none}
.settings-toggle:hover{background:#1e2330}
.toggle-label{font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;letter-spacing:.05em;color:var(--text)}
.toggle-arrow{font-size:14px;color:var(--muted);transition:transform .2s}
.toggle-arrow.open{transform:rotate(180deg)}

/* ── Settings panel ────────────────── */
.settings-panel{display:none}
.settings-panel.open{display:block}
.content{max-width:860px;margin:0 auto;padding:12px 16px 60px;display:flex;flex-direction:column;gap:7px}
.global-row{display:flex;gap:6px;justify-content:flex-end;padding-bottom:2px}
.global-btn{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;background:var(--surface);border:1px solid var(--border);color:var(--muted);padding:4px 10px;border-radius:4px;cursor:pointer;transition:all .15s}
.global-btn:hover{border-color:var(--text);color:var(--text)}
.category{background:var(--surface);border:1px solid var(--border);border-radius:5px;overflow:hidden}
.cat-header{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;border-bottom:2px solid var(--accent,#4ade80);background:color-mix(in srgb,var(--accent,#4ade80) 8%,var(--surface))}
.cat-header h2{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--accent,#4ade80)}
.cat-actions{display:flex;gap:4px}
.cat-all-btn{font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;background:transparent;border:1px solid var(--border);color:var(--muted);padding:2px 6px;border-radius:3px;cursor:pointer;transition:all .15s}
.cat-all-btn:hover{border-color:var(--accent,#4ade80);color:var(--accent,#4ade80)}
.obj-list{display:flex;flex-direction:column}
.obj-row{display:flex;align-items:center;justify-content:space-between;padding:5px 12px;border-bottom:1px solid var(--border);transition:background .1s}
.obj-row:last-child{border-bottom:none}
.obj-row:hover{background:rgba(255,255,255,.02)}
.obj-row.disabled{opacity:.4}
.obj-name{font-size:12px;width:130px;flex-shrink:0}
.obj-controls{display:flex;align-items:center;gap:7px}
.conf-label{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
.conf-input{width:58px;background:var(--inp);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:12px;padding:2px 4px;text-align:center;transition:border-color .15s}
.conf-input:focus{outline:none;border-color:#3b82f6}
.toggle-btn{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;width:40px;padding:3px 0;border:none;border-radius:4px;cursor:pointer;transition:background .15s,color .15s}
.toggle-btn.enabled{background:var(--on);color:#052e16}
.toggle-btn.disabled{background:var(--off);color:#94a3b8}
</style>
</head>
<body>

<div class="topbar">
  <h1>&#x2b22; OAK Camera</h1>
  <div class="topbar-actions">
    <button class="btn btn-reload"   onclick="loadSettings()">&#x21ba; Reload</button>
    <button class="btn btn-reset"    onclick="resetSettings()">Reset defaults</button>
    <button class="btn btn-download" onclick="exportSettings()">&#x2913; Save to file</button>
    <button class="btn btn-save"     onclick="saveSettings()">Save &amp; Apply</button>
  </div>
</div>
<div id="status"></div>

<!-- Live feed — served directly on port 8767 to bypass ingress proxy buffering -->
<div class="feed-section">
  <img id="feed" alt="Live feed" onerror="showOffline()" onload="hideOffline()">
  <div class="feed-offline" id="offline">
    <div class="feed-dot"></div>
    <span>Connecting...</span>
  </div>
</div>

<!-- Settings toggle -->
<div class="settings-toggle" onclick="toggleSettings()" id="settingsToggle">
  <span class="toggle-label">&#9881; Detection Settings</span>
  <span class="toggle-arrow" id="toggleArrow">&#x25BE;</span>
</div>

<!-- Settings panel (collapsed by default) -->
<div class="settings-panel" id="settingsPanel">
  <div class="content">
    <!-- Set All Confidence + Hardware Threshold controls -->
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding-bottom:6px">
      <div style="display:flex;align-items:center;gap:7px">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap">Set all confidence</span>
        <input type="number" id="setAllVal" min="0.01" max="1.0" step="0.01" value="0.50"
               style="width:62px;background:var(--inp);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:12px;padding:3px 5px;text-align:center">
        <button class="global-btn" onclick="setAllConf()">Apply to all</button>
      </div>
      <div style="display:flex;align-items:center;gap:7px">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap">Hardware threshold</span>
        <input type="number" id="hwThreshold" min="0.01" max="1.0" step="0.01" value="0.10"
               style="width:62px;background:var(--inp);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:12px;padding:3px 5px;text-align:center">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--muted)">(camera-level floor)</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:7px;padding-bottom:2px">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap">Filename tag min duration (sec)</span>
      <input type="number" id="tagDuration" min="0" max="60" step="0.1" value="0"
             style="width:62px;background:var(--inp);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:12px;padding:3px 5px;text-align:center">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--muted)">(0 = tag all detected objects)</span>
    </div>
    <div class="global-row">
      <button class="global-btn" onclick="setAll(true)">Enable All</button>
      <button class="global-btn" onclick="setAll(false)">Disable All</button>
    </div>
""" + sections_html + """
  </div>
</div>

<script>
function showStatus(msg,ok){
  const s=document.getElementById('status');
  s.textContent=msg; s.className=ok?'ok':'err'; s.style.display='block';
  if(ok) setTimeout(()=>s.style.display='none',3000);
}
function showOffline(){document.getElementById('offline').style.display='flex'}
function hideOffline(){document.getElementById('offline').style.display='none'}

function toggleSettings(){
  const panel=document.getElementById('settingsPanel');
  const arrow=document.getElementById('toggleArrow');
  const isOpen=panel.classList.contains('open');
  panel.classList.toggle('open',!isOpen);
  arrow.classList.toggle('open',!isOpen);
}

function toggleObject(btn){
  const on=btn.classList.contains('enabled');
  btn.classList.toggle('enabled',!on); btn.classList.toggle('disabled',on);
  btn.textContent=on?'OFF':'ON';
  btn.closest('.obj-row').classList.toggle('disabled',on);
}
function setCatAll(cat,enable){
  document.querySelectorAll(`.category[data-cat="${cat}"] .toggle-btn`).forEach(btn=>{
    if(btn.classList.contains('enabled')!==enable) toggleObject(btn);
  });
}
function setAll(enable){
  document.querySelectorAll('.toggle-btn').forEach(btn=>{
    if(btn.classList.contains('enabled')!==enable) toggleObject(btn);
  });
}
function setAllConf(){
  const val=parseFloat(document.getElementById('setAllVal').value)||0.70;
  document.querySelectorAll('.conf-input').forEach(inp=>inp.value=val.toFixed(2));
  showStatus('All confidence levels set to '+val.toFixed(2)+' — click Save & Apply to apply.',true);
}
function gatherSettings(){
  const objects={};
  document.querySelectorAll('.obj-row').forEach(row=>{
    const cls=row.dataset.class;
    const btn=row.querySelector('.toggle-btn');
    const inp=row.querySelector('.conf-input');
    objects[cls]={enabled:btn.classList.contains('enabled'),confidence:parseFloat(inp.value)||0.7};
  });
  const hw=parseFloat(document.getElementById('hwThreshold').value)||0.10;
  const _tdRaw=document.getElementById('tagDuration').value;
  const td=(_tdRaw===''||_tdRaw===null)?0.0:parseFloat(_tdRaw);
  return {objects, hw_threshold: hw, tag_duration: td};
}
function applyToUI(data){
  const objs=data.objects||{};
  document.querySelectorAll('.obj-row').forEach(row=>{
    const cls=row.dataset.class; const cfg=objs[cls]; if(!cfg) return;
    const btn=row.querySelector('.toggle-btn'); const inp=row.querySelector('.conf-input');
    const en=cfg.enabled!==false;
    btn.classList.toggle('enabled',en); btn.classList.toggle('disabled',!en);
    btn.textContent=en?'ON':'OFF';
    row.classList.toggle('disabled',!en);
    if(cfg.confidence!==undefined) inp.value=parseFloat(cfg.confidence).toFixed(2);
  });
  if(data.hw_threshold!==undefined)
    document.getElementById('hwThreshold').value=parseFloat(data.hw_threshold).toFixed(2);
  if(data.tag_duration!==undefined)
    document.getElementById('tagDuration').value=parseFloat(data.tag_duration);
}
async function loadSettings(){
  try{
    const r=await fetch('api/settings'); if(!r.ok) throw new Error(await r.text());
    applyToUI(await r.json()); showStatus('Settings loaded.',true);
  }catch(e){ showStatus('Load failed: '+e.message,false); }
}
async function saveSettings(){
  try{
    let oldHw=0.10;
    try{ const cur=await fetch('api/settings'); if(cur.ok){ const d=await cur.json(); oldHw=parseFloat(d.hw_threshold||0.10); } }catch(e){}
    const payload=gatherSettings();
    const newHw=parseFloat(payload.hw_threshold||0.10);
    const r=await fetch('api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!r.ok) throw new Error(await r.text());
    if(Math.abs(oldHw-newHw)>0.001){
      showStatus('\u2713 Saved. Hardware threshold changed to '+newHw.toFixed(2)+'.',true);
      const msg=[
        'Hardware threshold changed from '+oldHw.toFixed(2)+' to '+newHw.toFixed(2)+'.',
        '',
        'The camera pipeline must restart for this to take effect.',
        '',
        'Restart the app now?'
      ].join(String.fromCharCode(10));
      if(confirm(msg)){
        await fetch('api/restart',{method:'POST'});
        showStatus('\u231b Restarting... page will reload in 12 seconds.',true);
        setTimeout(()=>window.location.reload(),12000);
      }
    } else {
      showStatus('\u2713 Saved and applied.',true);
    }
  }catch(e){ showStatus('Save failed: '+e.message,false); }
}
function exportSettings(){
  const data=gatherSettings();
  const lines=['OAK Camera Detection Settings','Generated: '+new Date().toLocaleString(),''];
  // Global settings
  lines.push('Hardware Threshold: '+data.hw_threshold);
  lines.push('Filename Tag Min Duration (sec): '+data.tag_duration);
  lines.push('');
  // Per-object settings, grouped by category
  const cats={
    People:['person'],
    Animals:['bear','bird','cat','cow','dog','elephant','giraffe','horse','sheep','zebra'],
    Vehicles:['airplane','bicycle','boat','bus','car','motorcycle','train','truck'],
    Food:['apple','banana','broccoli','cake','carrot','donut','hot dog','orange','pizza','sandwich'],
    Kitchen:['bottle','bowl','cup','fork','knife','microwave','oven','refrigerator','sink','spoon','toaster','wine glass'],
    Furniture:['bed','chair','clock','couch','dining table','potted plant','scissors','teddy bear','toilet','vase'],
    Electronics:['cell phone','keyboard','laptop','mouse','remote','tv'],
    Sports:['baseball bat','baseball glove','frisbee','kite','skateboard','skis','snowboard','sports ball','surfboard','tennis racket'],
    Accessories:['backpack','book','hair drier','handbag','suitcase','tie','toothbrush','umbrella'],
    Outdoor:['bench','fire hydrant','parking meter','stop sign','traffic light']
  };
  for(const [cat,clsList] of Object.entries(cats)){
    lines.push('['+cat+']');
    for(const cls of clsList){
      const cfg=data.objects[cls]||{enabled:false,confidence:0.50};
      lines.push('  '+cls+': '+(cfg.enabled?'ON':'OFF')+', confidence='+parseFloat(cfg.confidence).toFixed(2));
    }
    lines.push('');
  }
  const blob=new Blob([lines.join(String.fromCharCode(10))],{type:'text/plain'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='oak_detection_settings_'+new Date().toISOString().slice(0,10)+'.txt';
  a.click();
  URL.revokeObjectURL(a.href);
  showStatus('\u2713 Settings exported to file.',true);
}
async function resetSettings(){
  if(!confirm('Reset all to defaults (0.70 confidence)?')) return;
  try{
    const r=await fetch('api/settings',{method:'DELETE'});
    if(!r.ok) throw new Error(await r.text());
    await loadSettings();
    showStatus('\u2713 Reset to defaults.',true);
  }catch(e){ showStatus('Reset failed: '+e.message,false); }
}
// Point stream directly at port 8767, bypassing the ingress proxy
// which buffers multipart/x-mixed-replace and prevents live streaming
const streamUrl = window.location.protocol + '//' + window.location.hostname + ':8767/stream';
document.getElementById('feed').src = streamUrl;

loadSettings();
</script>
</body>
</html>"""