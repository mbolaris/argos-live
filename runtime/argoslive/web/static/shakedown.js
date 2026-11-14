'use strict';
(() => {
  const token = new URLSearchParams(window.location.search).get('token');
  const byId = id => document.getElementById(id);
  const state = {data: null, mobileId: null, loading: false, polling: false,
    lastLap: null, comparison: null, comparisonLoadout: null, loadingComparison: false,
    queueChoices: [], queueEntries: [], queueRecord: null, queuePolling: false, lapRecord: null};
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
  function renderQueueChoices() {
    const select = byId('queue-loadout');
    select.replaceChildren(...state.queueChoices.map(item => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name;
      return option;
    }));
    const active = ['running', 'cancelling'].includes(state.queueRecord?.state);
    const lapActive = state.lapRecord?.state === 'running';
    byId('queue-add').disabled = active || lapActive || !state.queueChoices.length || state.queueEntries.length >= 12;
    byId('queue-start').disabled = active || lapActive || state.queueEntries.length === 0;
  }
  function renderQueueEntries() {
    const list = byId('queue-entries');
    if (['running', 'cancelling'].includes(state.queueRecord?.state)) {
      list.replaceChildren(...(state.queueRecord.entries || []).map((item, index) => {
        const row = document.createElement('li');
        const choice = state.queueChoices.find(value => value.id === item.loadout_id);
        const active = state.queueRecord.active_entry === index;
        row.textContent = `${choice?.name || 'Saved build'} · ${item.size} · ${active ? 'running' : item.state}`;
        return row;
      }));
      renderQueueChoices();
      return;
    }
    list.replaceChildren(...state.queueEntries.map((item, index) => {
      const row = document.createElement('li');
      const choice = state.queueChoices.find(value => value.id === item.loadout_id);
      const label = document.createElement('span');
      label.textContent = `${choice?.name || 'Saved build'} · ${item.size}`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'secondary';
      remove.textContent = 'Remove';
      remove.disabled = state.queueRecord?.state === 'running' || state.queueRecord?.state === 'cancelling';
      remove.addEventListener('click', () => {
        state.queueEntries.splice(index, 1);
        renderQueueEntries();
        renderQueueChoices();
      });
      row.append(label, remove);
      return row;
    }));
    renderQueueChoices();
  }
  function showQueue(record) {
    state.queueRecord = record;
    const active = record && ['running', 'cancelling'].includes(record.state);
    const entries = record?.entries || [];
    const total = entries.length;
    const position = Math.min(record?.position || 0, total);
    const current = record?.active_entry;
    byId('queue-cancel').hidden = !active;
    byId('run-lap').disabled = active || state.lapRecord?.state === 'running';
    byId('run-quick-empty').disabled = active || state.lapRecord?.state === 'running';
    byId('queue-add').disabled = active || !state.queueChoices.length || state.queueEntries.length >= 12;
    byId('queue-start').disabled = active || state.queueEntries.length === 0;
    if (active) {
      const item = entries[current];
      const progress = record.active_progress;
      byId('queue-summary').textContent = `Lap ${Math.max(1, position)} of ${total}${item ? ` · ${item.size}` : ''}` +
        `${progress?.stage ? ` · ${progress.stage}` : ''}` +
        `${progress?.total ? ` · ${progress.completed || 0}/${progress.total}` : ''} · ${record.estimate?.label || 'estimate unknown'}`;
      renderQueueEntries();
    } else if (record?.notice) {
      byId('queue-summary').textContent = record.notice;
      if (record.state !== 'idle') {
        byId('queue-entries').replaceChildren(...entries.map(item => {
          const row = document.createElement('li');
          const choice = state.queueChoices.find(value => value.id === item.loadout_id);
          row.textContent = `${choice?.name || 'Saved build'} · ${item.size} · ${item.state}`;
          return row;
        }));
      }
    } else {
      byId('queue-summary').textContent = `${state.queueEntries.length} laps queued. Add up to 12; estimate appears when earlier measurements exist.`;
      renderQueueEntries();
    }
    if (active && !state.queuePolling) pollQueue();
  }
  async function loadQueue() {
    try {
      const [choices, record] = await Promise.all([
        get('/api/shakedown/queue/choices'), get('/api/shakedown/queue')
      ]);
      state.queueChoices = choices.entries || [];
      showQueue(record);
      renderQueueEntries();
    } catch (error) {
      byId('queue-summary').textContent = error.message;
    }
  }
  async function pollQueue() {
    state.queuePolling = true;
    try {
      while (true) {
        const record = await get('/api/shakedown/queue');
        showQueue(record);
        if (!['running', 'cancelling'].includes(record.state)) break;
        await new Promise(resolve => window.setTimeout(resolve, 1500));
      }
      await load();
    } catch (error) {
      byId('queue-summary').textContent = error.message;
    } finally {
      state.queuePolling = false;
    }
  }
  async function startQueue() {
    try {
      const record = await post('/api/shakedown/queue/start', {entries: state.queueEntries});
      state.queueEntries = [];
      showQueue(record);
    } catch (error) {
      byId('queue-summary').textContent = error.message;
    }
  }
  async function saveExport() {
    const button = byId('export-scorecard');
    const label = byId('export-status');
    button.disabled = true;
    label.textContent = 'Saving a privacy-filtered scorecard to this machine…';
    byId('export-links').replaceChildren();
    try {
      const result = await post('/api/shakedown/export', {});
      const links = byId('export-links');
      for (const kind of result.files || []) {
        const link = document.createElement('a');
        link.href = `/api/shakedown/exports/${encodeURIComponent(result.export_id)}.${encodeURIComponent(kind)}?token=${encodeURIComponent(token || '')}`;
        link.download = `argos-shakedown.${kind}`;
        link.textContent = `Download ${kind.toUpperCase()}`;
        links.append(link);
      }
      label.textContent = `Saved in Argos storage. ${result.png_available ? 'PNG is available.' : 'PNG rendering is unavailable on this machine.'}`;
    } catch (error) {
      label.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }
  function showLap(record) {
    const label = byId('lap-state');
    state.lapRecord = record;
    const active = record && record.state === 'running';
    if (record && record.state === 'completed' && record.complete) state.lastLap = record;
    byId('run-lap').disabled = !!active;
    byId('run-quick-empty').disabled = !!active;
    byId('cancel-lap').hidden = !active;
    byId('run-lap').disabled = active || ['running', 'cancelling'].includes(state.queueRecord?.state);
    byId('run-quick-empty').disabled = active || ['running', 'cancelling'].includes(state.queueRecord?.state);
    renderQueueChoices();
    if (!record || record.state === 'idle') label.textContent = 'Ready when you are.';
    else if (active) {
      const progress = record.progress;
      label.textContent = `${record.size || 'Quick'} lap · ${record.stage || 'starting'}${progress && progress.total ? ` · ${progress.completed || 0}/${progress.total}` : ''}`;
    } else if (record.state === 'completed' && record.complete) label.textContent = `${record.size} lap complete.`;
    else label.textContent = `${record.size || 'Last'} lap ${record.outcome || record.state}.`;
    renderEstimate();
    renderResult();
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
  async function startLap(size, suites) {
    state.lastLap = null;
    state.comparison = null;
    renderResult();
    byId('run-lap').disabled = true;
    byId('run-quick-empty').disabled = true;
    byId('lap-state').textContent = 'Starting lap…';
    try {
      const selection = {size};
      if (Array.isArray(suites) && suites.length) selection.suites = suites;
      const record = await post('/api/shakedown/lap/start', selection);
      showLap(record);
      if (record.state !== 'running') load();
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
  function comparisonUrl(previous) {
    return '/api/shakedown/comparison' + (previous ? '?previous=' + encodeURIComponent(previous) : '');
  }
  function renderResult() {
    const panel = byId('lap-result');
    const visible = !!(state.lastLap && state.lastLap.state === 'completed' && state.lastLap.complete);
    panel.hidden = !visible;
    if (!visible) return;
    const result = state.comparison;
    if (!result) {
      byId('result-headline').textContent = 'Comparing saved builds…';
      return;
    }
    byId('result-headline').textContent = result.headline || 'Comparison unavailable.';
    byId('result-empty').hidden = !!result.has_comparison;
    byId('loadout-changes').hidden = !result.has_comparison;
    byId('row-results').hidden = !result.has_comparison;
    const select = byId('compare-loadout');
    const prior = state.comparisonLoadout || result.previous?.id || '';
    select.replaceChildren(...result.previous_options.map(item => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name;
      return option;
    }));
    select.disabled = result.previous_options.length < 2;
    if (prior) select.value = prior;
    select.closest('label').hidden = result.previous_options.length === 0;

    const diff = byId('loadout-diff');
    diff.replaceChildren(...result.loadout_diff.map(item => {
      const line = document.createElement('li');
      line.textContent = item.sentence;
      return line;
    }));
    byId('no-build-changes').hidden = result.loadout_diff.length > 0;

    const rows = byId('comparison-rows');
    rows.replaceChildren(...result.rows.map(item => {
      const line = document.createElement('li');
      const label = document.createElement('strong');
      label.textContent = item.label;
      const verdict = document.createElement('span');
      verdict.className = `verdict verdict-${item.verdict}`;
      verdict.textContent = item.verdict.replace('-', ' ');
      line.append(label, verdict);
      if (item.shared_items !== undefined) {
        const detail = document.createElement('span');
        detail.className = 'muted';
        detail.textContent = `${item.wins} wins · ${item.losses} losses · ${item.ties} ties · ${item.shared_items} shared questions`;
        line.append(detail);
      } else if (item.reason) {
        const detail = document.createElement('span');
        detail.className = 'muted';
        detail.textContent = item.reason;
        line.append(detail);
      }
      return line;
    }));
    const move = result.next_move;
    byId('next-move').hidden = !move;
    if (move) byId('next-move-description').textContent = move.description;
  }
  async function loadComparison(previous) {
    if (state.loadingComparison) return;
    state.loadingComparison = true;
    state.comparisonLoadout = previous || null;
    state.comparison = null;
    renderResult();
    try {
      state.comparison = await get(comparisonUrl(previous));
      state.comparisonLoadout = state.comparison.previous?.id || null;
      renderResult();
    } catch (error) {
      byId('result-headline').textContent = error.message;
    } finally {
      state.loadingComparison = false;
    }
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
    if (cell.personal_best) {
      const personalBest = document.createElement('span');
      personalBest.className = 'personal-best';
      personalBest.textContent = 'Personal best';
      box.append(personalBest);
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
      if (state.lastLap && state.lastLap.state === 'completed' && state.lastLap.complete &&
          !state.comparison && !state.loadingComparison) loadComparison(state.comparisonLoadout);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      state.loading = false;
    }
  }
  byId('refresh').addEventListener('click', load);
  byId('export-scorecard').addEventListener('click', saveExport);
  byId('lap-size').addEventListener('change', renderEstimate);
  byId('mobile-loadout').addEventListener('change', event => {
    state.mobileId = event.target.value;
    renderTable();
  });
  window.addEventListener('resize', () => { if (state.data) renderTable(); });
  byId('run-quick-empty').addEventListener('click', () => startLap('quick'));
  byId('run-lap').addEventListener('click', () => startLap(byId('lap-size').value));
  byId('compare-loadout').addEventListener('change', event => loadComparison(event.target.value));
  byId('run-more').addEventListener('click', () => {
    const move = state.comparison?.next_move;
    if (move) startLap(move.size, [move.suite]);
  });
  byId('cancel-lap').addEventListener('click', async () => {
    byId('cancel-lap').disabled = true;
    try { showLap(await post('/api/shakedown/lap/cancel')); }
    catch (error) { byId('lap-state').textContent = error.message; }
    finally { byId('cancel-lap').disabled = false; }
  });
  byId('queue-add').addEventListener('click', () => {
    const loadoutId = byId('queue-loadout').value;
    if (!loadoutId || state.queueEntries.length >= 12) return;
    state.queueEntries.push({loadout_id: loadoutId, size: byId('queue-size').value});
    renderQueueEntries();
  });
  byId('queue-start').addEventListener('click', startQueue);
  byId('queue-cancel').addEventListener('click', async () => {
    byId('queue-cancel').disabled = true;
    try { showQueue(await post('/api/shakedown/queue/cancel')); }
    catch (error) { byId('queue-summary').textContent = error.message; }
    finally { byId('queue-cancel').disabled = false; }
  });
  get('/api/shakedown/lap').then(showLap).catch(error => { byId('lap-state').textContent = error.message; });
  loadQueue();
  load();
})();
