/**
 * MLB Model page — shows ALL games with full metrics (including PASS tier).
 * Equivalent to V8.0 NBA_Model / NFL_Model Google Sheet.
 */

let allModel = [];
let currentTier = '';
let currentSearch = '';
let sortKey = 'game_date';
let sortAsc = true;
let countdownTimer;

async function loadModel() {
  try {
    const d = await API.get('/api/predictions/model');
    allModel = d.model || [];
    renderModel();
    const el = document.getElementById('last-refresh-time');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error(e);
    toast('Failed to load model', 'error');
  }
}

function renderModel() {
  let data = allModel;

  if (currentTier) data = data.filter(p => p.status === currentTier);
  if (currentSearch) {
    const s = currentSearch.toLowerCase();
    data = data.filter(p =>
      (p.matchup || '').toLowerCase().includes(s) ||
      (p.picked_team_name || '').toLowerCase().includes(s)
    );
  }

  // Sort
  if (sortKey) {
    data = [...data].sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
    });
  }

  const countEl = document.getElementById('model-count');
  const picks = data.filter(p => p.status !== 'PASS').length;
  if (countEl) countEl.textContent = `${data.length} games · ${picks} picks`;

  const tbody = document.getElementById('model-tbody');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="28"><div class="empty-state"><div class="empty-icon">⚾</div><p>No games found. Run a refresh first.</p></div></td></tr>';
    return;
  }

  tbody.innerHTML = data.map(p => {
    const isPass = p.status === 'PASS';
    const rowStyle = isPass ? 'opacity:0.6' : '';

    // SP Gate badge
    const spGate = p.sp_gate_blocked
      ? '<span class="badge badge-lost" style="font-size:10px">BLOCKED</span>'
      : '<span style="color:var(--text-muted);font-size:11px">—</span>';

    const clvColor = (p.clv_delta || 0) > 0 ? 'pos' : (p.clv_delta || 0) < 0 ? 'neg' : '';
    const evColor  = (p.ev_pct  || 0) > 0 ? 'pos' : 'neg';
    const sss = Math.round(p.sharp_split_score || 0);
    const sssColor = sss >= 20 ? 'pos' : sss >= 10 ? '' : 'neg';

    // Pitcher columns: "Name (score)" — single line, no wrapping
    const awaySP = `${p.away_pitcher_name || 'TBD'} <span style="color:var(--text-muted)">(${Math.round(p.away_pitcher_score || 50)})</span>`;
    const homeSP = `${p.home_pitcher_name || 'TBD'} <span style="color:var(--text-muted)">(${Math.round(p.home_pitcher_score || 50)})</span>`;

    // Bullpen depth columns (0–100 score; 50 = neutral/pre-season)
    const awayBPVal = Math.round(p.away_bullpen_score ?? 50);
    const homeBPVal = Math.round(p.home_bullpen_score ?? 50);
    const awayBPColor = awayBPVal > 55 ? 'pos' : awayBPVal < 45 ? 'neg' : '';
    const homeBPColor = homeBPVal > 55 ? 'pos' : homeBPVal < 45 ? 'neg' : '';
    const awayBP = `<span class="mono ${awayBPColor}">${awayBPVal}</span>`;
    const homeBP = `<span class="mono ${homeBPColor}">${homeBPVal}</span>`;

    // Park factor + O/U adjustment
    const parkFactor = (p.park_factor ?? 1.0).toFixed(2);
    const parkFactorColor = p.park_factor > 1.05 ? 'pos' : p.park_factor < 0.95 ? 'neg' : '';
    const parkFactorDisp = `<span class="mono ${parkFactorColor}">${parkFactor}</span>`;
    const parkOuVal = p.park_ou_adj ?? 0;
    const parkOuColor = parkOuVal > 0 ? 'pos' : parkOuVal < 0 ? 'neg' : '';
    const parkOuDisp = parkOuVal !== 0
      ? `<span class="mono ${parkOuColor}">${parkOuVal > 0 ? '+' : ''}${parkOuVal.toFixed(2)}</span>`
      : '<span class="mono">—</span>';

    // Injury impact (show as signed delta)
    const awayInj = p.away_injury_impact != null
      ? `<span class="${p.away_injury_impact < 0 ? 'neg' : ''}">${p.away_injury_impact > 0 ? '+' : ''}${(p.away_injury_impact||0).toFixed(1)}</span>`
      : '—';
    const homeInj = p.home_injury_impact != null
      ? `<span class="${p.home_injury_impact < 0 ? 'neg' : ''}">${p.home_injury_impact > 0 ? '+' : ''}${(p.home_injury_impact||0).toFixed(1)}</span>`
      : '—';

    // Weather O/U adj
    const wOverAdj  = (p.weather_over_adj  || 0).toFixed(1);
    const wUnderAdj = (p.weather_under_adj || 0).toFixed(1);
    const wAdj = (p.weather_over_adj || p.weather_under_adj)
      ? `<span class="mono" style="font-size:11px">O${wOverAdj > 0 ? '+' : ''}${wOverAdj} / U${wUnderAdj > 0 ? '+' : ''}${wUnderAdj}</span>`
      : '—';

    // Odds columns from raw game odds embedded in prediction
    const awayML  = fmtOdds(p.away_ml);
    const homeML  = fmtOdds(p.home_ml);
    const awaySpread = p.away_spread != null ? `${p.away_spread > 0 ? '+' : ''}${p.away_spread}` : '—';
    const homeSpread = p.home_spread != null ? `${p.home_spread > 0 ? '+' : ''}${p.home_spread}` : '—';
    const total   = p.total_line != null ? p.total_line : '—';

    // Pick column: highlight the picked side
    const pick = isPass
      ? '<span style="color:var(--text-muted)">PASS</span>'
      : `<strong>${p.picked_team_name || '—'}</strong> <span class="mono">${fmtOdds(p.bet_price)}</span>`;

    // Away/Home prob and EV (V8.0 style — show both sides)
    const awayEvVal = p.away_ev_pct != null ? p.away_ev_pct : null;
    const homeEvVal = p.home_ev_pct != null ? p.home_ev_pct : null;
    const awayEvColor = awayEvVal != null ? (awayEvVal >= 0 ? 'pos' : 'neg') : '';
    const homeEvColor = homeEvVal != null ? (homeEvVal >= 0 ? 'pos' : 'neg') : '';
    const awayEvDisp = awayEvVal != null ? fmtPct(awayEvVal) : '—';
    const homeEvDisp = homeEvVal != null ? fmtPct(homeEvVal) : '—';

    return `<tr style="${rowStyle}">
      <td style="font-size:11px;white-space:nowrap">${fmtDate(p.game_date)}</td>
      <td style="white-space:nowrap">${p.matchup || '—'}</td>
      <td style="font-size:11px;white-space:nowrap">${awaySP}</td>
      <td style="font-size:11px;white-space:nowrap">${homeSP}</td>
      <td>${awayBP}</td>
      <td>${homeBP}</td>
      <td>${parkFactorDisp}</td>
      <td>${parkOuDisp}</td>
      <td class="mono">${awayML}</td>
      <td class="mono">${homeML}</td>
      <td class="mono">${awaySpread}</td>
      <td class="mono">${homeSpread}</td>
      <td class="mono">${total}</td>
      <td class="mono">${fmtPct(p.away_prob_pct)}</td>
      <td class="mono">${fmtPct(p.home_prob_pct)}</td>
      <td class="mono ${awayEvColor}">${awayEvDisp}</td>
      <td class="mono ${homeEvColor}">${homeEvDisp}</td>
      <td class="mono">${fmtPct(p.confidence_pct)}</td>
      <td>${tierBadge(p.status)}</td>
      <td class="mono"><strong>${p.safe_units || 0}u</strong></td>
      <td class="mono ${clvColor}">${(p.clv_delta||0) > 0 ? '+' : ''}${(p.clv_delta||0).toFixed(2)}</td>
      <td class="mono ${sssColor}">${sss}</td>
      <td class="mono">${awayInj}</td>
      <td class="mono">${homeInj}</td>
      <td>${wAdj}</td>
      <td>${spGate}</td>
      <td style="white-space:nowrap">${pick}</td>
      <td class="cell-truncate" title="${(p.prediction_text || '').replace(/"/g, '&quot;')}">${p.prediction_text || '—'}</td>
    </tr>`;
  }).join('');
}

function sortTable(key) {
  if (sortKey === key) sortAsc = !sortAsc;
  else { sortKey = key; sortAsc = true; }
  renderModel();
}

function onSearch(val) {
  currentSearch = val;
  renderModel();
}

function exportCSV() {
  if (!allModel.length) { toast('No data to export', 'error'); return; }
  const cols = [
    'game_date','matchup','away_pitcher_name','away_pitcher_score',
    'home_pitcher_name','home_pitcher_score',
    'away_bullpen_score','home_bullpen_score',
    'park_factor','park_ou_adj',
    'away_ml','home_ml','away_spread','home_spread','total_line',
    'away_prob_pct','home_prob_pct','away_ev_pct','home_ev_pct',
    'confidence_pct','status','safe_units',
    'clv_delta','sharp_split_score',
    'away_injury_impact','home_injury_impact',
    'weather_over_adj','weather_under_adj',
    'sp_gate_blocked','picked_team_name','bet_price','prediction_text'
  ];
  const header = cols.join(',');
  const rows = allModel.map(p =>
    cols.map(c => {
      const v = p[c] ?? '';
      return typeof v === 'string' && v.includes(',') ? `"${v}"` : v;
    }).join(',')
  );
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `mlb_model_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// Tier filter tabs
document.querySelectorAll('#tier-filter .filter-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#tier-filter .filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTier = btn.dataset.tier;
    renderModel();
  });
});

function onRefreshComplete() { loadModel(); startAutoRefresh(); }

function startAutoRefresh() {
  clearInterval(countdownTimer);
  countdownTimer = startCountdown('countdown', 60, () => {
    loadModel();
    startAutoRefresh();
  });
}

loadModel();
startAutoRefresh();
