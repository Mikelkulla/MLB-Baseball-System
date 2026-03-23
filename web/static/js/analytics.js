/** Analytics page — Chart.js charts */

const CHART_DEFAULTS = {
  color: '#8b949e',
  gridColor: 'rgba(48,54,61,0.8)',
  font: { family: 'system-ui', size: 12 },
};

Chart.defaults.color = CHART_DEFAULTS.color;
Chart.defaults.font = CHART_DEFAULTS.font;

let pnlChart, tierChart, tierPnlChart;

const TIER_COLORS = {
  ELITE:     '#ffd700',
  STRONGEST: '#60a5fa',
  'BEST BET':'#34d399',
  GOLD:      '#fbbf24',
};

async function loadAnalytics() {
  try {
    const d = await API.get('/api/bets');
    const bets = d.bets || [];
    const rec = d.record || {};
    renderSummary(bets, rec, d.total_pnl || 0);
    renderPnLChart(bets);
    renderTierCharts(bets);
    renderRecentTable(bets);
  } catch(e) {
    toast('Failed to load analytics', 'error');
  }
}

function renderSummary(bets, rec, pnl) {
  const pnlEl = document.getElementById('an-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + 'u';
  pnlEl.className = 'card-value ' + (pnl >= 0 ? 'green' : 'red');

  const wr = rec.win_rate || 0;
  const wrEl = document.getElementById('an-wr');
  wrEl.textContent = wr.toFixed(1) + '%';
  wrEl.className = 'card-value ' + (wr >= 55 ? 'green' : wr >= 45 ? 'amber' : 'red');
  document.getElementById('an-record').textContent = `${rec.wins || 0}W – ${rec.losses || 0}L`;

  const settled = bets.filter(b => b.result !== 'ACTIVE');
  const avgEV = settled.length ? settled.reduce((s, b) => s + (b.ev_pct || 0), 0) / settled.length : 0;
  const avgConf = settled.length ? settled.reduce((s, b) => s + (b.confidence_pct || 0), 0) / settled.length : 0;
  document.getElementById('an-ev').textContent = (avgEV >= 0 ? '+' : '') + avgEV.toFixed(1) + '%';
  document.getElementById('an-conf').textContent = avgConf.toFixed(1) + '%';

  // Best tier by win rate
  const tiers = ['ELITE', 'STRONGEST', 'BEST BET', 'GOLD'];
  let bestTier = '—', bestWr = 0;
  for (const tier of tiers) {
    const tb = settled.filter(b => b.status_tier === tier);
    const tw = tb.filter(b => b.result === 'WON').length;
    const twr = tb.length ? tw / tb.length * 100 : 0;
    if (twr > bestWr && tb.length >= 3) { bestWr = twr; bestTier = tier; }
  }
  document.getElementById('an-best-tier').textContent = bestTier;
  document.getElementById('an-best-tier-wr').textContent = bestTier !== '—' ? bestWr.toFixed(1) + '% WR' : '';
}

function renderPnLChart(bets) {
  const settled = bets
    .filter(b => b.result === 'WON' || b.result === 'LOST' || b.result === 'PUSH')
    .sort((a, b) => (a.placed_at || '') < (b.placed_at || '') ? -1 : 1);

  const labels = [];
  const data = [];
  let cumulative = 0;
  settled.forEach((b, i) => {
    cumulative += b.pnl || 0;
    labels.push(fmtDate(b.placed_at) + ` #${i+1}`);
    data.push(+cumulative.toFixed(2));
  });

  if (pnlChart) pnlChart.destroy();
  const ctx = document.getElementById('pnl-chart').getContext('2d');
  pnlChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Cumulative P&L (units)',
        data,
        borderColor: data.at(-1) >= 0 ? '#3fb950' : '#f85149',
        backgroundColor: data.at(-1) >= 0 ? 'rgba(63,185,80,0.08)' : 'rgba(248,81,73,0.08)',
        tension: 0.3,
        fill: true,
        pointRadius: 3,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: CHART_DEFAULTS.gridColor }, ticks: { maxTicksLimit: 10 } },
        y: { grid: { color: CHART_DEFAULTS.gridColor }, beginAtZero: false },
      }
    }
  });
}

function renderTierCharts(bets) {
  const settled = bets.filter(b => b.result === 'WON' || b.result === 'LOST');
  const tiers = ['ELITE', 'STRONGEST', 'BEST BET', 'GOLD'];

  const wrData = tiers.map(tier => {
    const tb = settled.filter(b => b.status_tier === tier);
    if (!tb.length) return 0;
    return +(tb.filter(b => b.result === 'WON').length / tb.length * 100).toFixed(1);
  });

  const pnlData = tiers.map(tier => {
    return +settled.filter(b => b.status_tier === tier).reduce((s, b) => s + (b.pnl || 0), 0).toFixed(2);
  });

  const colors = tiers.map(t => TIER_COLORS[t] || '#8b949e');

  if (tierChart) tierChart.destroy();
  tierChart = new Chart(document.getElementById('tier-chart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: tiers,
      datasets: [{ label: 'Win Rate %', data: wrData, backgroundColor: colors }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: CHART_DEFAULTS.gridColor } },
        y: { grid: { color: CHART_DEFAULTS.gridColor }, max: 100, ticks: { callback: v => v + '%' } },
      }
    }
  });

  if (tierPnlChart) tierPnlChart.destroy();
  tierPnlChart = new Chart(document.getElementById('tier-pnl-chart').getContext('2d'), {
    type: 'bar',
    data: {
      labels: tiers,
      datasets: [{ label: 'P&L (units)', data: pnlData, backgroundColor: pnlData.map(v => v >= 0 ? '#3fb950' : '#f85149') }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: CHART_DEFAULTS.gridColor } },
        y: { grid: { color: CHART_DEFAULTS.gridColor }, ticks: { callback: v => v + 'u' } },
      }
    }
  });
}

function renderRecentTable(bets) {
  const recent = [...bets]
    .sort((a, b) => (a.placed_at || '') < (b.placed_at || '') ? 1 : -1)
    .slice(0, 10);

  const tbody = document.getElementById('recent-tbody');
  if (!recent.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><p>No bets yet.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = recent.map(b => `
    <tr>
      <td>${fmtDate(b.placed_at)}</td>
      <td>${b.matchup || '—'}</td>
      <td><strong>${b.picked_team_name || '—'}</strong></td>
      <td>${tierBadge(b.status_tier)}</td>
      <td class="mono">${fmtOdds(b.bet_price)}</td>
      <td class="mono">${b.units}u</td>
      <td>${resultBadge(b.result)}</td>
      <td>${fmtPnl(b.pnl)}</td>
    </tr>
  `).join('');
}

function onRefreshComplete() { loadAnalytics(); }
loadAnalytics();
