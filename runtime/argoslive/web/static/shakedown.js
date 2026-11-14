'use strict';
(() => {
  const token = new URLSearchParams(window.location.search).get('token');
  const byId = id => document.getElementById(id);
  const state = {data: null, mobileId: null, loading: false, polling: false};
  const status = byId('status');
  const escDate = value => {
    if (!value) return 'Date not recorded';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Date not recorded' : date.toLocaleDateString();
  };
  async function get(path) {
    const response = await fetch(path, {headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
    if (!response.ok) {
      let message = 'Scorecard unavailable';
      try { message = (await response.json()).error || message; } catch (_) {}
      throw new Error(message);
    }
    return response.json();
  }
  async function post(path, body) {
    const response = await fetch(path, {method: 'POST', headers: {
      'X-Argos-Token': token || '', 'Content-Type': 'application/json'
    }, body: JSON.stringify(body || {}), cache: 'no-store'});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Lap action unavailable');
    return value;
  }
  function showLap(record) {
    const label = byId('lap-state');
    const active = record && record.state === 'running';
    byId('run-lap').disabled = !!active;
    byId('run-quick-empty').disabled = !!active;
    byId('cancel-lap').hidden = !active;
    if (!record || record.state === 'idle') label.textContent = 'Ready when you are.';
    else if (active) {
      const progress = record.progress;
      label.textContent = `${record.size || 'Quick'} lap · ${record.stage || 'starting'}${progress && progress.total ? ` · ${progress.completed || 0}/${progress.total}` : ''}`;
    } else if (record.state === 'completed' && record.complete) label.textContent = `${record.size} lap complete.`;
    else label.textContent = `${record.size || 'Last'} lap ${record.outcome || record.state}.`;
    renderEstimate();
    if (active && !state.polling) pollLap();
  }
  function renderEstimate() {
    const size = byId('lap-size').value;
    const estimate = state.data?.lap_estimates?.[size];
    byId('lap-estimate').textContent = estimate ? `Estimate: ${estimate.label}.` : 'Estimate: unknown until the first lap.';
  }
  async function pollLap() {
    state.polling = true;
    try {
      while (true) {
        const record = await get('/api/shakedown/lap');
        showLap(record);
        if (record.state !== 'running') break;
        await new Promise(resolve => window.setTimeout(resolve, 1500));
      }
      await load();
    } catch (error) {
      byId('lap-state').textContent = error.message;
    } finally {
      state.polling = false;
    }
  }
  async function startLap(size) {
    byId('run-lap').disabled = true;
    byId('run-quick-empty').disabled = true;
    byId('lap-state').textContent = 'Starting lap…';
    try {
      const record = await post('/api/shakedown/lap/start', {size});
      showLap(record);
    } catch (error) {
      byId('run-lap').disabled = false;
      byId('run-quick-empty').disabled = false;
      byId('lap-state').textContent = error.message;
    }
  }
  function selectedQuery() {
    return new URLSearchParams(window.location.search).get('loadouts') || '';
  }
  function scorecardUrl() {
    const pinned = selectedQuery();
    return '/api/shakedown/scorecard' + (pinned ? '?loadouts=' + encodeURIComponent(pinned) : '');
  }
  function formatCell(row, cell) {
    const box = document.createElement('div');
    box.className = 'score-cell';
    if (!cell) {
      box.textContent = '—';
      return box;
    }
    if (row.kind === 'speed') {
      const value = row.unit === 's' ? `${cell.value.toFixed(2)} s` : `${cell.value.toFixed(1)} tokens/s`;
      const main = document.createElement('strong');
      main.textContent = `${value} · n=${cell.count}`;
      box.append(main);
    } else {
      const main = document.createElement('strong');
      main.textContent = `${cell.correct}/${cell.total} (${cell.percent.toFixed(1)}%)`;
      box.append(main);
      const interval = document.createElement('span');
      interval.className = 'muted';
      interval.textContent = `95% interval ${cell.interval[0].toFixed(1)}–${cell.interval[1].toFixed(1)}%`;
      box.append(interval);
    }
    if (cell.state !== 'completed' || cell.complete === false) {
      const partial = document.createElement('span');
      partial.className = 'incomparable';
      partial.textContent = 'Incomplete · excluded from best marks';
      box.append(partial);
    }
    const metadata = document.createElement('span');
    metadata.className = 'cell-meta';
    metadata.textContent = `${cell.slice || 'full'} · ${cell.suite_version || 'version unknown'} · ${escDate(cell.date)}`;
    box.append(metadata);
    if (cell.best) {
      const best = document.createElement('span');
      best.className = 'best';
      best.textContent = 'Best · distinguishable';
      box.append(best);
    } else if (cell.incomparable) {
      const note = document.createElement('span');
      note.className = 'incomparable';
      note.textContent = 'Different version or slice · not compared';
      box.append(note);
    }
    for (const noteText of cell.footnotes || []) {
      const note = document.createElement('span');
      note.className = 'footnote-marker';
      note.textContent = noteText;
      box.append(note);
    }
    const runLink = document.createElement('a');
    runLink.href = `/?token=${encodeURIComponent(token || '')}#replay=${encodeURIComponent(cell.run_id)}`;
    runLink.textContent = 'Open run';
    runLink.className = 'run-link';
    box.append(runLink);
    return box;
  }
  function renderTable() {
    const {loadouts, rows} = state.data;
    const mobile = window.matchMedia('(max-width: 700px)').matches;
    let visible = loadouts;
    if (mobile) {
      const chosen = state.mobileId || state.data.current_loadout_id || loadouts[0]?.id;
      visible = loadouts.filter(item => item.id === chosen);
    }
    const head = byId('head');
    head.replaceChildren();
    const tr = document.createElement('tr');
    const first = document.createElement('th');
    first.scope = 'col';
    first.textContent = 'Test';
    tr.append(first);
    for (const item of visible) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = item.name + (item.current ? ' · current' : '');
      const model = document.createElement('span');
      model.className = 'column-model';
      model.textContent = `${item.quantization} · ${item.recipe.context}`;
      th.append(document.createElement('br'), model);
      tr.append(th);
    }
    head.append(tr);
    const body = byId('body');
    body.replaceChildren();
    for (const row of rows) {
      const line = document.createElement('tr');
      const label = document.createElement('th');
      label.scope = 'row';
      label.textContent = row.label;
      line.append(label);
      for (const item of visible) {
        const td = document.createElement('td');
        td.append(formatCell(row, row.cells[item.id]));
        line.append(td);
      }
      body.append(line);
    }
  }
  function renderControls() {
    const {loadouts, available_loadouts, current_loadout_id, selected_loadout_ids} = state.data;
    const select = byId('mobile-loadout');
    select.replaceChildren(...loadouts.map(item => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name + (item.current ? ' · current' : '');
      return option;
    }));
    state.mobileId = state.mobileId || current_loadout_id || loadouts[0]?.id || null;
    if (state.mobileId) select.value = state.mobileId;
    const options = byId('loadout-options');
    options.replaceChildren();
    const pinned = selected_loadout_ids.filter(id => id !== current_loadout_id);
    for (const item of available_loadouts) {
      const label = document.createElement('label');
      label.className = 'loadout-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = item.id;
      checkbox.checked = pinned.includes(item.id);
      checkbox.disabled = item.current;
      checkbox.addEventListener('change', () => {
        const checked = [...options.querySelectorAll('input:checked:not(:disabled)')].map(input => input.value);
        if (checked.length > 4) {
          checkbox.checked = false;
          status.textContent = 'Pin up to four builds; your current build is included automatically.';
          return;
        }
        const url = new URL(window.location.href);
        if (checked.length) url.searchParams.set('loadouts', checked.join(','));
        else url.searchParams.delete('loadouts');
        window.history.replaceState({}, '', url);
        load();
      });
      const text = document.createElement('span');
      text.textContent = item.name + (item.current ? ' · current build' : '');
      label.append(checkbox, text);
      options.append(label);
    }
  }
  async function load() {
    if (state.loading) return;
    state.loading = true;
    status.textContent = 'Loading saved runs…';
    try {
      state.data = await get(scorecardUrl());
      byId('bench').hidden = state.data.empty;
      byId('empty').hidden = !state.data.empty;
      if (state.data.empty) status.textContent = 'No saved laps yet.';
      else {
        status.textContent = `${state.data.rows.length} scorecard rows · stored on this machine.`;
        renderControls();
        renderTable();
      }
      renderEstimate();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      state.loading = false;
    }
  }
  byId('refresh').addEventListener('click', load);
  byId('lap-size').addEventListener('change', renderEstimate);
  byId('mobile-loadout').addEventListener('change', event => {
    state.mobileId = event.target.value;
    renderTable();
  });
  window.addEventListener('resize', () => { if (state.data) renderTable(); });
  byId('run-quick-empty').addEventListener('click', () => startLap('quick'));
  byId('run-lap').addEventListener('click', () => startLap(byId('lap-size').value));
  byId('cancel-lap').addEventListener('click', async () => {
    byId('cancel-lap').disabled = true;
    try { showLap(await post('/api/shakedown/lap/cancel')); }
    catch (error) { byId('lap-state').textContent = error.message; }
    finally { byId('cancel-lap').disabled = false; }
  });
  get('/api/shakedown/lap').then(showLap).catch(error => { byId('lap-state').textContent = error.message; });
  load();
})();
