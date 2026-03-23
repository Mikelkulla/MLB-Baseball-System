/**
 * logs.js — Log viewer page logic
 * Loads /api/logs, renders colored log lines, handles filters + auto-refresh.
 */

let _currentFilter = 'DEBUG';   // minimum level to SHOW
let _autoInterval  = null;
let _lastEntries   = [];

// ── Boot ─────────────────────────────────────────────────────────────────────
(async function init() {
  await loadFiles();
  await loadCurrentLevel();
  await loadLogs();
  setFilter('DEBUG');
})();

// ── Load available log files ──────────────────────────────────────────────────
async function loadFiles() {
  try {
    const d = await API.get('/api/logs/files');
    const sel = document.getElementById('file-select');
    // Keep the first "Today's log" option
    while (sel.options.length > 1) sel.remove(1);
    (d.files || []).forEach(f => {
      if (f.name === 'mlb.log') return; // already represented by default
      const opt = document.createElement('option');
      opt.value = f.name;
      opt.textContent = `${f.name}  (${_fmtSize(f.size_bytes)})`;
      sel.appendChild(opt);
    });
  } catch (e) {}
}

// ── Load current runtime level ────────────────────────────────────────────────
async function loadCurrentLevel() {
  try {
    const d = await API.get('/api/logs/level');
    const sel = document.getElementById('runtime-level');
    if (sel) sel.value = d.level || 'INFO';
  } catch (e) {}
}

// ── Main log load ─────────────────────────────────────────────────────────────
async function loadLogs() {
  const lines  = document.getElementById('lines-select').value  || 500;
  const file   = document.getElementById('file-select').value   || '';
  const params = `?lines=${lines}&level=DEBUG&file=${encodeURIComponent(file)}`;

  try {
    const d = await API.get('/api/logs' + params);
    _lastEntries = d.entries || [];
    renderLogs(_lastEntries);
    document.getElementById('log-count-label').textContent =
      `${_lastEntries.length} entries`;
    document.getElementById('log-file-label').textContent =
      file ? `logs/${file}` : 'logs/mlb.log (active)';
  } catch (e) {
    document.getElementById('log-body').innerHTML =
      `<div class="log-empty">Error loading logs: ${e.message}</div>`;
  }
}

// ── Render log lines ──────────────────────────────────────────────────────────
function renderLogs(entries) {
  const body = document.getElementById('log-body');

  const levelOrder = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 };
  const minOrder   = levelOrder[_currentFilter] ?? 0;

  const filtered = entries.filter(e => (levelOrder[e.level] ?? 0) >= minOrder);

  if (!filtered.length) {
    body.innerHTML = `<div class="log-empty">No ${_currentFilter}+ entries in this range.</div>`;
    return;
  }

  const html = filtered.map(e => {
    const lvlClass = 'lvl-' + (e.level || 'debug').toLowerCase();
    const ts   = _esc(e.timestamp || '');
    const lvl  = _esc((e.level || '').padEnd(8));
    const name = _esc((e.logger  || '').slice(0, 28));
    const msg  = _esc(e.message  || e.raw || '');
    return `<div class="log-line ${lvlClass}">` +
      `<span class="log-ts">${ts}&nbsp;&nbsp;</span>` +
      `<span class="log-lvl">[${lvl}]&nbsp;</span>` +
      `<span class="log-name">${name}:&nbsp;</span>` +
      `<span class="log-msg">${msg}</span>` +
      `</div>`;
  }).join('');

  body.innerHTML = html;

  // Scroll to bottom
  body.scrollTop = body.scrollHeight;

  document.getElementById('log-count-label').textContent =
    `${filtered.length} / ${entries.length} entries`;
}

// ── Level filter (display only) ───────────────────────────────────────────────
function setFilter(level) {
  _currentFilter = level;

  // Update button active states
  document.querySelectorAll('.level-btn').forEach(btn => {
    const f = btn.dataset.filter;
    btn.className = 'level-btn';
    if (f === level) {
      btn.classList.add('active-' + level.toLowerCase());
    }
  });

  renderLogs(_lastEntries);
}

// ── Runtime level (what gets written to file) ─────────────────────────────────
async function setRuntimeLevel(level) {
  try {
    await API.post('/api/logs/level', { level });
    toast(`Log write level set to ${level}`, 'success');
  } catch (e) {
    toast('Failed to set level: ' + e.message, 'error');
  }
}

// ── Auto-refresh ──────────────────────────────────────────────────────────────
function toggleAuto() {
  const badge = document.getElementById('auto-badge');
  if (_autoInterval) {
    clearInterval(_autoInterval);
    _autoInterval = null;
    badge.textContent = '⟳ Auto-refresh: OFF';
    badge.classList.remove('on');
  } else {
    _autoInterval = setInterval(loadLogs, 5000);
    badge.textContent = '⟳ Auto-refresh: 5s';
    badge.classList.add('on');
    loadLogs();
  }
}

// ── Download current log file ─────────────────────────────────────────────────
function downloadLog() {
  if (!_lastEntries.length) return;
  const text = _lastEntries.map(e => e.raw || e.message).join('\n');
  const blob = new Blob([text], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = document.getElementById('file-select').value || 'mlb.log';
  a.click();
  URL.revokeObjectURL(url);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function _esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function _fmtSize(bytes) {
  if (bytes < 1024)       return bytes + ' B';
  if (bytes < 1024*1024)  return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/(1024*1024)).toFixed(1) + ' MB';
}
