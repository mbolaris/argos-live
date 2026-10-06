'use strict';
const token = new URLSearchParams(window.location.search).get('token');
const modelLabView = new URLSearchParams(window.location.search).get('view') === 'lab';
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
let managedStartup = false;
let handoffPending = false;
let startupRefreshing = false;
let liveRefreshing = false;
let downloadAvailable = false;
let downloadActive = false;
let downloadRefreshing = false;
let lastDownloadPhase = null;
let downloadChoice = null;
let catalogPreview = new Map();
let modelDestination = null;
let modelEncryption = null;
let selectionAvailable = false;
let selectionActive = false;
let selectionTag = null;
const startupSteps = {idle: 0, setup: 0, 'select-storage': 1, 'write-configuration': 1,
  configured: 2,
  'verify-starter': 1, 'verify-model': 2, 'model-service': 3, 'first-reply': 3, gateway: 4,
  reconnecting: 4, ready: 5};
function openConversation(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.pathname !== '/chat' ||
      url.username || url.password) throw new Error('Invalid chat URL');
  window.location.assign(url.href);
}
async function startupAction(action) {
  const response = await fetch('/api/startup/' + action, {method: 'POST',
    headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
  if (!response.ok) throw new Error('Startup action unavailable');
  return response.json();
}
async function refreshStartup() {
  if (startupRefreshing) return;
  startupRefreshing = true;
  try {
    const value = await api('/api/startup');
    managedStartup = value.managed === true;
    document.getElementById('startup-controls').hidden = !managedStartup;
    if (!managedStartup) return;
    document.getElementById('startup-status').textContent = value.message +
      (Number.isFinite(value.elapsed_seconds) ? ` · ${value.elapsed_seconds.toFixed(1)} s since starting` : '');
    document.getElementById('startup-progress').value = startupSteps[value.phase] ?? 0;
    document.getElementById('start-assistant').disabled = !value.can_start;
    document.getElementById('stop-assistant').disabled = !value.can_stop;
    const metrics = value.metrics;
    document.getElementById('startup-metrics').textContent = metrics && value.model_reply_verified ?
      'Warmup reply · ' +
      (Number.isInteger(metrics.raw?.eval_count) && metrics.raw.eval_count > 0 ? `${metrics.raw.eval_count} output tokens · ` : '') +
      `${metrics.backend.mode || 'Placement unknown'} · ` +
      (Number.isFinite(metrics.generation_tokens_per_second) ? `${metrics.generation_tokens_per_second.toFixed(1)} tokens/s` : 'Generation rate unavailable') +
      (Number.isFinite(metrics.time_to_first_token_seconds) ? ` · First token ${metrics.time_to_first_token_seconds.toFixed(2)} s` : '') :
      'The model check runs locally. Optional capabilities have their own setup and tests.';
    if (value.auto_open_chat && !modelLabView && !handoffPending) {
      handoffPending = true;
      try { openConversation((await startupAction('chat')).url); }
      catch (_) { handoffPending = false; }
    }
  } catch (_) {
    if (managedStartup) document.getElementById('startup-status').textContent = 'Startup status unavailable. Retry with the current session link.';
  } finally {
    startupRefreshing = false;
  }
}
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
const byteSize = bytes => !Number.isFinite(bytes) ? 'Unknown' : bytes >= 2 ** 30 ? `${(bytes / 2 ** 30).toFixed(2)} GiB` :
  bytes >= 2 ** 20 ? `${(bytes / 2 ** 20).toFixed(1)} MiB` : bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${bytes} bytes`;
const encrypted = value => value === true ? 'Encrypted' : value === false ? 'Unencrypted' : 'Encryption unknown';
async function api(path) {
  const response = await fetch(path, {headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
  if (!response.ok) throw new Error('Status unavailable');
  return response.json();
}
async function refreshLive() {
  if (liveRefreshing) return;
  liveRefreshing = true;
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
      managedStartup ? 'Your local assistant is being prepared. Progress and controls appear below.' :
      'Use Start Assistant in the welcome window. This dashboard does not start a second assistant.';
    chat.disabled = !live.chat_available;
    status.textContent = 'Live measurements refreshed. Missing measurements remain unknown.';
  } catch (_) {
    document.getElementById('hardware').replaceChildren();
    document.getElementById('assistant-status').textContent = 'Assistant status unavailable';
    chat.disabled = true;
    status.textContent = 'Live status unavailable. Retry using the current session link.';
  } finally {
    liveRefreshing = false;
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
    catalogPreview = new Map(result.catalog.map(model => [model.tag, model]));
    modelDestination = result.storage_path || null;
    modelEncryption = result.storage_encrypted;
    document.getElementById('upgrade-guidance').textContent = result.guidance?.message || 'Save a baseline, then compare the same tests after upgrading.';
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
      selectionButton(bundled.lastElementChild, result.bundled.models[0].tag, result.selected_model);
    } else if (result.bundled?.state === 'needs-attention') {
      card(bundled, 'Bundled starter needs attention',
        'Image model files or read-only access could not be confirmed. Startup must verify the source.');
    }
    for (const model of result.installed || []) {
      card(installed, model.tag, `${model.files_present ? 'Model files present' : 'Model files incomplete'} · ` +
        `${model.catalog_manifest_match ? 'Matches catalog manifest' : 'Outside reviewed catalog revision'} · ` +
        'Full artifact checks and current reply test are not performed by this view.');
      if (model.files_present && model.catalog_manifest_match) selectionButton(installed.lastElementChild, model.tag, result.selected_model);
    }
    if (result.installed !== null && result.installed.length === 0) card(installed, 'No downloaded models yet', 'New model downloads will be stored in your selected location.');
    for (const job of result.jobs || []) {
      const progress = job.progress;
      const speed = progress.recent_mib_per_second === null ? 'Speed unknown' : `${progress.recent_mib_per_second.toFixed(1)} MiB/s`;
      const eta = progress.eta_seconds === null ? 'ETA unknown' : `${Math.ceil(progress.eta_seconds)} seconds remaining`;
      card(jobs, job.tag, `${job.state} · ${byteSize(progress.bytes_done)} / ${byteSize(progress.bytes_total)} · Last measured: ${speed} · Last estimate: ${eta}` +
        (job.previous_reply_verified ? ' · A previous onboarding reply passed; current readiness has not been rechecked.' : ''));
      if (downloadAvailable && ['queued', 'paused', 'interrupted', 'failed', 'downloading', 'verifying', 'loading', 'testing', 'publishing'].includes(job.state)) {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = 'Review retry'; button.disabled = downloadActive;
        button.addEventListener('click', () => reviewDownload({job: job.id}, job.tag));
        jobs.lastElementChild.append(button);
      }
    }
    if (result.jobs !== null && result.jobs.length === 0) card(jobs, 'No download jobs', 'Existing verified-download jobs will appear here as they progress.');
    for (const model of result.catalog) {
      card(catalog, model.tag, `${model.description} · ${model.parameter_label} · ${model.quantization} · ` +
        `${gib(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license} · ` +
        `${model.context_tokens.toLocaleString()} context · CPU: ${model.cpu_fit.status} · GPU: ${model.gpu_fit.status} (estimates)`);
      if (downloadAvailable) {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = 'Review download';
        button.disabled = downloadActive || selectionActive || result.storage_state !== 'available';
        button.addEventListener('click', () => reviewDownload({tag: model.tag}, model.tag));
        catalog.lastElementChild.append(button);
      }
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
    await refreshModelControls();
    await refreshModels();
    await refreshBenchmarks();
    await refreshLab();
    await refreshStorage();
    busy = false;
    button.disabled = false;
  }
}
document.getElementById('chat').addEventListener('click', async () => {
  try {
    const result = await api('/api/assistant/chat');
    openConversation(result.url);
  } catch (_) {
    document.getElementById('assistant-help').textContent = 'Chat is not ready. Refresh status and retry.';
  }
});
document.getElementById('refresh').addEventListener('click', refresh);
for (const action of ['start', 'stop']) document.getElementById(action + '-assistant').addEventListener('click', async () => {
  try { await startupAction(action); await refreshStartup(); }
  catch (_) { document.getElementById('startup-status').textContent = 'Assistant action unavailable. Refresh and retry.'; }
});
refreshStartup();
setInterval(async () => {
  if (managedStartup) { await refreshStartup(); await refreshLive(); }
}, 3000);
const selectedRuns = new Set();
let comparedRuns = [];
let labRefreshing = false;
const labPhases = {idle: 'Ready to measure your model.', pausing: 'Pausing chat and releasing its resources…',
  'model-service': 'Starting the isolated local test service…', speed: 'Measuring model speed…',
  ability: 'Testing ability with fixed scored tasks…', cancelling: 'Cancelling; waiting for the current request and cleanup…',
  completed: 'Baseline saved. Compare the results below.', cancelled: 'Test cancelled. Any completed results remain saved.',
  failed: 'Test could not finish. Any completed results remain saved. Check model setup before retrying.'};
async function refreshLab() {
  if (labRefreshing) return;
  labRefreshing = true;
  try {
    const value = await api('/api/lab');
    document.getElementById('lab-controls').hidden = !value.available;
    document.getElementById('lab-unavailable').hidden = value.available;
    if (!value.available) return;
    document.getElementById('lab-start').disabled = value.active || downloadActive || selectionActive;
    document.getElementById('lab-cancel').disabled = !value.active || value.phase === 'cancelling';
    let message = labPhases[value.phase] || 'Checking test status…';
    if (value.model) message += ' · ' + value.model;
    if (Number.isFinite(value.elapsed_seconds)) message += ` · ${Math.round(value.elapsed_seconds)} s`;
    const progress = value.progress;
    if (value.phase === 'speed' && progress) message += progress.phase === 'warmup' ? ' · Load / warmup sample' : ` · Measured run ${progress.run}/3`;
    if (value.phase === 'ability' && progress) message += ` · ${progress.completed}/${progress.total} tasks scored`;
    if (value.resume_requested) message += ' · Assistant restart requested; see assistant status above.';
    document.getElementById('lab-status').textContent = message;
  } catch (_) {
    document.getElementById('lab-start').disabled = true;
    document.getElementById('lab-cancel').disabled = true;
    document.getElementById('lab-status').textContent = 'Test status unavailable. Refresh to retry.';
  } finally { labRefreshing = false; }
}
for (const action of ['start', 'cancel']) document.getElementById('lab-' + action).addEventListener('click', async () => {
  document.getElementById('lab-start').disabled = true;
  try {
    const response = await fetch('/api/lab/' + action, {method: 'POST', headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
    if (!response.ok) throw new Error('Test unavailable');
    await refreshLab(); await refreshStartup();
  } catch (_) { document.getElementById('lab-status').textContent = 'Test action unavailable. Refresh and retry.'; }
});
setInterval(async () => { await refreshLab(); }, 3000);
const metricLabels = {accuracy: 'Test accuracy', short_generation_tokens_per_second: 'Short-prompt output tokens/s',
  medium_generation_tokens_per_second: 'Medium-prompt output tokens/s', long_generation_tokens_per_second: 'Long-prompt output tokens/s'};
function reviewDownload(choice, tag) {
  downloadChoice = choice;
  const model = catalogPreview.get(tag);
  document.getElementById('download-review-details').textContent = model ?
    `${tag} · ${byteSize(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license} · Estimated GPU fit: ${model.gpu_fit.status}. ` +
    `Destination: ${modelDestination || 'your configured model store'} · ${encrypted(modelEncryption)}.` :
    `${tag} · Retry against the current catalog and the same identity-checked store.`;
  document.getElementById('download-confirm').disabled = !storageConfirmed;
  if (!storageConfirmed) document.getElementById('download-review-details').textContent +=
    ' Choose where models are stored (Where your data lives) before downloading.';
  document.getElementById('download-review').showModal();
}
async function refreshModelControls() {
  if (downloadRefreshing) return;
  downloadRefreshing = true;
  try {
    const value = await api('/api/models/control');
    downloadAvailable = value.available === true;
    downloadActive = value.active === true;
    document.getElementById('download-controls').hidden = !downloadAvailable;
    document.getElementById('download-pause').disabled = !downloadActive || value.phase === 'cancelling';
    document.getElementById('download-cancel').disabled = !downloadActive || value.phase === 'cancelling';
    const names = {idle: 'Choose a model below to review its download.', pausing: 'Pausing chat…',
      downloading: 'Downloading model artifacts…', verifying: 'Checking full artifact hashes…',
      loading: 'Loading the new model…', testing: 'Testing a short local reply…', publishing: 'Publishing verified files…',
      completed: 'Downloaded and reply-tested. Your active model is unchanged.', paused: 'Paused; review a retry to resume.',
      cancelled: 'Cancelled. Partial files retained; no automatic retry.', cancelling: 'Stopping the job and cleaning up its owned service…',
      failed: 'Download, storage or verification needs attention. Review before retrying.',
      interrupted: 'Backend interrupted. Review before retrying.'};
    let message = names[value.phase] || 'Checking model job…';
    if (value.model) message += ' · ' + value.model;
    const bar = document.getElementById('download-progress');
    bar.hidden = !(Number.isFinite(value.progress?.bytes_done) && value.progress?.bytes_total > 0);
    if (!bar.hidden) bar.value = Math.min(100, value.progress.bytes_done * 100 / value.progress.bytes_total);
    if (value.progress && Number.isFinite(value.progress.bytes_done)) {
      const p = value.progress;
      message += ` · ${byteSize(p.bytes_done)} / ${byteSize(p.bytes_total)}`;
      if (Number.isFinite(p.recent_mib_per_second)) message += ` · Last measured ${p.recent_mib_per_second.toFixed(1)} MiB/s`;
      if (Number.isFinite(p.eta_seconds)) message += ` · Last estimate ${Math.ceil(p.eta_seconds)} s remaining`;
    }
    const reply = value.reply_test;
    if (reply?.text_reply_verified) {
      message += ' · Onboarding reply sample';
      if (Number.isFinite(reply.eval_count)) message += `: ${reply.eval_count} output tokens`;
      if (reply.eval_duration > 0 && Number.isFinite(reply.eval_count)) message += ` · ${(reply.eval_count * 1e9 / reply.eval_duration).toFixed(1)} tokens/s`;
      message += ' (not a repeated benchmark)';
    }
    if (value.resume_requested) message += ' · Prior assistant restart requested.';
    document.getElementById('download-status').textContent = message;
    if (downloadActive) document.getElementById('lab-start').disabled = true;
    const changed = lastDownloadPhase !== value.phase;
    lastDownloadPhase = value.phase;
    if (changed && value.available) await refreshModels();
  } catch (_) {
    document.getElementById('download-status').textContent = 'Download status unavailable. Refresh before taking another action.';
  } finally { downloadRefreshing = false; }
}
document.getElementById('download-dismiss').addEventListener('click', () => document.getElementById('download-review').close());
document.getElementById('download-confirm').addEventListener('click', async () => {
  document.getElementById('download-confirm').disabled = true;
  try {
    const response = await fetch('/api/models/download', {method: 'POST',
      headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'}, body: JSON.stringify(downloadChoice)});
    if (!response.ok) throw new Error('Download unavailable');
    document.getElementById('download-review').close();
    await refreshModelControls();
  } catch (_) {
    document.getElementById('download-review-details').textContent = 'Download could not start. Check selected storage and active jobs, then refresh and review again.';
  }
});
for (const action of ['pause', 'cancel']) document.getElementById('download-' + action).addEventListener('click', async () => {
  try {
    const response = await fetch('/api/models/' + action, {method: 'POST', headers: {'X-Argos-Token': token || ''}});
    if (!response.ok) throw new Error('Control unavailable');
    await refreshModelControls();
  } catch (_) { document.getElementById('download-status').textContent = 'Job control unavailable. Refresh to check its state.'; }
});
setInterval(refreshModelControls, 3000);

function selectionButton(parent, tag, selected) {
  if (!selectionAvailable) return;
  const button = document.createElement('button'); button.type = 'button';
  button.textContent = tag === selected ? 'Current model' : 'Review switch';
  button.disabled = tag === selected || downloadActive || selectionActive;
  button.addEventListener('click', () => {
    selectionTag = tag;
    const model = catalogPreview.get(tag);
    document.getElementById('selection-details').textContent = `${selected || 'Current model'} → ${tag}. ` +
      (model ? `CPU fit: ${model.cpu_fit.status}; GPU fit: ${model.gpu_fit.status} (estimates). ` : '') +
      'Uses existing local files; no download is started.';
    document.getElementById('selection-confirm').disabled = false;
    document.getElementById('selection-review').showModal();
  });
  parent.append(button);
}
let selectionPhase = null;
let selectionRefreshing = false;
async function refreshSelection() {
  if (selectionRefreshing) return;
  selectionRefreshing = true;
  try {
    const value = await api('/api/models/selection');
    const changed = value.available !== selectionAvailable || value.phase !== selectionPhase || value.active !== selectionActive;
    selectionAvailable = value.available === true; selectionActive = value.active === true; selectionPhase = value.phase;
    document.getElementById('selection-controls').hidden = !selectionAvailable;
    document.getElementById('selection-cancel').disabled = !selectionActive || value.phase === 'cancelling';
    const messages = {idle: 'Choose Review switch on a local model.', pausing: 'Pausing the current assistant…',
      verifying: 'Rechecking all model artifacts…', starting: 'Testing the selected model through OpenClaw…',
      restoring: 'Restoring the previous selection…', 'rolled-back': 'Startup failed. The previous selection was restored.',
      completed: 'Selected model is ready. Run a baseline to compare speed and ability, or open chat.',
      cancelled: 'Switch cancelled. The previous selection was retained or restored.',
      cancelling: 'Cancelling switch and releasing resources…', failed: 'Switch needs attention. Inspect private diagnostics; owner edits are preserved.'};
    messages['recovery-blocked'] = 'Owner edits prevent automatic rollback. Assistant is stopped; private recovery record retained for review.';
    document.getElementById('selection-status').textContent = messages[value.phase] || 'Checking selection…';
    if (selectionActive) document.getElementById('lab-start').disabled = true;
    if (changed) await refreshModels();
  } catch (_) { document.getElementById('selection-status').textContent = 'Selection status unavailable. Refresh before switching.'; }
  finally { selectionRefreshing = false; }
}
document.getElementById('selection-dismiss').addEventListener('click', () => document.getElementById('selection-review').close());
document.getElementById('selection-confirm').addEventListener('click', async () => {
  document.getElementById('selection-confirm').disabled = true;
  try {
    const response = await fetch('/api/models/select', {method: 'POST', headers: {'X-Argos-Token': token || '',
      'Content-Type': 'application/json'}, body: JSON.stringify({tag: selectionTag})});
    if (!response.ok) throw new Error('Unavailable');
    document.getElementById('selection-review').close(); await refreshSelection();
  } catch (_) { document.getElementById('selection-details').textContent = 'Switch unavailable. Check local files and active workloads, then review again.'; }
});
document.getElementById('selection-cancel').addEventListener('click', async () => {
  await fetch('/api/models/select-cancel', {method: 'POST', headers: {'X-Argos-Token': token || ''}});
  await refreshSelection();
});
refreshSelection();
setInterval(refreshSelection, 3000);
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
      if (run.kind === 'ability' && run.summary.categories) {
        summary.textContent += ' · ' + Object.entries(run.summary.categories).map(([name, value]) =>
          `${name.replaceAll('_', ' ')}: ${value.correct}/${value.total}`).join(' · ');
      }
      if (run.kind === 'speed') {
        summary.textContent += ' · ' + run.summary.filter(item => !item.skipped).map(item => {
          const first = item.time_to_first_token_seconds?.median;
          const prefill = item.prompt_tokens_per_second?.median;
          return `${item.size}: first token ${Number.isFinite(first) ? first.toFixed(2) + ' s' : 'unknown'}; input ${Number.isFinite(prefill) ? prefill.toFixed(1) + ' tokens/s' : 'unknown'}`;
        }).join(' · ');
      }
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
    for (const row of result.rows) card(output, row.model,
      `${metricLabels[row.metric] || row.metric}: ${row.value === null ? 'unknown' : row.metric === 'accuracy' ? (row.value * 100).toFixed(1) + '%' : row.value.toFixed(2)}`);
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
let storageConfirmed = false;
let storageChoice = null;
let storageRefreshing = false;
const rebootText = {'not-started': 'Reboot check not started', pending: 'Reboot check started. Restart to verify.',
  retained: 'Kept across a reboot', 'not-retained': 'Marker missing after reboot', 'needs-attention': 'Reboot evidence needs review',
  unknown: 'Reboot evidence unknown'};
function backingText(backing) {
  if (!backing) return 'Backing device unknown';
  if (backing.kind === 'ram') return 'Temporary memory. Lost at reboot.';
  if (backing.kind !== 'disk') return 'Backing device unknown';
  const name = backing.label || backing.device || 'Unnamed volume';
  return `${name} · ${backing.filesystem || 'filesystem unknown'} · ${encrypted(backing.encrypted)}` +
    (backing.live_persistence ? ' · Live persistence' : '') + (backing.boot_medium ? ' · Boot drive' : '');
}
async function refreshStorage() {
  if (storageRefreshing) return;
  storageRefreshing = true;
  const status = document.getElementById('storage-status');
  const places = document.getElementById('storage-locations');
  const choices = document.getElementById('storage-choices');
  try {
    const view = await api('/api/storage');
    if (view.available === false) { status.textContent = 'Storage details are available in the managed desktop workspace.'; return; }
    places.replaceChildren(); choices.replaceChildren();
    storageConfirmed = view.confirmed === true;
    for (const row of view.locations) {
      const free = row.free_bytes === null ? '' : ` · ${gib(row.free_bytes)} free of ${gib(row.total_bytes)}`;
      card(places, row.label, `${row.path || 'Not chosen yet'} · ${backingText(row.backing)}${free} · ${rebootText[row.reboot?.state] || rebootText.unknown}` +
        (row.reboot?.verified_at ? ` (${row.reboot.verified_at.slice(0, 10)})` : '') + (row.note ? ' · ' + row.note : ''));
    }
    status.textContent = view.state === 'not-configured' ? 'No model location chosen yet.' :
      view.state === 'needs-attention' ? 'Selected model storage needs attention. No fallback location is used.' :
      storageConfirmed ? 'Model location confirmed.' : 'Model location not yet confirmed. Confirm it before large downloads.';
    if (!view.boot_id_available) status.textContent += ' Boot identity is unavailable, so reboot checks cannot run.';
    for (const item of view.candidates) {
      const detail = `${item.volume_label || item.mountpoint} · ${item.path} · ${gib(item.free_bytes)} free · ${encrypted(item.encrypted)}` +
        (item.temporary ? ' · Temporary: models are lost at reboot' : '') + (item.current ? ' · In use' : '') +
        (item.contains_data ? ' · Folder already has files; it cannot be used' : '');
      card(choices, item.kind === 'ram' ? 'Temporary memory' : 'Drive', detail);
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = item.current ? (storageConfirmed ? 'Confirmed' : 'Confirm this location') : 'Review this location';
      button.disabled = item.contains_data || (!item.current && !view.can_change) || (item.current && storageConfirmed);
      button.addEventListener('click', () => {
        storageChoice = item.id;
        document.getElementById('storage-review-details').textContent = `${item.path} · ${gib(item.free_bytes)} free · ${encrypted(item.encrypted)}` +
          (item.temporary ? '. Temporary: downloaded models will be lost at reboot.' : '.') +
          (view.change_blocked_reason ? ' ' + view.change_blocked_reason : '');
        document.getElementById('storage-confirm').disabled = false;
        document.getElementById('storage-review').showModal();
      });
      choices.lastElementChild.append(button);
    }
    if (!view.candidates.length) card(choices, 'No eligible location', 'No writable drive has enough free space. Chat and the bundled starter still work offline.');
    if (view.change_blocked_reason) document.getElementById('storage-choice-help').textContent = view.change_blocked_reason;
    document.getElementById('reboot-check').disabled = view.state !== 'available' || !view.boot_id_available;
  } catch (_) {
    status.textContent = 'Storage details unavailable. Refresh to retry.';
  } finally { storageRefreshing = false; }
}
document.getElementById('storage-dismiss').addEventListener('click', () => document.getElementById('storage-review').close());
document.getElementById('storage-confirm').addEventListener('click', async () => {
  document.getElementById('storage-confirm').disabled = true;
  try {
    const response = await fetch('/api/storage/choose', {method: 'POST',
      headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'}, body: JSON.stringify({candidate: storageChoice})});
    if (!response.ok) throw new Error('Storage unavailable');
    document.getElementById('storage-review').close();
    await refreshStorage(); await refreshModels();
  } catch (_) {
    document.getElementById('storage-review-details').textContent = 'That location could not be used. Its write check or space check failed, or it changed. Refresh and choose again.';
  }
});
document.getElementById('reboot-check').addEventListener('click', async () => {
  document.getElementById('reboot-check').disabled = true;
  try {
    const response = await fetch('/api/storage/reboot-check', {method: 'POST', headers: {'X-Argos-Token': token || ''}});
    if (!response.ok) throw new Error('Reboot check unavailable');
    await refreshStorage();
  } catch (_) { document.getElementById('storage-status').textContent = 'Reboot check could not start. Refresh and retry.'; }
});

refresh();
setInterval(refresh, 20000);
