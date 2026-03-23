/**
 * Shared API helpers + toast notifications
 * Available on every page via base.html
 */

const API = {
  async get(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    return res.json();
  },
  async post(url, body = {}) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    return res.json();
  },
  async put(url, body = {}) {
    const res = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    return res.json();
  },
  async patch(url, body = {}) {
    const res = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    return res.json();
  },
};

function toast(msg, type = 'info', duration = 3500) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${msg}</span>`;
  c.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

// Tier → badge CSS class
function tierBadge(tier) {
  const map = {
    'ELITE':       'badge-elite',
    'STRONGEST':   'badge-strongest',
    'BEST BET':    'badge-best-bet',
    'GOLD':        'badge-gold',
    'ACTION ONLY': 'badge-action-only',
    'PASS':        'badge-pass',
  };
  const cls = map[tier] || 'badge-pass';
  return `<span class="badge ${cls}">${tier}</span>`;
}

function resultBadge(result) {
  const map = {
    'ACTIVE':   'badge-active',
    'WON':      'badge-won',
    'LOST':     'badge-lost',
    'PUSH':     'badge-push',
    'VOID':     'badge-pass',
    'PASS_CLV': 'badge-pass',
  };
  return `<span class="badge ${map[result] || 'badge-pass'}">${result}</span>`;
}

function feedBadge(status) {
  const map = { OK: 'badge-ok', FAIL: 'badge-fail', PARTIAL: 'badge-partial', RUNNING: 'badge-running' };
  return `<span class="badge ${map[status] || 'badge-pass'}">${status}</span>`;
}

function fmtOdds(n) {
  if (n == null) return '—';
  return n > 0 ? `+${n}` : `${n}`;
}

function fmtPct(n, decimals = 1) {
  if (n == null) return '—';
  return `${(+n).toFixed(decimals)}%`;
}

function fmtPnl(n) {
  if (n == null || n === 0) return '<span class="neutral">0.00u</span>';
  const cls = n > 0 ? 'pos' : 'neg';
  const sign = n > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${(+n).toFixed(2)}u</span>`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch { return iso.slice(0, 10); }
}

// Countdown timer helper
function startCountdown(elementId, seconds, onComplete) {
  let remaining = seconds;
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = remaining;
  const iv = setInterval(() => {
    remaining--;
    if (el) el.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(iv);
      if (onComplete) onComplete();
    }
  }, 1000);
  return iv;
}
