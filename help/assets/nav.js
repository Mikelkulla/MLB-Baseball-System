/* Shared sidebar navigation — injected by each page */
const NAV_HTML = `
<div class="nav-section">Getting Started</div>
<a href="../index.html"><span class="icon">🏠</span> Home</a>
<a href="../overview/index.html"><span class="icon">🗺️</span> Architecture</a>
<a href="../pipeline/index.html"><span class="icon">⚙️</span> Pipeline</a>

<div class="nav-section">Engine</div>
<a href="../engine/probability.html"><span class="icon">📊</span> Probability</a>
<a href="../engine/ev.html"><span class="icon">💰</span> Expected Value</a>
<a href="../engine/confidence.html"><span class="icon">🎯</span> Confidence & Tiers</a>

<div class="nav-section">Adjustments</div>
<a href="../adjustments/pitcher.html"><span class="icon">⚾</span> Pitcher Scoring</a>
<a href="../adjustments/bullpen.html"><span class="icon">🔄</span> Bullpen Scoring</a>
<a href="../adjustments/injuries.html"><span class="icon">🏥</span> Injury Impact</a>
<a href="../adjustments/weather.html"><span class="icon">🌤️</span> Weather Impact</a>
<a href="../adjustments/park-factors.html"><span class="icon">🏟️</span> Park Factors</a>

<div class="nav-section">Data Sources</div>
<a href="../data-sources/index.html"><span class="icon">🔌</span> All Data Sources</a>

<div class="nav-section">Interface</div>
<a href="../web/index.html"><span class="icon">🌐</span> Web Pages & API</a>

<div class="nav-section">Reference</div>
<a href="../reference/index.html"><span class="icon">📋</span> Formula Reference</a>
`;

document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('.sidebar');
  if (sidebar) sidebar.innerHTML = NAV_HTML;

  // Mark active link
  const path = window.location.pathname.replace(/\\/g, '/');
  document.querySelectorAll('.sidebar a').forEach(a => {
    const href = a.getAttribute('href').replace(/\.\.\//g, '');
    if (path.endsWith(href.replace('../', ''))) {
      a.classList.add('active');
    }
  });
});
