/**
 * NFL Parlay Tracker — Chart.js helpers
 * All data fetched from /api/* endpoints (local DB only)
 */

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: true,
  plugins: {
    legend: { labels: { color: '#adb5bd', font: { size: 11 } } },
    tooltip: {
      backgroundColor: '#1a1a2e',
      borderColor: '#2a2a4a',
      borderWidth: 1,
      titleColor: '#f5a623',
      bodyColor: '#dee2e6',
    },
  },
  scales: {
    x: {
      ticks: { color: '#6c757d', font: { size: 10 } },
      grid: { color: 'rgba(255,255,255,0.05)' },
    },
    y: {
      ticks: { color: '#6c757d', font: { size: 10 } },
      grid: { color: 'rgba(255,255,255,0.05)' },
    },
  },
};

/** Fetch JSON from a local API endpoint and return parsed data. */
async function fetchData(url) {
  const resp = await fetch(url, { credentials: 'same-origin' });
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${url}`);
  return resp.json();
}

/** Render cumulative P&L line chart. */
async function fetchAndRenderPLChart(apiUrl, canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  try {
    const data = await fetchData(apiUrl);
    if (!data.length) {
      canvas.closest('.card-body').innerHTML = '<p class="text-muted text-center py-4">No completed parlays yet.</p>';
      return;
    }
    const labels = data.map(d => d.date || '');
    const values = data.map(d => d.cumulative_pl);
    const colors = values.map(v => v >= 0 ? 'rgba(74,222,128,0.8)' : 'rgba(248,113,113,0.8)');

    new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Cumulative P&L ($)',
          data: values,
          borderColor: '#f5a623',
          backgroundColor: 'rgba(245,166,35,0.1)',
          pointBackgroundColor: colors,
          pointRadius: 4,
          tension: 0.3,
          fill: true,
        }],
      },
      options: {
        ...CHART_DEFAULTS,
        plugins: {
          ...CHART_DEFAULTS.plugins,
          tooltip: {
            ...CHART_DEFAULTS.plugins.tooltip,
            callbacks: {
              label: ctx => `$${ctx.parsed.y.toFixed(2)}`,
            },
          },
        },
        scales: {
          ...CHART_DEFAULTS.scales,
          y: {
            ...CHART_DEFAULTS.scales.y,
            ticks: {
              ...CHART_DEFAULTS.scales.y.ticks,
              callback: v => '$' + v.toFixed(0),
            },
          },
        },
      },
    });
  } catch (e) {
    console.error('P&L chart error:', e);
  }
}

/** Render win rate by week bar chart. */
async function fetchAndRenderWinRateChart(apiUrl, canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  try {
    const data = await fetchData(apiUrl);
    if (!data.length) {
      canvas.closest('.card-body').innerHTML = '<p class="text-muted text-center py-4">No data yet.</p>';
      return;
    }
    new Chart(canvas, {
      type: 'bar',
      data: {
        labels: data.map(d => d.week),
        datasets: [{
          label: 'Win Rate %',
          data: data.map(d => d.win_rate),
          backgroundColor: data.map(d => d.win_rate >= 50 ? 'rgba(74,222,128,0.7)' : 'rgba(248,113,113,0.7)'),
          borderRadius: 4,
        }],
      },
      options: {
        ...CHART_DEFAULTS,
        scales: {
          ...CHART_DEFAULTS.scales,
          y: {
            ...CHART_DEFAULTS.scales.y,
            min: 0,
            max: 100,
            ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => v + '%' },
          },
        },
      },
    });
  } catch (e) {
    console.error('Win rate chart error:', e);
  }
}

/** Render a generic bar chart for stat leaders. */
function renderLeadersChart(canvasId, labels, values, label, color = '#f5a623') {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label, data: values, backgroundColor: color + 'bb', borderRadius: 4 }],
    },
    options: { ...CHART_DEFAULTS, indexAxis: 'y' },
  });
}

/** Drag-and-drop upload zone enhancement */
document.addEventListener('DOMContentLoaded', () => {
  const zone = document.querySelector('.upload-zone');
  const input = document.querySelector('input[type="file"]');
  if (!zone || !input) return;

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      zone.querySelector('.upload-label').textContent = e.dataTransfer.files[0].name;
    }
  });
  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => {
    const label = zone.querySelector('.upload-label');
    if (label && input.files.length) label.textContent = input.files[0].name;
  });
});
