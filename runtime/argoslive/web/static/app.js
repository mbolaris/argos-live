'use strict';
const token = new URLSearchParams(window.location.search).get('token');
const labels = {'local-chat': 'Local chat', 'local-vision': 'Image understanding', memory: 'Memory',
  browser: 'Browser', documents: 'Documents', 'voice-output': 'Speech output', 'voice-input': 'Speech input',
  'image-generation': 'Image generation', 'reviewed-skills': 'Personal skills', 'optional-channel': 'Messaging'};
const states = {'dependency-missing': 'Needs dependencies', 'acceptance-pending': 'Setup and test pending',
  'selection-pending': 'Choose a compatible engine or setup'};
const nextSteps = {'local-chat': 'Finish local model setup and test a reply.',
  'local-vision': 'Choose an image-capable model and test it with a picture.',
  memory: 'Set up private memory and verify recall after a restart.',
  browser: 'Set up a supported browser and review the assistant’s browsing permission.',
  documents: 'Set up PDF support and verify reading a sample document.',
  'voice-output': 'Choose a speech engine and voice, then test audio playback.',
  'voice-input': 'Choose local transcription support and test a recording.',
  'image-generation': 'Choose compatible image tools and test a generated image.',
  'reviewed-skills': 'Review your personal skills and their required permissions.',
  'optional-channel': 'Optional: connect a messaging account. Local chat does not require one.'};
let busy = false;
function card(parent, heading, detail) {
  const article = document.createElement('article');
  article.className = 'card';
  const title = document.createElement('h3');
  title.textContent = heading;
  const value = document.createElement('p');
  value.textContent = detail;
  article.append(title, value);
  parent.append(article);
}
const gib = bytes => typeof bytes === 'number' ? `${(bytes / 2 ** 30).toFixed(1)} GiB` : 'Unknown';
const encrypted = value => value === true ? 'Encrypted' : value === false ? 'Unencrypted' : 'Encryption unknown';
async function api(path) {
  const response = await fetch(path, {headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
  if (!response.ok) throw new Error('Status unavailable');
  return response.json();
}
async function refreshLive() {
  const status = document.getElementById('live-status');
  const chat = document.getElementById('chat');
  try {
    const live = await api('/api/status');
    const cards = document.getElementById('hardware');
    cards.replaceChildren();
    const hardware = live.hardware;
    card(cards, 'Processor', `${hardware.cpu.model || 'Unknown'} · ${hardware.cpu.threads ?? 'Unknown'} threads`);
    card(cards, 'Memory', `${gib(hardware.ram.available_bytes)} available / ${gib(hardware.ram.total_bytes)} total`);
    card(cards, 'Graphics', hardware.gpus === null ? 'Unknown' : hardware.gpus.length === 0 ? 'No GPU detected' :
      hardware.gpus.map(g => `${g.name} · ${gib(g.vram_used_bytes)} used / ${gib(g.vram_total_bytes)} VRAM`).join('; '));
    const storage = live.model_storage;
    card(cards, 'Model storage', storage.state === 'available' ?
      `${storage.path} · ${gib(storage.free_bytes)} free · ${encrypted(storage.encrypted)}` :
      storage.state === 'not-configured' ? 'Choose model storage in the welcome window.' : 'Selected storage needs attention. No fallback location is used.');
    const persistence = live.persistence;
    card(cards, 'Saved workspace', persistence.active === true ? `${encrypted(persistence.encrypted)} persistence active` :
      persistence.active === false ? 'Temporary session — changes may be lost at reboot' : 'Persistence status unknown');
    card(cards, 'Network', live.network.default_route === true ? 'Network connected · Internet access not verified' :
      live.network.default_route === false ? 'Offline · Local chat does not need internet' : 'Network status unknown');
    const ollama = live.ollama;
    card(cards, 'Model service', ollama.reachable ? `Ollama ${ollama.version || '(version unknown)'} reachable` : 'Ollama is not reachable');
    card(cards, 'Models in use', ollama.loaded_models === null ? 'Loaded model status unknown' : ollama.loaded_models.length ? ollama.loaded_models.map(m =>
      `${m.name} · ${m.backend.mode || 'Placement unknown'}`).join('; ') : 'No loaded models reported');
    document.getElementById('assistant-status').textContent = live.assistant === 'ready' ? 'Assistant gateway ready' :
      live.assistant === 'not-configured' ? 'Assistant setup needed' : 'Assistant is not ready';
    document.getElementById('assistant-help').textContent = live.chat_available ?
      'Open your existing conversation. A ready gateway does not yet verify a model reply.' :
      'Use Start Assistant in the welcome window. This dashboard does not start a second assistant.';
    chat.disabled = !live.chat_available;
    status.textContent = 'Live measurements refreshed. Missing measurements remain unknown.';
  } catch (_) {
    document.getElementById('hardware').replaceChildren();
    document.getElementById('assistant-status').textContent = 'Assistant status unavailable';
    chat.disabled = true;
    status.textContent = 'Live status unavailable. Retry using the current session link.';
  }
}
async function refreshModels() {
  const status = document.getElementById('models-status');
  const installed = document.getElementById('installed-models');
  const bundled = document.getElementById('bundled-models');
  const jobs = document.getElementById('model-jobs');
  const catalog = document.getElementById('model-catalog');
  installed.replaceChildren(); bundled.replaceChildren(); jobs.replaceChildren(); catalog.replaceChildren();
  try {
    const result = await api('/api/models');
    status.textContent = result.storage_state === 'available' ? 'Reading your selected Ollama store.' :
      result.storage_state === 'not-configured' ? 'Choose model storage in the welcome window.' :
      'Selected storage or job metadata needs attention. No fallback location is used.';
    if (result.invalid_manifests || result.invalid_jobs || result.truncated) {
      status.textContent += ' Some entries need review or were omitted by the display limit.';
    }
    if (result.bundled?.state === 'available') {
      card(bundled, `Bundled starter · ${result.bundled.models[0].tag}`,
        'Stored in the read-only live image. No download or weight copy needed.' +
        (result.selected_source === 'bundled' ? ' Selected for this session.' : '') +
        ' Startup checks full integrity; this view does not test a reply.');
    } else if (result.bundled?.state === 'needs-attention') {
      card(bundled, 'Bundled starter needs attention',
        'Image model files or read-only access could not be confirmed. Startup must verify the source.');
    }
    for (const model of result.installed || []) {
      card(installed, model.tag, `${model.files_present ? 'Model files present' : 'Model files incomplete'} · ` +
        `${model.catalog_manifest_match ? 'Matches catalog manifest' : 'Outside reviewed catalog revision'} · ` +
        'Full artifact checks and current reply test are not performed by this view.');
    }
    if (result.installed !== null && result.installed.length === 0) card(installed, 'No downloaded models yet', 'New model downloads will be stored in your selected location.');
    for (const job of result.jobs || []) {
      const progress = job.progress;
      const speed = progress.recent_mib_per_second === null ? 'Speed unknown' : `${progress.recent_mib_per_second.toFixed(1)} MiB/s`;
      const eta = progress.eta_seconds === null ? 'ETA unknown' : `${Math.ceil(progress.eta_seconds)} seconds remaining`;
      card(jobs, job.tag, `${job.state} · ${gib(progress.bytes_done)} / ${gib(progress.bytes_total)} · Last measured: ${speed} · Last estimate: ${eta}` +
        (job.previous_reply_verified ? ' · A previous onboarding reply passed; current readiness has not been rechecked.' : ''));
    }
    if (result.jobs !== null && result.jobs.length === 0) card(jobs, 'No download jobs', 'Existing verified-download jobs will appear here as they progress.');
    for (const model of result.catalog) {
      card(catalog, model.tag, `${model.description} · ${model.parameter_label} · ${model.quantization} · ` +
        `${gib(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license} · ` +
        `${model.context_tokens.toLocaleString()} context · CPU: ${model.cpu_fit.status} · GPU: ${model.gpu_fit.status} (estimates)`);
    }
  } catch (_) {
    status.textContent = 'Model inventory unavailable. Refresh status to retry.';
  }
}
async function refresh() {
  if (busy) return;
  busy = true;
  const status = document.getElementById('status');
  const button = document.getElementById('refresh');
  button.disabled = true;
  status.textContent = 'Checking capability inventory…';
  try {
    const result = await api('/api/capabilities');
    const cards = document.getElementById('capabilities');
    cards.replaceChildren();
    for (const item of result.capabilities) {
      const card = document.createElement('article');
      card.className = 'card';
      const heading = document.createElement('h3');
      heading.textContent = labels[item.capability] || item.capability;
      const state = document.createElement('span');
      state.className = 'state';
      state.textContent = states[item.state] || 'Status unavailable';
      card.append(heading, state);
      for (const requirement of [nextSteps[item.capability] || 'Review setup requirements.']) {
        const reason = document.createElement('p');
        reason.textContent = requirement;
        card.append(reason);
      }
      cards.append(card);
    }
    status.textContent = 'Inventory checked. Functional readiness tests are still pending.';
  } catch (_) {
    document.getElementById('capabilities').replaceChildren();
    status.textContent = 'Status unavailable. Reopen the dashboard using its current session link, then retry.';
  } finally {
    await refreshLive();
    await refreshModels();
    await refreshBenchmarks();
    busy = false;
    button.disabled = false;
  }
}
document.getElementById('chat').addEventListener('click', async () => {
  try {
    const result = await api('/api/assistant/chat');
    const url = new URL(result.url);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.pathname !== '/chat') throw new Error('Invalid chat URL');
    window.location.assign(url.href);
  } catch (_) {
    document.getElementById('assistant-help').textContent = 'Chat is not ready. Refresh status and retry.';
  }
});
document.getElementById('refresh').addEventListener('click', refresh);
const selectedRuns = new Set();
let comparedRuns = [];
async function download(path, filename) {
  const response = await fetch(path, {headers: {'X-Argos-Token': token}, cache: 'no-store'});
  if (!response.ok) throw new Error('Download unavailable');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function comparisonQuery(ids) {
  const query = new URLSearchParams();
  ids.forEach(id => query.append('run', id));
  return query.toString();
}
async function refreshBenchmarks() {
  const status = document.getElementById('benchmarks-status');
  const cards = document.getElementById('benchmark-runs');
  try {
    const result = await api('/api/benchmarks');
    cards.replaceChildren();
    const existing = new Set(result.runs.map(run => run.id));
    for (const id of selectedRuns) if (!existing.has(id)) selectedRuns.delete(id);
    for (const run of result.runs) {
      const article = document.createElement('article'); article.className = 'card';
      const label = document.createElement('label');
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = run.id;
      input.checked = selectedRuns.has(run.id);
      input.disabled = run.kind === 'ability' && !run.coverage?.complete;
      input.addEventListener('change', () => {
        if (input.checked) selectedRuns.add(run.id); else selectedRuns.delete(run.id);
        document.getElementById('compare-runs').disabled = selectedRuns.size < 2 || selectedRuns.size > 8;
        document.getElementById('download-comparison').disabled = true;
        comparedRuns = [];
      });
      label.append(input, document.createTextNode(` ${run.model} · ${run.kind}`));
      const summary = document.createElement('p');
      summary.textContent = run.kind === 'ability' ?
        `${run.summary.correct}/${run.summary.total} correct · ${run.summary.format_errors} format errors · ${run.state}` :
        run.summary.map(item => {
          if (item.skipped) return `${item.size}: skipped`;
          const timing = item.generation_tokens_per_second;
          const rate = timing.median === null ? 'unknown' : timing.median.toFixed(2) + ' tokens/s';
          return `${item.size}: ${rate} · ${timing.reported_runs}/${timing.total_runs} timings reported`;
        }).join('; ');
      const version = document.createElement('p'); version.textContent = `${run.suite_version} · ${run.created}`;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Download JSON';
      button.addEventListener('click', () => download('/api/benchmarks/run/' + run.id, `argos-${run.id}.json`).catch(() => {
        status.textContent = 'Result download unavailable. Refresh and retry.';
      }));
      article.append(label, summary, version, button); cards.append(article);
    }
    document.getElementById('compare-runs').disabled = selectedRuns.size < 2 || selectedRuns.size > 8;
    status.textContent = result.runs.length ? `${result.runs.length} saved benchmark runs.` : 'No saved benchmarks yet.';
    if (result.invalid_count || result.truncated) status.textContent += ' Some results need review or were omitted by display limits.';
  } catch (_) {
    cards.replaceChildren(); selectedRuns.clear(); comparedRuns = [];
    document.getElementById('compare-runs').disabled = true;
    document.getElementById('download-comparison').disabled = true;
    status.textContent = 'Saved results unavailable. Refresh to retry.';
  }
}
document.getElementById('compare-runs').addEventListener('click', async () => {
  const output = document.getElementById('benchmark-comparison'); output.replaceChildren();
  comparedRuns = []; document.getElementById('download-comparison').disabled = true;
  try {
    const ids = [...selectedRuns];
    const result = await api('/api/benchmarks/compare?' + comparisonQuery(ids));
    for (const row of result.rows) card(output, row.model, `${row.metric}: ${row.value === null ? 'unknown' : row.value.toFixed(3)}`);
    document.getElementById('benchmarks-status').textContent = result.limitations;
    comparedRuns = ids; document.getElementById('download-comparison').disabled = false;
  } catch (_) {
    document.getElementById('benchmarks-status').textContent = 'Select two to eight complete runs with matching suites and settings.';
  }
});
document.getElementById('download-comparison').addEventListener('click', () => {
  if (!comparedRuns.length) return;
  download('/api/benchmarks/compare.csv?' + comparisonQuery(comparedRuns), 'argos-comparison.csv').catch(() => {
    document.getElementById('benchmarks-status').textContent = 'Comparison download unavailable. Refresh and compare again.';
  });
});
refresh();
setInterval(refresh, 20000);
