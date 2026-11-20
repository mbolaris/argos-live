'use strict';
const token = new URLSearchParams(location.search).get('token') || '';
const history = [];
const safe = value => typeof value === 'string' ? value.replace(/[<>]/g, '').slice(0, 100) : '';
const fmtBytes = value => Number.isFinite(value) && value >= 0 ? `${(value / 1073741824).toFixed(1)} GiB` : '—';
const fmtTime = seconds => Number.isFinite(seconds) && seconds >= 0 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m` : '—';
const fmtElapsed = seconds => Number.isFinite(seconds) && seconds >= 0 ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '—';
async function api(path) {
  const auth = token ? `${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}` : '';
  const response = await fetch(`${path}${auth}`, {cache: 'no-store'});
  if (!response.ok) throw new Error(`${response.status}`);
  return response.json();
}
function put(id, value) { document.getElementById(id).textContent = value === null || value === undefined || value === '' ? '—' : String(value); }
function updateChart() {
  const points = history.slice(-60);
  const path = (key, max, y0, height) => points.map((point, index) => {
    const value = point[key];
    if (!Number.isFinite(value)) return null;
    const x = 12 + index * (576 / Math.max(1, points.length - 1));
    const y = y0 + height * (1 - Math.min(max, value) / max);
    return `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).filter(Boolean).join(' ');
  document.getElementById('temp-line').setAttribute('d', path('temp', 100, 30, 30));
  document.getElementById('util-line').setAttribute('d', path('util', 100, 78, 24));
}
function showCampaign(value) {
  const c = value || {};
  const progress = c.progress || {};
  const run = Array.isArray(c.evaluation_runs) ? c.evaluation_runs[0] : null;
  const itemCount = run && Number.isFinite(run.total) ? run.total : null;
  const done = run && Number.isFinite(run.completed) ? run.completed : 0;
  const active = c.active === true;
  put('run-state', active ? 'Running' : safe(c.phase || 'Idle'));
  put('run-name', active ? `${safe(c.measurement_suite || 'Evaluation')} · ${safe(c.model || '')}` : 'No active campaign');
  put('phase', safe(c.phase || 'Idle'));
  put('elapsed', fmtElapsed(c.elapsed_seconds));
  put('item', c.current ? `${safe(c.current.item_id)} · ${safe(c.current.category)} · ${safe(c.current.state)}` : '—');
  put('saved', Number.isInteger(progress.saved_evaluation_count) ? progress.saved_evaluation_count : '—');
  put('run-count', itemCount ? `${done} / ${itemCount}` : '—');
  const bar = document.getElementById('run-progress');
  bar.max = itemCount || 1;
  bar.value = itemCount ? Math.min(done, itemCount) : 0;
  const notes = [];
  if (c.failure_code) notes.push(`Failure: ${safe(c.failure_code)}.`);
  if (c.result_campaign?.audit_status) notes.push(`Audit: ${safe(c.result_campaign.audit_status)}.`);
  if (active) notes.push('In progress: no final score yet.');
  else if (c.phase === 'completed') notes.push('Completed; verify the saved run and audit before interpreting it.');
  else notes.push('No active campaign.');
  put('run-note', notes.join(' '));
  if (active) document.getElementById('run-state').className = 'pill active';
}
function showTelemetry(t) {
  const gpu = Array.isArray(t.gpu) ? t.gpu[0] : null;
  put('gpu-name', gpu?.name || 'GPU metrics unavailable');
  put('gpu-temp', Number.isFinite(gpu?.temperature_c) ? `${gpu.temperature_c}` : '—');
  put('gpu-util', Number.isFinite(gpu?.utilization_percent) ? `${gpu.utilization_percent}` : '—');
  put('gpu-vram', Number.isFinite(gpu?.vram_used_mib) ? `${(gpu.vram_used_mib / 1024).toFixed(1)} GiB` : '—');
  put('gpu-vram-total', Number.isFinite(gpu?.vram_total_mib) ? `of ${(gpu.vram_total_mib / 1024).toFixed(1)} GiB` : 'VRAM');
  put('gpu-power', Number.isFinite(gpu?.power_w) ? `${gpu.power_w}` : '—');
  put('gpu-power-limit', Number.isFinite(gpu?.power_limit_w) ? `of ${gpu.power_limit_w} W` : 'watts');
  const sensors = t.cpu_temperature_sensors;
  const cpu = Array.isArray(sensors) ? sensors[0] : null;
  put('cpu-temp', Number.isFinite(cpu?.temperature_c) ? `${cpu.temperature_c} °C` : 'Unavailable');
  put('cpu-sensor', cpu ? safe(cpu.sensor) : 'No CPU temperature sensor reported');
  put('ram', fmtBytes(t.memory?.available_bytes));
  put('ram-total', `of ${fmtBytes(t.memory?.total_bytes)}`);
  put('disk', fmtBytes(t.root_disk?.free_bytes));
  put('disk-total', `of ${fmtBytes(t.root_disk?.total_bytes)}`);
  put('uptime', fmtTime(t.uptime_seconds));
  history.push({temp: gpu?.temperature_c, util: gpu?.utilization_percent});
  if (history.length > 120) history.shift();
  updateChart();
}
function showResults(data) {
  const body = document.getElementById('results');
  body.replaceChildren();
  const rows = Array.isArray(data?.rounds) ? data.rounds.slice(0, 6) : [];
  if (!rows.length) { body.innerHTML = '<tr><td colspan="4">No saved runs yet.</td></tr>'; return; }
  for (const row of rows) {
    const tr = document.createElement('tr');
    const suite = safe((row.suite_version || row.suite || 'Test').replace(/^argos-openclaw-ability\//, ''));
    const result = row.complete === true && Number.isFinite(row.correct) && Number.isFinite(row.scored_total)
      ? `${row.correct} / ${row.scored_total}` : 'Not scored';
    const state = row.complete === true ? 'Complete' : safe(row.state || 'Incomplete');
    const created = row.created ? new Date(row.created).toLocaleString() : '—';
    for (const value of [suite, result, state, created]) {
      const td = document.createElement('td'); td.textContent = value; tr.append(td);
    }
    body.append(tr);
  }
}
async function refresh() {
  try {
    const [campaign, telemetry, recent] = await Promise.all([
      api('/api/monitor/campaign'), api('/api/telemetry'), api('/api/monitor/results')
    ]);
    showCampaign(campaign); showTelemetry(telemetry); showResults(recent);
    put('updated', `Updated ${new Date(telemetry.captured_utc).toLocaleTimeString()} · samples are point-in-time readings`);
    put('connection', 'Connected'); document.getElementById('connection').className = 'ok';
  } catch (error) {
    put('connection', 'Connection lost'); document.getElementById('connection').className = 'bad';
    put('updated', 'Live data unavailable; last good sample is retained.');
  }
}
refresh();
setInterval(refresh, 10000);
