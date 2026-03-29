# src/server/api/routes/preview_template.py
"""HTML template for the data preview workbench."""

PREVIEW_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock MCP - Data Preview Workbench</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--sidebar:#161b22;--card:#21262d;--border:#30363d;
  --text:#e6edf3;--text2:#8b949e;--accent:#58a6ff;--success:#3fb950;
  --error:#f85149;--warn:#d29922;--highlight:#1f6feb;
}
html,body{height:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
a{color:var(--accent);text-decoration:none}

/* Layout */
.app{display:flex;flex-direction:column;height:100vh}
.header{display:flex;align-items:center;justify-content:space-between;padding:10px 20px;border-bottom:1px solid var(--border);background:var(--sidebar)}
.header h1{font-size:16px;font-weight:600}
.header .meta-btn{font-size:12px;color:var(--text2);cursor:pointer;background:none;border:1px solid var(--border);padding:4px 10px;border-radius:4px}
.header .meta-btn:hover{border-color:var(--accent);color:var(--accent)}
.body-wrap{display:flex;flex:1;overflow:hidden}

/* Sidebar */
.sidebar{width:260px;min-width:260px;background:var(--sidebar);border-right:1px solid var(--border);overflow-y:auto;padding:8px 0}
.sidebar::-webkit-scrollbar{width:6px}
.sidebar::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.cat-group{margin-bottom:2px}
.cat-header{display:flex;align-items:center;padding:8px 14px;cursor:pointer;font-size:13px;font-weight:600;color:var(--text2);user-select:none}
.cat-header:hover{background:var(--card);color:var(--text)}
.cat-header .arrow{margin-right:6px;font-size:10px;transition:transform .15s}
.cat-header.open .arrow{transform:rotate(90deg)}
.cat-methods{display:none;padding:0}
.cat-header.open+.cat-methods{display:block}
.method-item{padding:5px 14px 5px 28px;font-size:12px;font-family:Consolas,'Courier New',monospace;color:var(--text2);cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.method-item:hover{background:var(--highlight);color:var(--text)}
.method-item.active{background:var(--highlight);color:var(--accent)}
.method-item .type-badge{font-size:10px;padding:1px 4px;border-radius:3px;margin-left:4px;background:var(--card);color:var(--warn)}

/* Main */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.params-panel{padding:16px 20px;border-bottom:1px solid var(--border);background:var(--bg)}
.params-panel .method-title{font-size:15px;font-weight:600;margin-bottom:10px;font-family:Consolas,'Courier New',monospace}
.params-panel .method-title .type-tag{font-size:11px;font-weight:400;color:var(--warn);margin-left:8px}
.param-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.param-row label{font-size:12px;color:var(--text2);min-width:60px}
.param-row input{background:var(--card);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:4px;font-size:13px;font-family:Consolas,'Courier New',monospace;min-width:200px}
.param-row input:focus{outline:none;border-color:var(--accent)}
.sources-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.sources-row label{font-size:12px;color:var(--text2);min-width:60px}
.source-check{display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text2);cursor:pointer}
.source-check input{accent-color:var(--accent)}
.exec-btn{background:var(--accent);color:#fff;border:none;padding:8px 20px;border-radius:4px;font-size:13px;cursor:pointer;font-weight:600}
.exec-btn:hover{opacity:.85}
.exec-btn:disabled{opacity:.4;cursor:not-allowed}
.loading{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;margin-left:8px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}

/* Results */
.results-panel{flex:1;overflow-y:auto;padding:16px 20px}
.results-panel::-webkit-scrollbar{width:6px}
.results-panel::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.tabs{display:flex;gap:0;margin-bottom:12px;border-bottom:1px solid var(--border)}
.tab{padding:6px 14px;font-size:12px;cursor:pointer;color:var(--text2);border-bottom:2px solid transparent}
.tab:hover{color:var(--text)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.source-card{background:var(--card);border:1px solid var(--border);border-radius:6px;margin-bottom:10px;overflow:hidden}
.source-header{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;cursor:pointer;font-size:12px;font-weight:600;user-select:none}
.source-header:hover{background:rgba(255,255,255,.03)}
.source-header .name{color:var(--accent)}
.source-header .ms{color:var(--text2);font-family:Consolas,'Courier New',monospace}
.source-header .ms.ok{color:var(--success)}
.source-header .ms.err{color:var(--error)}
.source-header .arrow{font-size:10px;transition:transform .15s}
.source-header.open .arrow{transform:rotate(90deg)}
.source-body{display:none;padding:10px 12px;font-family:Consolas,'Courier New',monospace;font-size:12px;white-space:pre-wrap;word-break:break-word;line-height:1.5;max-height:500px;overflow-y:auto}
.source-body::-webkit-scrollbar{width:4px}
.source-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.source-header.open+.source-body{display:block}

/* JSON syntax */
.jk{color:#79c0ff}.js{color:#a5d6ff}.jn{color:#79c0ff}.jb{color:#ffa657}.jl{color:#8b949e}

/* Table */
.result-table{width:100%;border-collapse:collapse;font-size:12px}
.result-table th{background:var(--sidebar);color:var(--text2);text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);position:sticky;top:0}
.result-table td{padding:5px 10px;border-bottom:1px solid var(--border);color:var(--text)}
.result-table tr:hover td{background:rgba(255,255,255,.03)}

/* Error */
.error-banner{background:rgba(248,81,73,.1);border:1px solid var(--error);border-radius:4px;padding:8px 12px;color:var(--error);font-size:12px;margin-bottom:10px}
.warn-banner{background:rgba(210,153,34,.1);border:1px solid var(--warn);border-radius:4px;padding:8px 12px;color:var(--warn);font-size:12px;margin-bottom:10px}

/* Empty */
.empty{color:var(--text2);font-size:13px;text-align:center;padding:40px}

/* Responsive */
@media(max-width:768px){
  .sidebar{display:none}
  .body-wrap.sidebar-open .sidebar{display:block;position:absolute;z-index:10;height:calc(100vh - 44px)}
  .menu-btn{display:inline-block !important}
}
.menu-btn{display:none;background:none;border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;cursor:pointer;font-size:16px}
</style>
</head>
<body>
<div class="app">
  <div class="header">
    <div style="display:flex;align-items:center;gap:10px">
      <button class="menu-btn" onclick="toggleSidebar()">&#9776;</button>
      <h1>Stock MCP Data Preview</h1>
    </div>
    <button class="meta-btn" onclick="showMeta()">Service Info</button>
  </div>
  <div class="body-wrap" id="bodyWrap">
    <div class="sidebar" id="sidebar"></div>
    <div class="main">
      <div class="params-panel" id="paramsPanel">
        <div class="empty">Select a method from the sidebar</div>
      </div>
      <div class="results-panel" id="resultsPanel">
        <div class="empty">Execute a query to see results</div>
      </div>
    </div>
  </div>
</div>

<script>
let catalogData = null;
let currentMethod = null;
let currentTab = 'json';
let lastResults = null;

// --- Init ---
(async function init() {
  try {
    const r = await fetch('/api/v1/preview/catalog');
    catalogData = await r.json();
    renderSidebar(catalogData);
  } catch(e) {
    document.getElementById('sidebar').innerHTML =
      '<div style="padding:12px;color:var(--error)">Failed to load catalog: '+esc(e.message)+'</div>';
  }
})();

function esc(s) {
  if (typeof s !== 'string') return String(s);
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// --- Sidebar ---
function renderSidebar(data) {
  const sb = document.getElementById('sidebar');
  let html = '';
  for (const cat of data.categories || []) {
    const catId = 'cat_' + cat.name.replace(/\s+/g,'_');
    html += '<div class="cat-group">';
    html += '<div class="cat-header open" onclick="toggleCat(this)"><span class="arrow">&#9654;</span>' +
            esc(cat.name) + ' <span style="color:var(--text2);font-weight:400">(' + cat.methods.length + ')</span></div>';
    html += '<div class="cat-methods">';
    for (const m of cat.methods) {
      html += '<div class="method-item" data-method="'+esc(m.name)+'" data-type="'+esc(m.type)+'" data-sources=\''+
              esc(JSON.stringify(m.sources))+'\' onclick="selectMethod(this)">'+
              esc(m.name) + '<span class="type-badge">' + esc(m.type) + '</span></div>';
    }
    html += '</div></div>';
  }
  sb.innerHTML = html;
}

function toggleCat(el) {
  el.classList.toggle('open');
}

function toggleSidebar() {
  document.getElementById('bodyWrap').classList.toggle('sidebar-open');
}

// --- Method selection ---
function selectMethod(el) {
  document.querySelectorAll('.method-item.active').forEach(e => e.classList.remove('active'));
  el.classList.add('active');
  const name = el.dataset.method;
  const type = el.dataset.type;
  const sources = JSON.parse(el.dataset.sources || '[]');
  currentMethod = { name, type, sources };
  renderParams(name, type, sources);
}

function renderParams(name, type, sources) {
  const p = document.getElementById('paramsPanel');
  let html = '<div class="method-title">' + esc(name) +
             '<span class="type-tag">' + esc(type) + '</span></div>';

  // Symbol input for ticker methods
  if (type === 'ticker') {
    html += '<div class="param-row"><label>symbol</label>' +
            '<input id="p_symbol" placeholder="e.g. SSE:600519 or AAPL" value="SSE:600519"></div>';
  }

  // Common params
  html += '<div class="param-row"><label>extra params</label>' +
          '<input id="p_extra" placeholder="key1=val1,key2=val2 (optional)"></div>';

  // Sources
  html += '<div class="sources-row"><label>sources</label>';
  html += '<label class="source-check"><input type="checkbox" value="auto" checked>auto</label>';
  for (const s of sources) {
    html += '<label class="source-check"><input type="checkbox" value="'+esc(s)+'" checked>'+esc(s)+'</label>';
  }
  html += '</div>';

  html += '<button class="exec-btn" id="execBtn" onclick="execute()">Execute</button>';
  html += '<span id="execSpinner" style="display:none" class="loading"></span>';
  p.innerHTML = html;
}

// --- Execute ---
async function execute() {
  if (!currentMethod) return;
  const btn = document.getElementById('execBtn');
  const spinner = document.getElementById('execSpinner');
  btn.disabled = true;
  spinner.style.display = 'inline-block';

  const params = {};
  if (currentMethod.type === 'ticker') {
    const sym = document.getElementById('p_symbol').value.trim();
    if (!sym) { alert('Symbol required for ticker methods'); btn.disabled=false; spinner.style.display='none'; return; }
    params.symbol = sym;
  }
  // Parse extra params
  const extra = (document.getElementById('p_extra').value || '').trim();
  if (extra) {
    for (const pair of extra.split(',')) {
      const [k,v] = pair.split('=').map(s => s.trim());
      if (k && v) {
        const num = Number(v);
        params[k] = isNaN(num) || v.includes('.') === false && v.length > 10 ? v : num;
      }
    }
  }

  // Get checked sources
  const sources = [];
  document.querySelectorAll('.sources-row input:checked').forEach(cb => sources.push(cb.value));
  if (sources.length === 0) sources.push('auto');

  try {
    const r = await fetch('/api/v1/preview/query', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ method: currentMethod.name, params, sources })
    });
    lastResults = await r.json();
    renderResults(lastResults);
  } catch(e) {
    document.getElementById('resultsPanel').innerHTML =
      '<div class="error-banner">Request failed: ' + esc(e.message) + '</div>';
  } finally {
    btn.disabled = false;
    spinner.style.display = 'none';
  }
}

// --- Results ---
function renderResults(data) {
  const rp = document.getElementById('resultsPanel');
  const results = data.results || {};

  // Check for diffs
  const keys = Object.keys(results);
  let hasDiff = false;
  if (keys.length > 1) {
    const sizes = keys.map(k => JSON.stringify(results[k].data).length);
    if (Math.max(...sizes) - Math.min(...sizes) > 100) hasDiff = true;
  }

  let html = '';

  // Tabs
  html += '<div class="tabs">';
  html += '<div class="tab '+(currentTab==='json'?'active':'')+'" onclick="switchTab(\'json\')">JSON</div>';
  html += '<div class="tab '+(currentTab==='table'?'active':'')+'" onclick="switchTab(\'table\')">Table</div>';
  html += '</div>';

  if (hasDiff) {
    html += '<div class="warn-banner">Sources returned different data sizes - possible discrepancy</div>';
  }

  for (const sourceName of keys) {
    const r = results[sourceName];
    const isError = !!r.error;
    const ms = r.elapsed_ms || 0;
    const cls = isError ? 'err' : 'ok';

    html += '<div class="source-card">';
    html += '<div class="source-header open" onclick="toggleSource(this)">' +
            '<span><span class="name">'+esc(sourceName)+'</span> '+
            (isError ? '<span style="color:var(--error)">ERROR</span>' : '')+'</span>' +
            '<span><span class="ms '+cls+'">'+ms+'ms</span> <span class="arrow">&#9660;</span></span></div>';

    if (isError) {
      html += '<div class="source-body" style="color:var(--error)">'+esc(r.error)+'</div>';
    } else if (currentTab === 'json') {
      html += '<div class="source-body">'+syntaxHighlight(JSON.stringify(r.data, null, 2))+'</div>';
    } else if (currentTab === 'table') {
      html += '<div class="source-body" style="white-space:normal">'+renderTable(r.data)+'</div>';
    }
    html += '</div>';
  }

  rp.innerHTML = html;
}

function switchTab(tab) {
  currentTab = tab;
  if (lastResults) renderResults(lastResults);
}

function toggleSource(el) {
  el.classList.toggle('open');
}

// --- JSON Syntax Highlight ---
function syntaxHighlight(json) {
  if (!json) return '';
  json = esc(json);
  return json.replace(/"([^"]+)"(?=\s*:)/g, '<span class="jk">"$1"</span>')
             .replace(/"([^"]*)"/g, '<span class="js">"$1"</span>')
             .replace(/\b(-?\d+\.?\d*([eE][+-]?\d+)?)\b/g, '<span class="jn">$1</span>')
             .replace(/\b(true|false|null)\b/g, '<span class="jb">$1</span>');
}

// --- Table ---
function renderTable(data) {
  if (!data) return '<span style="color:var(--text2)">No data</span>';
  let rows;
  if (Array.isArray(data)) {
    rows = data;
  } else if (data && typeof data === 'object') {
    // Try to find the first array field
    for (const key of Object.keys(data)) {
      if (Array.isArray(data[key]) && data[key].length > 0 && typeof data[key][0] === 'object') {
        rows = data[key];
        break;
      }
    }
    if (!rows) {
      // Show as key-value
      rows = Object.entries(data).map(([k,v]) => ({key:k, value: typeof v === 'object' ? JSON.stringify(v) : String(v)}));
    }
  }
  if (!rows || rows.length === 0) return '<span style="color:var(--text2)">No tabular data found</span>';

  const cols = Object.keys(rows[0]);
  const maxRows = 100;
  const limited = rows.slice(0, maxRows);
  let html = '<table class="result-table"><thead><tr>';
  for (const c of cols) html += '<th>'+esc(c)+'</th>';
  html += '</tr></thead><tbody>';
  for (const row of limited) {
    html += '<tr>';
    for (const c of cols) {
      const v = row[c];
      html += '<td>'+esc(v === null || v === undefined ? '-' : (typeof v === 'object' ? JSON.stringify(v) : String(v)))+'</td>';
    }
    html += '</tr>';
  }
  html += '</tbody></table>';
  if (rows.length > maxRows) {
    html += '<div style="color:var(--text2);font-size:11px;margin-top:4px">Showing '+maxRows+' of '+rows.length+' rows</div>';
  }
  return html;
}

// --- Meta ---
async function showMeta() {
  try {
    const r = await fetch('/api/meta');
    const data = await r.json();
    lastResults = { method: '/api/meta', results: { meta: { data, source: 'meta', elapsed_ms: 0, error: null } } };
    currentTab = 'json';
    renderResults(lastResults);
  } catch(e) {
    alert('Failed: ' + e.message);
  }
}

// --- Keyboard shortcut ---
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 'Enter') execute();
});
</script>
</body>
</html>
'''
