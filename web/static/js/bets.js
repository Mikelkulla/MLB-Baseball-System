/** Bets Log page */

let allBets = [];
let currentStatus = 'ALL';

async function loadBets() {
  try {
    const d = await API.get('/api/bets');
    allBets = d.bets || [];
    renderSummary(d.record || {}, d.total_pnl || 0);
    renderTable();
  } catch(e) {
    toast('Failed to load bets', 'error');
  }
}

function renderSummary(rec, pnl) {
  document.getElementById('b-total').textContent = rec.total || 0;
  document.getElementById('b-wins').textContent = rec.wins || 0;
  document.getElementById('b-losses').textContent = rec.losses || 0;

  const wr = rec.win_rate || 0;
  const wrEl = document.getElementById('b-winrate');
  wrEl.textContent = wr.toFixed(1) + '%';
  wrEl.className = 'card-value ' + (wr >= 55 ? 'green' : wr >= 45 ? 'amber' : 'red');

  const pnlEl = document.getElementById('b-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + 'u';
  pnlEl.className = 'card-value ' + (pnl >= 0 ? 'green' : 'red');
}

function renderTable() {
  let data = allBets;
  if (currentStatus !== 'ALL') data = data.filter(b => b.result === currentStatus);

  const tbody = document.getElementById('bets-tbody');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="14"><div class="empty-state"><div class="empty-icon">📋</div><p>No bets in this view.</p></div></td></tr>';
    return;
  }

  tbody.innerHTML = data.map(b => {
    const isActive = b.result === 'ACTIVE';
    const clvClass = (b.clv_pct || 0) >= 0 ? 'pos' : 'neg';
    return `<tr>
      <td>${fmtDate(b.game_date)}</td>
      <td>${b.matchup || '—'}</td>
      <td><strong>${b.picked_team_name || '—'}</strong></td>
      <td>${tierBadge(b.status_tier)}</td>
      <td class="mono">${fmtOdds(b.bet_price)}</td>
      <td class="mono">${b.units}u</td>
      <td class="mono ${(b.ev_pct||0) > 0 ? 'pos' : ''}">${fmtPct(b.ev_pct)}</td>
      <td class="mono">${fmtPct(b.confidence_pct)}</td>
      <td class="mono ${clvClass}">${b.clv_pct != null ? (b.clv_pct > 0 ? '+' : '') + b.clv_pct.toFixed(2) + '%' : '—'}</td>
      <td><span class="badge badge-${(b.clv_band||'').toLowerCase().replace('.','').replace('_','-')}">${b.clv_band || '—'}</span></td>
      <td class="mono">${b.adj_units || b.units}u</td>
      <td>${resultBadge(b.result)}</td>
      <td>${fmtPnl(b.pnl)}</td>
      <td style="display:flex;gap:4px">
        ${isActive ? `
          <button class="btn btn-secondary btn-sm" onclick="openSettleModal('${b.bet_id}', '${(b.matchup||'').replace(/'/g,"\\'")}')">Settle</button>
          <button class="btn btn-ghost btn-sm" onclick="openCLVModal('${b.bet_id}')">CLV</button>
        ` : ''}
      </td>
    </tr>`;
  }).join('');
}

// Status filter tabs
document.querySelectorAll('#status-filter .filter-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#status-filter .filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentStatus = btn.dataset.status;
    renderTable();
  });
});

// Settle modal
function openSettleModal(betId, matchup) {
  document.getElementById('settle-bet-id').value = betId;
  document.getElementById('settle-bet-desc').textContent = matchup;
  document.getElementById('settle-price').value = '';
  document.getElementById('settle-modal').classList.add('open');
}
function closeSettleModal() {
  document.getElementById('settle-modal').classList.remove('open');
}
async function confirmSettle() {
  const betId = document.getElementById('settle-bet-id').value;
  const result = document.getElementById('settle-result').value;
  const priceRaw = document.getElementById('settle-price').value;
  const finalPrice = priceRaw ? parseInt(priceRaw) : null;
  try {
    await API.post('/api/bets/settle', { bet_id: betId, result, final_price: finalPrice });
    toast('Bet settled!', 'success');
    closeSettleModal();
    loadBets();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}

// CLV modal
function openCLVModal(betId) {
  document.getElementById('clv-bet-id').value = betId;
  document.getElementById('clv-price').value = '';
  document.getElementById('clv-modal').classList.add('open');
}
async function confirmCLV() {
  const betId = document.getElementById('clv-bet-id').value;
  const price = parseInt(document.getElementById('clv-price').value);
  if (!price) { toast('Enter a valid price', 'error'); return; }
  try {
    await API.post('/api/bets/refresh-clv', { bet_id: betId, current_price: price });
    toast('CLV updated!', 'success');
    document.getElementById('clv-modal').classList.remove('open');
    loadBets();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}

async function exportCSV() {
  window.location.href = '/api/bets/export';
}

function onRefreshComplete() { loadBets(); }

loadBets();
