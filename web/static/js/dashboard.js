/** Dashboard page logic */

let countdownTimer;

async function loadDashboard() {
  await Promise.all([loadPredictions(), loadBetStats(), loadHealth(), loadSchedulerStatus()]);
}

async function loadPredictions() {
  try {
    const d = await API.get('/api/predictions');
    renderPicksTable(d.predictions || []);
    updateStatCards(d.predictions || []);
    const el = document.getElementById('last-refresh-time');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error('Failed to load predictions', e);
  }
}

function updateStatCards(picks) {
  document.getElementById('stat-picks').textContent = picks.length;
  const elite = picks.filter(p => p.status === 'ELITE' || p.status === 'STRONGEST').length;
  document.getElementById('stat-elite').textContent = elite;
}

async function loadBetStats() {
  try {
    const d = await API.get('/api/bets');
    const rec = d.record || {};
    const pnl = d.total_pnl || 0;
    const pnlEl = document.getElementById('stat-pnl');
    pnlEl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + 'u';
    pnlEl.className = 'card-value ' + (pnl >= 0 ? 'green' : 'red');

    const wr = rec.win_rate || 0;
    const wrEl = document.getElementById('stat-winrate');
    wrEl.textContent = wr.toFixed(1) + '%';
    wrEl.className = 'card-value ' + (wr >= 55 ? 'green' : wr >= 45 ? 'amber' : 'red');

    document.getElementById('stat-record').textContent = `${rec.wins || 0}W – ${rec.losses || 0}L`;

    const active = (d.bets || []).filter(b => b.result === 'ACTIVE').length;
    document.getElementById('stat-active').textContent = active;
  } catch(e) {}
}

async function loadHealth() {
  try {
    const d = await API.get('/api/health');
    renderFeedGrid(d.feeds || {});
    const el = document.getElementById('health-updated');
    if (el) el.textContent = 'Checked ' + new Date().toLocaleTimeString();
  } catch(e) {}
}

function renderFeedGrid(feeds) {
  const grid = document.getElementById('feed-grid');
  if (!grid) return;
  const feedNames = ['OddsAPI', 'DraftKings', 'Weather', 'Injuries', 'Pitchers'];
  grid.innerHTML = feedNames.map(name => {
    const f = feeds[name] || {};
    const status = f.status || 'UNKNOWN';
    const colorMap = { OK: 'var(--accent-green)', FAIL: 'var(--accent-red)', PARTIAL: 'var(--accent-amber)', RUNNING: 'var(--accent-blue)', UNKNOWN: 'var(--text-muted)' };
    const updated = f.updated_at ? new Date(f.updated_at).toLocaleTimeString() : 'never';
    return `<div class="feed-card">
      <div class="feed-card-name">${name}</div>
      <div class="feed-card-status" style="color:${colorMap[status]}">${status}</div>
      <div class="feed-card-meta">${f.record_count != null ? f.record_count + ' records' : ''}</div>
      <div class="feed-card-meta">${updated}</div>
    </div>`;
  }).join('');
}

async function loadSchedulerStatus() {
  try {
    const d = await API.get('/api/scheduler');
    const label = document.getElementById('scheduler-label');
    const dot = document.getElementById('scheduler-dot');
    const startBtn = document.getElementById('btn-scheduler-start');
    const stopBtn = document.getElementById('btn-scheduler-stop');
    const meta = document.getElementById('scheduler-meta');
    const indicator = document.getElementById('scheduler-indicator');
    const preset = document.getElementById('preset-select');

    if (d.running) {
      label.textContent = 'Scheduler Running';
      label.className = 'scheduler-running';
      dot.className = 'dot running';
      startBtn.style.display = 'none';
      stopBtn.style.display = '';
      meta.textContent = `Preset: ${d.preset}`;
      if (preset) preset.value = d.preset;
    } else {
      label.textContent = 'Scheduler Stopped';
      label.className = 'scheduler-stopped';
      dot.className = 'dot';
      startBtn.style.display = '';
      stopBtn.style.display = 'none';
      meta.textContent = '';
    }
  } catch(e) {}
}

async function startScheduler() {
  const preset = document.getElementById('preset-select').value;
  try {
    await API.post('/api/scheduler', { action: 'start', preset });
    toast(`Scheduler started (${preset})`, 'success');
    loadSchedulerStatus();
  } catch(e) { toast('Failed: ' + e.message, 'error'); }
}

async function stopScheduler() {
  try {
    await API.post('/api/scheduler', { action: 'stop', preset: 'default' });
    toast('Scheduler stopped', 'info');
    loadSchedulerStatus();
  } catch(e) { toast('Failed: ' + e.message, 'error'); }
}

function renderPicksTable(picks) {
  const tbody = document.getElementById('picks-tbody');
  if (!picks.length) {
    tbody.innerHTML = '<tr><td colspan="10"><div class="empty-state"><div class="empty-icon">⚾</div><p>No qualified picks right now.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = picks.map(p => `
    <tr>
      <td>${p.matchup || '—'}</td>
      <td><strong>${p.picked_team_name || '—'}</strong></td>
      <td>${tierBadge(p.status)}</td>
      <td style="font-size:11px">${p.away_pitcher_name || 'TBD'}</td>
      <td class="mono">${fmtOdds(p.bet_price)}</td>
      <td class="mono">${fmtPct(p.prob_pct)}</td>
      <td class="mono ${p.ev_pct > 0 ? 'pos' : ''}">${fmtPct(p.ev_pct)}</td>
      <td class="mono">${fmtPct(p.confidence_pct)}</td>
      <td class="mono"><strong>${p.safe_units || 0}u</strong></td>
      <td>
        <button class="btn btn-primary btn-sm" onclick="logBet('${p.game_id}', '${(p.matchup||'').replace(/'/g,"\\'")}', '${(p.picked_team_name||'').replace(/'/g,"\\'")}')">+ Log</button>
      </td>
    </tr>
  `).join('');
}

async function logBet(gameId, matchup, pick) {
  try {
    await API.post('/api/bets/log', { game_id: gameId });
    toast(`Bet logged: ${pick} — ${matchup}`, 'success');
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}

function onRefreshComplete() { loadDashboard(); }

// Start countdown and auto-refresh
function startAutoRefresh() {
  clearInterval(countdownTimer);
  countdownTimer = startCountdown('countdown', 60, () => {
    loadPredictions();
    startAutoRefresh();
  });
}

// Init
loadDashboard();
startAutoRefresh();
