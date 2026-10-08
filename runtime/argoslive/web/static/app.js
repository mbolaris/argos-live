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
let managedStartup = false;
let startupRefreshing = false;
let lastStartupStatus = null;
let lastLabRecovery = null;

function formatRecoveryStatus(recovery) {
  // Respect explicit not-running state
  const rawState = recovery?.state || recovery?.phase;
  if (rawState === 'not-running') return 'Assistant was not running.';

  // Prefer current startup evidence whenever available
  if (lastStartupStatus) {
    const sPhase = lastStartupStatus.phase;
    if (sPhase === 'ready') return 'Assistant ready.';
    if (sPhase === 'failed') return 'Assistant recovery failed.';
    if (sPhase === 'not-running' || sPhase === 'stopped') return 'Assistant was not running.';
    if (lastStartupStatus.active ||
        ['setup', 'verify-starter', 'select-storage', 'write-configuration',
         'verify-model', 'model-service', 'first-reply', 'gateway',
         'reconnecting', 'stopping', 'recovering'].includes(sPhase)) {
      return 'Assistant recovery in progress.';
    }
  }

  // Fallback to supplied recovery object when startup status is not yet available
  if (!recovery) return '';
  if (typeof recovery === 'string') return recovery;
  const phase = recovery.state || recovery.phase;
  if (phase === 'ready') return 'Assistant ready.';
  if (phase === 'failed') return 'Assistant recovery failed.';
  if (phase === 'not-running' || phase === 'stopped') return 'Assistant was not running.';
  if (phase === 'recovering' || recovery.active ||
      ['setup', 'verify-starter', 'select-storage', 'write-configuration',
       'verify-model', 'model-service', 'first-reply', 'gateway',
       'reconnecting', 'stopping'].includes(phase)) {
    return 'Assistant recovery in progress.';
  }
  if (recovery.message && !recovery.phase) return recovery.message;
  return phase ? `Assistant ${phase}.` : '';
}

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
    lastStartupStatus = value;
    const arenaBanner = document.getElementById('arena-summary-banner');
    const arenaHeadline = document.getElementById('arena-summary-headline');
    const arenaDetail = document.getElementById('arena-summary-detail');
    if (arenaBanner && !arenaBanner.hidden && arenaHeadline?.textContent === 'Stopped · incomplete' && arenaDetail) {
      const rec = formatRecoveryStatus(lastStartupStatus);
      if (rec) {
        const prefix = arenaDetail.textContent.replace(/\s*(?:Assistant [^.]+\.)?$/, '').trim();
        arenaDetail.textContent = prefix ? `${prefix} ${rec}` : rec;
      }
    }
    managedStartup = value.managed === true;
    document.getElementById('startup-controls').hidden = !managedStartup;
    if (!managedStartup) return;
    document.getElementById('startup-status').textContent = value.message +
      (Number.isFinite(value.elapsed_seconds) ? ` · ${value.elapsed_seconds.toFixed(1)} s since starting` : '');
    if (value.phase === 'ready' && value.model_reply_verified) {
      document.getElementById('assistant-status').textContent = `Argos online · ${value.model || 'local model'} passed its warm-up reply`;
      document.getElementById('assistant-help').textContent = 'Warm-up confirms one local reply. Run a systems trial below to measure speed and tested ability.';
    }
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
    card(cards, 'Saved workspace', live.guest_session === true ? 'Guest mode — conversations, settings, downloads and results reset on reboot' : persistence.active === true ? `${encrypted(persistence.encrypted)} persistence active` :
      persistence.active === false ? 'Temporary session — changes may be lost at reboot' : 'Persistence status unknown');
    card(cards, 'Network', live.network.default_route === true ? 'Network connected · Internet access not verified' :
      live.network.default_route === false ? 'Offline · Local chat does not need internet' : 'Network status unknown');
    const ollama = live.ollama;
    card(cards, 'Model service', ollama.reachable ? `Ollama ${ollama.version || '(version unknown)'} reachable` : 'Ollama is not reachable');
    card(cards, 'Models in use', ollama.loaded_models === null ? 'Loaded model status unknown' : ollama.loaded_models.length ? ollama.loaded_models.map(m =>
      `${m.name} · ${m.backend.mode || 'Placement unknown'}`).join('; ') : 'No loaded models reported');
    if (!managedStartup) {
    document.getElementById('assistant-status').textContent = live.assistant === 'ready' ? 'Assistant gateway ready' :
      live.assistant === 'not-configured' ? 'Assistant setup needed' : 'Assistant is not ready';
    document.getElementById('assistant-help').textContent = live.chat_available ?
      'Open your existing conversation. A ready gateway does not yet verify a model reply.' :
      managedStartup ? 'Your local assistant is being prepared. Progress and controls appear below.' :
      'Use Start Assistant in the welcome window. This dashboard does not start a second assistant.';
    }
    chat.disabled = !live.chat_available;
    document.getElementById('chat-fallback').disabled = !live.chat_available;
    status.textContent = 'Live measurements refreshed. Missing measurements remain unknown.';
  } catch (_) {
    document.getElementById('hardware').replaceChildren();
    document.getElementById('assistant-status').textContent = 'Assistant status unavailable';
    chat.disabled = true;
    document.getElementById('chat-fallback').disabled = true;
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
    const distinctInstalled = (result.installed || []).filter(model => !sameBundledModel(model, result.bundled));
    for (const model of distinctInstalled) {
      card(installed, model.tag, `${model.files_present ? 'Model files present' : 'Model files incomplete'} · ` +
        `${model.catalog_manifest_match ? 'Matches catalog manifest' : 'Outside reviewed catalog revision'} · ` +
        'Full artifact checks and current reply test are not performed by this view.');
      if (model.files_present && model.catalog_manifest_match) selectionButton(installed.lastElementChild, model.tag, result.selected_model);
    }
    if (result.installed !== null && distinctInstalled.length === 0) card(installed, 'No additional models yet', 'Choose a candidate below. Download and verify it, then compare it with your starter on the same trials.');
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
async function openChat() {
  try {
    const result = await api('/api/assistant/chat');
    openConversation(result.url);
  } catch (_) {
    document.getElementById('assistant-help').textContent = 'Chat is not ready. Refresh status and retry.';
  }
}
document.getElementById('chat').addEventListener('click', openChat);
document.getElementById('chat-fallback').addEventListener('click', openChat);
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
let lastLabPhase = null;
const labPhases = {idle: 'Ready to measure your model.', pausing: 'Pausing chat and releasing its resources…',
  'model-service': 'Starting the isolated local test service…', speed: 'Measuring model speed…',
  debrief: 'Argos is reflecting on the measured results…', task: 'Reading your document…', ability: 'Testing ability with fixed scored tasks…', documents: 'Reading short documents and answering from them…', cancelling: 'Cancelling; waiting for the current request and cleanup…',
  completed: 'Baseline saved. Compare the results below.', cancelled: 'Test cancelled. Any completed results remain saved.',
  failed: 'Test could not finish. Any completed results remain saved. Check model setup before retrying.'};
let arenaRunId = null;
let arenaCursor = 0;
let arenaPolling = false;
let arenaTimer = null;
let arenaReceipts = [];
let arenaCurrentAnswer = '';

const outcomeMeta = {
  pass: {label: 'Pass', cls: 'outcome-pass', reason: 'Criteria verified'},
  wrong_answer: {label: 'Wrong Answer', cls: 'outcome-wrong', reason: 'Answer did not match expected criteria'},
  format_error: {label: 'Format Error', cls: 'outcome-format', reason: 'Did not follow required format or closed JSON schema'},
  unscored: {label: 'Summary', cls: 'outcome-unscored', reason: 'Summary generated for owner judgment'}
};

function renderReceiptItem(receipt) {
  const meta = outcomeMeta[receipt.outcome] || outcomeMeta.unscored;
  const row = document.createElement('div');
  row.className = 'arena-receipt-row';

  const head = document.createElement('div');
  head.className = 'arena-receipt-head';

  const badge = document.createElement('span');
  badge.className = `arena-badge-outcome ${meta.cls}`;
  badge.textContent = meta.label;

  const tag = document.createElement('span');
  tag.className = 'arena-tag';
  tag.textContent = `${receipt.item_id || 'item'} · ${receipt.category || ''}`;

  const latency = document.createElement('span');
  latency.className = 'arena-receipt-meta';
  if (Number.isFinite(receipt.latency_seconds)) {
    latency.textContent = `${receipt.latency_seconds.toFixed(2)}s`;
  }

  head.append(badge, tag, latency);

  const reason = document.createElement('div');
  reason.className = 'arena-receipt-reason';
  reason.textContent = meta.reason;

  row.append(head, reason);

  if (receipt.output) {
    const out = document.createElement('div');
    out.className = 'arena-receipt-output';
    out.textContent = receipt.output;
    row.append(out);
  }
  return row;
}

function updateArenaHUD(arena, phase, model, elapsed, active) {
  const badge = document.getElementById('arena-phase-badge');
  if (badge) {
    if (phase === 'cancelled') {
      badge.textContent = 'STOPPED · INCOMPLETE';
      badge.className = 'arena-badge phase-cancelled incomplete';
    } else if (phase === 'failed') {
      badge.textContent = 'FAILED · INCOMPLETE';
      badge.className = 'arena-badge phase-failed incomplete';
    } else {
      badge.textContent = labPhases[phase] ? phase.toUpperCase() : 'IDLE';
      badge.className = `arena-badge phase-${phase}`;
    }
    badge.classList.toggle('running', active === true);
  }
  const m = document.getElementById('arena-model');
  if (m) m.textContent = model || 'Configured model';
  const el = document.getElementById('arena-elapsed');
  if (el) el.textContent = Number.isFinite(elapsed) ? `${Math.round(elapsed)} s` : '0 s';

  const total = (arena && arena.total) ? arena.total : 20;
  const completed = (arena && arena.completed) ? arena.completed : 0;
  const bar = document.getElementById('arena-progress-bar');
  if (bar) { bar.max = total; bar.value = completed; }
  const pl = document.getElementById('arena-progress-label');
  if (pl) pl.textContent = `${completed} / ${total} challenges`;

  const passed = (arena && arena.correct) ? arena.correct : 0;
  const formatErrors = (arena && arena.format_errors) ? arena.format_errors : 0;
  const tp = document.getElementById('arena-tally-passed');
  if (tp) tp.textContent = `${passed} passed`;
  const tf = document.getElementById('arena-tally-format-errors');
  if (tf) tf.textContent = `${formatErrors} format errors`;
}

function updateArenaReceipts(receipts) {
  const list = document.getElementById('arena-receipts-list');
  if (!list) return;
  list.replaceChildren();
  for (const r of receipts) {
    list.appendChild(renderReceiptItem(r));
  }
  const tally = document.getElementById('arena-receipts-tally');
  if (tally) tally.textContent = `${receipts.length} scored`;
}

function renderArenaState(arena, active, phase, model, elapsed) {
  const arenaEl = document.getElementById('arena');
  if (!arenaEl) return;
  arenaEl.hidden = false;

  updateArenaHUD(arena, phase, model, elapsed, active);

  const livePrompt = document.getElementById('arena-current-prompt');
  const liveStream = document.getElementById('arena-current-stream');
  const streamInd = document.getElementById('arena-stream-indicator');
  const liveId = document.getElementById('arena-current-id');
  const liveCat = document.getElementById('arena-current-category');

  if (phase === 'speed') {
    if (liveId) liveId.textContent = 'speed-run';
    if (liveCat) liveCat.textContent = 'throughput';
    if (livePrompt) livePrompt.textContent = 'Measuring short-prompt generation speed, prompt processing, and first-token latency with fixed prompts.';
    if (liveStream) liveStream.textContent = 'Running model speed measurements…';
    if (streamInd) streamInd.hidden = true;
  } else if (arena && arena.current_item) {
    if (liveId) liveId.textContent = arena.current_item.item_id || 'active';
    if (liveCat) liveCat.textContent = arena.current_item.category || '';
    if (livePrompt) livePrompt.textContent = arena.current_item.prompt || 'Running challenge…';
    if (arena.current_item.answer) {
      if (liveStream) liveStream.textContent = arena.current_item.answer;
      arenaCurrentAnswer = arena.current_item.answer;
    }
    if (streamInd) streamInd.hidden = !active;
  } else {
    if (streamInd) streamInd.hidden = true;
  }

  // Clear working/generating indicators when cancelled, failed or inactive
  if (!active && (phase === 'cancelled' || phase === 'failed')) {
    if (streamInd) streamInd.hidden = true;
    if (liveStream) {
      if (!liveStream.textContent || liveStream.textContent === 'Generating response…' || liveStream.textContent === 'Awaiting model response…') {
        liveStream.textContent = phase === 'cancelled' ?
          '(Trial stopped before response was generated)' :
          '(Trial failed before response was generated)';
      } else if (phase === 'cancelled' && !liveStream.textContent.includes('[Stopped · incomplete]')) {
        liveStream.textContent += '\n[Stopped · incomplete]';
      }
    }
    document.querySelector('#cc-schematic [data-system="power-core"]')?.classList.remove('working');
  }

  if (arena && Array.isArray(arena.receipts)) {
    arenaReceipts = arena.receipts;
    updateArenaReceipts(arenaReceipts);
  }

  const banner = document.getElementById('arena-summary-banner');
  const headline = document.getElementById('arena-summary-headline');
  const detail = document.getElementById('arena-summary-detail');

  if (banner && headline && detail) {
    if (phase === 'completed') {
      banner.hidden = false;
      headline.textContent = 'Trial completed and saved';
      detail.textContent = `${arena?.correct || 0} of ${arena?.total || 0} passed · ${arena?.format_errors || 0} format errors · Evidence bound to ${model || 'model'} digest. Baseline saved.`;
    } else if (phase === 'cancelled') {
      banner.hidden = false;
      headline.textContent = 'Stopped · incomplete';
      const recoveryText = formatRecoveryStatus(arena?.recovery || lastLabRecovery);
      const recoverySuffix = recoveryText ? ` ${recoveryText}` : '';
      detail.textContent = `${arena?.completed || 0} of ${arena?.total || 0} challenges evaluated (incomplete). Partial results are preserved but do not qualify.${recoverySuffix}`;
    } else if (phase === 'failed') {
      banner.hidden = false;
      headline.textContent = 'Trial failed · incomplete';
      detail.textContent = 'Check model setup and compute resources before retrying. Partial results do not qualify.';
    } else {
      banner.hidden = true;
    }
  }
}

function applyArenaEvent(ev) {
  if (ev.type === 'phase') {
    const badge = document.getElementById('arena-phase-badge');
    if (badge) {
      if (ev.phase === 'cancelled') {
        badge.textContent = 'STOPPED · INCOMPLETE';
        badge.className = 'arena-badge phase-cancelled incomplete';
      } else if (ev.phase === 'failed') {
        badge.textContent = 'FAILED · INCOMPLETE';
        badge.className = 'arena-badge phase-failed incomplete';
      } else {
        badge.textContent = ev.phase.toUpperCase();
        badge.className = `arena-badge phase-${ev.phase}`;
      }
    }
    if (Number.isFinite(ev.elapsed_seconds)) {
      const el = document.getElementById('arena-elapsed');
      if (el) el.textContent = `${Math.round(ev.elapsed_seconds)} s`;
    }
  } else if (ev.type === 'item-start') {
    const liveId = document.getElementById('arena-current-id');
    if (liveId) liveId.textContent = ev.item_id || 'active';
    const liveCat = document.getElementById('arena-current-category');
    if (liveCat) liveCat.textContent = ev.category || '';
    const livePrompt = document.getElementById('arena-current-prompt');
    if (livePrompt) livePrompt.textContent = ev.prompt || 'Evaluating challenge…';
    arenaCurrentAnswer = '';
    const liveStream = document.getElementById('arena-current-stream');
    if (liveStream) liveStream.textContent = 'Generating response…';
    const streamInd = document.getElementById('arena-stream-indicator');
    if (streamInd) streamInd.hidden = false;
    if (Number.isFinite(ev.completed) && Number.isFinite(ev.total)) {
      const bar = document.getElementById('arena-progress-bar');
      if (bar) bar.value = ev.completed;
      const pl = document.getElementById('arena-progress-label');
      if (pl) pl.textContent = `${ev.completed} / ${ev.total} challenges`;
    }
  } else if (ev.type === 'answer-delta') {
    const delta = ev.delta || '';
    const MAX_BROWSER_STREAM = 8192;
    if (arenaCurrentAnswer.length < MAX_BROWSER_STREAM) {
      const remaining = MAX_BROWSER_STREAM - arenaCurrentAnswer.length;
      arenaCurrentAnswer += delta.slice(0, remaining);
      if (arenaCurrentAnswer.length >= MAX_BROWSER_STREAM && !arenaCurrentAnswer.endsWith('\n[truncated]')) {
        arenaCurrentAnswer += '\n[truncated]';
      }
    }
    const stream = document.getElementById('arena-current-stream');
    if (stream) {
      stream.textContent = arenaCurrentAnswer;
      stream.scrollTop = stream.scrollHeight;
    }
  } else if (ev.type === 'item-scored') {
    if (ev.receipt) {
      arenaReceipts.push(ev.receipt);
      const MAX_BROWSER_RECEIPTS = 100;
      if (arenaReceipts.length > MAX_BROWSER_RECEIPTS) {
        arenaReceipts.shift();
      }
      const list = document.getElementById('arena-receipts-list');
      if (list) {
        list.appendChild(renderReceiptItem(ev.receipt));
        while (list.children.length > MAX_BROWSER_RECEIPTS) {
          list.removeChild(list.firstChild);
        }
        list.scrollTop = list.scrollHeight;
      }
      const tally = document.getElementById('arena-receipts-tally');
      if (tally) tally.textContent = `${arenaReceipts.length} scored`;
      const passed = arenaReceipts.filter(r => r.score === 1).length;
      const errors = arenaReceipts.filter(r => r.outcome === 'format_error').length;
      const tp = document.getElementById('arena-tally-passed');
      if (tp) tp.textContent = `${passed} passed`;
      const tf = document.getElementById('arena-tally-format-errors');
      if (tf) tf.textContent = `${errors} format errors`;
      if (Number.isFinite(ev.completed) && Number.isFinite(ev.total)) {
        const bar = document.getElementById('arena-progress-bar');
        if (bar) bar.value = ev.completed;
        const pl = document.getElementById('arena-progress-label');
        if (pl) pl.textContent = `${ev.completed} / ${ev.total} challenges`;
      }
    }
  } else if (ev.type === 'final') {
    const streamInd = document.getElementById('arena-stream-indicator');
    if (streamInd) streamInd.hidden = true;
    const liveStream = document.getElementById('arena-current-stream');
    if (liveStream) {
      if (!liveStream.textContent || liveStream.textContent === 'Generating response…' || liveStream.textContent === 'Awaiting model response…') {
        liveStream.textContent = ev.outcome === 'cancelled' ?
          '(Trial stopped before response was generated)' :
          ev.outcome === 'failed' ?
          '(Trial failed before response was generated)' :
          liveStream.textContent;
      } else if (ev.outcome === 'cancelled' && !liveStream.textContent.includes('[Stopped · incomplete]')) {
        liveStream.textContent += '\n[Stopped · incomplete]';
      }
    }
    const badge = document.getElementById('arena-phase-badge');
    if (badge) {
      if (ev.outcome === 'cancelled') {
        badge.textContent = 'STOPPED · INCOMPLETE';
        badge.className = 'arena-badge phase-cancelled incomplete';
      } else if (ev.outcome === 'failed') {
        badge.textContent = 'FAILED · INCOMPLETE';
        badge.className = 'arena-badge phase-failed incomplete';
      }
      badge.classList.remove('running');
    }
    const banner = document.getElementById('arena-summary-banner');
    if (banner) {
      banner.hidden = false;
      const headline = document.getElementById('arena-summary-headline');
      const detail = document.getElementById('arena-summary-detail');
      if (ev.outcome === 'completed') {
        if (headline) headline.textContent = 'Trial completed and saved';
        if (detail) detail.textContent = `${ev.correct || 0} of ${ev.total || 0} passed · ${ev.format_errors || 0} format errors · Baseline saved.`;
      } else if (ev.outcome === 'cancelled') {
        if (headline) headline.textContent = 'Stopped · incomplete';
        const recoveryText = formatRecoveryStatus(ev.recovery || lastLabRecovery);
        const recoverySuffix = recoveryText ? ` ${recoveryText}` : '';
        if (detail) detail.textContent = `${ev.completed || 0} of ${ev.total || 0} challenges evaluated (incomplete). Partial results are preserved but do not qualify.${recoverySuffix}`;
      } else {
        if (headline) headline.textContent = 'Trial failed · incomplete';
        if (detail) detail.textContent = 'Check model setup and compute resources before retrying. Partial results do not qualify.';
      }
    }
    document.querySelector('#cc-schematic [data-system="power-core"]')?.classList.remove('working');
    stopArenaPolling();
    refreshBenchmarks();
    refreshStartup();
    refreshCommand();
  }
}

async function pollArenaEvents() {
  if (arenaPolling) return;
  arenaPolling = true;
  try {
    const url = `/api/lab/events?after=${arenaCursor}` + (arenaRunId ? `&run=${encodeURIComponent(arenaRunId)}` : '');
    const data = await api(url);
    if (!data) return;
    if (data.reset || data.gap) {
      arenaCursor = data.cursor || 0;
      arenaRunId = data.run_id;
      if (data.arena) {
        renderArenaState(data.arena, data.active, data.phase, data.arena.model, data.arena.elapsed_seconds);
      }
      return;
    }
    arenaCursor = data.cursor || arenaCursor;
    arenaRunId = data.run_id;
    if (Array.isArray(data.events)) {
      for (const ev of data.events) {
        applyArenaEvent(ev);
      }
    }
    if (!data.active) {
      stopArenaPolling();
    }
  } catch (_) {
    // transient network error
  } finally {
    arenaPolling = false;
  }
}

function startArenaPolling() {
  if (!arenaTimer) {
    arenaTimer = setInterval(pollArenaEvents, 300);
  }
}

function stopArenaPolling() {
  if (arenaTimer) {
    clearInterval(arenaTimer);
    arenaTimer = null;
  }
}

async function refreshLab() {
  if (labRefreshing) return;
  labRefreshing = true;
  try {
    const value = await api('/api/lab');
    lastLabRecovery = value.recovery;
    document.getElementById('lab-controls').hidden = !value.available;
    document.getElementById('lab-unavailable').hidden = value.available;
    if (!value.available) return;
    document.getElementById('lab-start').disabled = value.active || downloadActive || selectionActive;
    document.getElementById('lab-start-documents').disabled = value.active || downloadActive || selectionActive;
    if (['baseline', 'documents'].includes(commandAction?.action)) {
      document.getElementById('cc-next-go').disabled = value.active || downloadActive || selectionActive;
    }
    document.getElementById('lab-cancel').disabled = !value.active || value.phase === 'cancelling';
    let message = labPhases[value.phase] || 'Checking test status…';
    if (value.model) message += ' · ' + value.model;
    if (Number.isFinite(value.elapsed_seconds)) message += ` · ${Math.round(value.elapsed_seconds)} s`;
    const progress = value.progress;
    if (value.phase === 'speed' && progress) message += progress.phase === 'warmup' ? ' · Load / warmup sample' : ` · Measured run ${progress.run}/3`;
    if ((value.phase === 'ability' || value.phase === 'documents') && progress) message += ` · ${progress.completed}/${progress.total} tasks scored`;
    if (value.phase === 'completed' && value.plan === 'documents') message = 'Document trial saved. Compare the results below.' + (value.model ? ' · ' + value.model : '');
    if (value.resume_requested) message += ' · Assistant restart requested; see assistant status above.';
    document.getElementById('lab-status').textContent = message;
    lastLabDebrief = value.debrief;
    document.getElementById('cc-live-trial').textContent = value.active ? message : '';
    renderTask(value);
    document.querySelector('#cc-schematic [data-system="power-core"]')?.classList.toggle('working', value.active === true);
    if (lastLabPhase && lastLabPhase !== value.phase && !value.active) refreshCommand();
    lastLabPhase = value.phase;

    // Render live arena state and manage polling
    if (value.arena || value.active) {
      if (value.run_id && value.run_id !== arenaRunId) {
        arenaRunId = value.run_id;
        arenaCursor = value.seq || 0;
        arenaReceipts = [];
        arenaCurrentAnswer = '';
      }
      renderArenaState(value.arena, value.active, value.phase, value.model, value.elapsed_seconds);
      if (value.active) {
        startArenaPolling();
      } else {
        stopArenaPolling();
      }
    }
  } catch (_) {
    document.getElementById('lab-start').disabled = true;
    document.getElementById('lab-start-documents').disabled = true;
    document.getElementById('lab-cancel').disabled = true;
    document.getElementById('lab-status').textContent = 'Test status unavailable. Refresh to retry.';
  } finally { labRefreshing = false; }
}
for (const [id, route] of [['lab-start', 'start'], ['lab-start-documents', 'start-documents'], ['lab-cancel', 'cancel']]) document.getElementById(id).addEventListener('click', async () => {
  document.getElementById('lab-start').disabled = true;
  document.getElementById('lab-start-documents').disabled = true;
  document.getElementById('lab-status').textContent = route === 'cancel' ? 'Requesting cancellation…' : 'Starting trial; pausing chat…';
  if (route === 'cancel') {
    const badge = document.getElementById('arena-phase-badge');
    if (badge) badge.textContent = 'STOPPING…';
  }
  try {
    const response = await fetch('/api/lab/' + route, {method: 'POST', headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
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
    document.getElementById('selection-controls').hidden = !selectionAvailable || value.phase === 'idle';
    document.getElementById('selection-cancel').disabled = !selectionActive || value.phase === 'cancelling';
    document.getElementById('selection-cancel').hidden = !selectionActive;
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
      if (run.qualification) {
        const q = run.qualification;
        const verdict = document.createElement('p');
        verdict.textContent = (q.qualified ? 'Qualified for short documents. ' : q.complete ? 'Not qualified for short documents. ' : 'Incomplete run: not qualified. ') +
          q.checks.map(c => `${c.label}: ${c.observed} (${c.name === 'format_errors' ? 'at most' : 'needs'} ${c.required}) ${c.met ? 'met' : 'not met'}`).join(' · ') +
          ` · Context ${run.document_context?.context ?? 'unknown'}` +
          (run.document_context?.longest_prompt_tokens_tested ? `, longest prompt ${run.document_context.longest_prompt_tokens_tested} tokens` : '') +
          '. ' + q.scope;
        article.append(verdict);
      }
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
const pct = (v) => v === null || v === undefined ? 'unknown' : (v * 100).toFixed(1) + '%';
const num = (v, unit) => v === null || v === undefined ? 'unknown' : v.toFixed(2) + (unit || '');
function cell(row, text, header) {
  const c = document.createElement(header ? 'th' : 'td'); c.textContent = text; row.append(c); return c;
}
function table(parent, caption, heads, rows) {
  const t = document.createElement('table'); const cap = document.createElement('caption'); cap.textContent = caption; t.append(cap);
  const head = document.createElement('tr'); heads.forEach((h) => cell(head, h, true)); t.append(head);
  for (const r of rows) { const tr = document.createElement('tr'); r.forEach((v, i) => cell(tr, v, i === 0)); t.append(tr); }
  parent.append(t);
}
function renderMatched(output, result) {
  const runs = result.runs || [];
  const names = runs.map((r, i) => `${i === 0 ? 'Before' : runs.length > 2 ? 'Run ' + (i + 1) : 'After'}: ${r.model}`);
  if (result.kind === 'ability') {
    table(output, 'Accuracy and format, shown separately from speed', ['Run', 'Correct', 'Accuracy', 'Format errors', 'Document criteria'],
      runs.map((r, i) => [names[i], `${r.correct}/${r.total}`, pct(r.accuracy), String(r.format_errors),
        r.qualification ? (r.qualification.complete ? (r.qualification.qualified ? 'Met' : 'Not met') : 'Incomplete') : 'Not applicable']));
    const cats = [...new Set(runs.flatMap((r) => Object.keys(r.categories || {})))];
    if (cats.length) table(output, 'By category', ['Category', ...names], cats.map((c) => [c.replace('_', ' '),
      ...runs.map((r) => { const v = (r.categories || {})[c]; return v ? `${v.correct}/${v.total}` : 'n/a'; })]));
    const items = result.items || [];
    const changed = items.filter((i) => new Set(Object.values(i.runs).map((x) => x.outcome)).size > 1);
    const heading = document.createElement('h3'); heading.textContent = `Same questions, side by side (${changed.length} of ${items.length} differ)`; output.append(heading);
    for (const item of (changed.length ? changed : items.slice(0, 3))) {
      const box = document.createElement('details'); const sum = document.createElement('summary');
      sum.textContent = `${item.category.replace('_', ' ')}: ${item.question || item.item_id}`; box.append(sum);
      runs.forEach((r, i) => { const x = item.runs[r.id]; const p = document.createElement('p');
        p.textContent = `${names[i]} (${x.outcome.replace('_', ' ')}): ${x.output ?? 'no output kept'}`; box.append(p); });
      output.append(box);
    }
    if ((result.summaries || []).length) {
      const h = document.createElement('h3'); h.textContent = 'Summaries for you to judge (not scored)'; output.append(h);
      for (const s of result.summaries) { const box = document.createElement('details'); const sm = document.createElement('summary');
        sm.textContent = s.question || s.item_id; box.append(sm);
        runs.forEach((r, i) => { const p = document.createElement('p'); p.textContent = `${names[i]}: ${s.runs[r.id] ?? 'no output kept'}`; box.append(p); });
        output.append(box); }
    }
  } else {
    const sizes = [...new Set(runs.flatMap((r) => (r.prompts || []).map((p) => p.size)))];
    for (const [field, label, unit] of [['generation_tokens_per_second', 'Generation speed', ' tok/s'],
        ['prompt_tokens_per_second', 'Prompt processing speed', ' tok/s'], ['time_to_first_token_seconds', 'Wait for first token', ' s']]) {
      table(output, label, ['Prompt size', ...names], sizes.map((s) => [s, ...runs.map((r) => {
        const p = (r.prompts || []).find((x) => x.size === s); return !p || p.skipped ? 'skipped' : num(p[field], unit); })]));
    }
  }
  const note = document.createElement('p'); note.textContent = 'Speed and accuracy are separate. You decide which tradeoff is worth keeping.'; output.append(note);
}
document.getElementById('compare-runs').addEventListener('click', async () => {
  const output = document.getElementById('benchmark-comparison'); output.replaceChildren();
  comparedRuns = []; document.getElementById('download-comparison').disabled = true;
  try {
    const ids = [...selectedRuns];
    const result = await api('/api/benchmarks/compare?' + comparisonQuery(ids));
    renderMatched(output, result);
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
    document.getElementById('reboot-check').disabled = view.state !== 'available' || !view.boot_id_available || view.configured?.temporary === true;
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
    await refreshStorage(); await refreshModels(); await refreshCommand();
  } catch (_) {
    document.getElementById('storage-review-details').textContent = 'That location could not be used. Its write check or space check failed, or it changed. Refresh and choose again.';
  }
});
document.getElementById('reboot-check').addEventListener('click', async () => {
  document.getElementById('reboot-check').disabled = true;
  try {
    const response = await fetch('/api/storage/reboot-check', {method: 'POST', headers: {'X-Argos-Token': token || ''}});
    if (!response.ok) throw new Error('Reboot check unavailable');
    await refreshStorage(); await refreshCommand();
  } catch (_) { document.getElementById('storage-status').textContent = 'Reboot check could not start. Refresh and retry.'; }
});

refresh();
setInterval(refresh, 20000);

let lastLabDebrief = null;
const tierText = {routine: 'Routine', qualified: 'Qualified', commissioned: 'Commissioned'};
const systemState = {unknown: 'Not yet tested', 'bench-test': 'Bench test', qualified: 'Qualified', commissioned: 'Commissioned',
  attention: 'Needs attention'};
let commandAction = null;
function focusSection(id, control) {
  const target = document.getElementById(id);
  target.scrollIntoView({behavior: 'smooth', block: 'start'});
  if (control) document.getElementById(control)?.focus({preventScroll: true});
}
function sameBundledModel(model, bundled) {
  return bundled?.state === 'available' && model.files_present === true &&
    bundled.models.some(starter => model.tag === starter.tag &&
      typeof model.manifest_digest === 'string' && model.manifest_digest === starter.manifest_digest);
}
function startMissionTrial(control) {
  focusSection('lab-controls', control);
  const button = document.getElementById(control);
  if (!button.disabled) button.click();
}
const commandActions = {
  storage: () => focusSection('storage-title'),
  baseline: () => startMissionTrial('lab-start'),
  documents: () => startMissionTrial('lab-start-documents'),
  models: () => focusSection('models-title'),
  capabilities: () => focusSection('capabilities-title'),
  reboot: () => focusSection('storage-title', 'reboot-check'),
  chat: () => document.getElementById('chat').click(),
  task: () => { const box = document.getElementById('cc-task-box'); box.open = true; focusSection('cc-task-box', 'cc-doc'); },
  restore: () => {
    if (!commandAction?.model) return focusSection('models-title');
    selectionTag = commandAction.model;
    document.getElementById('selection-details').textContent = `Restore ${commandAction.model}. Uses existing local files; no download is started.`;
    document.getElementById('selection-confirm').disabled = false;
    document.getElementById('selection-review').showModal();
  }};
let commandRefreshing = false;
async function refreshCommand() {
  if (commandRefreshing) return;
  commandRefreshing = true;
  try {
    const value = await api('/api/command-center');
    const section = document.getElementById('command-center');
    section.hidden = value.available === false;
    if (value.available === false) return;
    document.getElementById('cc-name').textContent = value.name + (value.model ? ' · ' + value.model : '');
    const heroAi = document.getElementById('cc-hero-ai');
    if (heroAi) heroAi.textContent = value.name || 'your AI';
    const heroModel = document.getElementById('cc-hero-model');
    if (heroModel) heroModel.textContent = value.model || 'Current model';
    const heroResult = document.getElementById('cc-hero-result');
    if (heroResult) {
      const ab = value.report?.ability;
      const qualState = ab ? (ab.qualified === true ? 'Qualified' : (ab.qualified === false ? 'Criteria not met' : 'Not assessed')) : '';
      heroResult.textContent = ab ? `${ab.correct}/${ab.total} (${qualState})` : 'Not yet tested';
    }
    renderMissionReceipt(value.report);
    renderSkillMap(value.skill_map);
    const path = value.build_path;
    const pathBox = document.getElementById('cc-build-path'); pathBox.hidden = !path;
    if (path) {
      document.getElementById('cc-build-summary').textContent = `Your build path · ${path.completed} of ${path.steps.length} checks recorded`;
      document.getElementById('cc-build-scope').textContent = path.scope;
      const names = ['Prototype · ready to test', 'Mapped prototype', 'Document reader · qualified', 'Document mission · field tested'];
      const stepState = Object.fromEntries(path.steps.map(s => [s.id, s.state]));
      const stage = stepState.task === 'complete' && stepState.documents === 'complete' ? 3 :
                    stepState.documents === 'complete' ? 2 :
                    stepState.baseline === 'complete' ? 1 : 0;
      document.getElementById('cc-stage').textContent = names[stage];
      const steps = document.getElementById('cc-build-steps'); steps.replaceChildren();
      for (const step of path.steps) {
        const item = document.createElement('li'); item.dataset.state = step.state;
        if (step.state === 'current') item.setAttribute('aria-current', 'step');
        const title = document.createElement('strong'); title.textContent = step.title;
        const state = document.createElement('span');
        state.textContent = {complete: 'Recorded', current: 'Next', attention: 'Needs work', untested: 'Not yet tested'}[step.state] || 'Unknown';
        const detail = document.createElement('p'); detail.textContent = step.detail;
        const number = document.createElement('b'); number.className = 'rung-number'; number.textContent = String(path.steps.indexOf(step) + 1).padStart(2, '0');
        const notes = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'What counts'; notes.append(summary, detail);
        item.append(number, title, state, notes); steps.append(item);
      }
    }
    const next = value.next_action;
    commandAction = next;
    document.getElementById('cc-next-title').textContent = next.title;
    document.getElementById('cc-next-reason').textContent = next.reason;
    const go = document.getElementById('cc-next-go');
    go.hidden = !next.action; go.textContent = {storage: 'Set up model storage', baseline: 'Pause chat and run the first trial', documents: 'Start: Read this brief',
      models: 'Compare a model candidate', reboot: 'Verify storage after restart', chat: 'Talk to Argos', capabilities: 'Choose a capability',
      task: 'Test a document you care about', restore: 'Review the previous model'}[next.action] || 'Start this mission';
    const trialControl = {baseline: 'lab-start', documents: 'lab-start-documents'}[next.action];
    go.disabled = !!trialControl && document.getElementById(trialControl).disabled;
    const list = document.getElementById('cc-systems'); list.replaceChildren();
    const readings = document.getElementById('cc-readings'); readings.replaceChildren();
    for (const system of value.systems) {
      const item = document.createElement('li');
      item.textContent = `${system.label}: ${systemState[system.state] || system.state}. ${system.detail}`;
      list.append(item);
      const shape = document.querySelector(`#cc-schematic [data-system="${system.id}"]`);
      if (shape) shape.dataset.state = system.state;

    }
    document.getElementById('cc-scope').textContent = value.scope;
    const journalList = document.getElementById('cc-journal'); journalList.replaceChildren();
    if (!value.journal.length) { const empty = document.createElement('li'); empty.textContent = 'No milestones yet. Every robot starts on the bench.'; journalList.append(empty); }
    for (const entry of value.journal) {
      const item = document.createElement('li');
      item.textContent = `${tierText[entry.tier]} · ${entry.title}. ${entry.detail} (${entry.at.slice(0, 10)})` +
        (entry.applies_to_selected === false ? ' Earlier model files; not evidence for the files selected now.' : '');
      journalList.append(item);
    }
    const moment = document.getElementById('cc-moment');
    moment.hidden = !value.moment;
    moment.dataset.tier = value.moment?.tier || '';
    if (value.moment) {
      document.getElementById('cc-moment-title').textContent = value.moment.title;
      document.getElementById('cc-moment-tier').textContent = tierText[value.moment.tier];
      document.getElementById('cc-moment-detail').textContent = value.moment.detail;
    }
    document.getElementById('cc-quiet').checked = value.quiet === true;
  } catch (_) {
    document.getElementById('cc-next-title').textContent = 'Command center unavailable. Refresh to retry.';
  } finally { commandRefreshing = false; }
}
async function post(path, body) {
  const headers = {'X-Argos-Token': token || ''};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method: 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store'});
  if (!response.ok) throw new Error('Action unavailable');
  return response.json();
}
document.getElementById('cc-next-go').addEventListener('click', () => {
  if (['baseline', 'documents'].includes(commandAction?.action)) document.getElementById('cc-next-go').disabled = true;
  commandActions[commandAction?.action]?.();
});
document.getElementById('cc-moment-dismiss').addEventListener('click', async () => {
  try { await post('/api/command-center/seen'); } catch (_) {}
  await refreshCommand();
});
document.getElementById('cc-quiet').addEventListener('change', async (event) => {
  try { await post('/api/command-center/quiet', {quiet: event.target.checked}); } catch (_) {}
  await refreshCommand();
});
document.getElementById('cc-ask').addEventListener('click', async () => {
  const status = document.getElementById('cc-task-status');
  document.getElementById('cc-ask').disabled = true;
  try {
    await post('/api/lab/task', {document: document.getElementById('cc-doc').value, question: document.getElementById('cc-question').value});
    status.textContent = 'Pausing chat and reading your document…';
    await refreshLab(); await refreshStartup();
  } catch (_) {
    status.textContent = 'Could not start. Paste a document up to 6000 characters, ask a question, and make sure no other test or download is running.';
    document.getElementById('cc-ask').disabled = false;
  }
});
for (const [id, verdict] of [['cc-accept', 'accepted'], ['cc-reject', 'rejected']]) document.getElementById(id).addEventListener('click', async () => {
  try {
    await post('/api/lab/task-verdict', {verdict});
    document.getElementById('cc-task-note').textContent = verdict === 'accepted' ? 'Recorded: you accepted this answer.' : 'Recorded: not good enough. The result stays private.';
    document.getElementById('cc-accept').disabled = document.getElementById('cc-reject').disabled = true;
    await refreshCommand();
  } catch (_) { document.getElementById('cc-task-note').textContent = 'Could not record that. The answer may already be judged.'; }
});
let shownTask = null;
function renderTask(value) {
  const status = document.getElementById('cc-task-status');
  const box = document.getElementById('cc-task-result');
  const active = value.active && value.plan === 'task';
  document.getElementById('cc-ask').disabled = value.active === true || downloadActive || selectionActive;
  if (active) { status.textContent = labPhases[value.phase] || 'Working…'; box.hidden = true; return; }
  const task = value.plan === 'task' ? value.task : null;
  if (!task) {
    if (value.plan === 'task' && ['failed', 'cancelled'].includes(value.phase)) status.textContent = 'The document could not be read. Chat is restored.';
    return;
  }
  const answers = {answered: task.answer || '(empty answer)', not_stated: 'The document does not say.',
    too_long: 'This document is too long for the tested context. Nothing was truncated; try a shorter passage.',
    format_error: 'The model did not answer in the required form. Try again or judge it not good enough.'};
  box.hidden = false;
  document.getElementById('cc-answer').textContent = answers[task.outcome] || 'No answer.';
  document.getElementById('cc-quote').textContent = task.quote ? `Quoted: “${task.quote}”` : '';
  const judged = task.outcome === 'answered' || task.outcome === 'not_stated';
  if (shownTask !== task.task_id) {
    shownTask = task.task_id;
    document.getElementById('cc-task-note').textContent = !judged ? '' : task.quote_supported ? 'The quoted sentence appears in your text.' :
      task.outcome === 'answered' ? 'The quoted sentence was not found in your text. Check the answer before trusting it.' : '';
    document.getElementById('cc-accept').disabled = document.getElementById('cc-reject').disabled = !judged;
  }
  status.textContent = `Answered by ${task.model} in ${Number.isFinite(task.elapsed_seconds) ? task.elapsed_seconds.toFixed(1) + ' s' : 'unknown time'}. Chat is restored.`;
}
refreshCommand();
setInterval(refreshCommand, 20000);

let currentSkillMapData = null;
let selectedSkillNode = null;

function formatNodeStateBadge(state) {
  return {
    qualified: '● Qualified',
    measured: '◆ Measured',
    attention: '▲ Needs work',
    untested: '○ Untested',
    unavailable: '🔒 Future'
  }[state] || 'Unknown';
}

function openSkillNodeModal(node) {
  selectedSkillNode = node;
  const modal = document.getElementById('skill-node-modal');
  document.getElementById('node-modal-domain').textContent = node.domain_label || node.domain || '';
  document.getElementById('node-modal-title').textContent = node.title;
  const badge = document.getElementById('node-modal-state-badge');
  badge.className = `state-badge ${node.state}`;
  badge.textContent = formatNodeStateBadge(node.state);
  document.getElementById('node-modal-criteria').textContent = node.criteria || 'Fixed criteria for this challenge suite.';
  document.getElementById('node-modal-scope').textContent = node.scope || 'Scoped to fixed challenges at recorded context.';
  document.getElementById('node-modal-binding').textContent = node.manifest_digest ?
    `Bound to model "${node.model || 'selected'}" · manifest ${node.manifest_digest.slice(0, 16)}…` :
    'No verified model digest bound to this node.';

  const evEl = document.getElementById('node-modal-evidence');
  if (node.evidence) {
    if (node.id === 'doc-short') {
      evEl.textContent = `${node.evidence.qualified ? 'Passed threshold' : 'Criteria missed'}: ${node.evidence.correct}/${node.evidence.total} correct, ${node.evidence.format_errors} format errors (${node.evidence.created ? node.evidence.created.slice(0, 10) : ''}).`;
    } else if (node.id === 'storage-retention') {
      evEl.textContent = node.evidence.reboot === 'retained' ?
        `Retained across machine restart (verified: ${node.evidence.verified_at || 'yes'}).` :
        'Model storage directory confirmed; restart check pending.';
    } else {
      evEl.textContent = `Observed ${node.evidence.correct}/${node.evidence.total} correct, ${node.evidence.format_errors} format errors in latest run (${node.evidence.created ? node.evidence.created.slice(0, 10) : ''}).`;
    }
  } else {
    evEl.textContent = 'No trial runs or evidence recorded for this build yet.';
  }

  const startBtn = document.getElementById('skill-node-start');
  if (!node.available) {
    startBtn.disabled = true;
    startBtn.textContent = 'Future suite: unavailable';
  } else {
    const isDoc = node.action === 'documents';
    const isBase = node.action === 'baseline';
    const triggerId = isDoc ? 'lab-start-documents' : isBase ? 'lab-start' : null;
    startBtn.disabled = triggerId ? !!document.getElementById(triggerId)?.disabled : false;
    startBtn.textContent = node.action_label || 'Start test';
    startBtn.onclick = () => {
      modal.close();
      if (triggerId) startMissionTrial(triggerId);
      else if (node.action === 'storage') focusSection('storage-title');
    };
  }

  const upgBtn = document.getElementById('skill-node-upgrade');
  upgBtn.onclick = () => {
    modal.close();
    focusSection('models-title');
  };

  const closeBtn = document.getElementById('skill-node-close');
  closeBtn.onclick = () => modal.close();

  modal.showModal();
}

function renderSkillMap(mapData) {
  if (!mapData || !mapData.domains) return;
  currentSkillMapData = mapData;

  // Compact map overview
  const compactTally = document.getElementById('compact-map-tally');
  if (compactTally && mapData.tally) {
    compactTally.textContent = `${mapData.tally.qualified} / ${mapData.tally.active_nodes || mapData.tally.total_nodes} tasks qualified`;
  }
  const compactDomains = document.getElementById('compact-map-domains');
  if (compactDomains) {
    compactDomains.replaceChildren();
    for (const domain of mapData.domains) {
      const qCount = domain.nodes.filter(n => n.state === 'qualified').length;
      const activeCount = domain.nodes.filter(n => n.available).length;
      const pill = document.createElement('a');
      pill.href = '#skill-map-bay';
      pill.className = `compact-domain-pill ${qCount > 0 ? 'has-qualified' : ''}`;
      pill.innerHTML = `<span class="domain-icon icon-${domain.icon}"></span> <span class="pill-label">${domain.label}</span> <span class="pill-count">${qCount}/${activeCount}</span>`;
      compactDomains.append(pill);
    }
  }

  const graphContainer = document.getElementById('skill-map-graph');
  const listContainer = document.getElementById('skill-map-list');
  graphContainer.replaceChildren();
  listContainer.replaceChildren();

  // Desktop graph: domain clusters
  for (const domain of mapData.domains) {
    const cluster = document.createElement('div');
    cluster.className = 'domain-cluster';
    cluster.dataset.domain = domain.id;

    const hdr = document.createElement('div');
    hdr.className = 'domain-cluster-header';
    const icon = document.createElement('span'); icon.className = `domain-icon icon-${domain.icon}`;
    const title = document.createElement('h4'); title.textContent = domain.label;
    hdr.append(icon, title);
    cluster.append(hdr);

    const nodesGrid = document.createElement('div');
    nodesGrid.className = 'domain-nodes-grid';

    for (const node of domain.nodes) {
      node.domain_label = domain.label;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `skill-node-card state-${node.state}`;
      btn.dataset.nodeId = node.id;
      btn.setAttribute('aria-label', `${node.title}: ${formatNodeStateBadge(node.state)}`);

      const dot = document.createElement('span'); dot.className = `node-dot ${node.state}`;
      const name = document.createElement('span'); name.className = 'node-name'; name.textContent = node.title;
      const tag = document.createElement('span'); tag.className = `node-tag ${node.state}`; tag.textContent = formatNodeStateBadge(node.state);

      btn.append(dot, name, tag);
      btn.onclick = () => openSkillNodeModal(node);
      nodesGrid.append(btn);
    }
    cluster.append(nodesGrid);
    graphContainer.append(cluster);

    // Mobile grouped list
    const details = document.createElement('details');
    details.className = 'domain-list-group';
    details.open = true;

    const summary = document.createElement('summary');
    const qualifiedCount = domain.nodes.filter(n => n.state === 'qualified').length;
    const activeCount = domain.nodes.filter(n => n.available).length;
    summary.innerHTML = `<span class="domain-icon icon-${domain.icon}"></span> <strong>${domain.label}</strong> <span class="group-tally">${qualifiedCount}/${activeCount} qualified</span>`;
    details.append(summary);

    const listBody = document.createElement('div');
    listBody.className = 'domain-list-body';
    for (const node of domain.nodes) {
      const row = document.createElement('div');
      row.className = `skill-list-row state-${node.state}`;
      const info = document.createElement('div');
      const rowName = document.createElement('strong'); rowName.textContent = node.title;
      const rowTag = document.createElement('span'); rowTag.className = `node-tag ${node.state}`; rowTag.textContent = formatNodeStateBadge(node.state);
      info.append(rowName, rowTag);

      const inspectBtn = document.createElement('button');
      inspectBtn.type = 'button';
      inspectBtn.className = 'btn-inspect';
      inspectBtn.textContent = 'Details';
      inspectBtn.onclick = () => openSkillNodeModal(node);

      row.append(info, inspectBtn);
      listBody.append(row);
    }
    details.append(listBody);
    listContainer.append(details);
  }
}

function renderMissionReceipt(report) {
  const scoreboard = document.getElementById('cc-scoreboard'); scoreboard.replaceChildren();
  const bars = document.getElementById('cc-skill-bars'); bars.replaceChildren();
  const ability = report?.ability, speed = report?.speed;
  const metric = (value, label, note) => {
    const tile = document.createElement('div'); tile.className = 'score-tile';
    const number = document.createElement('strong'); number.textContent = value;
    const name = document.createElement('span'); name.textContent = label;
    const scope = document.createElement('small'); scope.textContent = note;
    tile.append(number, name, scope); scoreboard.append(tile);
  };
  metric(ability ? `${ability.correct} / ${ability.total}` : '—', 'Exercises solved', ability ? 'Latest completed fixed suite' : 'Not tested yet');
  metric(Number.isFinite(speed?.tokens_per_second) ? speed.tokens_per_second.toFixed(1) : '—', 'Output tokens / second', Number.isFinite(speed?.first_token_seconds) ? `${speed.first_token_seconds.toFixed(2)} s before the first token · short prompt` : 'No repeated speed measurement yet');
  if (Number.isFinite(speed?.prompt_tokens_per_second)) {
    metric(speed.prompt_tokens_per_second.toFixed(1), 'Prompt tokens / second', 'Prompt processing rate');
  }
  document.getElementById('cc-receipt-title').textContent = !ability ? 'Let’s find your starting point' : ability.qualified === true ? 'Short-document criteria met' : ability.qualified === false || ability.correct === 0 ? 'We found the next things to work on' : 'Your strengths are on the map';
  const categories = [...(ability?.categories || [])].filter(c => c.total > 0).sort((a, b) => b.correct / b.total - a.correct / a.total);
  const best = categories[0], gap = categories[categories.length - 1];
  const leadVerdict = ability?.lead_sentence || '';
  const takeawayEl = document.getElementById('cc-takeaway');
  if (!ability) {
    takeawayEl.textContent = 'Start here: run one trial, then try a mission below.';
  } else {
    const categoryAdvice = ability.correct === 0 ? 'Every exercise in this suite was missed. Try a sample below to inspect an answer, then compare a candidate on the same trial.' : best ? `Best result: ${best.label} (${best.correct}/${best.total}). ` + (gap.correct < gap.total ? `Practice next: ${gap.label} (${gap.correct}/${gap.total}).` : 'All categories passed these exercises. Try a practical mission next.') : 'Inspect the detailed records below.';
    takeawayEl.textContent = leadVerdict ? `${leadVerdict} ${categoryAdvice}` : categoryAdvice;
  }
  for (const category of ability?.categories || []) {
    const row = document.createElement('div'); row.className = 'skill-row';
    const name = document.createElement('span'); name.textContent = category.label;
    const result = document.createElement('strong'); result.textContent = `${category.correct}/${category.total}`;
    const meter = document.createElement('meter'); meter.min = 0; meter.max = Math.max(1, category.total); meter.value = category.correct;
    meter.setAttribute('aria-label', `${category.label}: ${category.correct} of ${category.total}`);
    row.append(name, result, meter); bars.append(row);
  }
  document.getElementById('cc-receipt-note').textContent = ability ?
    `${ability.format_errors} response contract failures · ${ability.wrong_answers ?? Math.max(0, ability.total - ability.correct - ability.format_errors)} wrong answers. ${ability.scope} ${ability.created ? ability.created.slice(0, 10) : ''} · ${ability.suite}.` : 'One trial gives your next upgrade a fair starting point. No model download needed.';

  // Render representative challenge replay (failed items first)
  const replayBox = document.getElementById('receipt-replay');
  const replayList = document.getElementById('receipt-replay-list');
  const rep = ability?.replay;
  const hasReplay = (rep?.passed?.length || 0) + (rep?.failed?.length || 0) > 0;
  replayBox.hidden = !hasReplay;
  if (hasReplay) {
    replayList.replaceChildren();
    const renderCard = (item) => {
      const isPass = item.outcome === 'pass';
      const outcomeClass = isPass ? 'pass' : (item.outcome === 'format_error' ? 'format' : 'wrong');
      const card = document.createElement('div');
      card.className = `replay-item outcome-${outcomeClass}`;

      const hdr = document.createElement('div');
      hdr.className = 'replay-item-header';
      const titleGroup = document.createElement('div');
      titleGroup.className = 'replay-title-group';
      const cat = document.createElement('span');
      cat.className = 'replay-tag';
      cat.textContent = item.category_label || item.category;
      const idSpan = document.createElement('span');
      idSpan.className = 'replay-id';
      idSpan.textContent = item.item_id ? ` · ${item.item_id}` : '';
      titleGroup.append(cat, idSpan);

      const statusGroup = document.createElement('div');
      statusGroup.className = 'replay-status-group';
      if (Number.isFinite(item.latency_seconds)) {
        const lat = document.createElement('span');
        lat.className = 'replay-latency';
        lat.textContent = `${item.latency_seconds.toFixed(2)} s`;
        statusGroup.append(lat);
      }
      const tag = document.createElement('span');
      tag.className = `badge ${outcomeClass}`;
      tag.textContent = isPass ? '● Pass' : (item.outcome === 'format_error' ? '▲ Contract failure' : '✕ Wrong answer');
      statusGroup.append(tag);
      hdr.append(titleGroup, statusGroup);
      card.append(hdr);

      const comp = document.createElement('div');
      comp.className = 'replay-comparison';

      const colChallenge = document.createElement('div');
      colChallenge.className = 'replay-col replay-col-challenge';
      const headingChallenge = document.createElement('span');
      headingChallenge.className = 'replay-col-heading';
      headingChallenge.textContent = 'Original Public Challenge';
      const promptEl = document.createElement('p');
      promptEl.className = 'replay-prompt-text';
      promptEl.textContent = item.prompt || item.question || 'Challenge prompt not available';
      colChallenge.append(headingChallenge, promptEl);

      const colAnswer = document.createElement('div');
      colAnswer.className = 'replay-col replay-col-answer';
      const headingAnswer = document.createElement('span');
      headingAnswer.className = 'replay-col-heading';
      headingAnswer.textContent = 'Actual Model Answer';
      const outEl = document.createElement('pre');
      outEl.className = 'replay-output-text';
      outEl.textContent = (item.output && item.output.trim()) ? item.output : '(empty response)';
      colAnswer.append(headingAnswer, outEl);

      comp.append(colChallenge, colAnswer);
      card.append(comp);

      if (item.reason) {
        const reasonBox = document.createElement('div');
        reasonBox.className = `replay-reason-box outcome-${outcomeClass}`;
        const reasonLabel = document.createElement('strong');
        reasonLabel.className = 'replay-reason-label';
        reasonLabel.textContent = isPass ? 'Assessment: ' : (item.outcome === 'format_error' ? 'Contract failure: ' : 'Why it failed: ');
        const reasonText = document.createElement('span');
        reasonText.textContent = item.reason;
        reasonBox.append(reasonLabel, reasonText);
        card.append(reasonBox);
      }

      return card;
    };

    for (const item of (rep.failed || [])) {
      replayList.append(renderCard(item));
    }
    for (const item of (rep.passed || [])) {
      replayList.append(renderCard(item));
    }
  }

  // Render qualification checks if present
  const criteriaBox = document.getElementById('receipt-criteria-box');
  const criteriaList = document.getElementById('receipt-criteria-list');
  const checks = ability?.checks || [];
  criteriaBox.hidden = !checks.length;
  if (checks.length) {
    criteriaList.replaceChildren();
    for (const chk of checks) {
      const li = document.createElement('li'); li.className = `criteria-row ${chk.met ? 'met' : 'missed'}`;
      const badge = document.createElement('span'); badge.className = `badge ${chk.met ? 'pass' : 'attention'}`;
      badge.textContent = chk.met ? '✓ Met' : '✗ Missed';
      const desc = document.createElement('span');
      desc.textContent = `${chk.label}: observed ${chk.observed} (required: ${chk.required})`;
      li.append(badge, desc); criteriaList.append(li);
    }
  }

  // Action buttons
  const actBox = document.getElementById('receipt-actions');
  actBox.hidden = !ability;
  const pracBtn = document.getElementById('receipt-practice');
  const upgBtn = document.getElementById('receipt-upgrade');
  pracBtn.textContent = 'Retest unchanged';
  pracBtn.onclick = () => {
    if (ability.suite === 'documents-short') commandActions.documents();
    else commandActions.baseline();
  };
  upgBtn.onclick = () => focusSection('models-title');

  const debrief = document.getElementById('cc-debrief');
  const ids = [speed?.run, ability?.run];
  const current = lastLabDebrief?.state === 'completed' && lastLabDebrief.runs?.length && lastLabDebrief.runs.every(id => ids.includes(id));
  debrief.hidden = !ability;
  document.getElementById('cc-debrief-text').textContent = current ? lastLabDebrief.text : 'No local-model debrief for these results in this session. Run a trial to hear the selected model’s take.';
  document.getElementById('cc-debrief-note').textContent = current ? lastLabDebrief.label : 'Debriefs are optional, stay in memory and never change a score.';
}
const missionSamples = [
  {title: 'Expedition planner', hook: 'Help a robot crew get home before the tide rises.',
   document: 'The Beacon crew must return to the harbour before 18:00. The ridge trail takes 90 minutes and is open all day. The beach trail takes 40 minutes but closes at 16:00 when the tide rises. At 15:30 the crew is at the trail junction. Their battery has enough charge for either route. No ferry timetable is provided.',
   question: 'Which open route gets the crew to the harbour earliest? Quote the sentence supporting its travel time.'},
  {title: 'Repair-bay detective', hook: 'Find the useful part in a pile of convincing distractions.',
   document: 'Robot Finch has a cracked left gripper. Part G-14 fits Finch and costs 35 credits. Part G-20 fits robot Heron and costs 20 credits. A new Finch costs 800 credits. The workshop installs a compatible gripper for 15 credits. Shipping times are not listed.',
   question: 'Which gripper fits Finch, and what does the part cost? Quote the supporting sentence.'},
  {title: 'Unknown-signal check', hook: 'Can your companion resist making up a confident answer?',
   document: 'The observatory logged a repeating signal at 02:10. The signal repeated every 12 seconds. Two receivers recorded it. Engineers ruled out a fault in either receiver. The report does not identify the source of the signal.',
   question: 'Which planet sent the signal? If the brief does not say, use not_stated.'}
];
for (const sample of missionSamples) {
  const article = document.createElement('article'); article.className = 'card challenge-card';
  const title = document.createElement('h4'); title.textContent = sample.title;
  const hook = document.createElement('p'); hook.textContent = sample.hook;
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Preview this mission';
  button.addEventListener('click', () => {
    document.getElementById('cc-doc').value = sample.document;
    document.getElementById('cc-question').value = sample.question;
    document.getElementById('cc-task-box').open = true;
    focusSection('cc-task-box', 'cc-question');
  });
  article.append(title, hook, button); document.getElementById('cc-challenges').append(article);
}
