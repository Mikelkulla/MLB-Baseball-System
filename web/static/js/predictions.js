/** Live Picks page */

let allPredictions = [];
let loggedBets = {};      // { matchup: { bet_price, prob_pct, ev_pct, confidence_pct, units, status_tier, placed_at } }
let currentTier = '';
let sortKey = '';
let sortAsc = true;
let countdownTimer;

async function loadPredictions() {
  try {
    const [d, loggedData] = await Promise.all([
      API.get('/api/predictions'),
      API.get('/api/bets/logged-matchups').catch(() => ({ bets: {} })),
    ]);
    allPredictions = d.predictions || [];
    loggedBets = loggedData.bets || {};
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
    const isLogged = p.matchup in loggedBets;
    const rowClass = isLogged ? 'row-logged' : '';

    const spGate = p.sp_gate_blocked
      ? '<span class="badge badge-lost">BLOCKED</span>'
      : '<span class="badge badge-ok">OK</span>';
    const clvColor = (p.clv_delta || 0) >= 0 ? 'pos' : 'neg';
    const awayPitcher = `${p.away_pitcher_name || 'TBD'} <span style="color:var(--text-muted)">(${Math.round(p.away_pitcher_score || 50)})</span>`;
    const homePitcher = `${p.home_pitcher_name || 'TBD'} <span style="color:var(--text-muted)">(${Math.round(p.home_pitcher_score || 50)})</span>`;

    const safeMatchup = (p.matchup || '').replace(/`/g, '\\`').replace(/'/g, "\\'");
    const safePick    = (p.picked_team_name || '').replace(/`/g, '\\`');
    const logBtn = isLogged
      ? `<button class="btn btn-logged btn-sm" onclick="openLogModal('${p.game_id}', \`${safeMatchup}\`, \`${safePick}\`, ${JSON.stringify(p).replace(/</g,'\\u003c')})">✓ Logged</button>`
      : `<button class="btn btn-primary btn-sm" onclick="openLogModal('${p.game_id}', \`${safeMatchup}\`, \`${safePick}\`, ${JSON.stringify(p).replace(/</g,'\\u003c')})">+ Log</button>`;

    return `<tr class="${rowClass}">
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
      <td>${logBtn}</td>
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

// ── Log bet modal ────────────────────────────────────────────────────────────

let pendingLogGameId  = '';
let pendingLogMatchup = '';

function openLogModal(gameId, matchup, pick, prediction) {
  pendingLogGameId  = gameId;
  pendingLogMatchup = matchup;

  document.getElementById('log-game-id').value = gameId;
  document.getElementById('log-game-desc').textContent = `${matchup} — Pick: ${pick}`;
  document.getElementById('log-notes').value = '';

  const warning = document.getElementById('log-duplicate-warning');
  const existing = loggedBets[matchup];

  if (existing && warning) {
    warning.style.display = 'block';
    renderDiff(existing, prediction);
  } else if (warning) {
    warning.style.display = 'none';
  }

  document.getElementById('log-modal').classList.add('open');
}

function renderDiff(old, now) {
  // Higher odds = better for bettor (less negative / more positive)
  // Higher prob, ev, conf, units = better
  function diffClass(oldVal, newVal, higherIsBetter) {
    if (oldVal == null || newVal == null) return 'diff-same';
    const delta = newVal - oldVal;
    if (Math.abs(delta) < 0.01) return 'diff-same';
    return (higherIsBetter ? delta > 0 : delta < 0) ? 'diff-up' : 'diff-down';
  }

  function fmtOddsVal(v) {
    if (v == null) return '—';
    return v > 0 ? `+${v}` : `${v}`;
  }

  const rows = [
    {
      label: 'Pick',
      oldVal: old.picked_team_name || '—',
      newVal: now.picked_team_name || '—',
      fmt: v => v,
      cls: old.picked_team_name !== now.picked_team_name ? 'diff-down' : 'diff-same',
    },
    {
      label: 'Tier',
      oldVal: old.status_tier,
      newVal: now.status,
      fmt: v => v,
      cls: old.status_tier !== now.status ? 'diff-down' : 'diff-same',
    },
    {
      label: 'Odds',
      oldVal: old.bet_price,
      newVal: now.bet_price,
      fmt: fmtOddsVal,
      cls: diffClass(old.bet_price, now.bet_price, true),
    },
    {
      label: 'Prob%',
      oldVal: old.prob_pct,
      newVal: now.prob_pct,
      fmt: v => v != null ? v.toFixed(1) + '%' : '—',
      cls: diffClass(old.prob_pct, now.prob_pct, true),
    },
    {
      label: 'EV%',
      oldVal: old.ev_pct,
      newVal: now.ev_pct,
      fmt: v => v != null ? (v >= 0 ? '+' : '') + v.toFixed(1) + '%' : '—',
      cls: diffClass(old.ev_pct, now.ev_pct, true),
    },
    {
      label: 'Conf%',
      oldVal: old.confidence_pct,
      newVal: now.confidence_pct,
      fmt: v => v != null ? v.toFixed(1) + '%' : '—',
      cls: diffClass(old.confidence_pct, now.confidence_pct, true),
    },
    {
      label: 'Units',
      oldVal: old.units,
      newVal: now.safe_units,
      fmt: v => v != null ? v + 'u' : '—',
      cls: diffClass(old.units, now.safe_units, true),
    },
  ];

  const tbody = document.getElementById('log-diff-body');
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.label}</td>
      <td>${r.fmt(r.oldVal)}</td>
      <td class="${r.cls || 'diff-same'}">${r.fmt(r.newVal)}</td>
    </tr>
  `).join('');
}

function closeLogModal() {
  document.getElementById('log-modal').classList.remove('open');
}

async function confirmLogBet() {
  const gameId = document.getElementById('log-game-id').value;
  const notes  = document.getElementById('log-notes').value;
  try {
    const resp = await API.post('/api/bets/log', { game_id: gameId, notes });
    // Update local cache so the row reflects logged state immediately (survives re-renders)
    if (resp.bet) {
      loggedBets[pendingLogMatchup] = {
        picked_team_name: resp.bet.picked_team_name,
        status_tier:      resp.bet.status_tier,
        bet_price:        resp.bet.bet_price,
        prob_pct:         resp.bet.prob_pct,
        ev_pct:           resp.bet.ev_pct,
        confidence_pct:   resp.bet.confidence_pct,
        units:            resp.bet.units,
        placed_at:        resp.bet.placed_at,
      };
    }
    toast('Bet logged!', 'success');
    closeLogModal();
    renderTable();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}

// ── Auto-refresh ─────────────────────────────────────────────────────────────

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
