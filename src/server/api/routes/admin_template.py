# src/server/api/routes/admin_template.py
"""HTML template for the structured data approval workbench."""

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock MCP - Approval Workbench</title>
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
.header a{font-size:12px;color:var(--text2);border:1px solid var(--border);padding:4px 10px;border-radius:4px}
.header a:hover{border-color:var(--accent);color:var(--accent)}
.body-wrap{display:flex;flex:1;overflow:hidden}

/* Sidebar */
.sidebar{width:280px;min-width:280px;background:var(--sidebar);border-right:1px solid var(--border);overflow-y:auto;display:flex;flex-direction:column}
.sidebar-header{padding:12px 14px;font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid var(--border)}
.ds-group{border-bottom:1px solid var(--border)}
.ds-group-title{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;font-size:12px;font-weight:600;color:var(--text2);cursor:pointer;user-select:none}
.ds-group-title:hover{background:var(--card);color:var(--text)}
.badge{background:var(--warn);color:#000;font-size:10px;font-weight:700;padding:1px 6px;border-radius:10px;min-width:20px;text-align:center}
.task-list{display:none}
.ds-group.open .task-list{display:block}
.task-item{padding:7px 14px 7px 22px;font-size:12px;font-family:Consolas,'Courier New',monospace;color:var(--text2);cursor:pointer;border-left:2px solid transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.task-item:hover{background:var(--highlight);color:var(--text);border-left-color:var(--accent)}
.task-item.active{background:var(--highlight);color:var(--accent);border-left-color:var(--accent)}
.task-item .task-bkey{font-size:11px;color:var(--text2);margin-top:2px;overflow:hidden;text-overflow:ellipsis}
.sidebar-empty{padding:20px 14px;font-size:12px;color:var(--text2);text-align:center}

/* Stats bar */
.stats-bar{padding:8px 14px;border-top:1px solid var(--border);background:var(--card);font-size:11px;color:var(--text2)}
.stats-bar .stat{display:inline-block;margin-right:16px}
.stats-bar .stat-val{color:var(--accent);font-weight:600}

/* Main panel */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.main-empty{display:flex;align-items:center;justify-content:center;flex:1;color:var(--text2);font-size:14px}

/* Detail panel */
.detail{flex:1;overflow-y:auto;padding:16px 20px;display:none}
.detail.visible{display:block}
.section{margin-bottom:20px}
.section-title{font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.section-title .count{background:var(--card);color:var(--text2);font-size:10px;padding:1px 5px;border-radius:8px}

/* Task meta */
.task-meta{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px 16px;font-size:12px}
.meta-row{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:4px}
.meta-row span{color:var(--text2)}
.meta-row strong{color:var(--text)}

/* JSON viewer */
.json-view{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;font-family:Consolas,'Courier New',monospace;font-size:12px;max-height:260px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;color:var(--success)}

/* Diff table */
.diff-table{width:100%;border-collapse:collapse;font-size:12px}
.diff-table th{background:var(--card);color:var(--text2);padding:6px 10px;text-align:left;border:1px solid var(--border);font-weight:600}
.diff-table td{padding:5px 10px;border:1px solid var(--border);font-family:Consolas,'Courier New',monospace;vertical-align:top}
.diff-table tr.changed td{background:#2d1b00}
.diff-table tr.changed td.new-val{color:var(--success)}
.diff-table tr.changed td.old-val{color:var(--error)}
.diff-table tr:not(.changed) td{color:var(--text2)}

/* Issues list */
.issue-item{background:var(--card);border:1px solid var(--border);border-radius:4px;padding:8px 12px;margin-bottom:6px;font-size:12px}
.issue-item .sev-error{color:var(--error)}
.issue-item .sev-warn{color:var(--warn)}
.issue-item .issue-field{font-family:Consolas,'Courier New',monospace;color:var(--accent)}

/* Action timeline */
.timeline{position:relative;padding-left:16px;border-left:2px solid var(--border)}
.tl-item{position:relative;margin-bottom:10px;font-size:12px}
.tl-dot{position:absolute;left:-21px;top:4px;width:8px;height:8px;border-radius:50%;background:var(--border);border:2px solid var(--bg)}
.tl-item.APPROVE .tl-dot{background:var(--success)}
.tl-item.REJECT .tl-dot{background:var(--error)}
.tl-item.OVERRIDE_PUBLISH .tl-dot{background:var(--warn)}
.tl-item.COMMENT .tl-dot{background:var(--accent)}
.tl-header{color:var(--text2);margin-bottom:2px}
.tl-header strong{color:var(--text)}
.tl-comment{background:var(--card);border-radius:4px;padding:5px 8px;color:var(--text2);font-style:italic}

/* Action buttons */
.action-bar{padding:12px 20px;border-top:1px solid var(--border);background:var(--sidebar);display:none;gap:8px;flex-wrap:wrap;align-items:center}
.action-bar.visible{display:flex}
.btn{padding:7px 16px;border-radius:4px;font-size:13px;font-weight:600;cursor:pointer;border:none}
.btn-approve{background:var(--success);color:#000}
.btn-approve:hover{opacity:.85}
.btn-reject{background:var(--error);color:#fff}
.btn-reject:hover{opacity:.85}
.btn-override{background:var(--warn);color:#000}
.btn-override:hover{opacity:.85}
.btn:disabled{opacity:.4;cursor:not-allowed}
.reviewer-input{background:var(--card);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:4px;font-size:13px;font-family:inherit;min-width:140px}
.comment-input{background:var(--card);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:4px;font-size:13px;font-family:inherit;flex:1;min-width:200px}
.reviewer-input:focus,.comment-input:focus{outline:none;border-color:var(--accent)}
.label{font-size:12px;color:var(--text2)}

/* Toast */
.toast{position:fixed;bottom:20px;right:20px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px 16px;font-size:13px;z-index:999;display:none}
.toast.show{display:block}
.toast.success{border-color:var(--success);color:var(--success)}
.toast.error{border-color:var(--error);color:var(--error)}

/* Loading spinner */
.spinner{display:inline-block;width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;margin-left:6px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="app">
  <div class="header">
    <h1>⚙️ Structured Data Approval Workbench</h1>
    <a href="/docs#/结构化数据 Structured Data">API Docs</a>
  </div>
  <div class="body-wrap">
    <!-- Left sidebar -->
    <div class="sidebar">
      <div class="sidebar-header">待审批任务 <span id="total-badge" class="badge" style="background:var(--accent);color:#000">…</span></div>
      <div id="task-groups"></div>
      <div id="sidebar-empty" class="sidebar-empty" style="display:none">暂无待审批任务 ✅</div>
      <div class="stats-bar" id="stats-bar" style="display:none">
        <span class="stat">待审批 <span class="stat-val" id="stat-pending">—</span></span>
      </div>
    </div>

    <!-- Main content -->
    <div class="main">
      <div class="main-empty" id="main-empty">← 从左侧选择一个审批任务</div>

      <div class="detail" id="detail-panel">
        <!-- Task meta -->
        <div class="section">
          <div class="section-title">任务信息</div>
          <div class="task-meta" id="task-meta"></div>
        </div>

        <!-- Candidate data -->
        <div class="section">
          <div class="section-title">候选数据 (Candidate)</div>
          <div class="json-view" id="candidate-json">—</div>
        </div>

        <!-- Field diff -->
        <div class="section">
          <div class="section-title">字段差异 <span class="count" id="diff-count">0</span></div>
          <table class="diff-table">
            <thead><tr><th>字段</th><th class="old-val">当前 Canonical</th><th class="new-val">候选值</th></tr></thead>
            <tbody id="diff-body"></tbody>
          </table>
        </div>

        <!-- Validation issues -->
        <div class="section">
          <div class="section-title">校验问题 <span class="count" id="issues-count">0</span></div>
          <div id="issues-list"></div>
        </div>

        <!-- Action history -->
        <div class="section">
          <div class="section-title">操作历史 <span class="count" id="actions-count">0</span></div>
          <div class="timeline" id="actions-timeline"></div>
        </div>
      </div>

      <!-- Action bar -->
      <div class="action-bar" id="action-bar">
        <span class="label">审批人</span>
        <input class="reviewer-input" id="reviewer-input" value="admin" placeholder="Reviewer">
        <input class="comment-input" id="comment-input" placeholder="备注（可选）">
        <button class="btn btn-approve" id="btn-approve" onclick="doAction('approve')">✅ Approve</button>
        <button class="btn btn-reject" id="btn-reject" onclick="doAction('reject')">❌ Reject</button>
        <button class="btn btn-override" id="btn-override" onclick="doAction('override')">⚡ Override Publish</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const BASE = '/api/v1/structured-data';
let currentTaskId = null;
let currentTaskResolved = false;

// ---- Init ----
(async () => {
  await loadSidebar();
  await loadStats();
})();

async function loadSidebar() {
  const res = await fetch(`${BASE}/approval/pending?limit=200`);
  const json = await res.json();
  const tasks = json.data || [];
  document.getElementById('total-badge').textContent = tasks.length;

  if (!tasks.length) {
    document.getElementById('sidebar-empty').style.display = 'block';
    return;
  }

  // Group by dataset_key
  const groups = {};
  for (const t of tasks) {
    const dk = t.dataset_key || 'unknown';
    if (!groups[dk]) groups[dk] = [];
    groups[dk].push(t);
  }

  const container = document.getElementById('task-groups');
  container.innerHTML = '';
  for (const [dk, items] of Object.entries(groups)) {
    const grp = document.createElement('div');
    grp.className = 'ds-group open';
    grp.innerHTML = `
      <div class="ds-group-title" onclick="this.parentElement.classList.toggle('open')">
        <span>${dk}</span><span class="badge">${items.length}</span>
      </div>
      <div class="task-list">
        ${items.map(t => `
          <div class="task-item" id="task-${t.task_id}" onclick="selectTask('${t.task_id}', ${t.is_resolved || false})">
            <div>${t.task_id.slice(0,8)}…</div>
            <div class="task-bkey">${t.business_key || ''}</div>
          </div>`).join('')}
      </div>`;
    container.appendChild(grp);
  }
}

async function loadStats() {
  try {
    const res = await fetch(`${BASE}/stats`);
    const json = await res.json();
    const d = json.data || {};
    document.getElementById('stat-pending').textContent = d.pending_count ?? '—';
    document.getElementById('stats-bar').style.display = 'block';
  } catch (_) {}
}

async function selectTask(taskId, isResolved) {
  // Deactivate previous
  document.querySelectorAll('.task-item.active').forEach(el => el.classList.remove('active'));
  const el = document.getElementById('task-' + taskId);
  if (el) el.classList.add('active');

  currentTaskId = taskId;
  currentTaskResolved = isResolved;

  document.getElementById('main-empty').style.display = 'none';
  document.getElementById('detail-panel').className = 'detail visible';

  // Load detail
  const res = await fetch(`${BASE}/approval/${taskId}`);
  const json = await res.json();
  const detail = json.data || {};
  renderDetail(detail);

  // Show/hide action bar
  const bar = document.getElementById('action-bar');
  if (!isResolved) bar.classList.add('visible');
  else bar.classList.remove('visible');
}

function renderDetail(d) {
  const task = d.task || {};
  const candidate = d.candidate || {};
  const canonicalCurrent = d.canonical_current;
  const diff = d.field_diff || [];
  const issues = d.validation_issues || [];
  const actions = d.actions || [];

  // Meta
  document.getElementById('task-meta').innerHTML = `
    <div class="meta-row">
      <span>Task ID: <strong>${task.task_id || '—'}</strong></span>
      <span>Dataset: <strong>${task.dataset_key || '—'}</strong></span>
      <span>Business Key: <strong>${task.business_key || '—'}</strong></span>
    </div>
    <div class="meta-row">
      <span>状态: <strong>${task.is_resolved ? '✅ Resolved' : '⏳ Pending'}</strong></span>
      <span>创建时间: <strong>${task.created_at || '—'}</strong></span>
      ${task.reason ? `<span>原因: <strong>${task.reason}</strong></span>` : ''}
    </div>`;

  // Candidate JSON
  const candData = candidate.normalized_data || candidate || {};
  document.getElementById('candidate-json').textContent = JSON.stringify(
    typeof candData === 'string' ? JSON.parse(candData) : candData, null, 2
  );

  // Field diff
  const changedOnly = diff.filter(r => r.changed);
  const allRows = diff;
  document.getElementById('diff-count').textContent = changedOnly.length + ' changed / ' + allRows.length;
  document.getElementById('diff-body').innerHTML = allRows.map(r => `
    <tr class="${r.changed ? 'changed' : ''}">
      <td>${r.field}</td>
      <td class="old-val">${fmtVal(r.old_value)}</td>
      <td class="new-val">${fmtVal(r.new_value)}</td>
    </tr>`).join('');

  // Issues
  document.getElementById('issues-count').textContent = issues.length;
  document.getElementById('issues-list').innerHTML = issues.length
    ? issues.map(i => `
        <div class="issue-item">
          <span class="sev-${(i.severity||'').toLowerCase()}">[${i.severity || 'INFO'}]</span>
          <span class="issue-field"> ${i.field_path || ''}</span>: ${i.message || ''}
        </div>`).join('')
    : '<div style="color:var(--success);font-size:12px">无校验问题 ✅</div>';

  // Actions timeline
  document.getElementById('actions-count').textContent = actions.length;
  document.getElementById('actions-timeline').innerHTML = actions.length
    ? actions.map(a => `
        <div class="tl-item ${a.action || ''}">
          <div class="tl-dot"></div>
          <div class="tl-header"><strong>${a.reviewer || '?'}</strong> · ${a.action || '?'} · <span>${a.created_at || ''}</span></div>
          ${a.comment ? `<div class="tl-comment">${a.comment}</div>` : ''}
        </div>`).join('')
    : '<div style="color:var(--text2);font-size:12px">暂无操作记录</div>';
}

function fmtVal(v) {
  if (v === null || v === undefined) return '<em style="color:var(--text2)">null</em>';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

async function doAction(type) {
  if (!currentTaskId) return;
  const reviewer = document.getElementById('reviewer-input').value.trim() || 'admin';
  const comment = document.getElementById('comment-input').value.trim() || null;

  const btns = document.querySelectorAll('.action-bar .btn');
  btns.forEach(b => b.disabled = true);

  try {
    let url, method;
    if (type === 'approve') {
      url = `${BASE}/approval/${currentTaskId}/approve?reviewer=${encodeURIComponent(reviewer)}${comment ? '&comment='+encodeURIComponent(comment) : ''}`;
      method = 'POST';
    } else if (type === 'reject') {
      url = `${BASE}/approval/${currentTaskId}/reject?reviewer=${encodeURIComponent(reviewer)}${comment ? '&comment='+encodeURIComponent(comment) : ''}`;
      method = 'POST';
    } else {
      url = `${BASE}/approval/${currentTaskId}/override?reviewer=${encodeURIComponent(reviewer)}${comment ? '&comment='+encodeURIComponent(comment) : ''}`;
      method = 'POST';
    }

    const res = await fetch(url, { method });
    const json = await res.json();
    if (res.ok) {
      showToast('success', `操作成功: ${type}`);
      // Remove from sidebar and reload
      const el = document.getElementById('task-' + currentTaskId);
      if (el) el.remove();
      currentTaskId = null;
      document.getElementById('detail-panel').className = 'detail';
      document.getElementById('action-bar').classList.remove('visible');
      document.getElementById('main-empty').style.display = '';
      await loadStats();
    } else {
      showToast('error', json.detail || '操作失败');
      btns.forEach(b => b.disabled = false);
    }
  } catch (e) {
    showToast('error', e.message);
    btns.forEach(b => b.disabled = false);
  }
}

function showToast(type, msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = 'toast'; }, 3000);
}
</script>
</body>
</html>
"""
