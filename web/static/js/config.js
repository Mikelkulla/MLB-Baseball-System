/** Configuration page — load, edit, save config overrides */

let cfg = {};

const TIER_BADGE_COLORS = {
  ELITE:     'var(--tier-elite)',
  STRONGEST: 'var(--tier-strongest)',
  'BEST BET':'var(--tier-best-bet)',
  GOLD:      'var(--tier-gold)',
};

const WEIGHT_LABELS = {
  ev:           'EV Weight',
  probability:  'Probability Weight',
  clv:          'CLV Weight',
  sharp_action: 'Sharp Action Weight',
};

const PITCHER_LABELS = {
  era:         'ERA',
  whip:        'WHIP',
  k9:          'K/9',
  bb9:         'BB/9',
  recent_form: 'Recent Form (last 3)',
};

async function loadConfig() {
  try {
    cfg = await API.get('/api/config');
    renderTiers(cfg.tiers || []);
    renderWeights(cfg.confidence_weights || {}, 'weights-config', 'weight-sum', WEIGHT_LABELS);
    renderWeights(cfg.pitcher_weights || {}, 'pitcher-weights-config', 'pitcher-weight-sum', PITCHER_LABELS);
    renderBettingConfig(cfg.betting || {});
    renderSchedulerConfig(cfg.scheduler || {});
    renderLoggingConfig(cfg);
  } catch(e) {
    toast('Failed to load config: ' + e.message, 'error');
  }
}

function renderTiers(tiers) {
  const el = document.getElementById('tiers-config');
  el.innerHTML = tiers.map((t, i) => `
    <div class="tier-row">
      <span class="tier-label" style="color:${TIER_BADGE_COLORS[t.name] || 'inherit'}">${t.name}</span>
      <input type="number" class="input input-number input-sm" id="tier-conf-${i}" value="${t.min_confidence}" step="0.5" min="0" max="100">
      <input type="number" class="input input-number input-sm" id="tier-units-${i}" value="${t.units}" step="0.25" min="0" max="10">
    </div>
  `).join('');
}

function renderWeights(weights, containerId, sumId, labels) {
  const el = document.getElementById(containerId);
  el.innerHTML = Object.entries(weights).map(([key, val]) => `
    <div class="weight-row">
      <span style="font-size:12px;width:160px">${labels[key] || key}</span>
      <div class="weight-bar-wrap"><div class="weight-bar" id="bar-${containerId}-${key}" style="width:${val*100}%"></div></div>
      <input type="number" class="input input-number input-sm" id="weight-${containerId}-${key}"
        value="${val}" step="0.01" min="0" max="1" style="width:70px"
        oninput="updateWeightBar('${containerId}', '${key}', this.value); updateWeightSum('${containerId}', '${sumId}', ${JSON.stringify(Object.keys(weights))})">
    </div>
  `).join('');
  updateWeightSum(containerId, sumId, Object.keys(weights));
}

function updateWeightBar(containerId, key, val) {
  const bar = document.getElementById(`bar-${containerId}-${key}`);
  if (bar) bar.style.width = (Math.min(1, Math.max(0, +val)) * 100) + '%';
}

function updateWeightSum(containerId, sumId, keys) {
  const sum = keys.reduce((s, k) => {
    const el = document.getElementById(`weight-${containerId}-${k}`);
    return s + (el ? +el.value : 0);
  }, 0);
  const el = document.getElementById(sumId);
  if (el) {
    el.textContent = sum.toFixed(2);
    const diff = Math.abs(sum - 1.0);
    el.className = 'weight-sum ' + (diff < 0.01 ? 'valid' : 'invalid');
  }
}

function renderBettingConfig(betting) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  set('cfg-max-ml', betting.max_ml_odds);
  set('cfg-min-ev', betting.min_ev_threshold);
  set('cfg-unit-size', betting.unit_size_dollars);
  const spGate = document.getElementById('cfg-sp-gate');
  if (spGate) spGate.checked = betting.sp_gate_enabled !== false;
}

function renderLoggingConfig(c) {
  const lvl = document.getElementById('cfg-log-level');
  if (lvl) lvl.value = c.log_level || 'INFO';
  const lines = document.getElementById('cfg-log-lines');
  if (lines) lines.value = c.log_lines || 500;
}

function renderSchedulerConfig(scheduler) {
  const set = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = val; };
  set('cfg-odds-min', scheduler.odds_min);
  set('cfg-injuries-min', scheduler.injuries_min);
  set('cfg-weather-min', scheduler.weather_min);
  set('cfg-dk-min', scheduler.dk_splits_min);
  set('cfg-pitchers-min', scheduler.pitchers_min);
  set('cfg-pred-min', scheduler.live_predictions_min);
}

function collectConfig() {
  // Tiers
  const tiers = (cfg.tiers || []).map((t, i) => ({
    name: t.name,
    min_confidence: +document.getElementById(`tier-conf-${i}`)?.value || t.min_confidence,
    units: +document.getElementById(`tier-units-${i}`)?.value || t.units,
  }));

  // Confidence weights
  const confKeys = Object.keys(cfg.confidence_weights || {});
  const confidence_weights = {};
  confKeys.forEach(k => {
    confidence_weights[k] = +document.getElementById(`weight-weights-config-${k}`)?.value || 0;
  });

  // Pitcher weights
  const pitchKeys = Object.keys(cfg.pitcher_weights || {});
  const pitcher_weights = {};
  pitchKeys.forEach(k => {
    pitcher_weights[k] = +document.getElementById(`weight-pitcher-weights-config-${k}`)?.value || 0;
  });

  // Betting
  const betting = {
    max_ml_odds: +document.getElementById('cfg-max-ml')?.value || -200,
    min_ev_threshold: +document.getElementById('cfg-min-ev')?.value || 2.0,
    unit_size_dollars: +document.getElementById('cfg-unit-size')?.value || 100,
    sp_gate_enabled: document.getElementById('cfg-sp-gate')?.checked ?? true,
  };

  // Scheduler
  const scheduler = {
    odds_min: +document.getElementById('cfg-odds-min')?.value || 30,
    injuries_min: +document.getElementById('cfg-injuries-min')?.value || 120,
    weather_min: +document.getElementById('cfg-weather-min')?.value || 240,
    dk_splits_min: +document.getElementById('cfg-dk-min')?.value || 180,
    pitchers_min: +document.getElementById('cfg-pitchers-min')?.value || 60,
    live_predictions_min: +document.getElementById('cfg-pred-min')?.value || 10,
  };

  // Logging
  const log_level = document.getElementById('cfg-log-level')?.value || 'INFO';
  const log_lines = +document.getElementById('cfg-log-lines')?.value || 500;

  return { tiers, confidence_weights, pitcher_weights, betting, scheduler, log_level, log_lines };
}

async function saveConfig() {
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  try {
    const payload = collectConfig();
    await API.put('/api/config', payload);
    // Apply log level immediately
    if (payload.log_level) {
      await API.post('/api/logs/level', { level: payload.log_level });
    }
    cfg = payload;
    toast('Configuration saved!', 'success');
  } catch(e) {
    toast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '✓ Save Changes';
  }
}

async function resetConfig() {
  if (!confirm('Reset all settings to defaults?')) return;
  try {
    const d = await API.post('/api/config/reset');
    cfg = d.config;
    loadConfig();
    toast('Config reset to defaults', 'info');
  } catch(e) {
    toast('Reset failed: ' + e.message, 'error');
  }
}

loadConfig();
