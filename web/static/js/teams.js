/**
 * Team Registry — client-side logic for /teams
 *
 * - Loads all 30 team rows from GET /api/teams/registry
 * - Renders an editable table with source-name inputs and a lock toggle
 * - PATCH /api/teams/registry/{team_key} on Save (sets locked=1 server-side)
 * - POST  /api/teams/registry/{team_key}/lock to toggle lock
 * - POST  /api/teams/registry/reload to hot-reload the resolver
 */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────

/** @type {Array<Object>} */
let _teams = [];

// Source columns: API field name → display header (already in the <th>)
const SRC_FIELDS = ['odds_api_name', 'dk_name', 'mlb_stats_name', 'covers_name'];

// Division → CSS class suffix for the badge
const DIV_CLASS = {
  'AL East':    'al-east',
  'AL Central': 'al-central',
  'AL West':    'al-west',
  'NL East':    'nl-east',
  'NL Central': 'nl-central',
  'NL West':    'nl-west',
};

// ── Bootstrap ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', loadRegistry);

async function loadRegistry() {
  try {
    const data = await API.get('/api/teams/registry');
    _teams = data.teams || [];
    renderTable(_teams);
    document.getElementById('reg-info').textContent =
      `${_teams.length} teams  ·  ${_teams.filter(t => t.locked).length} locked`;
  } catch (e) {
    document.getElementById('reg-tbody').innerHTML =
      `<tr><td colspan="9" style="color:#f85149;text-align:center;padding:20px">Failed to load: ${e.message}</td></tr>`;
    document.getElementById('reg-info').textContent = 'Error';
  }
}

// ── Render ─────────────────────────────────────────────────────────────────────

function renderTable(teams) {
  const tbody = document.getElementById('reg-tbody');
  if (!teams.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:30px">No teams found</td></tr>';
    return;
  }
  tbody.innerHTML = teams.map(t => rowHTML(t)).join('');
}

function rowHTML(t) {
  const divClass = DIV_CLASS[t.division] || 'nl-east';
  const isLocked = !!t.locked;

  const srcInputs = SRC_FIELDS.map(field => `
    <td class="src-cell">
      <input
        type="text"
        id="inp-${t.team_key}-${field}"
        data-team="${t.team_key}"
        data-field="${field}"
        value="${escHtml(t[field] || '')}"
        ${isLocked ? '' : ''}
        oninput="markDirty('${t.team_key}', this)"
        onkeydown="handleKey(event, '${t.team_key}')"
        title="${isLocked ? 'Locked — click 🔒 to unlock before editing' : 'Type to edit, then click Save'}"
      >
    </td>`).join('');

  const lockIcon = isLocked ? '🔒' : '🔓';
  const lockClass = isLocked ? 'locked' : 'unlocked';
  const lockTitle = isLocked ? 'Locked (click to unlock)' : 'Unlocked (click to lock)';

  return `
    <tr id="row-${t.team_key}" class="${isLocked ? 'row-locked' : ''}">
      <td>
        <div class="team-cell">
          <span class="team-abbr">${escHtml(t.abbreviation)}</span>
          <span class="team-full">${escHtml(t.display_city)} ${escHtml(t.display_name)}</span>
        </div>
      </td>
      <td><span class="div-badge ${divClass}">${escHtml(t.division)}</span></td>
      ${srcInputs}
      <td class="src-cell">
        <input
          type="text"
          class="notes-input"
          id="inp-${t.team_key}-notes"
          data-team="${t.team_key}"
          data-field="notes"
          value="${escHtml(t.notes || '')}"
          oninput="markDirty('${t.team_key}', this)"
          onkeydown="handleKey(event, '${t.team_key}')"
          placeholder="—"
        >
      </td>
      <td class="lock-cell">
        <button
          class="lock-btn ${lockClass}"
          id="lock-btn-${t.team_key}"
          onclick="toggleLock('${t.team_key}', ${isLocked})"
          title="${lockTitle}"
        >${lockIcon}</button>
      </td>
      <td>
        <button
          class="save-btn"
          id="save-btn-${t.team_key}"
          onclick="saveRow('${t.team_key}')"
        >Save</button>
      </td>
    </tr>`;
}

// ── Interaction ────────────────────────────────────────────────────────────────

function markDirty(teamKey, inputEl) {
  inputEl.classList.add('dirty');
  const saveBtn = document.getElementById(`save-btn-${teamKey}`);
  if (saveBtn) saveBtn.classList.add('visible');
}

function handleKey(event, teamKey) {
  if (event.key === 'Enter') {
    event.preventDefault();
    saveRow(teamKey);
  }
  if (event.key === 'Escape') {
    event.target.blur();
    revertRow(teamKey);
  }
}

function revertRow(teamKey) {
  const team = _teams.find(t => t.team_key === teamKey);
  if (!team) return;
  [...SRC_FIELDS, 'notes'].forEach(field => {
    const inp = document.getElementById(`inp-${teamKey}-${field}`);
    if (inp) {
      inp.value = team[field] || '';
      inp.classList.remove('dirty');
    }
  });
  const saveBtn = document.getElementById(`save-btn-${teamKey}`);
  if (saveBtn) saveBtn.classList.remove('visible');
}

async function saveRow(teamKey) {
  const updates = {};
  [...SRC_FIELDS, 'notes'].forEach(field => {
    const inp = document.getElementById(`inp-${teamKey}-${field}`);
    if (inp && inp.classList.contains('dirty')) {
      updates[field] = inp.value.trim();
    }
  });

  if (!Object.keys(updates).length) return;

  // Visual feedback
  Object.keys(updates).forEach(field => {
    const inp = document.getElementById(`inp-${teamKey}-${field}`);
    if (inp) inp.classList.add('saving');
  });

  try {
    const result = await API.patch(`/api/teams/registry/${teamKey}`, updates);
    // Update local state
    const idx = _teams.findIndex(t => t.team_key === teamKey);
    if (idx >= 0) _teams[idx] = result.team;
    // Refresh this row
    refreshRow(result.team);
    toast(`Saved — ${teamKey} (locked)`, 'success');
    updateInfo();
  } catch (e) {
    Object.keys(updates).forEach(field => {
      const inp = document.getElementById(`inp-${teamKey}-${field}`);
      if (inp) inp.classList.remove('saving');
    });
    toast(`Save failed: ${e.message}`, 'error');
  }
}

async function toggleLock(teamKey, currentlyLocked) {
  const newLocked = !currentlyLocked;
  try {
    const result = await API.post(`/api/teams/registry/${teamKey}/lock`, { locked: newLocked });
    const idx = _teams.findIndex(t => t.team_key === teamKey);
    if (idx >= 0) _teams[idx] = result.team;
    refreshRow(result.team);
    toast(`${teamKey} ${newLocked ? 'locked 🔒' : 'unlocked 🔓'}`, 'success');
    updateInfo();
  } catch (e) {
    toast(`Lock toggle failed: ${e.message}`, 'error');
  }
}

async function reloadRegistry() {
  try {
    await API.post('/api/teams/registry/reload');
    toast('Resolver reloaded from registry', 'success');
  } catch (e) {
    toast(`Reload failed: ${e.message}`, 'error');
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Re-render a single row in-place after a save/lock change. */
function refreshRow(team) {
  const row = document.getElementById(`row-${team.team_key}`);
  if (!row) return;
  const tmp = document.createElement('tbody');
  tmp.innerHTML = rowHTML(team);
  row.replaceWith(tmp.firstElementChild);
}

function filterRows(query) {
  const q = query.toLowerCase();
  const filtered = q
    ? _teams.filter(t =>
        `${t.display_city} ${t.display_name} ${t.abbreviation} ${t.division}`.toLowerCase().includes(q) ||
        SRC_FIELDS.some(f => (t[f] || '').toLowerCase().includes(q))
      )
    : _teams;
  renderTable(filtered);
}

function updateInfo() {
  document.getElementById('reg-info').textContent =
    `${_teams.length} teams  ·  ${_teams.filter(t => t.locked).length} locked`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// API.patch is defined in api.js (loaded via base.html before this file).
