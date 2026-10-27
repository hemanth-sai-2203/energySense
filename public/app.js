/**
 * EnergySense India — Interactive Analytical Engine & UI Controller
 * High-performance Canvas Charting, SQLite REST integration, Data Analysis
 */

// Application State
const state = {
  dailyData: [],
  filteredDaily: [],
  generationData: [],
  statesData: [],
  stateCapacities: [],
  insights: null,
  activeTab: 'tabDemand',
  demandMetric: 'peak_met_mw',
  demandYear: 'all',
  showMovingAvg: true,
  genView: 'stacked',
  stateYear: '2023',
  selectedState: 'Maharashtra',
  stateSearchQuery: '',
  forecastTarget: 'energy_met_mu',
  forecastHorizon: 7,
  forecastOrigin: '2024-04-28',
  forecastData: null,
  forecastLoading: false
};

// Colors mapping
const COLORS = {
  cyan: '#38bdf8',
  blue: '#3b82f6',
  emerald: '#10b981',
  amber: '#f59e0b',
  purple: '#a855f7',
  rose: '#f43f5e',
  orange: '#f97316',
  coal: '#64748b',
  gas: '#ea580c',
  hydro: '#2563eb',
  solar: '#eab308',
  wind: '#06b6d4',
  nuclear: '#9333ea',
  bioenergy: '#059669',
  gridLine: 'rgba(255, 255, 255, 0.07)',
  axisText: '#94a3b8'
};

// Initialize Application
document.addEventListener('DOMContentLoaded', async () => {
  setupNavigation();
  setupDemandControls();
  setupGenControls();
  setupStateControls();
  setupSqlSandbox();
  setupRefresh();
  setupForecastControls();

  // Load Initial Datasets concurrently for optimal page load speed
  await Promise.allSettled([
    loadAnalytics(),
    loadDailyData(),
    loadGenerationData(),
    loadStatesData(),
    loadCapacities(),
    loadForecastData()
  ]);

  renderAllViews();
  setupResizeListener();
});

// -------------------------------------------------------------
// 1. Navigation & Tab Switching
// -------------------------------------------------------------
function setupNavigation() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetPanel = document.getElementById(tab.dataset.tab);
      if (targetPanel) {
        targetPanel.classList.add('active');
        state.activeTab = tab.dataset.tab;
        
        // Re-render canvas for the newly active panel so dimensions match
        requestAnimationFrame(() => {
          if (state.activeTab === 'tabDemand') renderDemandChart();
          else if (state.activeTab === 'tabForecast') renderForecastChart();
          else if (state.activeTab === 'tabClimate') { renderClimateChart(); renderClimateScatter(); }
          else if (state.activeTab === 'tabGeneration') renderGenChart();
          else if (state.activeTab === 'tabStates') renderStateDetail();
        });
      }
    });
  });

  document.getElementById('btnHeaderSQL')?.addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('tabBtnSql')?.click();
  });
}

// -------------------------------------------------------------
// 2. Data Fetching API with Static File Fallback
// -------------------------------------------------------------
async function fetchJsonWithFallback(apiUrl, fallbackUrl) {
  try {
    const res = await fetch(apiUrl);
    if (res.ok) return await res.json();
  } catch (err) {}
  if (fallbackUrl) {
    try {
      const res = await fetch(fallbackUrl);
      if (res.ok) return await res.json();
    } catch (err) {
      console.warn(`Fallback fetch error for ${fallbackUrl}:`, err);
    }
  }
  return null;
}

async function loadAnalytics() {
  const data = await fetchJsonWithFallback('/api/analytics', './data/insights_analytics.json');
  if (data) {
    state.insights = data;
    updateKpiCards();
  }
}

async function loadDailyData() {
  const data = await fetchJsonWithFallback('/api/daily', './data/daily_demand_india.json');
  if (data) {
    state.dailyData = data;
    filterDailyData();
  }
}

async function loadGenerationData() {
  const data = await fetchJsonWithFallback('/api/generation', './data/monthly_generation_india.json');
  if (data) {
    state.generationData = data;
  }
}

async function loadStatesData() {
  const yr = parseInt(state.stateYear, 10);
  let data = await fetchJsonWithFallback(`/api/states?year=${state.stateYear}`, './data/state_annual_summary.json');
  if (data) {
    if (Array.isArray(data) && data.length > 0 && data[0].year !== undefined && data[0].year !== yr) {
      data = data.filter(s => s.year === yr).sort((a, b) => b.total_energy_mu - a.total_energy_mu);
    }
    state.statesData = data;
    renderStatesTable();
    renderStateDetail();
  }
}

async function loadCapacities() {
  const data = await fetchJsonWithFallback('/api/capacity', './data/state_capacity_latest.json');
  if (data) {
    state.stateCapacities = data;
    renderStateCapacity();
  }
}

function updateKpiCards() {
  if (!state.insights) return;
  const ins = state.insights;
  
  if (ins.all_time_peak_met) {
    document.getElementById('valPeakMet').textContent = ins.all_time_peak_met.peak_met_mw.toLocaleString();
    document.getElementById('datePeakMet').textContent = `${ins.all_time_peak_met.date} • All-Time Record`;
  }
  if (ins.all_time_daily_energy_met) {
    document.getElementById('valDailyEnergy').textContent = ins.all_time_daily_energy_met.energy_met_mu.toLocaleString();
    document.getElementById('dateDailyEnergy').textContent = `${ins.all_time_daily_energy_met.date} • Record Met`;
  }
  if (ins.growth_10yr_cagr) {
    document.getElementById('valCAGR').textContent = `+${ins.growth_10yr_cagr.cagr_pct}%`;
  }
  if (ins.grid_reliability_progress) {
    document.getElementById('valDeficit').textContent = `-${ins.grid_reliability_progress.deficit_reduction_pct}%`;
  }
  if (ins.clean_energy_milestones) {
    document.getElementById('valSolarSurge').textContent = `${ins.clean_energy_milestones.solar_expansion_multiplier}x`;
  }
  if (ins.covid_lockdown_impact) {
    document.getElementById('valCovidShock').textContent = `${ins.covid_lockdown_impact.lockdown_drop_pct}%`;
  }
}

function setupRefresh() {
  document.getElementById('btnRefresh')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnRefresh');
    btn.style.transform = 'rotate(180deg)';
    await loadAnalytics();
    await loadDailyData();
    renderAllViews();
    setTimeout(() => { btn.style.transform = 'none'; }, 300);
  });
}

// -------------------------------------------------------------
// 3. Tab 1: Demand & Peak Load Canvas Chart
// -------------------------------------------------------------
function setupDemandControls() {
  // Metric buttons
  const metricBtns = document.querySelectorAll('#demandMetricGroup .btn-pill');
  metricBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      metricBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.demandMetric = btn.dataset.metric;
      renderDemandChart();
    });
  });

  // Moving average toggle
  const chkMa = document.getElementById('chkMovingAvg');
  if (chkMa) {
    chkMa.addEventListener('change', () => {
      state.showMovingAvg = chkMa.checked;
      renderDemandChart();
    });
  }

  // Year buttons
  const yearBtns = document.querySelectorAll('#yearSelectorBar .btn-year');
  yearBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      yearBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.demandYear = btn.dataset.year;
      filterDailyData();
      renderDemandChart();
    });
  });
}

function filterDailyData() {
  if (state.demandYear === 'all') {
    state.filteredDaily = state.dailyData;
  } else {
    const yr = parseInt(state.demandYear, 10);
    state.filteredDaily = state.dailyData.filter(d => d.year === yr);
  }
  updateDemandSummaryBar();
}

function updateDemandSummaryBar() {
  if (!state.filteredDaily || state.filteredDaily.length === 0) return;
  const vals = state.filteredDaily.map(d => d[state.demandMetric] || 0);
  const maxVal = Math.max(...vals);
  const minVal = Math.min(...vals);
  const avgVal = vals.reduce((a, b) => a + b, 0) / vals.length;
  const deficits = state.filteredDaily.map(d => d.peak_unmet_mw || 0);
  const maxDeficit = Math.max(...deficits);

  const unit = state.demandMetric.includes('mw') ? ' MW' : (state.demandMetric.includes('mu') ? ' MU' : ' %');
  document.getElementById('sumPeriodMax').textContent = maxVal.toLocaleString(undefined, { maximumFractionDigits: 1 }) + unit;
  document.getElementById('sumPeriodMin').textContent = minVal.toLocaleString(undefined, { maximumFractionDigits: 1 }) + unit;
  document.getElementById('sumPeriodAvg').textContent = avgVal.toLocaleString(undefined, { maximumFractionDigits: 1 }) + unit;
  document.getElementById('sumPeriodDeficit').textContent = maxDeficit.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' MW';
}

function renderDemandChart() {
  const canvas = document.getElementById('demandChartCanvas');
  const tooltip = document.getElementById('demandChartTooltip');
  if (!canvas || !state.filteredDaily || state.filteredDaily.length === 0) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 25, right: 30, bottom: 40, left: 65 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);

  const metric = state.demandMetric;
  const values = state.filteredDaily.map(d => d[metric] || 0);
  const minV = 0;
  const maxV = Math.max(...values) * 1.12 || 100;

  // Draw Grid Lines & Y-Axis Labels
  ctx.strokeStyle = COLORS.gridLine;
  ctx.fillStyle = COLORS.axisText;
  ctx.font = '10px JetBrains Mono';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';

  const yTicks = 5;
  for (let i = 0; i <= yTicks; i++) {
    const val = minV + (maxV - minV) * (i / yTicks);
    const y = padding.top + chartH - (i / yTicks) * chartH;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillText(val >= 1000 ? Math.round(val).toLocaleString() : val.toFixed(1), padding.left - 10, y);
  }

  // Draw X-Axis Ticks
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const dataLen = state.filteredDaily.length;
  const xTicks = Math.min(8, dataLen);
  for (let i = 0; i < xTicks; i++) {
    const idx = Math.floor(i * (dataLen - 1) / (xTicks - 1));
    const d = state.filteredDaily[idx];
    const x = padding.left + (idx / (dataLen - 1)) * chartW;
    ctx.fillText(d.date.substring(0, 7), x, height - padding.bottom + 10);
  }

  // Draw Metric Gradient Fill Area
  const grad = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
  let mainColor = COLORS.cyan;
  if (metric === 'energy_met_mu') mainColor = COLORS.blue;
  else if (metric === 'peak_unmet_mw') mainColor = COLORS.purple;
  else if (metric === 'deficit_pct') mainColor = COLORS.rose;

  grad.addColorStop(0, mainColor + '40');
  grad.addColorStop(1, mainColor + '00');

  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top + chartH);
  for (let i = 0; i < dataLen; i++) {
    const x = padding.left + (i / (dataLen - 1)) * chartW;
    const y = padding.top + chartH - ((values[i] - minV) / (maxV - minV)) * chartH;
    ctx.lineTo(x, y);
  }
  ctx.lineTo(padding.left + chartW, padding.top + chartH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Draw Main Line
  ctx.beginPath();
  ctx.strokeStyle = mainColor;
  ctx.lineWidth = dataLen > 500 ? 1.2 : 2;
  for (let i = 0; i < dataLen; i++) {
    const x = padding.left + (i / (dataLen - 1)) * chartW;
    const y = padding.top + chartH - ((values[i] - minV) / (maxV - minV)) * chartH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Draw 7-Day Moving Average Line (if enabled and applicable)
  if (state.showMovingAvg && (metric === 'peak_met_mw' || metric === 'energy_met_mu')) {
    const maKey = metric === 'peak_met_mw' ? 'peak_7d_avg' : 'energy_7d_avg';
    ctx.beginPath();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.8;
    ctx.setLineDash([4, 4]);
    for (let i = 0; i < dataLen; i++) {
      const maVal = state.filteredDaily[i][maKey] || values[i];
      const x = padding.left + (i / (dataLen - 1)) * chartW;
      const y = padding.top + chartH - ((maVal - minV) / (maxV - minV)) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Interactive Hover Handler
  canvas.onmousemove = (e) => {
    const mRect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - mRect.left;
    if (mouseX >= padding.left && mouseX <= width - padding.right) {
      const ratio = (mouseX - padding.left) / chartW;
      const idx = Math.min(dataLen - 1, Math.max(0, Math.round(ratio * (dataLen - 1))));
      const item = state.filteredDaily[idx];
      const val = item[metric];
      const posX = padding.left + (idx / (dataLen - 1)) * chartW;
      const posY = padding.top + chartH - ((val - minV) / (maxV - minV)) * chartH;

      tooltip.innerHTML = `
        <div class="tt-date">${item.date} (${item.day_of_week})</div>
        <div class="tt-row"><span class="tt-label">Peak Met:</span> <span class="tt-val text-cyan">${item.peak_met_mw.toLocaleString()} MW</span></div>
        <div class="tt-row"><span class="tt-label">Daily Energy:</span> <span class="tt-val text-blue">${item.energy_met_mu.toLocaleString()} MU</span></div>
        <div class="tt-row"><span class="tt-label">Deficit:</span> <span class="tt-val text-rose">${item.peak_unmet_mw.toLocaleString()} MW (${item.deficit_pct}%)</span></div>
        ${item.utci_celsius !== null ? `<div class="tt-row"><span class="tt-label">UTCI Temp:</span> <span class="tt-val text-amber">${item.utci_celsius}°C</span></div>` : ''}
      `;
      tooltip.style.left = `${posX}px`;
      tooltip.style.top = `${posY}px`;
      tooltip.classList.add('visible');
    }
  };

  canvas.onmouseleave = () => {
    tooltip.classList.remove('visible');
  };
}

// -------------------------------------------------------------
// 4. Tab 2: Climate & Heat Elasticity Charts
// -------------------------------------------------------------
function renderClimateChart() {
  const canvas = document.getElementById('climateChartCanvas');
  const tooltip = document.getElementById('climateChartTooltip');
  if (!canvas || !state.dailyData || state.dailyData.length === 0) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 25, right: 55, bottom: 35, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);

  // Filter 2 years of climate + demand for clear visual correlation (e.g. 2019-2020)
  const subset = state.dailyData.filter(d => d.year === 2019 && d.utci_celsius !== null);
  if (subset.length === 0) return;

  const peakVals = subset.map(d => d.peak_met_mw);
  const utciVals = subset.map(d => d.utci_celsius);

  const minPeak = Math.min(...peakVals) * 0.95;
  const maxPeak = Math.max(...peakVals) * 1.05;
  const minUtci = Math.min(...utciVals) - 2;
  const maxUtci = Math.max(...utciVals) + 2;

  // Grid
  ctx.strokeStyle = COLORS.gridLine;
  ctx.fillStyle = COLORS.axisText;
  ctx.font = '10px JetBrains Mono';

  // Left Y-axis (Peak MW)
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {
    const val = minPeak + (maxPeak - minPeak) * (i / 4);
    const y = padding.top + chartH - (i / 4) * chartH;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillText(`${Math.round(val / 1000)}k`, padding.left - 8, y);
  }

  // Right Y-axis (UTCI °C)
  ctx.textAlign = 'left';
  for (let i = 0; i <= 4; i++) {
    const val = minUtci + (maxUtci - minUtci) * (i / 4);
    const y = padding.top + chartH - (i / 4) * chartH;
    ctx.fillText(`${Math.round(val)}°C`, width - padding.right + 8, y);
  }

  // Draw UTCI Line (Amber)
  ctx.beginPath();
  ctx.strokeStyle = COLORS.amber;
  ctx.lineWidth = 1.8;
  for (let i = 0; i < subset.length; i++) {
    const x = padding.left + (i / (subset.length - 1)) * chartW;
    const y = padding.top + chartH - ((subset[i].utci_celsius - minUtci) / (maxUtci - minUtci)) * chartH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Draw Peak MW Line (Cyan)
  ctx.beginPath();
  ctx.strokeStyle = COLORS.cyan;
  ctx.lineWidth = 1.8;
  for (let i = 0; i < subset.length; i++) {
    const x = padding.left + (i / (subset.length - 1)) * chartW;
    const y = padding.top + chartH - ((subset[i].peak_met_mw - minPeak) / (maxPeak - minPeak)) * chartH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function renderClimateScatter() {
  const canvas = document.getElementById('climateScatterCanvas');
  if (!canvas || !state.dailyData) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 20, right: 20, bottom: 35, left: 55 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);

  // Sample points with valid UTCI
  const sample = state.dailyData.filter((d, i) => d.utci_celsius !== null && i % 4 === 0);
  if (sample.length === 0) return;

  const minX = 12; // UTCI deg C
  const maxX = 38;
  const minY = 100000; // MW
  const maxY = 220000;

  // Grid
  ctx.strokeStyle = COLORS.gridLine;
  ctx.fillStyle = COLORS.axisText;
  ctx.font = '9px JetBrains Mono';
  ctx.textAlign = 'right';

  for (let i = 0; i <= 3; i++) {
    const yVal = minY + (maxY - minY) * (i / 3);
    const y = padding.top + chartH - (i / 3) * chartH;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillText(`${Math.round(yVal / 1000)}k MW`, padding.left - 6, y);
  }

  // X-axis labels
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let xV = 15; xV <= 35; xV += 5) {
    const x = padding.left + ((xV - minX) / (maxX - minX)) * chartW;
    ctx.fillText(`${xV}°C`, x, height - padding.bottom + 8);
  }

  // Scatter dots
  sample.forEach(pt => {
    const x = padding.left + ((pt.utci_celsius - minX) / (maxX - minX)) * chartW;
    const y = padding.top + chartH - ((pt.peak_met_mw - minY) / (maxY - minY)) * chartH;
    if (x >= padding.left && x <= width - padding.right && y >= padding.top && y <= height - padding.bottom) {
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.fillStyle = pt.utci_celsius > 30 ? 'rgba(245, 158, 11, 0.4)' : 'rgba(56, 189, 248, 0.3)';
      ctx.fill();
    }
  });

  // Trend line (+199.7 MW/°C)
  const x1 = minX;
  const y1 = 125000;
  const x2 = maxX;
  const y2 = y1 + (x2 - x1) * 199.7 * 10; // trend visual

  const px1 = padding.left;
  const py1 = padding.top + chartH - ((y1 - minY) / (maxY - minY)) * chartH;
  const px2 = width - padding.right;
  const py2 = padding.top + chartH - ((y2 - minY) / (maxY - minY)) * chartH;

  ctx.beginPath();
  ctx.strokeStyle = COLORS.amber;
  ctx.lineWidth = 2;
  ctx.moveTo(px1, py1);
  ctx.lineTo(px2, py2);
  ctx.stroke();
}

// -------------------------------------------------------------
// 5. Tab 3: Monthly Fuel Generation & Decarbonization
// -------------------------------------------------------------
function setupGenControls() {
  const btns = document.querySelectorAll('#genViewToggle .btn-pill');
  btns.forEach(btn => {
    btn.addEventListener('click', () => {
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.genView = btn.dataset.gen;
      renderGenChart();
    });
  });
}

function renderGenChart() {
  const canvas = document.getElementById('genChartCanvas');
  const tooltip = document.getElementById('genChartTooltip');
  if (!canvas || !state.generationData || state.generationData.length === 0) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 25, right: 30, bottom: 40, left: 65 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);

  const genData = state.generationData;
  const count = genData.length;

  if (state.genView === 'stacked') {
    // Stacked Fuels (Coal, Solar, Wind, Hydro, Nuclear, Gas, Bioenergy)
    const fuels = [
      { key: 'coal_gwh', color: COLORS.coal, label: 'Coal' },
      { key: 'gas_gwh', color: COLORS.gas, label: 'Gas' },
      { key: 'nuclear_gwh', color: COLORS.nuclear, label: 'Nuclear' },
      { key: 'hydro_gwh', color: COLORS.hydro, label: 'Hydro' },
      { key: 'wind_gwh', color: COLORS.wind, label: 'Wind' },
      { key: 'solar_gwh', color: COLORS.solar, label: 'Solar' },
      { key: 'bioenergy_gwh', color: COLORS.bioenergy, label: 'Bioenergy' }
    ];

    const maxTotal = Math.max(...genData.map(d => d.total_gwh)) * 1.08;

    // Y-Axis Grid
    ctx.strokeStyle = COLORS.gridLine;
    ctx.fillStyle = COLORS.axisText;
    ctx.font = '10px JetBrains Mono';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const val = (maxTotal * (i / 4));
      const y = padding.top + chartH - (i / 4) * chartH;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.fillText(`${Math.round(val / 1000)} TWh`, padding.left - 8, y);
    }

    // Draw Stacked Bars
    const barWidth = Math.max(3, (chartW / count) * 0.75);
    for (let i = 0; i < count; i++) {
      const d = genData[i];
      const x = padding.left + (i / (count - 1)) * (chartW - barWidth);
      let currentY = padding.top + chartH;

      for (let f = 0; f < fuels.length; f++) {
        const val = d[fuels[f].key] || 0;
        const barH = (val / maxTotal) * chartH;
        ctx.fillStyle = fuels[f].color;
        ctx.fillRect(x, currentY - barH, barWidth, barH);
        currentY -= barH;
      }
    }

    // X-Axis Year Labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i < count; i += 12) {
      const x = padding.left + (i / (count - 1)) * chartW;
      ctx.fillText(genData[i].date.substring(0, 4), x, height - padding.bottom + 10);
    }

  } else if (state.genView === 'shares') {
    // Clean Share vs Fossil Share Lines
    ctx.strokeStyle = COLORS.gridLine;
    ctx.fillStyle = COLORS.axisText;
    ctx.font = '10px JetBrains Mono';
    ctx.textAlign = 'right';

    for (let p = 0; p <= 100; p += 25) {
      const y = padding.top + chartH - (p / 100) * chartH;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.fillText(`${p}%`, padding.left - 8, y);
    }

    // Clean Share Line (Emerald)
    ctx.beginPath();
    ctx.strokeStyle = COLORS.emerald;
    ctx.lineWidth = 2.5;
    for (let i = 0; i < count; i++) {
      const x = padding.left + (i / (count - 1)) * chartW;
      const y = padding.top + chartH - (genData[i].clean_share_pct / 100) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Solar + Wind Share Line (Amber)
    ctx.beginPath();
    ctx.strokeStyle = COLORS.amber;
    ctx.lineWidth = 2;
    for (let i = 0; i < count; i++) {
      const x = padding.left + (i / (count - 1)) * chartW;
      const y = padding.top + chartH - (genData[i].solar_wind_share_pct / 100) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

  } else if (state.genView === 'emissions') {
    // Emissions Intensity (gCO2/kWh)
    const maxIntensity = 850;
    const minIntensity = 650;

    ctx.strokeStyle = COLORS.gridLine;
    ctx.fillStyle = COLORS.axisText;
    ctx.font = '10px JetBrains Mono';
    ctx.textAlign = 'right';

    for (let i = 0; i <= 4; i++) {
      const val = minIntensity + (maxIntensity - minIntensity) * (i / 4);
      const y = padding.top + chartH - (i / 4) * chartH;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.fillText(`${Math.round(val)} g`, padding.left - 8, y);
    }

    ctx.beginPath();
    ctx.strokeStyle = COLORS.purple;
    ctx.lineWidth = 2.5;
    for (let i = 0; i < count; i++) {
      const val = genData[i].carbon_intensity_gco2_kwh || 750;
      const x = padding.left + (i / (count - 1)) * chartW;
      const y = padding.top + chartH - ((val - minIntensity) / (maxIntensity - minIntensity)) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}

// -------------------------------------------------------------
// 6. Tab 4: State Matrix & Deep Dive
// -------------------------------------------------------------
function setupStateControls() {
  const selectYear = document.getElementById('stateYearSelect');
  if (selectYear) {
    selectYear.addEventListener('change', async () => {
      state.stateYear = selectYear.value;
      await loadStatesData();
    });
  }

  const searchInput = document.getElementById('stateSearchInput');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      state.stateSearchQuery = e.target.value.toLowerCase();
      renderStatesTable();
    });
  }
}

function renderStatesTable() {
  const tbody = document.getElementById('statesTableBody');
  if (!tbody || !state.statesData) return;

  const filtered = state.statesData.filter(s => 
    s.state.toLowerCase().includes(state.stateSearchQuery)
  );

  tbody.innerHTML = '';
  filtered.forEach((st, idx) => {
    const tr = document.createElement('tr');
    if (st.state === state.selectedState) tr.classList.add('selected-row');

    tr.innerHTML = `
      <td class="text-muted font-mono">#${idx + 1}</td>
      <td class="font-bold text-white">${st.state}</td>
      <td class="text-right font-mono text-cyan">${st.total_energy_mu.toLocaleString()}</td>
      <td class="text-right font-mono text-emerald">${st.peak_demand_mw.toLocaleString()}</td>
      <td class="text-right font-mono text-muted">${st.avg_daily_mu}</td>
      <td class="text-muted font-mono">${st.peak_date || '--'}</td>
    `;

    tr.addEventListener('click', () => {
      document.querySelectorAll('#statesTableBody tr').forEach(r => r.classList.remove('selected-row'));
      tr.classList.add('selected-row');
      state.selectedState = st.state;
      renderStateDetail();
    });

    tbody.appendChild(tr);
  });
}

async function renderStateDetail() {
  const stateName = state.selectedState;
  document.getElementById('detailStateName').textContent = stateName;

  const currentSt = state.statesData.find(s => s.state === stateName);
  if (currentSt) {
    document.getElementById('detailStateEnergy').textContent = `${currentSt.total_energy_mu.toLocaleString()} MU`;
    document.getElementById('detailStatePeak').textContent = `${currentSt.peak_demand_mw.toLocaleString()} MW`;
    document.getElementById('detailStateDaily').textContent = `${currentSt.avg_daily_mu} MU/day`;
  }

  // Fetch full state annual trend for mini canvas
  try {
    const res = await fetch(`/api/states?year=all`);
    if (res.ok) {
      const allStates = await res.json();
      const stateHistory = allStates.filter(s => s.state === stateName).sort((a, b) => a.year - b.year);
      renderStateTrendCanvas(stateHistory);
    }
  } catch (e) {
    console.warn('State history fetch error:', e);
  }

  renderStateCapacity();
}

function renderStateTrendCanvas(history) {
  const canvas = document.getElementById('stateTrendCanvas');
  if (!canvas || !history || history.length === 0) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const pad = { top: 15, right: 15, bottom: 25, left: 45 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;

  ctx.clearRect(0, 0, width, height);

  const values = history.map(h => h.total_energy_mu);
  const minV = Math.min(...values) * 0.9;
  const maxV = Math.max(...values) * 1.1;

  ctx.strokeStyle = COLORS.gridLine;
  ctx.fillStyle = COLORS.axisText;
  ctx.font = '9px JetBrains Mono';
  ctx.textAlign = 'right';

  // Grid
  for (let i = 0; i <= 2; i++) {
    const y = pad.top + chartH - (i / 2) * chartH;
    const v = minV + (maxV - minV) * (i / 2);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillText(v >= 1000 ? `${Math.round(v / 1000)}k` : Math.round(v), pad.left - 6, y);
  }

  // Line
  ctx.beginPath();
  ctx.strokeStyle = COLORS.cyan;
  ctx.lineWidth = 2;
  for (let i = 0; i < history.length; i++) {
    const x = pad.left + (i / (history.length - 1)) * chartW;
    const y = pad.top + chartH - ((values[i] - minV) / (maxV - minV)) * chartH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Dots
  history.forEach((h, i) => {
    const x = pad.left + (i / (history.length - 1)) * chartW;
    const y = pad.top + chartH - ((values[i] - minV) / (maxV - minV)) * chartH;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.cyan;
    ctx.fill();
  });
}

function renderStateCapacity() {
  const container = document.getElementById('stateCapacityMix');
  if (!container || !state.stateCapacities) return;

  const cap = state.stateCapacities.find(c => c.state === state.selectedState);
  if (!cap || cap.total_mw === 0) {
    container.innerHTML = '<span class="text-dim font-mono text-xs">No capacity breakdown available for this state.</span>';
    return;
  }

  const fuels = [
    { name: 'Coal', val: cap.coal_mw, color: COLORS.coal },
    { name: 'Solar', val: cap.solar_mw, color: COLORS.solar },
    { name: 'Wind', val: cap.wind_mw, color: COLORS.wind },
    { name: 'Hydro', val: cap.hydro_mw, color: COLORS.hydro },
    { name: 'Gas', val: cap.gas_mw, color: COLORS.gas },
    { name: 'Nuclear', val: cap.nuclear_mw, color: COLORS.nuclear },
    { name: 'Bioenergy', val: cap.bioenergy_mw, color: COLORS.bioenergy }
  ].filter(f => f.val > 0);

  container.innerHTML = '';
  fuels.forEach(f => {
    const pct = ((f.val / cap.total_mw) * 100).toFixed(1);
    const item = document.createElement('div');
    item.className = 'cap-bar-item';
    item.innerHTML = `
      <div class="cap-bar-info">
        <span>${f.name}</span>
        <span class="font-mono">${f.val.toLocaleString()} MW (${pct}%)</span>
      </div>
      <div class="cap-bar-track">
        <div class="cap-bar-fill" style="width: ${pct}%; background: ${f.color};"></div>
      </div>
    `;
    container.appendChild(item);
  });
}

// -------------------------------------------------------------
// 7. Tab 6: Interactive SQLite Query Sandbox
// -------------------------------------------------------------
function setupSqlSandbox() {
  const btnRun = document.getElementById('btnRunSql');
  const sqlInput = document.getElementById('sqlInput');
  const status = document.getElementById('sqlExecutionStatus');

  btnRun?.addEventListener('click', async () => {
    const query = sqlInput.value.trim();
    if (!query) return;

    status.textContent = 'Executing query...';
    status.style.color = COLORS.cyan;
    const t0 = performance.now();

    try {
      const res = await fetch('/api/sql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      });
      if (res.ok) {
        const data = await res.json();
        const elapsed = (performance.now() - t0).toFixed(1);

        if (data.error) {
          status.textContent = `Error: ${data.error}`;
          status.style.color = COLORS.rose;
        } else {
          status.textContent = `SQLite returned ${data.count} rows in ${elapsed} ms`;
          status.style.color = COLORS.emerald;
          renderSqlResults(data.columns, data.rows);
          return;
        }
      }
    } catch (e) {}

    // Fallback: In-browser Client SQL Engine
    try {
      const clientRes = executeClientSql(query);
      const elapsed = (performance.now() - t0).toFixed(1);
      if (clientRes.error) {
        status.textContent = `Query Error: ${clientRes.error}`;
        status.style.color = COLORS.rose;
      } else {
        status.textContent = `In-Browser Engine returned ${clientRes.count} rows in ${elapsed} ms`;
        status.style.color = COLORS.emerald;
        renderSqlResults(clientRes.columns, clientRes.rows);
      }
    } catch (err) {
      status.textContent = `SQL Execution Error: ${err.message}`;
      status.style.color = COLORS.rose;
    }
  });

  // Preset chips
  const presets = document.querySelectorAll('.btn-preset');
  presets.forEach(p => {
    p.addEventListener('click', () => {
      sqlInput.value = p.dataset.sql;
      btnRun.click();
    });
  });
}

function executeClientSql(query) {
  let q = query.trim();
  let source = state.dailyData;
  if (/from\s+state_annual_summary/i.test(q)) source = state.statesData;
  else if (/from\s+monthly_generation/i.test(q)) source = state.generationData;
  
  if (!source || source.length === 0) return { error: "No data loaded yet for query" };

  const matchCols = q.match(/select\s+(.*?)\s+from/i);
  if (!matchCols) return { error: "Invalid SELECT query structure" };
  const colStr = matchCols[1].trim();
  const selectAll = colStr === "*";
  const reqCols = selectAll ? Object.keys(source[0]) : colStr.split(",").map(c => c.trim().toLowerCase());

  let working = [...source];

  // ORDER BY
  const matchOrder = q.match(/order\s+by\s+([a-zA-Z0-9_]+)(\s+(asc|desc))?/i);
  if (matchOrder) {
    const orderCol = matchOrder[1].toLowerCase();
    const isDesc = matchOrder[3] && matchOrder[3].toLowerCase() === "desc";
    working.sort((a, b) => {
      const va = a[orderCol] ?? 0;
      const vb = b[orderCol] ?? 0;
      return isDesc ? (vb > va ? 1 : -1) : (va > vb ? 1 : -1);
    });
  }

  // LIMIT
  const matchLimit = q.match(/limit\s+(\d+)/i);
  const limitN = matchLimit ? parseInt(matchLimit[1], 10) : 50;
  working = working.slice(0, limitN);

  const columns = reqCols;
  const rows = working.map(item => reqCols.map(col => item[col] ?? ""));
  return { columns, rows, count: rows.length };
}

function renderSqlResults(columns, rows) {
  const thead = document.getElementById('sqlResultsHead');
  const tbody = document.getElementById('sqlResultsBody');
  if (!thead || !tbody) return;

  thead.innerHTML = '';
  tbody.innerHTML = '';

  const trHead = document.createElement('tr');
  columns.forEach(col => {
    const th = document.createElement('th');
    th.textContent = col;
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">0 rows returned.</td></tr>';
    return;
  }

  rows.forEach(r => {
    const tr = document.createElement('tr');
    r.forEach(val => {
      const td = document.createElement('td');
      td.textContent = (val !== null && val !== undefined) ? val : 'NULL';
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

// -------------------------------------------------------------
// 8. General Helpers
// -------------------------------------------------------------
function renderAllViews() {
  renderDemandChart();
  renderForecastChart();
  renderClimateChart();
  renderClimateScatter();
  renderGenChart();
  renderStatesTable();
  renderStateDetail();
}

function setupResizeListener() {
  let timer;
  window.addEventListener('resize', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      renderAllViews();
    }, 150);
  });
}

// -------------------------------------------------------------
// 9. Tab Forecast: AI Forecasting Engine & Canvas Chart
// -------------------------------------------------------------
function setupForecastControls() {
  // Target buttons (Energy Met vs Peak Met)
  const targetBtns = document.querySelectorAll('#forecastTargetGroup .btn-pill');
  targetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      targetBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.forecastTarget = btn.dataset.target;
      loadForecastData();
    });
  });

  // Horizon buttons (1, 3, 5, 7 days)
  const horizonBtns = document.querySelectorAll('#forecastHorizonGroup .btn-pill');
  horizonBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      horizonBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.forecastHorizon = parseInt(btn.dataset.horizon, 10);
      loadForecastData();
    });
  });

  // Origin input date
  const inputOrigin = document.getElementById('inputForecastOrigin');
  if (inputOrigin) {
    inputOrigin.addEventListener('change', (e) => {
      state.forecastOrigin = e.target.value;
      const presetSelect = document.getElementById('selectOriginPreset');
      if (presetSelect) presetSelect.value = e.target.value;
    });
  }

  // Preset dropdown
  const selectPreset = document.getElementById('selectOriginPreset');
  if (selectPreset) {
    selectPreset.addEventListener('change', (e) => {
      state.forecastOrigin = e.target.value;
      if (inputOrigin) inputOrigin.value = e.target.value;
      loadForecastData();
    });
  }

  // Run Forecast button
  const btnRun = document.getElementById('btnRunForecast');
  if (btnRun) {
    btnRun.addEventListener('click', () => {
      if (inputOrigin) state.forecastOrigin = inputOrigin.value;
      loadForecastData();
    });
  }
}

async function loadForecastData() {
  const errorBox = document.getElementById('forecastErrorBox');
  const btnRun = document.getElementById('btnRunForecast');
  if (btnRun) {
    btnRun.disabled = true;
    btnRun.style.opacity = '0.6';
  }

  try {
    const url = `/api/forecast?target=${state.forecastTarget}&origin=${state.forecastOrigin}&horizon=${state.forecastHorizon}`;
    const res = await fetch(url);
    const data = await res.json();

    if (!res.ok || data.status === 'error') {
      showForecastError(data.code || 'REQUEST_FAILED', data.message || 'Unable to generate forecast for requested origin.');
      return;
    }

    if (errorBox) errorBox.style.display = 'none';
    state.forecastData = data;

    updateForecastKpis(data);
    renderForecastTable(data);
    renderForecastChart();
  } catch (err) {
    showForecastError('NETWORK_ERROR', 'Failed to connect to forecast service endpoint: ' + err.message);
  } finally {
    if (btnRun) {
      btnRun.disabled = false;
      btnRun.style.opacity = '1';
    }
  }
}

function showForecastError(code, message) {
  const errorBox = document.getElementById('forecastErrorBox');
  const titleEl = document.getElementById('forecastErrorTitle');
  const msgEl = document.getElementById('forecastErrorMessage');

  if (errorBox && titleEl && msgEl) {
    titleEl.textContent = `Forecast Notice [${code}]`;
    msgEl.textContent = message;
    errorBox.style.display = 'flex';
  }
}

function updateForecastKpis(data) {
  if (!data || !data.predictions || data.predictions.length === 0) return;

  const unit = data.units;
  const preds = data.predictions;
  const day1 = preds[0];

  // Origin
  const originVal = data.data_quality?.origin_observed_value;
  document.getElementById('txtOriginDisplay').textContent = data.forecast_origin;
  document.getElementById('txtOriginValue').textContent = originVal !== undefined
    ? `Origin Actual: ${originVal.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`
    : `Origin: ${data.forecast_origin}`;

  // Day 1
  document.getElementById('txtDay1Value').textContent = day1.predicted_value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  document.getElementById('txtDay1Unit').textContent = unit;
  document.getElementById('txtDay1Strategy').textContent = `Method: ${day1.recommended_model === 'ridge' ? 'Ridge ML' : 'Seasonal Naive'}`;

  // Horizon Total / Avg
  const sumVal = preds.reduce((acc, p) => acc + (p.predicted_value || 0), 0);
  const avgVal = sumVal / preds.length;
  document.getElementById('kpiHorizonBadge').textContent = `${preds.length} Days`;
  document.getElementById('txtTrajectoryTotal').textContent = Math.round(sumVal).toLocaleString();
  document.getElementById('txtTrajectoryUnit').textContent = unit.includes('MU') ? 'MU Total' : 'MW Sum';
  document.getElementById('txtTrajectoryAvg').textContent = `Avg: ${avgVal.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}/day`;

  // Strategy badge
  const txtStrategy = document.getElementById('txtStrategyTitle');
  if (data.status === 'degraded') {
    txtStrategy.textContent = 'Degraded Fallback';
    txtStrategy.className = 'kpi-value-text text-amber';
  } else {
    txtStrategy.textContent = preds.length >= 7 ? 'Hybrid Multi-Step' : 'Direct Ridge ML';
    txtStrategy.className = 'kpi-value-text text-emerald';
  }

  // Sync dates
  const txtObs = document.getElementById('txtLatestObservedDate');
  if (txtObs && data.data_freshness) txtObs.textContent = data.data_freshness.latest_observed_date;
  const tableOrigin = document.getElementById('tableOriginDate');
  if (tableOrigin) tableOrigin.textContent = data.forecast_origin;
}

function renderForecastTable(data) {
  const tbody = document.getElementById('forecastTableBody');
  if (!tbody || !data || !data.predictions) return;

  tbody.innerHTML = '';
  data.predictions.forEach(p => {
    const tr = document.createElement('tr');

    const badgeClass = p.recommended_model === 'ridge' ? 'badge-method-ridge' : 'badge-method-snaive';
    const badgeLabel = p.recommended_model === 'ridge' ? 'Ridge ML' : 'Seasonal Naive';

    tr.innerHTML = `
      <td><strong>Day ${p.horizon}</strong> <span class="text-dim">(D+${p.horizon})</span></td>
      <td>${p.target_date} <span class="text-dim">(${p.target_day_of_week.slice(0, 3)})</span></td>
      <td><strong class="text-cyan">${p.predicted_value.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${p.units}</strong></td>
      <td><span class="${badgeClass}">${badgeLabel}</span></td>
      <td>${p.ridge_prediction !== null ? p.ridge_prediction.toLocaleString(undefined, { maximumFractionDigits: 1 }) : '—'}</td>
      <td>${p.persistence_baseline.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
      <td>${p.seasonal_naive_baseline.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderForecastChart() {
  const canvas = document.getElementById('forecastChartCanvas');
  const tooltip = document.getElementById('forecastChartTooltip');
  if (!canvas || !state.forecastData || !state.forecastData.predictions) return;

  const data = state.forecastData;
  const preds = data.predictions;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 35, right: 35, bottom: 45, left: 70 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);

  // Extract all value series to determine Y scale
  const allVals = [];
  preds.forEach(p => {
    if (p.predicted_value) allVals.push(p.predicted_value);
    if (p.ridge_prediction) allVals.push(p.ridge_prediction);
    if (p.persistence_baseline) allVals.push(p.persistence_baseline);
    if (p.seasonal_naive_baseline) allVals.push(p.seasonal_naive_baseline);
  });
  if (data.data_quality?.origin_observed_value) allVals.push(data.data_quality.origin_observed_value);

  const rawMin = Math.min(...allVals);
  const rawMax = Math.max(...allVals);
  const span = rawMax - rawMin || 100;
  const yMin = Math.floor((rawMin - span * 0.12) / 50) * 50;
  const yMax = Math.ceil((rawMax + span * 0.12) / 50) * 50;

  // Grid lines & Y Axis Labels
  ctx.strokeStyle = COLORS.gridLine;
  ctx.lineWidth = 1;
  ctx.fillStyle = COLORS.axisText;
  ctx.font = '11px "JetBrains Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';

  const yTicks = 5;
  for (let i = 0; i <= yTicks; i++) {
    const val = yMin + (yMax - yMin) * (i / yTicks);
    const y = padding.top + plotH - (plotH * (i / yTicks));
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillText(Math.round(val).toLocaleString(), padding.left - 12, y);
  }

  // X Positions
  const n = preds.length;
  const xStep = n > 1 ? plotW / (n - 1) : plotW / 2;
  const points = preds.map((p, idx) => {
    const x = padding.left + (n > 1 ? idx * xStep : plotW / 2);
    const yPred = padding.top + plotH - ((p.predicted_value - yMin) / (yMax - yMin)) * plotH;
    const yRidge = p.ridge_prediction ? padding.top + plotH - ((p.ridge_prediction - yMin) / (yMax - yMin)) * plotH : null;
    const yPersist = padding.top + plotH - ((p.persistence_baseline - yMin) / (yMax - yMin)) * plotH;
    const ySNaive = padding.top + plotH - ((p.seasonal_naive_baseline - yMin) / (yMax - yMin)) * plotH;

    return { x, yPred, yRidge, yPersist, ySNaive, data: p };
  });

  // X Axis labels
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  points.forEach((pt, i) => {
    const label = `D+${pt.data.horizon} (${pt.data.target_date.slice(5)})`;
    ctx.fillStyle = COLORS.axisText;
    ctx.fillText(label, pt.x, height - padding.bottom + 12);
  });

  // Helper for line drawing
  function drawLine(getY, strokeColor, lineWidth, dash = []) {
    ctx.save();
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash(dash);
    ctx.beginPath();
    let started = false;
    points.forEach(pt => {
      const y = getY(pt);
      if (y !== null && !isNaN(y)) {
        if (!started) { ctx.moveTo(pt.x, y); started = true; }
        else { ctx.lineTo(pt.x, y); }
      }
    });
    ctx.stroke();
    ctx.restore();
  }

  // 1. Persistence Baseline (Amber Dashed)
  drawLine(pt => pt.yPersist, COLORS.amber, 2, [6, 4]);

  // 2. Seasonal-Naive Baseline (Purple Dotted)
  drawLine(pt => pt.ySNaive, COLORS.purple, 2, [3, 4]);

  // 3. Raw Ridge ML (Blue Translucent)
  drawLine(pt => pt.yRidge, 'rgba(59, 130, 246, 0.45)', 2, []);

  // 4. Hybrid Selected Forecast (Solid Cyan with Neon Glow)
  ctx.save();
  ctx.shadowBlur = 12;
  ctx.shadowColor = COLORS.cyan;
  drawLine(pt => pt.yPred, COLORS.cyan, 3.5, []);
  ctx.restore();

  // Draw Points on Selected Forecast
  points.forEach(pt => {
    ctx.save();
    ctx.beginPath();
    ctx.arc(pt.x, pt.yPred, 5, 0, Math.PI * 2);
    ctx.fillStyle = pt.data.recommended_model === 'ridge' ? COLORS.cyan : COLORS.purple;
    ctx.fill();
    ctx.strokeStyle = '#0a0e17';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
  });

  // Interactive Hover Tooltip
  canvas.onmousemove = (e) => {
    const r = canvas.getBoundingClientRect();
    const mouseX = e.clientX - r.left;

    let nearest = null;
    let minDist = Infinity;
    points.forEach(pt => {
      const dist = Math.abs(pt.x - mouseX);
      if (dist < minDist) {
        minDist = dist;
        nearest = pt;
      }
    });

    if (nearest && minDist < 40) {
      const p = nearest.data;
      tooltip.style.display = 'block';
      tooltip.style.left = `${nearest.x}px`;
      tooltip.style.top = `${nearest.yPred - 20}px`;

      const methodBadge = p.recommended_model === 'ridge'
        ? '<span style="color:#38bdf8; font-weight:600;">[Ridge ML]</span>'
        : '<span style="color:#a855f7; font-weight:600;">[Seasonal Naive]</span>';

      tooltip.innerHTML = `
        <div style="font-weight:700; color:#f8fafc; margin-bottom:4px;">
          Day ${p.horizon}: ${p.target_date} (${p.target_day_of_week})
        </div>
        <div style="color:#38bdf8; font-size:12px; margin-bottom:6px;">
          <strong>Selected:</strong> ${p.predicted_value.toLocaleString()} ${p.units} ${methodBadge}
        </div>
        <div style="font-size:11px; color:#94a3b8; display:grid; grid-template-columns:auto auto; gap:4px 8px;">
          <span>Raw Ridge ML:</span><span style="color:#f8fafc;">${p.ridge_prediction ? p.ridge_prediction.toLocaleString() : '—'}</span>
          <span>Day-0 Persist [y(D)]:</span><span style="color:#f59e0b;">${p.persistence_baseline.toLocaleString()}</span>
          <span>Seasonal Naive:</span><span style="color:#a855f7;">${p.seasonal_naive_baseline.toLocaleString()}</span>
        </div>
      `;
    } else {
      tooltip.style.display = 'none';
    }
  };

  canvas.onmouseleave = () => {
    tooltip.style.display = 'none';
  };
}

