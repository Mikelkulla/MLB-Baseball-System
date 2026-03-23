/** Live Picks page */

let allPredictions = [];
let currentTier = '';
let sortKey = '';
let sortAsc = true;
let countdownTimer;

async function loadPredictions() {
  try {
    const d = await API.get('/api/predictions');
    allPredictions = d.predictions || [];
    renderTable();
    const el = document.getElementById('last-refresh-time');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error(e);
    toast('Failed to load predictions', 'error');
  }
}

function renderTable() {
  let data = allPredictions;
  if (currentTier) data = data.filter(p => p.status === currentTier);

  // Sort
  if (sortKey) {
    data = [...data].sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
    });
  }

  const count = document.getElementById('picks-count');
  if (count) count.textContent = `${data.length} picks`;

  const tbody = document.getElementById('predictions-tbody');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="15"><div class="empty-state"><div class="empty-icon">⚾</div><p>No picks match this filter.</p></div></td></tr>';
    return;
  }

  tbody.innerHTML = data.map(p => {
    const spGate = p.sp_gate_blocked
      ? '<span class="badge badge-lost">BLOCKED</span>'
      : '<span class="badge badge-ok">OK</span>';
    const clvColor = (p.clv_delta || 0) >= 0 ? 'pos' : 'neg';
    const awayPitcher = `${p.away_pitcher_name || 'TBD'} <span style="color:var(--text-muted)">(${Math.round(p.away_pitcher_score || 50)})</span>`;
    const homePitcher = `${p.home_pitcher_name || 'TBD'} <span style="color:var(--text-muted)">(${Math.round(p.home_pitcher_score || 50)})</span>`;
    return `<tr>
      <td>${fmtDate(p.game_date)}</td>
      <td>${p.matchup || '—'}</td>
      <td><strong>${p.picked_team_name || '—'}</strong></td>
      <td>${tierBadge(p.status)}</td>
      <td style="font-size:12px">${awayPitcher}</td>
      <td style="font-size:12px">${homePitcher}</td>
      <td class="mono">${fmtOdds(p.bet_price)}</td>
      <td class="mono">${fmtPct(p.prob_pct)}</td>
      <td class="mono ${(p.ev_pct||0) > 0 ? 'pos' : 'neg'}">${fmtPct(p.ev_pct)}</td>
      <td class="mono">${fmtPct(p.confidence_pct)}</td>
      <td class="mono"><strong>${p.safe_units || 0}u</strong></td>
      <td class="mono ${clvColor}">${fmtOdds(p.clv_delta)}</td>
      <td class="mono">${Math.round(p.sharp_split_score || 0)}</td>
      <td>${spGate}</td>
      <td>
        <button class="btn btn-primary btn-sm" onclick="openLogModal('${p.game_id}', \`${(p.matchup||'').replace(/`/g,'\\`')}\`, \`${(p.picked_team_name||'').replace(/`/g,'\\`')}\`)">+ Log</button>
      </td>
    </tr>`;
  }).join('');
}

function sortTable(key) {
  if (sortKey === key) sortAsc = !sortAsc;
  else { sortKey = key; sortAsc = false; }
  document.querySelectorAll('thead th').forEach(th => th.classList.remove('sorted'));
  renderTable();
}

// Tier filter tabs
document.querySelectorAll('#tier-filter .filter-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#tier-filter .filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTier = btn.dataset.tier;
    renderTable();
  });
});

// Log bet modal
let pendingLogGameId = '';
function openLogModal(gameId, matchup, pick) {
  pendingLogGameId = gameId;
  document.getElementById('log-game-id').value = gameId;
  document.getElementById('log-game-desc').textContent = `${matchup} — Pick: ${pick}`;
  document.getElementById('log-notes').value = '';
  document.getElementById('log-modal').classList.add('open');
}
function closeLogModal() {
  document.getElementById('log-modal').classList.remove('open');
}
async function confirmLogBet() {
  const gameId = document.getElementById('log-game-id').value;
  const notes = document.getElementById('log-notes').value;
  try {
    await API.post('/api/bets/log', { game_id: gameId, notes });
    toast('Bet logged!', 'success');
    closeLogModal();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}

function onRefreshComplete() { loadPredictions(); startAutoRefresh(); }

function startAutoRefresh() {
  clearInterval(countdownTimer);
  countdownTimer = startCountdown('countdown', 60, () => {
    loadPredictions();
    startAutoRefresh();
  });
}

loadPredictions();
startAutoRefresh();
