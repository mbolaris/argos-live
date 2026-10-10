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
let lastStartupStatusTime = 0;
let lastStartupReqId = 0;
let lastLabRecovery = null;
let labRecoveryTime = 0;

function formatRecoveryStatus(recovery) {
  // Respect explicit not-running state
  const rawState = recovery?.state || recovery?.phase;
  if (rawState === 'not-running') return 'Assistant was not running.';

  const labEvidence = recovery || lastLabRecovery;
  const hasLabEvidence = Boolean(labEvidence && (labEvidence.state || labEvidence.phase || labEvidence.message));

  // If startup evidence is newer than current Lab recovery evidence (or no Lab evidence exists),
  // prefer current startup evidence. Older startup responses must not override newer Lab recovery.
  const startupIsNewer = Boolean(lastStartupStatus && (!hasLabEvidence || lastStartupStatusTime >= labRecoveryTime));

  if (startupIsNewer) {
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

  // Fallback to supplied Lab recovery evidence
  const target = labEvidence || recovery;
  if (!target) return '';
  if (typeof target === 'string') return target;
  const phase = target.state || target.phase;
  if (phase === 'ready') return 'Assistant ready.';
  if (phase === 'failed') return 'Assistant recovery failed.';
  if (phase === 'not-running' || phase === 'stopped') return 'Assistant was not running.';
  if (phase === 'recovering' || target.active ||
      ['setup', 'verify-starter', 'select-storage', 'write-configuration',
       'verify-model', 'model-service', 'first-reply', 'gateway',
       'reconnecting', 'stopping'].includes(phase)) {
    return 'Assistant recovery in progress.';
  }
  if (target.message && !target.phase) return target.message;
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
  const reqTime = Date.now();
  const reqId = ++lastStartupReqId;
  try {
    const value = await api('/api/startup');
    if (reqId < lastStartupReqId) return;

    // An older /api/startup response initiated before current Lab recovery evidence must NOT override it
    const isOlderThanLabRecovery = Boolean(labRecoveryTime && reqTime < labRecoveryTime);
    if (isOlderThanLabRecovery) {
      return;
    }

    lastStartupStatus = value;
    lastStartupStatusTime = Date.now();
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
  if (!response.ok) {
    let msg = 'Status unavailable';
    try {
      const err = await response.json();
      if (err?.error) msg = err.error;
    } catch (_) {}
    throw new Error(msg);
  }
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
  const curatedEl = document.getElementById('model-curated');
  const catalog = document.getElementById('model-catalog');
  installed.replaceChildren(); bundled.replaceChildren(); jobs.replaceChildren();
  if (curatedEl) curatedEl.replaceChildren();
  if (catalog) catalog.replaceChildren();
  try {
    const result = await api('/api/models');
    catalogPreview = new Map(result.catalog.map(model => [model.tag, model]));
    modelDestination = result.storage_path || null;
    modelEncryption = result.storage_encrypted;
    document.getElementById('upgrade-guidance').textContent = result.guidance?.message || 'Save a baseline, then compare the same tests after upgrading.';
    status.textContent = result.storage_state === 'available' ? 'Model storage is available. Installed models and download jobs are listed below.' :
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
      const isCurated = model.curated === true;
      if (catalog) {
        card(catalog, model.tag + (isCurated ? ` (${model.curated_label || model.role})` : ''),
          `${model.rationale || model.description} · ${model.parameter_label} · ${model.quantization} · ` +
          `${gib(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license} · ` +
          `${model.context_tokens.toLocaleString()} context · CPU: ${model.cpu_fit.status} · GPU: ${model.gpu_fit.status} (estimates)`);
        if (downloadAvailable && model.downloadable !== false) {
          const button = document.createElement('button'); button.type = 'button';
          button.textContent = result.storage_state === 'available' ? 'Review download' : 'Choose storage & download';
          button.disabled = downloadActive || selectionActive;
          button.addEventListener('click', () => reviewDownload({tag: model.tag}, model.tag));
          catalog.lastElementChild.append(button);
        }
      }
      if (curatedEl && isCurated && model.downloadable !== false) {
        const isRecommended = result.guidance?.next_model === model.tag;
        const title = `${model.curated_label || model.role}: ${model.tag}` + (isRecommended ? ' ★ Recommended upgrade' : '');
        card(curatedEl, title,
          (isRecommended ? 'Recommended candidate for your machine. ' : '') +
          `${model.rationale || model.description} · ${model.parameter_label} · ${model.quantization} · ` +
          `${gib(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license} · ` +
          `${model.context_tokens.toLocaleString()} context · CPU: ${model.cpu_fit.status} · GPU: ${model.gpu_fit.status} (estimates)`);
        if (downloadAvailable) {
          const button = document.createElement('button'); button.type = 'button';
          button.textContent = result.storage_state === 'available' ? 'Review download' : 'Choose storage & download';
          button.disabled = downloadActive || selectionActive;
          button.addEventListener('click', () => reviewDownload({tag: model.tag}, model.tag));
          curatedEl.lastElementChild.append(button);
        }
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
let arenaCurrentItemId = null;
let sessionActive = false;

function updateSessionPath(active, hasResult) {
  sessionActive = active;
  const section = document.getElementById('command-center');
  if (section) section.dataset.watching = String(active);
  const watch = document.getElementById('session-watch');
  const result = document.getElementById('session-result');
  if (watch) watch.setAttribute('aria-disabled', String(document.getElementById('arena').hidden));
  if (result) result.setAttribute('aria-disabled', String(!hasResult));
  const current = active ? 'session-watch' : hasResult ? 'session-result' : 'session-play';
  for (const id of ['session-play', 'session-watch', 'session-result']) {
    const link = document.getElementById(id);
    if (id === current) link?.setAttribute('aria-current', 'step');
    else link?.removeAttribute('aria-current');
  }
}
let retainedBaselineDocRunId = sessionStorage.getItem('argos_baseline_doc_run_id') || null;
let autoComparedCandidateId = null;

const outcomeMeta = {
  pass: {label: 'Pass', cls: 'outcome-pass', reason: 'Criteria verified', plain: 'correct.'},
  wrong_answer: {label: 'Wrong Answer', cls: 'outcome-wrong', reason: 'Answer did not match expected criteria',
    plain: 'wrong. The answer didn’t match what the passage supports.'},
  format_error: {label: 'Format Error', cls: 'outcome-format', reason: 'Did not follow required format or closed JSON schema',
    plain: 'not scorable. It didn’t use the required answer format, so it counts as a miss.'},
  unscored: {label: 'Summary', cls: 'outcome-unscored', reason: 'Summary generated for owner judgment',
    plain: 'a summary written for you to read. Summaries aren’t scored.'}
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
  if (receipt.outcome === 'wrong_answer') {
    reason.textContent = 'Miss: answer did not match expected criteria.';
  } else if (receipt.outcome === 'format_error') {
    reason.textContent = 'Miss: response failed format contract or closed JSON schema.';
  } else {
    reason.textContent = meta.reason;
  }

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
  if (m) {
    const isFixture = (model || '').startsWith('fixture:');
    m.textContent = (model || 'Configured model') + (isFixture ? ' (simulated fixture)' : '');
  }
  const el = document.getElementById('arena-elapsed');
  if (el) el.textContent = Number.isFinite(elapsed) ? `${Math.round(elapsed)} s` : '0 s';

  const total = (arena && arena.total) ? arena.total : 0;
  const completed = (arena && arena.completed) ? arena.completed : 0;
  setArenaProgress(completed, total);
  const status = document.getElementById('watch-status');
  if (status) status.textContent = watchStatus[phase] || 'Getting ready…';
  const recEl = document.getElementById('arena-recipe');
  if (recEl) {
    const curRec = arena?.recipe;
    if (curRec && curRec.preset !== 'standard') {
      recEl.textContent = curRec.preset === 'concise' ? 'Strict format instructions' : curRec.preset;
    } else {
      recEl.textContent = 'Standard';
    }
  }
}

const watchStatus = {pausing: 'Pausing chat so your AI can focus on the test…',
  'model-service': 'Starting the private test service…', speed: 'First, a quick speed check. Reading starts next.',
  documents: 'Reading passages and answering questions. Fixed rules score each answer as it finishes.',
  ability: 'Answering fixed exercises. Fixed rules score each answer as it finishes.',
  debrief: 'Scoring is finished. Your AI is writing its opinion of the results (not scored)…',
  cancelling: 'Stopping after the current answer…', completed: 'Finished. Your result is ready under Improve.',
  cancelled: 'Stopped. Answers scored so far are kept, but an incomplete run cannot qualify.',
  failed: 'The test could not finish. Answers scored so far are kept; check model setup before retrying.'};

function setArenaProgress(completed, total) {
  const bar = document.getElementById('arena-progress-bar');
  if (bar) { bar.max = Math.max(1, total); bar.value = Math.min(completed, Math.max(1, total)); }
  const label = document.getElementById('arena-progress-label');
  if (label) label.textContent = total ? `${completed} of ${total} responses done` : 'Starting…';
}

function updateArenaTally(receipts) {
  // Summaries are written for the owner to read; only the other answers are scored.
  const count = outcome => receipts.filter(r => r.outcome === outcome).length;
  const correct = receipts.filter(r => r.score === 1).length;
  const wrong = count('wrong_answer'), format = count('format_error'), summaries = count('unscored');
  const set = (id, value, text, alwaysShown) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.hidden = !alwaysShown && value === 0;
  };
  set('arena-tally-passed', correct, `${correct} correct` + (wrong ? ` · ${wrong} wrong` : ''), true);
  set('arena-tally-format-errors', format, `${format} wrong format`);
  set('arena-tally-summaries', summaries, `${summaries} ${summaries === 1 ? 'summary' : 'summaries'} (not scored)`);
}

const challengeKinds = {answer: 'Find the fact', quote: 'Quote the evidence', not_stated: 'Notice what’s missing',
  summary: 'Summary · for you, not scored'};

function extractPassage(promptText) {
  const match = (promptText || '').match(/PASSAGE:\s*([\s\S]+?)(?=\n\s*(?:QUESTION:|Respond|Summarize)|$)/i);
  return match ? match[1].trim() : '';
}

let passageRevealed = false;
function hidePassage() {
  const passage = document.getElementById('arena-current-passage');
  if (passage) { passage.dataset.text = ''; passage.textContent = ''; }
  const details = document.getElementById('arena-source-details');
  if (details) details.hidden = true;
  // Without a passage the challenge takes the full card width instead of the passage column.
  document.getElementById('arena-live-card')?.classList.add('no-passage');
}
function showChallenge(item) {
  const details = document.getElementById('arena-source-details');
  if (details) details.hidden = false;
  document.getElementById('arena-live-card')?.classList.remove('no-passage');
  const id = document.getElementById('arena-current-id');
  if (id) id.textContent = item.item_id || 'active';
  const kind = document.getElementById('arena-current-category');
  if (kind) kind.textContent = challengeKinds[item.category] || item.category || '';
  const prompt = document.getElementById('arena-current-prompt');
  if (prompt) prompt.textContent = item.prompt || 'Running challenge…';
  const question = document.getElementById('arena-current-question');
  if (question) question.textContent = extractQuestion(item.prompt, item.category);
  const passage = document.getElementById('arena-current-passage');
  const text = extractPassage(item.prompt);
  if (passage && passage.dataset.text !== text) {
    passage.dataset.text = text;
    passage.textContent = text || 'This challenge has no separate passage. The full prompt is below.';
  }
  // Wide screens show the passage beside the question; phones keep it one tap away.
  if (details && text && !passageRevealed) {
    passageRevealed = true;
    if (window.matchMedia('(min-width: 900px)').matches) details.open = true;
  }
}

function markQuotedSentence(raw) {
  // Highlight only an exact quotation the model actually returned.
  const passage = document.getElementById('arena-current-passage');
  const text = passage?.dataset.text;
  if (!passage || !text) return;
  let quote = '';
  const match = (raw || '').match(/"quote"\s*:\s*"((?:\\.|[^"\\])*)"/);
  if (match) { try { quote = JSON.parse('"' + match[1] + '"').trim(); } catch (_) {} }
  const at = quote.length >= 8 ? text.indexOf(quote) : -1;
  if (at < 0) {
    if (passage.querySelector('mark')) passage.textContent = text;
    return;
  }
  const mark = document.createElement('mark');
  mark.textContent = quote;
  mark.title = 'The sentence your AI quoted';
  passage.replaceChildren(text.slice(0, at), mark, text.slice(at + quote.length));
}

function updateArenaReceipts(receipts) {
  const list = document.getElementById('arena-receipts-list');
  if (!list) return;
  list.replaceChildren();
  for (const r of receipts) {
    list.appendChild(renderReceiptItem(r));
  }
  const tally = document.getElementById('arena-receipts-tally');
  if (tally) tally.textContent = `${receipts.length} done`;
  updateArenaTally(receipts);
  updateLatestChallenge(receipts.at(-1));
}

function updateLatestChallenge(receipt) {
  const label = document.getElementById('arena-latest-result');
  if (!label) return;
  label.hidden = !receipt;
  if (!receipt) return;
  const meta = outcomeMeta[receipt.outcome] || outcomeMeta.unscored;
  label.className = 'latest-challenge-result ' + meta.cls;
  label.textContent = `Last answer (${challengeKinds[receipt.category] || receipt.item_id || 'challenge'}): ${meta.plain}`;
}

function extractQuestion(promptText, category) {
  if (!promptText) return 'Waiting for challenge…';
  const qMatch = promptText.match(/QUESTION:\s*([\s\S]+?)(?=\n\s*(?:Respond|PASSAGE|\{)|$)/i);
  if (qMatch) return qMatch[1].trim();
  if (category === 'summary' || promptText.includes('Summarize')) return 'Summarize this passage in two sentences.';
  if (promptText.startsWith('Measuring')) return promptText;
  return promptText.slice(0, 160);
}

function arenaAnswerPreview(raw) {
  // A reading challenge streams a JSON envelope. Present only text actually
  // received; the original output remains visible and goes unchanged to scoring.
  if (!raw.trimStart().startsWith('{')) return raw;
  try {
    const value = JSON.parse(raw);
    const answer = typeof value.answer === 'string' ? value.answer : null;
    const quote = typeof value.quote === 'string' ? value.quote : null;
    if (value.status === 'not_stated' && !answer) return 'Not stated in the passage.';
    if (answer !== null) return answer + (quote ? '\n\nSupporting quote:\n“' + quote + '”' : '');
    if (value.status === 'not_stated') return 'Not stated in the passage.';
    return raw;
  } catch (_) {
    // The expected envelope has started but no answer text has arrived yet.
    if (/^\s*\{\s*"status"\s*:\s*"not_stated"/.test(raw) && !/"answer"\s*:\s*"[^"]/.test(raw)) return 'Not stated in the passage.';
    // Decode an already received answer prefix, including JSON escapes. An
    // incomplete escape waits for the next delta instead of inventing text.
    const match = raw.match(/"answer"\s*:\s*"((?:\\.|[^"\\])*)/);
    if (match) {
      try { return JSON.parse('"' + match[1] + '"') || 'Waiting for answer text…'; }
      catch (_) { return 'Receiving answer text…'; }
    }
    if (/^\s*\{\s*"status"/.test(raw)) return 'Receiving answer text…';
    return raw;
  }
}

function presentArenaAnswer(raw) {
  const stream = document.getElementById('arena-current-stream');
  if (stream) stream.textContent = arenaAnswerPreview(raw);
  const original = document.getElementById('arena-current-raw');
  if (original) original.textContent = raw;
  markQuotedSentence(raw);
}

function renderArenaState(arena, active, phase, model, elapsed) {
  const arenaEl = document.getElementById('arena');
  if (!arenaEl) return;
  arenaEl.hidden = false;
  const mission = document.getElementById('command-center');
  if (mission?.hidden) {
    mission.dataset.commandUnavailable = 'true';
    mission.hidden = false;
  }
  updateSessionPath(active, !document.getElementById('cc-receipt').hidden);

  updateArenaHUD(arena, phase, model, elapsed, active);

  const livePrompt = document.getElementById('arena-current-prompt');
  const liveQuestion = document.getElementById('arena-current-question');
  const liveStream = document.getElementById('arena-current-stream');
  const streamInd = document.getElementById('arena-stream-indicator');
  const liveId = document.getElementById('arena-current-id');
  const liveCat = document.getElementById('arena-current-category');

  if (phase === 'speed') {
    // No passage belongs to the speed check; never leave the previous run's passage beside it.
    hidePassage();
    if (liveId) liveId.textContent = 'speed check';
    if (liveCat) liveCat.textContent = 'Speed · timed, not scored for correctness';
    if (livePrompt) livePrompt.textContent = 'Measuring short-prompt generation speed, prompt processing, and first-token latency with fixed prompts.';
    if (liveQuestion) liveQuestion.textContent = 'How quickly does your AI start and finish an answer?';
    if (liveStream) liveStream.textContent = 'Timing a few fixed prompts…';
    if (streamInd) streamInd.hidden = true;
  } else if (arena && arena.current_item) {
    showChallenge(arena.current_item);
    // Live events own the answer for the item they started; a polled snapshot only fills
    // in an item the events have not reached, so received text is never appended twice.
    const sameItem = arena.current_item.item_id === arenaCurrentItemId && arenaCurrentAnswer;
    if (arena.current_item.answer && !sameItem) {
      arenaCurrentItemId = arena.current_item.item_id;
      presentArenaAnswer(arena.current_item.answer);
      arenaCurrentAnswer = arena.current_item.answer;
    }
    if (streamInd) streamInd.hidden = !active;
  } else {
    // Before the first challenge (pausing chat, starting the service) there is no passage yet.
    hidePassage();
    if (liveQuestion && !active) liveQuestion.textContent = 'Waiting for challenge…';
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
  const nextActionBtn = document.getElementById('arena-next-action');

  if (banner && headline && detail) {
    const secActionBtn = document.getElementById('arena-secondary-action');
    if (phase === 'completed') {
      banner.hidden = false;
      if (secActionBtn) secActionBtn.hidden = true;
      const arenaDocRunId = (arena && Array.isArray(arena.runs) && arena.runs.length) ? arena.runs[arena.runs.length - 1] : null;
      if (arenaDocRunId && arenaDocRunId === autoComparedCandidateId) {
        headline.textContent = 'Experiment finished · before and after are ready';
        if (detail) detail.textContent = `Paired with retained baseline (${(retainedBaselineDocRunId || '').slice(0, 8)}…) on identical hardware. One action recommended below.`;
        if (nextActionBtn) {
          nextActionBtn.hidden = false;
          nextActionBtn.textContent = 'See before and after ↑';
          nextActionBtn.onclick = () => focusSection('improve-comparison');
        }
      } else if (retainedBaselineDocRunId && arenaDocRunId && arenaDocRunId !== retainedBaselineDocRunId) {
        headline.textContent = 'Experiment finished · comparing with your earlier result…';
        if (detail) detail.textContent = `Evaluating candidate against retained baseline (${(retainedBaselineDocRunId || '').slice(0, 8)}…) on identical hardware…`;
        if (nextActionBtn) nextActionBtn.hidden = true;
      } else {
        if (!retainedBaselineDocRunId && arenaDocRunId && (!arena.recipe || arena.recipe.preset === 'standard')) {
          retainedBaselineDocRunId = arenaDocRunId;
          try { sessionStorage.setItem('argos_baseline_doc_run_id', arenaDocRunId); } catch (_) {}
        }
        if (nextActionBtn) {
          nextActionBtn.hidden = false;
          nextActionBtn.textContent = 'Step through every answer ↑';
          nextActionBtn.onclick = () => focusSection(document.getElementById('replay').hidden ? 'cc-receipt' : 'replay');
        }
        headline.textContent = 'Finished and saved';
        const scored = (arena?.receipts || []).filter(r => r.outcome !== 'unscored').length;
        detail.textContent = scored ?
          `${arena?.correct || 0} of ${scored} scored questions correct · ${arena?.format_errors || 0} in the wrong format. Saved for ${model || 'this model'}.` :
          `Results saved for ${model || 'this model'}.`;
      }
    } else if (phase === 'cancelled') {
      banner.hidden = false;
      if (nextActionBtn) {
        nextActionBtn.hidden = false;
        nextActionBtn.textContent = 'Run it again with the same settings';
        nextActionBtn.onclick = async () => {
          try {
            await post('/api/lab/start-documents', arena?.recipe?.preset && arena.recipe.preset !== 'standard' ? {recipe: arena.recipe.preset} : {});
            await refreshLab();
          } catch (err) {
            headline.textContent = 'Retry rejected';
            detail.textContent = err.message || 'Trial action rejected.';
          }
        };
      }
      if (secActionBtn) {
        secActionBtn.hidden = !(arena?.recipe?.preset && arena.recipe.preset !== 'standard');
        secActionBtn.textContent = 'Restore standard instructions';
        secActionBtn.onclick = async () => {
          try {
            await restoreLabRecipe();
          } catch (err) {
            headline.textContent = 'Restore rejected';
            detail.textContent = err.message || 'Restore rejected.';
          }
        };
      }
      headline.textContent = 'Stopped · incomplete';
      if (arena?.recovery) {
        lastLabRecovery = arena.recovery;
        labRecoveryTime = Math.max(labRecoveryTime, Date.now());
      }
      const recoveryText = formatRecoveryStatus(arena?.recovery || lastLabRecovery);
      const recoverySuffix = recoveryText ? ` ${recoveryText}` : '';
      detail.textContent = `${arena?.completed || 0} of ${arena?.total || 0} challenges evaluated (incomplete). Partial results are preserved but do not qualify.${recoverySuffix}`;
    } else if (phase === 'failed') {
      banner.hidden = false;
      if (nextActionBtn) {
        nextActionBtn.hidden = false;
        nextActionBtn.textContent = 'Run it again with the same settings';
        nextActionBtn.onclick = async () => {
          try {
            await post('/api/lab/start-documents', arena?.recipe?.preset && arena.recipe.preset !== 'standard' ? {recipe: arena.recipe.preset} : {});
            await refreshLab();
          } catch (err) {
            headline.textContent = 'Retry rejected';
            detail.textContent = err.message || 'Trial action rejected.';
          }
        };
      }
      if (secActionBtn) {
        secActionBtn.hidden = !(arena?.recipe?.preset && arena.recipe.preset !== 'standard');
        secActionBtn.textContent = 'Restore standard instructions';
        secActionBtn.onclick = async () => {
          try {
            await restoreLabRecipe();
          } catch (err) {
            headline.textContent = 'Restore rejected';
            detail.textContent = err.message || 'Restore rejected.';
          }
        };
      }
      headline.textContent = 'Trial failed · incomplete';
      detail.textContent = 'Check model setup and compute resources before retrying. Partial results do not qualify.';
    } else {
      banner.hidden = true;
      if (nextActionBtn) nextActionBtn.hidden = true;
      if (secActionBtn) secActionBtn.hidden = true;
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
        const headline = document.getElementById('arena-summary-headline');
        if (headline) headline.textContent = 'Stopped · incomplete';
      } else if (ev.phase === 'failed') {
        badge.textContent = 'FAILED · INCOMPLETE';
        badge.className = 'arena-badge phase-failed incomplete';
        const headline = document.getElementById('arena-summary-headline');
        if (headline) headline.textContent = 'Trial failed · incomplete';
      } else {
        badge.textContent = ev.phase.toUpperCase();
        badge.className = `arena-badge phase-${ev.phase}`;
      }
    }
    const status = document.getElementById('watch-status');
    if (status && watchStatus[ev.phase]) status.textContent = watchStatus[ev.phase];
    if (Number.isFinite(ev.elapsed_seconds)) {
      const el = document.getElementById('arena-elapsed');
      if (el) el.textContent = `${Math.round(ev.elapsed_seconds)} s`;
    }
  } else if (ev.type === 'item-start') {
    showChallenge(ev);
    arenaCurrentItemId = ev.item_id;
    arenaCurrentAnswer = '';
    const raw = document.getElementById('arena-current-raw');
    if (raw) raw.textContent = '';
    const liveStream = document.getElementById('arena-current-stream');
    if (liveStream) liveStream.textContent = 'Generating response…';
    const streamInd = document.getElementById('arena-stream-indicator');
    if (streamInd) streamInd.hidden = false;
    if (Number.isFinite(ev.completed) && Number.isFinite(ev.total)) setArenaProgress(ev.completed, ev.total);
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
      presentArenaAnswer(arenaCurrentAnswer);
      stream.scrollTop = stream.scrollHeight;
    }
  } else if (ev.type === 'item-scored') {
    if (ev.receipt) {
      arenaReceipts.push(ev.receipt);
      updateLatestChallenge(ev.receipt);
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
      if (tally) tally.textContent = `${arenaReceipts.length} done`;
      updateArenaTally(arenaReceipts);
      if (Number.isFinite(ev.completed) && Number.isFinite(ev.total)) setArenaProgress(ev.completed, ev.total);
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
      const nextActionBtn = document.getElementById('arena-next-action');
      const secActionBtn = document.getElementById('arena-secondary-action');
      if (ev.outcome === 'completed') {
        if (secActionBtn) secActionBtn.hidden = true;
        const savedDocRunId = (Array.isArray(ev.runs) && ev.runs.length) ? ev.runs[ev.runs.length - 1] : null;
        if (savedDocRunId && savedDocRunId === autoComparedCandidateId) {
          if (headline) headline.textContent = 'Experiment finished · before and after are ready';
          if (detail) detail.textContent = `Paired with retained baseline (${(retainedBaselineDocRunId || '').slice(0, 8)}…) on identical hardware. One action recommended below.`;
          if (nextActionBtn) {
            nextActionBtn.hidden = false;
            nextActionBtn.textContent = 'See before and after ↑';
            nextActionBtn.onclick = () => focusSection('improve-comparison');
          }
        } else if (retainedBaselineDocRunId && savedDocRunId && savedDocRunId !== retainedBaselineDocRunId) {
          if (headline) headline.textContent = 'Experiment finished · comparing with your earlier result…';
          if (detail) detail.textContent = `Evaluating candidate against retained baseline (${(retainedBaselineDocRunId || '').slice(0, 8)}…) on identical hardware…`;
          if (nextActionBtn) nextActionBtn.hidden = true;
        } else {
          if (!retainedBaselineDocRunId && savedDocRunId && (!ev.recipe || ev.recipe.preset === 'standard')) {
            retainedBaselineDocRunId = savedDocRunId;
            try { sessionStorage.setItem('argos_baseline_doc_run_id', savedDocRunId); } catch (_) {}
          }
          if (nextActionBtn) {
            nextActionBtn.hidden = false;
            nextActionBtn.textContent = 'Step through every answer ↑';
            nextActionBtn.onclick = () => focusSection(document.getElementById('replay').hidden ? 'cc-receipt' : 'replay');
          }
          if (headline) headline.textContent = 'Finished and saved';
          const scored = arenaReceipts.filter(r => r.outcome !== 'unscored').length;
          if (detail) detail.textContent = scored ?
            `${ev.correct || 0} of ${scored} scored questions correct · ${ev.format_errors || 0} in the wrong format. Saved for ${ev.model || 'this model'}.` :
            `Results saved for ${ev.model || 'this model'}.`;
        }
      } else if (ev.outcome === 'cancelled') {
        if (nextActionBtn) {
          nextActionBtn.hidden = false;
          nextActionBtn.textContent = 'Run it again with the same settings';
          nextActionBtn.onclick = async () => {
            try {
              await post('/api/lab/start-documents', ev.recipe?.preset && ev.recipe.preset !== 'standard' ? {recipe: ev.recipe.preset} : {});
              await refreshLab();
            } catch (err) {
              if (headline) headline.textContent = 'Retry rejected';
              if (detail) detail.textContent = err.message || 'Trial action rejected.';
            }
          };
        }
        if (secActionBtn) {
          secActionBtn.hidden = !(ev.recipe?.preset && ev.recipe.preset !== 'standard');
          secActionBtn.textContent = 'Restore standard instructions';
          secActionBtn.onclick = async () => {
            try {
              await restoreLabRecipe();
            } catch (err) {
              if (headline) headline.textContent = 'Restore rejected';
              if (detail) detail.textContent = err.message || 'Restore rejected.';
            }
          };
        }
        if (headline) headline.textContent = 'Stopped · incomplete';
        if (ev.recovery) {
          lastLabRecovery = ev.recovery;
          labRecoveryTime = Math.max(labRecoveryTime, Date.now());
        }
        const recoveryText = formatRecoveryStatus(ev.recovery || lastLabRecovery);
        const recoverySuffix = recoveryText ? ` ${recoveryText}` : '';
        if (detail) detail.textContent = `${ev.completed || 0} of ${ev.total || 0} challenges evaluated (incomplete). Partial results are preserved but do not qualify.${recoverySuffix}`;
      } else {
        if (nextActionBtn) {
          nextActionBtn.hidden = false;
          nextActionBtn.textContent = 'Run it again with the same settings';
          nextActionBtn.onclick = async () => {
            try {
              await post('/api/lab/start-documents', ev.recipe?.preset && ev.recipe.preset !== 'standard' ? {recipe: ev.recipe.preset} : {});
              await refreshLab();
            } catch (err) {
              if (headline) headline.textContent = 'Retry rejected';
              if (detail) detail.textContent = err.message || 'Trial action rejected.';
            }
          };
        }
        if (secActionBtn) {
          secActionBtn.hidden = !(ev.recipe?.preset && ev.recipe.preset !== 'standard');
          secActionBtn.textContent = 'Restore standard instructions';
          secActionBtn.onclick = async () => {
            try {
              await restoreLabRecipe();
            } catch (err) {
              if (headline) headline.textContent = 'Restore rejected';
              if (detail) detail.textContent = err.message || 'Restore rejected.';
            }
          };
        }
        if (headline) headline.textContent = 'Trial failed · incomplete';
        if (detail) detail.textContent = 'Check model setup and compute resources before retrying. Partial results do not qualify.';
      }
    }
    document.querySelector('#cc-schematic [data-system="power-core"]')?.classList.remove('working');
    stopArenaPolling();
    refreshBenchmarks();
    refreshStartup();
    refreshCommand();
    setTimeout(async () => {
      try {
        await refreshLab();
        await refreshCommand();
      } catch (_) {}
    }, 400);
  }
}

async function pollArenaEvents() {
  if (arenaPolling) return;
  arenaPolling = true;
  try {
    const url = `/api/lab/events?after=${arenaCursor}` + (arenaRunId ? `&run=${encodeURIComponent(arenaRunId)}` : '');
    const data = await api(url);
    if (!data) return;
    const connection = document.getElementById('watch-connection');
    if (connection) connection.hidden = true;
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
    const connection = document.getElementById('watch-connection');
    if (connection) connection.hidden = false;
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
    if (!value.active && (value.phase === 'cancelled' || value.phase === 'failed') && value.recovery) {
      labRecoveryTime = Math.max(labRecoveryTime, Date.now());
    }
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
    const activeRec = value.selected_recipe;
    const labActiveRecipeEl = document.getElementById('lab-active-recipe');
    const labRecipeRestoreBtn = document.getElementById('lab-recipe-restore');
    if (labActiveRecipeEl) {
      if (activeRec && activeRec.preset !== 'standard') {
        labActiveRecipeEl.textContent = activeRec.preset === 'concise' ? 'Strict format instructions (concise)' : activeRec.preset;
        if (labRecipeRestoreBtn) labRecipeRestoreBtn.hidden = false;
      } else {
        labActiveRecipeEl.textContent = 'Standard calibration';
        if (labRecipeRestoreBtn) labRecipeRestoreBtn.hidden = true;
      }
    }
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
        arenaCurrentItemId = null;
        const raw = document.getElementById('arena-current-raw');
        if (raw) raw.textContent = '';
        document.getElementById('arena-current-stream').textContent = 'Preparing the next mission…';
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
  if (route !== 'cancel') {
    labRecoveryTime = 0;
    lastLabRecovery = null;
    lastStartupStatusTime = 0;
  } else {
    labRecoveryTime = Math.max(labRecoveryTime, Date.now());
  }
  document.getElementById('lab-start').disabled = true;
  document.getElementById('lab-start-documents').disabled = true;
  document.getElementById('lab-status').textContent = route === 'cancel' ? 'Requesting cancellation…' : 'Starting trial; pausing chat…';
  if (route === 'cancel') {
    const badge = document.getElementById('arena-phase-badge');
    if (badge) badge.textContent = 'STOPPING…';
  }
  try {
    const response = await fetch('/api/lab/' + route, {method: 'POST', headers: {'X-Argos-Token': token || ''}, cache: 'no-store'});
    if (!response.ok) {
      let msg = `Test action unavailable (HTTP ${response.status})`;
      try { const err = await response.json(); if (err?.error) msg = err.error; } catch (_) {}
      throw new Error(msg);
    }
    await refreshLab(); await refreshStartup();
    if (route !== 'cancel') focusSection('arena', 'lab-cancel');
  } catch (err) {
    document.getElementById('lab-status').textContent = err.message || 'Test action unavailable. Refresh and retry.';
    focusSection('lab-status');
  }
});
setInterval(async () => { await refreshLab(); }, 3000);
const metricLabels = {accuracy: 'Test accuracy', short_generation_tokens_per_second: 'Short-prompt output tokens/s',
  medium_generation_tokens_per_second: 'Medium-prompt output tokens/s', long_generation_tokens_per_second: 'Long-prompt output tokens/s'};
async function reviewDownload(choice, tag) {
  downloadChoice = choice;
  const model = catalogPreview.get(tag);
  const inlineSec = document.getElementById('inline-storage-section');
  const inlineChoices = document.getElementById('inline-storage-choices');
  if (!storageConfirmed) {
    document.getElementById('download-confirm').disabled = true;
    if (inlineSec && inlineChoices) {
      inlineSec.hidden = false;
      inlineChoices.replaceChildren();
      try {
        const view = await api('/api/storage');
        if (view && view.candidates) {
          const needed = model?.total_download_bytes || 0;
          const disks = view.candidates.filter(c => c.kind === 'disk');
          const rams = view.candidates.filter(c => c.kind === 'ram');

          // Recommend strictly only a selectable destination
          const selectableDisks = disks.filter(c => !c.contains_data && (c.current || view.can_change));
          const blockedDisks = disks.filter(c => c.contains_data || (!c.current && !view.can_change));

          // 1. Recommended Persistent Destination (strictly one selectable recommendation)
          if (selectableDisks.length > 0) {
            const diskGroup = document.createElement('div');
            diskGroup.className = 'storage-group-persistent';
            const grpTitle = document.createElement('div');
            grpTitle.className = 'storage-group-title';
            grpTitle.textContent = 'Recommended Persistent Drive';
            diskGroup.append(grpTitle);

            const recItem = selectableDisks[0];
            const art = document.createElement('article');
            art.className = 'destination-card recommended';

            const strip = document.createElement('div');
            strip.className = 'dest-compact-strip';

            const info = document.createElement('div');
            info.className = 'dest-compact-info';

            const nameRow = document.createElement('div');
            nameRow.className = 'dest-name-row';
            const nameEl = document.createElement('strong');
            nameEl.className = 'dest-name-title';
            nameEl.textContent = recItem.volume_label || (recItem.device ? recItem.device.split('/').pop() : 'Persistent Drive');
            const badge = document.createElement('span');
            badge.className = 'dest-badge-rec';
            badge.textContent = 'Recommended · Retained on reboot';
            nameRow.append(nameEl, badge);

            const spaceRow = document.createElement('div');
            spaceRow.className = 'dest-space-row';
            const neededStr = needed > 0 ? ` · Needs ${byteSize(needed)}` : '';
            spaceRow.textContent = `${gib(recItem.free_bytes)} free${neededStr}`;
            info.append(nameRow, spaceRow);

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'mission-primary dest-select-btn';
            btn.textContent = 'Use this drive (Recommended)';
            btn.disabled = false;
            btn.addEventListener('click', async () => {
              btn.disabled = true;
              btn.textContent = 'Checking write access…';
              try {
                const resp = await fetch('/api/storage/choose', {
                  method: 'POST',
                  headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
                  body: JSON.stringify({candidate: recItem.id})
                });
                if (!resp.ok) throw new Error('Write check failed');
                await refreshStorage();
                await refreshModels();
                inlineSec.hidden = true;
                document.getElementById('download-confirm').disabled = false;
                document.getElementById('download-review-details').textContent =
                  `${tag} · ${byteSize(model?.total_download_bytes || 0)} download · Confirmed destination: ${recItem.path} (Persistent disk).`;
              } catch (_) {
                btn.disabled = false;
                btn.textContent = 'Use this drive (Recommended)';
              }
            });

            strip.append(info, btn);
            art.append(strip);

            const reasonP = document.createElement('p');
            reasonP.className = 'dest-reason-factual';
            reasonP.textContent = `Selection reason: ${recItem.reason || 'Largest eligible writable persistent drive; live boot medium excluded'}.`;
            art.append(reasonP);

            const details = document.createElement('details');
            details.className = 'dest-details-collapse';
            const summary = document.createElement('summary');
            summary.textContent = 'Drive path & details';
            const body = document.createElement('div');
            body.className = 'dest-details-body';
            body.innerHTML = `
              <div class="dest-path-box"><code>${recItem.path}</code></div>
              <div class="dest-meta-grid">
                <div class="meta-field"><div class="field-lbl">Mountpoint</div><div class="field-val">${recItem.mountpoint}</div></div>
                <div class="meta-field"><div class="field-lbl">Persistence</div><div class="field-val">Persistent disk · retained across reboots</div></div>
                <div class="meta-field"><div class="field-lbl">Encryption</div><div class="field-val">${encrypted(recItem.encrypted)}</div></div>
              </div>
            `;
            details.append(summary, body);
            art.append(details);

            diskGroup.append(art);

            // Any secondary selectable disks are listed as alternatives
            if (selectableDisks.length > 1) {
              const altTitle = document.createElement('div');
              altTitle.className = 'storage-group-title title-muted';
              altTitle.textContent = 'Alternative Persistent Drives';
              diskGroup.append(altTitle);

              for (const altItem of selectableDisks.slice(1)) {
                const altArt = document.createElement('article');
                altArt.className = 'destination-card alternative';

                const aStrip = document.createElement('div');
                aStrip.className = 'dest-compact-strip';

                const aInfo = document.createElement('div');
                aInfo.className = 'dest-compact-info';

                const aNameRow = document.createElement('div');
                aNameRow.className = 'dest-name-row';
                const aName = document.createElement('strong');
                aName.className = 'dest-name-title';
                aName.textContent = altItem.volume_label || (altItem.device ? altItem.device.split('/').pop() : 'Alternative Drive');
                const aBadge = document.createElement('span');
                aBadge.className = 'dest-badge-alt';
                aBadge.textContent = 'Alternative drive';
                aNameRow.append(aName, aBadge);

                const aSpaceRow = document.createElement('div');
                aSpaceRow.className = 'dest-space-row';
                aSpaceRow.textContent = `${gib(altItem.free_bytes)} free${neededStr}`;
                aInfo.append(aNameRow, aSpaceRow);

                const aBtn = document.createElement('button');
                aBtn.type = 'button';
                aBtn.className = 'mission-secondary dest-select-btn';
                aBtn.textContent = 'Use this drive';
                aBtn.addEventListener('click', async () => {
                  aBtn.disabled = true;
                  aBtn.textContent = 'Checking…';
                  try {
                    const resp = await fetch('/api/storage/choose', {
                      method: 'POST',
                      headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
                      body: JSON.stringify({candidate: altItem.id})
                    });
                    if (!resp.ok) throw new Error('Write check failed');
                    await refreshStorage();
                    await refreshModels();
                    inlineSec.hidden = true;
                    document.getElementById('download-confirm').disabled = false;
                    document.getElementById('download-review-details').textContent =
                      `${tag} · ${byteSize(model?.total_download_bytes || 0)} download · Confirmed destination: ${altItem.path} (Persistent disk).`;
                  } catch (_) {
                    aBtn.disabled = false;
                    aBtn.textContent = 'Use this drive';
                  }
                });

                aStrip.append(aInfo, aBtn);
                altArt.append(aStrip);

                const aDetails = document.createElement('details');
                aDetails.className = 'dest-details-collapse';
                const aSummary = document.createElement('summary');
                aSummary.textContent = 'Drive path & details';
                const aBody = document.createElement('div');
                aBody.className = 'dest-details-body';
                aBody.innerHTML = `
                  <div class="dest-path-box"><code>${altItem.path}</code></div>
                  <div class="dest-meta-grid">
                    <div class="meta-field"><div class="field-lbl">Mountpoint</div><div class="field-val">${altItem.mountpoint}</div></div>
                    <div class="meta-field"><div class="field-lbl">Persistence</div><div class="field-val">Persistent disk</div></div>
                    <div class="meta-field"><div class="field-lbl">Encryption</div><div class="field-val">${encrypted(altItem.encrypted)}</div></div>
                  </div>
                `;
                aDetails.append(aSummary, aBody);
                altArt.append(aDetails);

                diskGroup.append(altArt);
              }
            }
            inlineChoices.append(diskGroup);
          } else {
            const noDisk = document.createElement('div');
            noDisk.className = 'notice';
            noDisk.innerHTML = '<strong>No persistent disk eligible</strong><p>No mounted disk has sufficient free space and an empty folder. Models can only be downloaded to temporary session RAM below.</p>';
            inlineChoices.append(noDisk);
          }

          // 2. Group Temporary RAM Candidates Secondarily
          if (rams.length > 0) {
            const ramBox = document.createElement('div');
            ramBox.className = 'temporary-ram-box';
            const ramHdr = document.createElement('div');
            ramHdr.className = 'temp-ram-header';
            ramHdr.textContent = selectableDisks.length > 0 ? 'Temporary Memory Alternatives (Session only)' : 'Temporary Memory Storage (Session only)';
            const ramDesc = document.createElement('div');
            ramDesc.className = 'temp-ram-desc';
            ramDesc.textContent = '⚠️ Memory storage (tmpfs) disappears at reboot. Models downloaded to RAM will be lost when you restart or power off.';
            ramBox.append(ramHdr, ramDesc);

            for (const item of rams) {
              const row = document.createElement('div');
              row.className = 'dest-compact-strip';
              const rInfo = document.createElement('div');
              rInfo.className = 'dest-compact-info';
              const rName = document.createElement('strong');
              rName.className = 'dest-name-title';
              rName.textContent = `RAM: ${item.mountpoint}`;
              const rSpace = document.createElement('div');
              rSpace.className = 'dest-space-row';
              rSpace.textContent = `${gib(item.free_bytes)} free memory${needed > 0 ? ' · Needs ' + byteSize(needed) : ''}`;
              rInfo.append(rName, rSpace);

              const btn = document.createElement('button');
              btn.type = 'button';
              btn.className = 'mission-secondary dest-select-btn';
              btn.textContent = 'Use temporary RAM';
              btn.disabled = item.contains_data || (!item.current && !view.can_change);
              btn.addEventListener('click', async () => {
                btn.disabled = true;
                btn.textContent = 'Checking…';
                try {
                  const resp = await fetch('/api/storage/choose', {
                    method: 'POST',
                    headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
                    body: JSON.stringify({candidate: item.id})
                  });
                  if (!resp.ok) throw new Error('Write check failed');
                  await refreshStorage();
                  await refreshModels();
                  inlineSec.hidden = true;
                  document.getElementById('download-confirm').disabled = false;
                  document.getElementById('download-review-details').textContent =
                    `${tag} · ${byteSize(model?.total_download_bytes || 0)} download · Destination: ${item.path} (Temporary memory · lost at reboot).`;
                } catch (_) {
                  btn.disabled = false;
                  btn.textContent = 'Use temporary RAM';
                }
              });
              row.append(rInfo, btn);
              ramBox.append(row);
            }
            inlineChoices.append(ramBox);
          }

          // 3. Collapsed Excluded Destinations & Policy Guardrails (code-grounded; no unsupported read-only claims)
          const policyDetails = document.createElement('details');
          policyDetails.className = 'storage-policy-collapse';
          const policySummary = document.createElement('summary');
          policySummary.textContent = 'Excluded destinations & policy guardrails';
          const policyBody = document.createElement('div');
          policyBody.className = 'storage-policy-body';

          let blockedItemsHtml = '';
          for (const b of blockedDisks) {
            blockedItemsHtml += `
              <div class="blocked-drive-item">
                <div class="blocked-name"><span>${b.volume_label || b.mountpoint} (${b.mountpoint})</span><span class="badge badge-excluded">Unavailable</span></div>
                <div class="blocked-reason">${b.contains_data ? 'Blocked: folder has existing files. Argos requires an empty dedicated store.' : 'Drive modification locked.'}</div>
              </div>
            `;
          }

          policyBody.innerHTML = `
            <div class="blocked-drive-item">
              <div class="blocked-name"><span>Live Boot Medium (/dev/sdb)</span><span class="badge badge-excluded">Excluded</span></div>
              <div class="blocked-reason">Live boot medium and its drive partitions (/dev/sdb) are excluded from model storage to protect operating system and boot integrity.</div>
            </div>
            <div class="blocked-drive-item">
              <div class="blocked-name"><span>Folders with Existing Files</span><span class="badge badge-excluded">Blocked</span></div>
              <div class="blocked-reason">Folders with existing files are blocked. Argos requires creating an empty dedicated directory and never adopts or moves pre-existing files.</div>
            </div>
            ${blockedItemsHtml}
          `;
          policyDetails.append(policySummary, policyBody);
          inlineChoices.append(policyDetails);
        }
      } catch (_) {}
    }
    document.getElementById('download-confirm').disabled = true;
    document.getElementById('download-review-details').textContent = model ?
      `${tag} · ${byteSize(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license}. Choose where models are stored below to run the write check:` :
      `${tag} · Choose where models are stored below:`;
  } else {
    if (inlineSec) inlineSec.hidden = true;
    document.getElementById('download-confirm').disabled = false;
    document.getElementById('download-review-details').textContent = model ?
      `${tag} · ${byteSize(model.total_download_bytes)} download (${model.total_download_bytes.toLocaleString()} bytes) · ${model.license} · Estimated GPU fit: ${model.gpu_fit.status}. ` +
      `Destination: ${modelDestination || 'your configured model store'} · ${encrypted(modelEncryption)}.` :
      `${tag} · Retry against the current catalog and the same identity-checked store.`;
  }
  document.getElementById('download-review').showModal();
}
window.reviewDownload = reviewDownload;
window.resetStorageForReview = () => { storageConfirmed = false; };
async function refreshModelControls() {
  if (downloadRefreshing) return;
  downloadRefreshing = true;
  try {
    const value = await api('/api/models/control');
    downloadAvailable = value.available === true;
    downloadActive = value.active === true;
    document.getElementById('download-controls').hidden = !downloadAvailable;
    document.getElementById('download-pause').hidden = !downloadActive;
    document.getElementById('download-cancel').hidden = !downloadActive;
    document.getElementById('download-pause').disabled = !downloadActive || value.phase === 'cancelling';
    document.getElementById('download-cancel').disabled = !downloadActive || value.phase === 'cancelling';
    const names = {idle: 'Choose a model below to review its download.', pausing: 'Pausing chat…',
      downloading: 'Downloading model artifacts…', verifying: 'Checking full artifact hashes…',
      loading: 'Loading the new model…', testing: 'Testing a short local reply…', publishing: 'Publishing verified files…',
      completed: 'Downloaded and reply-tested. Check the selected model below.', paused: 'Paused; review a retry to resume.',
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
let selectionRollbackAvailable = false;
let selectionPreviousModel = null;
let currentModelName = null;
let commandModelName = null;
let activeModelMonitoring = null;
let selectionProgressRevealed = false;
async function refreshSelection() {
  if (selectionRefreshing) return;
  selectionRefreshing = true;
  try {
    const value = await api('/api/models/selection');
    const changed = value.available !== selectionAvailable || value.phase !== selectionPhase || value.active !== selectionActive;
    selectionAvailable = value.available === true; selectionActive = value.active === true; selectionPhase = value.phase;
    selectionRollbackAvailable = value.rollback_available === true;
    selectionPreviousModel = value.previous_model || null;
    currentModelName = value.model || null;
    const pending = getPendingModelAction();
    document.getElementById('selection-controls').hidden = (!selectionAvailable || value.phase === 'idle') && !pending;
    if ((pending || selectionActive) && !selectionProgressRevealed) {
      focusSection('selection-controls');
      selectionProgressRevealed = true;
    } else if (!pending && !selectionActive) {
      selectionProgressRevealed = false;
    }
    document.getElementById('selection-cancel').disabled = !selectionActive || value.phase === 'cancelling';
    document.getElementById('selection-cancel').hidden = !selectionActive;
    const messages = {idle: 'Choose Review switch on a local model.', pausing: 'Pausing the current assistant…',
      verifying: 'Rechecking all model artifacts…', starting: 'Testing the selected model through OpenClaw…',
      restoring: 'Restoring the previous selection…', 'rolled-back': 'Startup failed. The previous selection was restored.',
      completed: 'Selected model is ready. Run a baseline to compare speed and ability, or open chat.',
      cancelled: 'Switch cancelled. The previous selection was retained or restored.',
      cancelling: 'Cancelling switch and releasing resources…', failed: 'Switch needs attention. Inspect private diagnostics; owner edits are preserved.'};
    messages['recovery-blocked'] = 'Owner edits prevent automatic rollback. Assistant is stopped; private recovery record retained for review.';
    if (pending) {
      const elapsedMs = Date.now() - (pending.startedAt || 0);
      if (elapsedMs >= 60000 && value.active) {
        document.getElementById('selection-status').textContent = 'Switch still running—reconnecting';
      } else if (!value.active) {
        if (value.phase !== 'completed') {
          document.getElementById('selection-status').textContent = messages[value.phase] || 'Checking selection…';
        }
      } else {
        document.getElementById('selection-status').textContent = messages[value.phase] || 'Checking selection…';
      }
      if (!activeModelMonitoring && value.active) {
        resumePendingModelMonitoring();
      }
    } else {
      document.getElementById('selection-status').textContent = messages[value.phase] || 'Checking selection…';
    }
    if (selectionActive) document.getElementById('lab-start').disabled = true;
    if (changed) {
      await refreshModels();
      if (value.phase === 'completed') await refreshCommand();
    }
  } catch (_) {
    const pending = getPendingModelAction();
    if (pending) {
      const selControls = document.getElementById('selection-controls');
      if (selControls) selControls.hidden = false;
      document.getElementById('selection-status').textContent = 'Switch still running—reconnecting';
    } else {
      document.getElementById('selection-status').textContent = 'Selection status unavailable. Refresh before switching.';
    }
  }
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
resumePendingModelMonitoring();
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
        const expBtn = document.getElementById('compare-experiment');
        if (expBtn) expBtn.disabled = selectedRuns.size !== 2;
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
    const expBtn = document.getElementById('compare-experiment');
    if (expBtn) expBtn.disabled = selectedRuns.size !== 2;
    status.textContent = result.runs.length ? `${result.runs.length} saved benchmark runs.` : 'No saved benchmarks yet.';
    if (result.invalid_count || result.truncated) status.textContent += ' Some results need review or were omitted by display limits.';

    // Continuous experiment journey: automatic baseline retention and candidate pairing
    try {
      const docRuns = result.runs.filter(r => r.kind === 'ability' && (r.suite_version || '').startsWith('documents/'));
      if (retainedBaselineDocRunId && !docRuns.some(r => r.id === retainedBaselineDocRunId)) {
        retainedBaselineDocRunId = null;
        try { sessionStorage.removeItem('argos_baseline_doc_run_id'); } catch (_) {}
      }
      if (!retainedBaselineDocRunId) {
        for (const r of docRuns) {
          if (r.state === 'completed') {
            const full = await api('/api/benchmarks/run/' + r.id);
            if (!full.recipe || full.recipe.preset === 'standard') {
              retainedBaselineDocRunId = r.id;
              sessionStorage.setItem('argos_baseline_doc_run_id', r.id);
              break;
            }
          }
        }
      }
      if (retainedBaselineDocRunId && docRuns.length >= 2) {
        const latestDoc = docRuns.find(r => r.id !== retainedBaselineDocRunId && r.state === 'completed');
        const baselineRow = docRuns.find(r => r.id === retainedBaselineDocRunId);
        // An older candidate or one already kept/restored is history, not the current decision.
        const current = latestDoc && baselineRow && latestDoc.created > baselineRow.created &&
          !decidedExperiments().includes(latestDoc.id);
        if (!current && latestDoc?.id !== autoComparedCandidateId) {
          document.getElementById('improve-comparison')?.replaceChildren();
          lastExperiment = null;
        }
        if (current && latestDoc.id !== autoComparedCandidateId) {
          const fullCand = await api('/api/benchmarks/run/' + latestDoc.id);
          const candPreset = fullCand.recipe?.preset || 'standard';
          if (candPreset !== 'standard') {
            const expOut = document.getElementById('improve-comparison');
            document.getElementById('experiment-comparison')?.replaceChildren();
            try {
              const expRes = await api(`/api/benchmarks/experiment?baseline=${encodeURIComponent(retainedBaselineDocRunId)}&candidate=${encodeURIComponent(latestDoc.id)}`);
              autoComparedCandidateId = latestDoc.id;
              if (expOut) { lastExperiment = expRes; renderExperiment(expOut, expRes); refreshCommand(); renderReplay(); }
              status.textContent = 'Controlled experiment comparison ready. Evaluated on identical hardware with exactly one recipe intervention.';
              const arenaBanner = document.getElementById('arena-summary-banner');
              const arenaHeadline = document.getElementById('arena-summary-headline');
              const arenaDetail = document.getElementById('arena-summary-detail');
              const arenaNext = document.getElementById('arena-next-action');
              if (arenaBanner && arenaHeadline) {
                arenaBanner.hidden = false;
                arenaHeadline.textContent = 'Experiment finished · before and after are ready';
                if (arenaDetail) arenaDetail.textContent = `Paired with retained baseline (${retainedBaselineDocRunId.slice(0, 8)}…) on identical hardware. One action recommended below.`;
                if (arenaNext) {
                  arenaNext.hidden = false;
                  arenaNext.textContent = 'See before and after ↑';
                  arenaNext.onclick = () => focusSection('improve-comparison');
                }
              }
            } catch (cmpErr) {
              autoComparedCandidateId = null;
              status.textContent = 'Controlled comparison refused: ' + cmpErr.message;
              const arenaBanner = document.getElementById('arena-summary-banner');
              const arenaHeadline = document.getElementById('arena-summary-headline');
              const arenaDetail = document.getElementById('arena-summary-detail');
              const arenaNext = document.getElementById('arena-next-action');
              if (arenaBanner && arenaHeadline) {
                arenaBanner.hidden = false;
                arenaHeadline.textContent = 'Comparison refused by server';
                if (arenaDetail) arenaDetail.textContent = cmpErr.message || 'The server rejected this comparison pair. Runs must be completed on identical hardware with exactly one controlled intervention.';
                if (arenaNext) {
                  arenaNext.hidden = false;
                  arenaNext.textContent = 'See why ↑';
                  arenaNext.onclick = () => focusSection('improve-comparison');
                }
              }
              if (expOut) {
                expOut.replaceChildren();
                const card = document.createElement('article');
                card.className = 'experiment-card experiment-refusal-card';
                card.id = 'experiment-refusal';
                const badge = document.createElement('span');
                badge.className = 'experiment-badge badge-refusal';
                badge.textContent = 'Comparison Refused';
                const title = document.createElement('h3');
                title.textContent = 'Controlled comparison rejected';
                title.prepend(badge);
                const msg = document.createElement('p');
                msg.className = 'experiment-refusal-message';
                msg.textContent = cmpErr.message || 'The server rejected this comparison pair. Runs must be completed on identical hardware with exactly one controlled intervention.';
                card.append(title, msg);
                expOut.append(card);
              }
            }
          }
        }
      }
    } catch (err) {
      console.error('Auto-pairing experiment error:', err);
    }
  } catch (_) {
    cards.replaceChildren(); selectedRuns.clear(); comparedRuns = [];
    document.getElementById('compare-runs').disabled = true;
    const expBtn = document.getElementById('compare-experiment');
    if (expBtn) expBtn.disabled = true;
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
const normalizeDigest = (d) => {
  if (!d || typeof d !== 'string') return '';
  return d.startsWith('sha256:') ? d.slice(7).toLowerCase() : d.toLowerCase();
};

function getPendingModelAction() {
  try {
    const raw = sessionStorage.getItem('argos_pending_model_action');
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function updateModelActionStatus(text, isError = false, statusNote = null) {
  const selStatus = document.getElementById('selection-status');
  const selControls = document.getElementById('selection-controls');
  if (selStatus) {
    selStatus.textContent = text;
    selStatus.classList.toggle('status-error', isError);
    if (selControls && !isError) selControls.hidden = false;
  }
  if (statusNote) {
    statusNote.textContent = text;
    statusNote.classList.toggle('status-error', isError);
  }
  document.querySelectorAll('#recommendation-status, .recommendation-status').forEach(el => {
    el.textContent = text;
    el.classList.toggle('status-error', isError);
  });
}

// Both normal polling and lost-response recovery use the same evidence rules.
function selectionOutcome(snap) {
  if (!snap || snap.available === false) throw new Error('Model selection controller unavailable');
  if (snap.active) return 'pending';
  if (snap.phase === 'completed') return 'completed';
  const errors = {
    'rolled-back': 'Startup failed. The previous selection was restored (rolled back).',
    cancelled: 'Switch cancelled. The previous selection was retained or restored.',
    'recovery-blocked': 'Owner edits prevent automatic rollback. Assistant is stopped; recovery blocked.',
    failed: 'Model switch failed. Inspect private diagnostics; owner edits are preserved.',
    idle: 'No model operation confirmed. Controls restored; review the current selection before retrying.'
  };
  if (errors[snap.phase]) throw new Error(errors[snap.phase]);
  return 'pending';
}

async function waitSelectionTerminal(statusNote, actionLabel, startedAt) {
  const maxBudgetMs = 1500000;
  const observationStart = startedAt || Date.now();
  const pollInterval = 100;
  let consecutiveErrors = 0;

  const messages = {
    verifying: 'Rechecking all model artifacts…',
    stopping: 'Pausing the current assistant…',
    starting: 'Testing the selected model through OpenClaw…',
    restoring: 'Restoring the previous selection…',
    cancelling: 'Cancelling switch and releasing resources…'
  };

  while (Date.now() - observationStart < maxBudgetMs) {
    let snap;
    try {
      snap = await api('/api/models/selection');
      consecutiveErrors = 0;
    } catch (_) {
      consecutiveErrors++;
      updateModelActionStatus('Switch still running—reconnecting', false, statusNote);
      await new Promise(r => setTimeout(r, pollInterval));
      continue;
    }

    const outcome = selectionOutcome(snap);

    const elapsedMs = Date.now() - observationStart;
    const observationTimedOut = elapsedMs >= 60000;

    if (snap.active) {
      if (observationTimedOut || consecutiveErrors > 0) {
        updateModelActionStatus('Switch still running—reconnecting', false, statusNote);
      } else {
        const msg = messages[snap.phase] || (actionLabel === 'switch-candidate' ? 'Switching model…' : 'Restoring model…');
        updateModelActionStatus(msg, false, statusNote);
      }
      await new Promise(r => setTimeout(r, pollInterval));
      continue;
    }

    if (outcome === 'completed') return snap;
    await new Promise(r => setTimeout(r, pollInterval));
  }
  throw new Error('Model selection timed out');
}

async function verifyModelSelectionIdentity(expectedTag, expectedDigest) {
  const modelsData = await api('/api/models');
  if (modelsData.selected_model !== expectedTag) {
    throw new Error(`Selected model mismatch: expected '${expectedTag}', got '${modelsData.selected_model || 'none'}'`);
  }
  if (expectedDigest) {
    const allModels = [
      ...(modelsData.installed || []),
      ...((modelsData.bundled && modelsData.bundled.models) || [])
    ];
    const match = allModels.find(m => m.tag === expectedTag);
    let actualDigest = match?.manifest_digest;
    if (!actualDigest) {
      try {
        const cc = await api('/api/command-center');
        actualDigest = cc.skill_map?.manifest_digest || cc.model?.digest;
      } catch (_) {}
    }
    const expNorm = normalizeDigest(expectedDigest);
    const actNorm = normalizeDigest(actualDigest);
    if (!actNorm || expNorm !== actNorm) {
      throw new Error(`Manifest digest mismatch: expected '${expectedDigest}', got '${actualDigest || 'unidentified'}'`);
    }
  }
}

async function monitorModelAction(statusNote, btnPrimary, btnSecondary, pendingAction, observedSnapshot = null) {
  const { actionType, targetModel, targetDigest, startedAt } = pendingAction;
  if (btnPrimary) btnPrimary.disabled = true;
  if (btnSecondary) btnSecondary.disabled = true;
  const initialMsg = Date.now() - (startedAt || 0) >= 60000
    ? 'Switch still running—reconnecting'
    : 'Testing the selected model through OpenClaw…';
  updateModelActionStatus(initialMsg, false, statusNote);

  try {
    const observedOutcome = observedSnapshot ? selectionOutcome(observedSnapshot) : 'pending';
    if (observedOutcome !== 'completed') await waitSelectionTerminal(statusNote, actionType, startedAt);
    await refreshModels();
    await refreshSelection();
    await verifyModelSelectionIdentity(targetModel, targetDigest);
    try { sessionStorage.removeItem('argos_pending_model_action'); } catch (_) {}
    const successMsg = actionType === 'switch-candidate'
      ? `Switched to candidate model ${targetModel}. Model switch verified with matching manifest digest.`
      : `Baseline model ${targetModel} retained. Model switch verified with matching manifest digest.`;
    updateModelActionStatus(successMsg, false, statusNote);
  } catch (err) {
    try { sessionStorage.removeItem('argos_pending_model_action'); } catch (_) {}
    const errMsg = (actionType === 'switch-candidate' ? 'Failed to switch model: ' :
      actionType === 'keep-baseline' ? 'Failed to retain baseline model: ' : 'Action failed: ') + err.message;
    updateModelActionStatus(errMsg, true, statusNote);
  } finally {
    if (btnPrimary) btnPrimary.disabled = false;
    if (btnSecondary) btnSecondary.disabled = false;
    const bp = document.getElementById('exp-action-primary');
    const bs = document.getElementById('exp-action-secondary');
    if (bp) bp.disabled = false;
    if (bs) bs.disabled = false;
  }
}

function resumePendingModelMonitoring() {
  const pending = getPendingModelAction();
  if (!pending) return;
  const selControls = document.getElementById('selection-controls');
  if (selControls) selControls.hidden = false;
  const elapsed = Date.now() - (pending.startedAt || 0);
  const initialMsg = elapsed >= 60000 ? 'Switch still running—reconnecting' : 'Testing the selected model through OpenClaw…';
  updateModelActionStatus(initialMsg, false, null);

  if (!activeModelMonitoring) {
    const recStatus = document.getElementById('recommendation-status');
    const btnPrimary = document.getElementById('exp-action-primary');
    const btnSecondary = document.getElementById('exp-action-secondary');
    activeModelMonitoring = monitorModelAction(recStatus, btnPrimary, btnSecondary, pending)
      .finally(() => { activeModelMonitoring = null; });
  }
}

async function reconcileModelActionWithController(pending, statusNote, btnPrimary, btnSecondary) {
  updateModelActionStatus('Reconciling switch status with controller…', false, statusNote);
  let snap;
  try {
    snap = await api('/api/models/selection');
  } catch (_) {
    updateModelActionStatus('Switch still running—reconnecting', false, statusNote);
    activeModelMonitoring = monitorModelAction(statusNote, btnPrimary, btnSecondary, pending)
      .finally(() => { activeModelMonitoring = null; });
    return activeModelMonitoring;
  }

  // A lost POST can already have failed or rolled back. Retain that outcome.
  activeModelMonitoring = monitorModelAction(statusNote, btnPrimary, btnSecondary, pending, snap)
    .finally(() => { activeModelMonitoring = null; });
  return activeModelMonitoring;
}

function renderExperimentRecommendation(card, result) {
  const box = document.createElement('div');
  box.id = 'experiment-recommendation';
  box.className = 'experiment-recommendation-box';

  const intervention = result.intervention || 'recipe';
  const verdict = result.delta?.verdict || 'no_change';
  const deltaCorr = result.delta?.correct_delta ?? 0;
  const deltaFmt = result.delta?.format_error_delta ?? 0;

  let badgeText = 'Based on this comparison';
  let recTitle = '';
  let recReason = '';
  let primaryBtnText = '';
  let secondaryBtnText = '';
  let primaryActionType = '';
  let secondaryActionType = '';

  if (intervention === 'model') {
    const candModel = result.candidate?.model || 'candidate model';
    const baseModel = result.baseline?.model || 'baseline model';
    if (result.kind === 'speed') {
      const prompts = result.delta?.prompts || [];
      const hasSpeedGain = prompts.some(p => (p.delta_generation_tok_s ?? 0) > 0);
      if (hasSpeedGain) {
        box.classList.add('verdict-keep');
        recTitle = `Switch to candidate model (${candModel})`;
        recReason = `Evidence shows generation speed advantage with ${candModel} on identical hardware. Switch to the candidate model, or keep ${baseModel}.`;
        primaryBtnText = `Switch to ${candModel}`;
        secondaryBtnText = `Keep ${baseModel}`;
        primaryActionType = 'switch-candidate';
        secondaryActionType = 'keep-baseline';
      } else {
        box.classList.add('verdict-restore');
        recTitle = `Keep baseline model (${baseModel})`;
        recReason = `Evidence shows no speed advantage with ${candModel} compared to ${baseModel}. Keep baseline model to avoid unnecessary changes.`;
        primaryBtnText = `Keep ${baseModel}`;
        secondaryBtnText = `Switch to ${candModel}`;
        primaryActionType = 'keep-baseline';
        secondaryActionType = 'switch-candidate';
      }
    } else {
      if (verdict === 'observed_gain' || deltaCorr > 0) {
        box.classList.add('verdict-keep');
        recTitle = `Switch to candidate model (${candModel})`;
        recReason = `Evidence shows observed performance gain (+${deltaCorr} tasks) with ${candModel} on identical hardware. Switch to the candidate model, or keep ${baseModel}.`;
        primaryBtnText = `Switch to ${candModel}`;
        secondaryBtnText = `Keep ${baseModel}`;
        primaryActionType = 'switch-candidate';
        secondaryActionType = 'keep-baseline';
      } else if (verdict === 'regression' || deltaCorr < 0) {
        box.classList.add('verdict-restore');
        recTitle = `Keep baseline model (${baseModel})`;
        recReason = `Evidence shows performance regression (${deltaCorr} tasks) with ${candModel} compared to ${baseModel}. Keep ${baseModel} to preserve task accuracy.`;
        primaryBtnText = `Keep ${baseModel}`;
        secondaryBtnText = `Switch to ${candModel}`;
        primaryActionType = 'keep-baseline';
        secondaryActionType = 'switch-candidate';
      } else {
        box.classList.add('verdict-restore');
        recTitle = `Keep baseline model (${baseModel})`;
        recReason = `No measurable performance difference observed between ${candModel} and ${baseModel}. Keep ${baseModel} to maintain stability.`;
        primaryBtnText = `Keep ${baseModel}`;
        secondaryBtnText = `Switch to ${candModel}`;
        primaryActionType = 'keep-baseline';
        secondaryActionType = 'switch-candidate';
      }
    }
  } else {
    const KEEP = 'Keep for lab tests', RESTORE = 'Restore standard instructions';
    const count = (n, what) => `${Math.abs(n)} ${what}${Math.abs(n) === 1 ? '' : 's'}`;
    const keepFirst = (title, why) => {
      recTitle = title; recReason = why;
      primaryBtnText = KEEP; secondaryBtnText = RESTORE; primaryActionType = 'keep'; secondaryActionType = 'restore';
    };
    const restoreFirst = (title, why) => {
      recTitle = title; recReason = why;
      primaryBtnText = RESTORE; secondaryBtnText = KEEP; primaryActionType = 'restore'; secondaryActionType = 'keep';
    };
    if (deltaCorr < 0 && deltaFmt < 0) {
      box.classList.add('verdict-tradeoff');
      badgeText = 'Tradeoff';
      restoreFirst('restore standard instructions',
        `A tradeoff: the instruction reduced format errors (${deltaFmt}), but correct answers decreased (${deltaCorr} tasks). Restoring standard protects accuracy; keep the instruction only if format matters more to you.`);
    } else if (deltaCorr < 0) {
      box.classList.add('verdict-restore');
      badgeText = 'Worse on this retest';
      restoreFirst('restore standard instructions',
        `On the same questions, ${count(deltaCorr, 'fewer answer')} ${Math.abs(deltaCorr) === 1 ? 'was' : 'were'} correct with the instruction` +
        (deltaFmt > 0 ? ` and ${count(deltaFmt, 'more format error')} appeared.` : '.'));
    } else if (deltaCorr > 0 && deltaFmt > 0) {
      box.classList.add('verdict-tradeoff');
      badgeText = 'Tradeoff';
      keepFirst('keep strict format instructions for lab tests',
        `A tradeoff: correct answers improved (+${deltaCorr} tasks), but format errors increased (+${deltaFmt}). Keep it if accuracy matters more to you.`);
    } else if (deltaCorr > 0) {
      box.classList.add('verdict-keep');
      badgeText = 'Better on this retest';
      keepFirst('keep strict format instructions for lab tests',
        `On the same questions, ${count(deltaCorr, 'more answer')} ${deltaCorr === 1 ? 'was' : 'were'} correct with the instruction` +
        (deltaFmt < 0 ? ` and ${count(deltaFmt, 'fewer format error')} appeared.` : '.') + ' This is one matched retest, not a guarantee.');
    } else if (deltaFmt < 0) {
      box.classList.add('verdict-keep');
      badgeText = 'Fewer format errors';
      keepFirst('keep strict format instructions for lab tests',
        `The same number of answers were correct, with ${count(deltaFmt, 'fewer format error')}. This is one matched retest, not a guarantee.`);
    } else if (deltaFmt > 0) {
      box.classList.add('verdict-restore');
      badgeText = 'Worse on this retest';
      restoreFirst('restore standard instructions',
        `The same number of answers were correct, with ${count(deltaFmt, 'more format error')}.`);
    } else {
      box.classList.add('verdict-restore');
      badgeText = 'No difference';
      restoreFirst('restore standard instructions',
        'No measurable difference in correct answers or format errors. Restoring standard keeps lab tests unchanged.');
    }
  }

  const hdr = document.createElement('div');
  hdr.className = 'recommendation-header';
  const badge = document.createElement('span');
  badge.className = 'recommendation-badge';
  badge.textContent = badgeText;
  const title = document.createElement('h4');
  title.id = 'recommendation-title';
  title.textContent = `Suggested: ${recTitle}`;
  hdr.append(badge, title);

  const reason = document.createElement('p');
  reason.id = 'recommendation-reason';
  reason.className = 'recommendation-reason';
  reason.textContent = recReason;

  const actions = document.createElement('div');
  actions.className = 'recommendation-actions';

  const btnPrimary = document.createElement('button');
  btnPrimary.id = 'exp-action-primary';
  btnPrimary.type = 'button';
  btnPrimary.className = 'mission-primary';
  btnPrimary.textContent = primaryBtnText;

  const btnSecondary = document.createElement('button');
  btnSecondary.id = 'exp-action-secondary';
  btnSecondary.type = 'button';
  btnSecondary.className = 'mission-secondary';
  btnSecondary.textContent = secondaryBtnText;

  const statusNote = document.createElement('p');
  statusNote.id = 'recommendation-status';
  statusNote.className = 'recommendation-status';
  statusNote.setAttribute('role', 'status');

  // Resume monitoring after reload if a model action was pending
  const pendingAction = getPendingModelAction();
  if (pendingAction && intervention === 'model') {
    btnPrimary.disabled = true;
    btnSecondary.disabled = true;
    const elapsed = Date.now() - (pendingAction.startedAt || 0);
    statusNote.textContent = elapsed >= 60000 ? 'Switch still running—reconnecting' : 'Testing the selected model through OpenClaw…';
    if (!activeModelMonitoring) {
      activeModelMonitoring = monitorModelAction(statusNote, btnPrimary, btnSecondary, pendingAction)
        .finally(() => { activeModelMonitoring = null; });
    }
  }

  const executeAction = async (actionType) => {
    if (sessionStorage.getItem('argos_pending_model_action')) {
      return; // prevent duplicate submissions
    }
    btnPrimary.disabled = true;
    btnSecondary.disabled = true;
    statusNote.classList.remove('status-error');

    try {
      if (actionType === 'restore') {
        statusNote.textContent = 'Restoring standard calibration…';
        await restoreLabRecipe();
        const recipes = await api('/api/lab/recipes');
        if (recipes.selected !== null && recipes.selected?.preset !== 'standard') {
          throw new Error(`Recipe restore verification failed: expected standard (null), got '${recipes.selected?.preset}'`);
        }
        statusNote.textContent = 'Restored standard instructions and verified. Lab tests are back to how they were before the experiment.';
        if (result.candidate?.id) rememberDecided(result.candidate.id);
        const activeRecEl = document.getElementById('lab-active-recipe');
        if (activeRecEl) activeRecEl.textContent = 'Standard calibration';
        const restoreBtn = document.getElementById('lab-recipe-restore');
        if (restoreBtn) restoreBtn.hidden = true;
      } else if (actionType === 'keep') {
        const candPreset = result.candidate?.recipe?.preset || 'concise';
        const candLabel = candPreset === 'concise' ? 'Strict format instructions (concise)' : candPreset;
        statusNote.textContent = `Selecting tested recipe (${candPreset})…`;
        const res = await fetch('/api/lab/recipe/select', {
          method: 'POST',
          headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
          body: JSON.stringify({preset: candPreset}),
          cache: 'no-store'
        });
        if (!res.ok) {
          let msg = `Recipe selection failed (HTTP ${res.status})`;
          try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
          throw new Error(msg);
        }
        await refreshLab();
        const recipes = await api('/api/lab/recipes');
        if (recipes.selected?.preset !== candPreset) {
          throw new Error(`Recipe selection verification failed: expected '${candPreset}', got '${recipes.selected?.preset}'`);
        }
        statusNote.textContent = `Kept and verified for lab tests: they now use ${candPreset === 'concise' ? 'strict format instructions' : candLabel}. Your everyday assistant is unchanged. You can restore standard at any time.`;
        if (result.candidate?.id) rememberDecided(result.candidate.id);
        const activeRecEl = document.getElementById('lab-active-recipe');
        if (activeRecEl) activeRecEl.textContent = candLabel;
        const restoreBtn = document.getElementById('lab-recipe-restore');
        if (restoreBtn) restoreBtn.hidden = false;
      } else if (actionType === 'switch-candidate') {
        const candModel = result.candidate?.model;
        const candDigest = result.candidate?.manifest_digest;
        const pending = {
          actionType,
          targetModel: candModel,
          targetDigest: candDigest,
          startedAt: Date.now()
        };
        try { sessionStorage.setItem('argos_pending_model_action', JSON.stringify(pending)); } catch (_) {}
        statusNote.textContent = `Initiating switch to candidate model (${candModel})…`;

        let res;
        try {
          res = await fetch('/api/models/select', {
            method: 'POST',
            headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
            body: JSON.stringify({tag: candModel}),
            cache: 'no-store'
          });
        } catch (netErr) {
          await reconcileModelActionWithController(pending, statusNote, btnPrimary, btnSecondary);
          return;
        }

        if (!res.ok) {
          try { sessionStorage.removeItem('argos_pending_model_action'); } catch (_) {}
          let msg = `Model switch rejected (HTTP ${res.status})`;
          try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
          statusNote.classList.add('status-error');
          statusNote.textContent = 'Failed to switch model: ' + msg;
          btnPrimary.disabled = false;
          btnSecondary.disabled = false;
          return;
        }

        activeModelMonitoring = monitorModelAction(statusNote, btnPrimary, btnSecondary, pending)
          .finally(() => { activeModelMonitoring = null; });
        await activeModelMonitoring;
      } else if (actionType === 'keep-baseline') {
        const baseModel = result.baseline?.model;
        const baseDigest = result.baseline?.manifest_digest;
        let usedRestore = false;
        try {
          const selSnap = await api('/api/models/selection');
          if (selSnap && selSnap.rollback_available === true && selSnap.previous_model === baseModel) {
            usedRestore = true;
          }
        } catch (_) {}

        const pending = {
          actionType,
          targetModel: baseModel,
          targetDigest: baseDigest,
          startedAt: Date.now()
        };
        try { sessionStorage.setItem('argos_pending_model_action', JSON.stringify(pending)); } catch (_) {}

        let res;
        try {
          if (usedRestore) {
            statusNote.textContent = `Restoring previous baseline model transaction (${baseModel})…`;
            res = await fetch('/api/models/restore', {
              method: 'POST',
              headers: {'X-Argos-Token': token || '', 'Content-Length': '0'},
              cache: 'no-store'
            });
          } else {
            statusNote.textContent = `Retaining baseline model (${baseModel})…`;
            res = await fetch('/api/models/select', {
              method: 'POST',
              headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
              body: JSON.stringify({tag: baseModel}),
              cache: 'no-store'
            });
          }
        } catch (netErr) {
          await reconcileModelActionWithController(pending, statusNote, btnPrimary, btnSecondary);
          return;
        }

        if (!res.ok) {
          try { sessionStorage.removeItem('argos_pending_model_action'); } catch (_) {}
          let msg = (usedRestore ? 'Model restoration rejected' : 'Model selection rejected') + ` (HTTP ${res.status})`;
          try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
          statusNote.classList.add('status-error');
          statusNote.textContent = (actionType === 'keep-baseline' ? 'Failed to retain baseline model: ' : 'Failed to switch model: ') + msg;
          btnPrimary.disabled = false;
          btnSecondary.disabled = false;
          return;
        }

        activeModelMonitoring = monitorModelAction(statusNote, btnPrimary, btnSecondary, pending)
          .finally(() => { activeModelMonitoring = null; });
        await activeModelMonitoring;
      } else if (actionType === 'retry') {
        statusNote.textContent = 'Restarting candidate trial…';
        const res = await fetch('/api/lab/start-documents', {
          method: 'POST',
          headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
          body: JSON.stringify({recipe: 'concise'}),
          cache: 'no-store'
        });
        if (!res.ok) {
          let msg = `Retry failed (HTTP ${res.status})`;
          try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
          throw new Error(msg);
        }
        await refreshLab();
        statusNote.textContent = 'Candidate trial started.';
      }
    } catch (err) {
      statusNote.classList.add('status-error');
      statusNote.textContent = (actionType === 'restore' ? 'Failed to restore standard recipe: ' :
        actionType === 'keep' ? 'Failed to keep trial recipe: ' :
        actionType === 'retry' ? 'Retry failed: ' :
        actionType === 'switch-candidate' ? 'Failed to switch model: ' :
        actionType === 'keep-baseline' ? 'Failed to retain baseline model: ' : 'Action failed: ') + err.message;
    } finally {
      if (!sessionStorage.getItem('argos_pending_model_action')) {
        btnPrimary.disabled = false;
        btnSecondary.disabled = false;
      }
    }
  };

  btnPrimary.addEventListener('click', () => {
    if (btnPrimary.disabled || sessionStorage.getItem('argos_pending_model_action')) return;
    executeAction(primaryActionType);
  });
  btnSecondary.addEventListener('click', () => {
    if (btnSecondary.disabled || sessionStorage.getItem('argos_pending_model_action')) return;
    executeAction(secondaryActionType);
  });

  actions.append(btnPrimary, btnSecondary);
  box.append(hdr, reason, actions, statusNote);
  card.append(box);
}
function renderExperiment(output, result) {
  output.replaceChildren();
  const card = document.createElement('article');
  card.className = 'experiment-card';
  const recipeLabel = preset => (!preset || preset === 'standard') ? 'standard instructions' :
    preset === 'concise' ? 'strict format instructions' : preset;

  const badge = document.createElement('span');
  badge.className = `experiment-badge badge-${result.delta?.verdict || 'no_change'}`;
  badge.textContent = result.delta?.verdict === 'observed_gain' ? 'Better on this retest' :
                      result.delta?.verdict === 'regression' ? 'Worse on this retest' :
                      result.delta?.verdict === 'no_change' ? 'No change' : 'Compared';

  const title = document.createElement('h3');
  title.textContent = result.intervention === 'recipe' ?
    `Experiment result: ${recipeLabel(result.candidate.recipe?.preset)}` :
    `Experiment result: ${result.candidate.model} compared with ${result.baseline.model}`;
  title.prepend(badge);
  card.append(title);

  if (result.kind === 'ability') {
    const rows = document.createElement('dl');
    rows.className = 'before-after';
    const row = (label, before, after) => {
      const item = document.createElement('div');
      const name = document.createElement('dt'); name.textContent = label;
      const value = document.createElement('dd');
      const b = document.createElement('span'); b.className = 'before'; b.textContent = before;
      const arrow = document.createElement('span'); arrow.className = 'arrow'; arrow.textContent = ' → ';
      const a = document.createElement('strong'); a.textContent = after;
      value.append(b, arrow, a); item.append(name, value); rows.append(item);
    };
    row('Correct answers', `${result.baseline.correct} of ${result.baseline.total}`, `${result.candidate.correct} of ${result.candidate.total}`);
    row('Wrong answer format', String(result.baseline.format_errors ?? 0), String(result.candidate.format_errors ?? 0));
    card.append(rows);
  }
  if (result.intervention === 'recipe') {
    // A lab instruction is not part of the everyday assistant; never imply that it improved.
    const scope = document.createElement('p');
    scope.className = 'experiment-scope';
    scope.textContent = 'Lab tests only. Your everyday assistant doesn’t use this instruction, so this result doesn’t show the assistant itself improved.';
    card.append(scope);
  }

  const full = document.createElement('details');
  full.className = 'experiment-full';
  const fullSummary = document.createElement('summary');
  fullSummary.textContent = 'Full comparison';
  const meta = document.createElement('p');
  meta.className = 'experiment-meta';
  meta.textContent = `Before: ${result.baseline.model} with ${recipeLabel(result.baseline.recipe?.preset)}. After: ${result.candidate.model} with ${recipeLabel(result.candidate.recipe?.preset)}.`;
  const summary = document.createElement('p');
  summary.className = 'experiment-summary';
  summary.textContent = result.delta?.summary || '';
  full.append(fullSummary, meta, summary);

  if (result.kind === 'ability') {
    const heads = ['Metric', `Baseline (${result.baseline.recipe?.preset || 'standard'})`, `Candidate (${result.candidate.recipe?.preset || 'standard'})`, 'Delta'];
    const bAcc = pct(result.baseline.accuracy);
    const cAcc = pct(result.candidate.accuracy);
    const dAcc = (result.delta.accuracy_delta >= 0 ? '+' : '') + (result.delta.accuracy_delta * 100).toFixed(1) + '%';
    const bCorr = `${result.baseline.correct}/${result.baseline.total}`;
    const cCorr = `${result.candidate.correct}/${result.candidate.total}`;
    const dCorr = (result.delta.correct_delta >= 0 ? '+' : '') + result.delta.correct_delta;
    const bFmt = String(result.baseline.format_errors ?? 0);
    const cFmt = String(result.candidate.format_errors ?? 0);
    const dFmt = (result.delta.format_error_delta >= 0 ? '+' : '') + result.delta.format_error_delta;
    table(full, 'Controlled task outcomes', heads, [
      ['Correct tasks', bCorr, cCorr, dCorr],
      ['Accuracy', bAcc, cAcc, dAcc],
      ['Format errors', bFmt, cFmt, dFmt],
    ]);

    const changedItems = (result.items || []).filter(it => it.changed);
    if (changedItems.length) {
      const hChanged = document.createElement('h4');
      hChanged.textContent = `Answers that changed (${changedItems.length})`;
      full.append(hChanged);
      for (const it of changedItems) {
        const box = document.createElement('details');
        const sum = document.createElement('summary');
        sum.textContent = `${it.category.replace('_', ' ')}: ${it.question || it.item_id} [${it.baseline_outcome} → ${it.candidate_outcome}]`;
        box.append(sum);
        const pBase = document.createElement('p');
        pBase.textContent = `Before (${it.baseline_outcome}): ${it.baseline_output || 'no output kept'}`;
        const pCand = document.createElement('p');
        pCand.textContent = `After (${it.candidate_outcome}): ${it.candidate_output || 'no output kept'}`;
        box.append(pBase, pCand);
        full.append(box);
      }
    }
  } else if (result.kind === 'speed') {
    const heads = ['Prompt size', 'Baseline tok/s', 'Candidate tok/s', 'Delta tok/s', 'Baseline first token', 'Candidate first token', 'Delta first token'];
    const rows = (result.delta.prompts || []).map(p => [
      p.size,
      p.baseline_generation_tok_s !== null ? p.baseline_generation_tok_s.toFixed(2) : 'n/a',
      p.candidate_generation_tok_s !== null ? p.candidate_generation_tok_s.toFixed(2) : 'n/a',
      p.delta_generation_tok_s !== null ? (p.delta_generation_tok_s >= 0 ? '+' : '') + p.delta_generation_tok_s.toFixed(2) : 'n/a',
      p.baseline_ttft_s !== null ? p.baseline_ttft_s.toFixed(2) + ' s' : 'n/a',
      p.candidate_ttft_s !== null ? p.candidate_ttft_s.toFixed(2) + ' s' : 'n/a',
      p.delta_ttft_s !== null ? (p.delta_ttft_s >= 0 ? '+' : '') + p.delta_ttft_s.toFixed(3) + ' s' : 'n/a',
    ]);
    table(full, 'Paired prompt speed comparison (3-run medians)', heads, rows);
  }
  const limits = document.createElement('p');
  limits.className = 'experiment-limits';
  limits.textContent = result.limitations;
  full.append(limits);

  // Evidence-based action recommendation
  renderExperimentRecommendation(card, result);
  card.append(full);
  output.append(card);
}
document.getElementById('compare-experiment')?.addEventListener('click', async () => {
  const output = document.getElementById('experiment-comparison');
  if (output) output.replaceChildren();
  if (selectedRuns.size !== 2) return;
  const ids = [...selectedRuns];
  try {
    const result = await api(`/api/benchmarks/experiment?baseline=${encodeURIComponent(ids[0])}&candidate=${encodeURIComponent(ids[1])}`);
    renderExperiment(output, result);
    document.getElementById('benchmarks-status').textContent = result.limitations || 'Controlled experiment comparison.';
  } catch (err) {
    if (output) {
      output.replaceChildren();
      const card = document.createElement('article');
      card.className = 'experiment-card experiment-refusal-card';
      card.id = 'experiment-refusal';
      const badge = document.createElement('span');
      badge.className = 'experiment-badge badge-refusal';
      badge.textContent = 'Comparison Refused';
      const title = document.createElement('h3');
      title.textContent = 'Controlled comparison rejected';
      title.prepend(badge);
      const msg = document.createElement('p');
      msg.className = 'experiment-refusal-message';
      msg.textContent = err.message || 'Comparison rejected: verify runs differ by exactly one intervention with matching hardware.';
      card.append(title, msg);
      output.append(card);
    }
    document.getElementById('benchmarks-status').textContent = err.message || 'Experiment comparison failed. Verify runs differ by exactly one intervention with matching hardware.';
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
  if (!target) return;
  for (let parent = target.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') parent.open = true;
  }
  if (target.tagName === 'DETAILS') target.open = true;
  target.scrollIntoView({behavior: 'smooth', block: 'start'});
  if (control) document.getElementById(control)?.focus({preventScroll: true});
}
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (!link) return;
  const id = link.getAttribute('href').slice(1);
  if (!document.getElementById(id)) return;
  event.preventDefault();
  if (link.getAttribute('aria-disabled') === 'true') return;
  focusSection(id);
});
if (new URLSearchParams(location.search).get('view') === 'lab') {
  document.getElementById('workbench').open = true;
}
function sameBundledModel(model, bundled) {
  return bundled?.state === 'available' && model.files_present === true &&
    bundled.models.some(starter => model.tag === starter.tag &&
      typeof model.manifest_digest === 'string' && model.manifest_digest === starter.manifest_digest);
}
function startMissionTrial(control) {
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
    section.dataset.commandUnavailable = String(value.available === false);
    section.hidden = value.available === false && document.getElementById('arena').hidden;
    if (value.available === false) return;
    document.getElementById('cc-name').textContent = value.name + (value.model ? ' · ' + value.model : '');
    const heroAi = document.getElementById('cc-hero-ai');
    if (heroAi) heroAi.textContent = value.name || 'your AI';
    commandModelName = value.model || null;
    const heroModel = document.getElementById('cc-hero-model');
    if (heroModel) {
      const isFixture = (value.model || '').startsWith('fixture:');
      heroModel.textContent = (value.model || 'Current model') + (isFixture ? ' (simulated fixture)' : '');
    }
    const heroResult = document.getElementById('cc-hero-result');
    if (heroResult) {
      const ab = value.report?.ability;
      const qualState = ab ? (ab.qualified === true ? 'Qualified' : (ab.qualified === false ? 'Criteria not met' : 'Not assessed')) : '';
      heroResult.textContent = ab ? `${ab.correct}/${ab.total} (${qualState})` : 'Not yet tested';
    }
    const rung1Badge = document.getElementById('rung-1-status');
    const curriculumOverallBadge = document.getElementById('curriculum-overall-badge');
    if (rung1Badge) {
      const ab = value.report?.ability;
      if (!ab) {
        rung1Badge.className = 'rung-status-badge current';
        rung1Badge.textContent = 'Ready to test';
        if (curriculumOverallBadge) curriculumOverallBadge.textContent = 'Rung 1: Ready to test';
      } else if (ab.qualified === true) {
        rung1Badge.className = 'rung-status-badge pass';
        rung1Badge.textContent = '● Qualified';
        if (curriculumOverallBadge) curriculumOverallBadge.textContent = 'Rung 1: Qualified';
      } else {
        rung1Badge.className = 'rung-status-badge attention';
        rung1Badge.textContent = '▲ Criteria not met';
        if (curriculumOverallBadge) curriculumOverallBadge.textContent = 'Rung 1: Criteria not met';
      }
    }
    renderMissionReceipt(value.report);
    const hasResult = Boolean(value.report?.ability || value.report?.speed);
    document.getElementById('cc-receipt').hidden = !hasResult;
    updateSessionPath(sessionActive, hasResult);
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
  if (!response.ok) {
    let msg = `Action unavailable (HTTP ${response.status})`;
    try {
      const err = await response.json();
      if (err?.error) msg = err.error;
    } catch (_) {}
    const error = new Error(msg);
    error.status = response.status;
    throw error;
  }
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
    measured: '◐ Tested · validation pending',
    attention: '▲ Needs work',
    untested: '○ Untested',
    unavailable: '◇ Future'
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

let displayedReceiptKey = null;
function renderMissionReceipt(report) {
  const scoreboard = document.getElementById('cc-scoreboard'); scoreboard.replaceChildren();
  const bars = document.getElementById('cc-skill-bars'); bars.replaceChildren();
  const ability = report?.ability, speed = report?.speed;
  const receiptKey = JSON.stringify([ability?.run, speed?.run, ability?.qualified]);
  const newReceipt = receiptKey !== displayedReceiptKey;
  displayedReceiptKey = receiptKey;
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
  const missed = (ability?.checks || []).filter(c => !c.met);
  document.getElementById('cc-receipt-title').textContent = !ability ? 'Let’s find your starting point' :
    `${ability.correct} of ${ability.total} correct`;
  const takeawayEl = document.getElementById('cc-takeaway');
  if (!ability) {
    takeawayEl.textContent = 'Start here: run one trial, then try a mission below.';
  } else {
    const wrong = ability.wrong_answers ?? Math.max(0, ability.total - ability.correct - ability.format_errors);
    const misses = [wrong ? `${wrong} wrong` : '', ability.format_errors ? `${ability.format_errors} in the wrong answer format` : '']
      .filter(Boolean).join(' and ');
    const standing = ability.qualified === true ? 'Qualified for short-document reading.' :
      ability.qualified === false ? `Not qualified yet: ${missed.map(c => `${c.label.toLowerCase()} ${c.observed} (needs ${c.name === 'format_errors' ? 'at most ' : ''}${c.required})`).join('; ')}.` : '';
    takeawayEl.textContent = [standing, misses ? `Missed: ${misses}.` : 'Nothing missed in this suite.'].filter(Boolean).join(' ');
  }
  const countNote = document.getElementById('cc-count-note');
  countNote.hidden = !ability?.unscored;
  if (ability?.unscored) {
    countNote.textContent = `Your AI wrote ${ability.total + ability.unscored} responses: ${ability.total} scored questions, plus ${ability.unscored} summaries for you to read that are not scored.`;
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

  // Every answer of this run, persistent until the next result.
  showReplayFor(ability?.suite === 'documents-short' ? ability.run : null);

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

  // Render recipe indicator if present
  const recipeBar = document.getElementById('receipt-recipe-bar');
  if (recipeBar) {
    // The before/after card already offers Restore; the bar covers results shown without one.
    if (ability?.recipe && ability.recipe.preset !== 'standard' && !document.getElementById('improve-comparison').childElementCount) {
      recipeBar.hidden = false;
      const recTitle = ability.recipe.preset === 'concise' ? 'strict format instructions' : ability.recipe.preset;
      document.getElementById('receipt-tested-recipe').textContent = recTitle;
    } else {
      recipeBar.hidden = true;
    }
  }

  // Model transaction rollback bar (J3)
  const rollbackBar = document.getElementById('receipt-model-rollback-bar');
  if (rollbackBar) {
    if (selectionRollbackAvailable && selectionPreviousModel) {
      rollbackBar.hidden = false;
      const curEl = document.getElementById('receipt-current-model');
      // Outside a switch the selection snapshot omits the model; the mission report names it.
      if (curEl) curEl.textContent = currentModelName || commandModelName || 'Current model';
      const prevEl = document.getElementById('receipt-previous-model');
      if (prevEl) prevEl.textContent = selectionPreviousModel;
      const resBtn = document.getElementById('receipt-restore-model');
      if (resBtn) {
        resBtn.onclick = async () => {
          resBtn.disabled = true;
          try {
            const resp = await fetch('/api/models/restore', {
              method: 'POST',
              headers: {'X-Argos-Token': token || ''}
            });
            if (!resp.ok) throw new Error('Restore unavailable');
            await refreshSelection();
            await refreshCommand();
            await refreshModels();
          } catch (_) {
            resBtn.disabled = false;
          }
        };
      }
      const keepBtn = document.getElementById('receipt-keep-model');
      if (keepBtn) {
        keepBtn.onclick = async () => {
          keepBtn.disabled = true;
          try {
            await fetch('/api/models/keep', {
              method: 'POST',
              headers: {'X-Argos-Token': token || ''}
            });
            selectionRollbackAvailable = false;
            rollbackBar.hidden = true;
          } catch (_) {
            keepBtn.disabled = false;
          }
        };
      }
    } else {
      rollbackBar.hidden = true;
    }
  }

  // Action buttons
  const actBox = document.getElementById('receipt-actions');
  actBox.hidden = !ability;
  const useBtn = document.getElementById('receipt-use');
  const secOptions = document.getElementById('receipt-secondary-options');
  const metricsDetails = document.getElementById('receipt-metrics-details');
  const pracBtn = document.getElementById('receipt-practice');
  const upgBtn = document.getElementById('receipt-upgrade');
  const changeBtn = document.getElementById('receipt-change');
  const openRecipeReview = () => {
    const modal = document.getElementById('recipe-modal');
    if (!modal) return;
    const note = document.getElementById('recipe-status-note');
    if (note) note.textContent = '';
    modal.showModal();
  };
  const rerun = () => (ability?.suite === 'documents-short' ? commandActions.documents() : commandActions.baseline());

  const next = nextExperiment(ability);
  renderNextExperiment(next, {format: openRecipeReview, model: () => focusSection('models-title'), repeat: rerun,
    records: () => focusSection('benchmarks-title')});

  useBtn.hidden = ability?.qualified !== true;
  useBtn.onclick = () => {
    const box = document.getElementById('cc-task-box');
    if (box) box.open = true;
    focusSection('cc-task-box', 'cc-question');
  };
  if (secOptions && newReceipt) secOptions.open = false;
  if (metricsDetails && newReceipt) metricsDetails.open = false;
  // The proposed experiment is not repeated among the other choices.
  changeBtn.hidden = next?.kind === 'format';
  changeBtn.disabled = !ability;
  changeBtn.onclick = openRecipeReview;
  pracBtn.hidden = next?.kind === 'repeat';
  pracBtn.onclick = rerun;
  upgBtn.hidden = next?.kind === 'model';
  upgBtn.onclick = () => focusSection('models-title');

  // A debrief is shown only when the local model actually wrote one for these exact runs.
  const debrief = document.getElementById('cc-debrief');
  const ids = [speed?.run, ability?.run];
  const current = lastLabDebrief?.state === 'completed' && lastLabDebrief.runs?.length && lastLabDebrief.runs.every(id => ids.includes(id));
  debrief.hidden = !current;
  document.getElementById('cc-debrief-text').textContent = current ? lastLabDebrief.text : '';
  const facts = (ability?.categories || []).map(c => `${c.label} ${c.correct}/${c.total}`);
  document.getElementById('cc-debrief-facts').textContent = current && ability ?
    `Measured for this run: ${ability.correct} of ${ability.total} correct · ${facts.join(' · ')} · ${ability.format_errors} in the wrong format.` : '';
  document.getElementById('cc-debrief-note').textContent = current ?
    `Written by ${lastLabDebrief.model || 'the selected model'} after scoring. ${lastLabDebrief.label}` : '';
}

function nextExperiment(ability) {
  // Choose from experiments the product can actually run, using only measured evidence.
  // The instruction retest reruns the document trial, so only a document result can be matched.
  if (!ability || ability.suite !== 'documents-short') return null;
  const preset = ability.recipe?.preset || 'standard';
  const plural = (n, one, many) => (n === 1 ? one : many);
  if (preset !== 'standard') {
    if (document.getElementById('improve-comparison')?.childElementCount || decidedExperiments().includes(ability.run)) return null;
    return {kind: 'records', title: 'Compare this run with a standard one',
      why: 'This result used strict format instructions, and there is no matching standard result from this session to compare it with.',
      change: 'Nothing changes. Saved test records let you pair two runs of the same trial.',
      measure: 'A controlled comparison shows before and after for each question.',
      button: 'Open test records'};
  }
  const formatErrors = ability.format_errors || 0;
  const wrong = ability.wrong_answers ?? Math.max(0, ability.total - ability.correct - formatErrors);
  if (formatErrors > 0) {
    return {kind: 'format', title: 'Try strict format instructions',
      why: `${formatErrors} of ${ability.total} scored ${plural(formatErrors, 'answer was', 'answers were')} in the wrong answer format, so ${plural(formatErrors, 'it', 'they')} couldn’t count as correct.`,
      change: 'One lab instruction is added: “Follow the requested output format; omit extra prose.” Same model, same passages, same scoring. Your chat assistant is not changed.',
      measure: 'Your AI reruns the same trial. You compare before and after, then keep the instruction or restore standard.',
      button: 'Review experiment'};
  }
  if (wrong > 0) {
    return {kind: 'model', title: 'Compare a different model',
      why: `${wrong} ${plural(wrong, 'answer was', 'answers were')} wrong and none had format problems. The only instruction experiment targets format problems, so it doesn’t fit this result.`,
      change: 'Pick a candidate model in Models & setup. It runs this same trial, and switching your assistant can be undone.',
      measure: 'Matched results on the same questions show whether the candidate does better here.',
      button: 'Choose a model to compare'};
  }
  return {kind: 'repeat', title: 'Check that it’s consistent',
    why: `All ${ability.total} scored questions were correct this time.`,
    change: 'Nothing. Your AI reruns the same trial unchanged.',
    measure: 'If the result holds, you can trust it more. If it changes, you’ve found variation worth knowing about.',
    button: 'Rerun the same trial unchanged'};
}

function renderNextExperiment(next, actions) {
  const box = document.getElementById('improve-next');
  box.hidden = !next;
  if (!next) return;
  box.dataset.kind = next.kind;
  document.getElementById('improve-next-title').textContent = next.title;
  document.getElementById('improve-why').textContent = next.why;
  document.getElementById('improve-change').textContent = next.change;
  document.getElementById('improve-measure').textContent = next.measure;
  const go = document.getElementById('improve-go');
  go.textContent = next.button;
  go.onclick = actions[next.kind];
}
const replayShort = {answer: 'Fact', quote: 'Quote', not_stated: 'Missing', summary: 'Summary'};
const replayMarks = {pass: '✓', wrong_answer: '✗', format_error: '▲', unscored: '·'};
const replayVerdicts = {pass: 'Correct', wrong_answer: 'Wrong', format_error: 'Not scorable', unscored: 'Not scored'};
const replay = {runId: null, data: null, index: 0, loading: null};
let lastExperiment = null;

function replayMisses() {
  return (replay.data?.items || []).map((item, i) => ['wrong_answer', 'format_error'].includes(item.outcome) ? i : -1).filter(i => i >= 0);
}

function replayChanges() {
  // A before/after comparison marks the answers that changed in this run.
  if (!lastExperiment || lastExperiment.candidate?.id !== replay.runId) return null;
  return new Map((lastExperiment.items || []).filter(row => row.changed).map(row => [row.item_id, row]));
}

async function showReplayFor(runId) {
  const section = document.getElementById('replay');
  if (!runId) { section.hidden = true; replay.runId = null; replay.data = null; return; }
  if (replay.runId === runId && (replay.data || replay.loading)) return;
  replay.runId = runId; replay.data = null;
  const loading = replay.loading = api('/api/benchmarks/replay/' + encodeURIComponent(runId)).catch(() => null);
  const data = await loading;
  if (replay.loading !== loading) return;
  replay.loading = null;
  if (!data || replay.runId !== runId) { section.hidden = true; return; }
  replay.data = data;
  const misses = replayMisses();
  replay.index = misses.length ? misses[0] : 0;
  section.hidden = false;
  renderReplay();
}

function renderReplay() {
  const data = replay.data;
  if (!data) return;
  const run = data.run, changes = replayChanges();
  const misses = replayMisses().length;
  document.getElementById('replay-summary').textContent =
    `${run.correct} of ${run.total} correct · ${misses} ${misses === 1 ? 'miss' : 'misses'} · ${run.unscored} summaries for you` +
    (changes ? ` · ${changes.size} changed in the experiment` : '') + (misses ? '. Start with a miss, or pick any answer.' : '. Pick any answer.');
  const grid = document.getElementById('replay-grid');
  grid.replaceChildren();
  const groups = new Map();
  data.items.forEach((item, i) => {
    if (!groups.has(item.passage_id)) groups.set(item.passage_id, []);
    groups.get(item.passage_id).push([item, i]);
  });
  for (const [passageId, entries] of groups) {
    const row = document.createElement('div');
    row.className = 'replay-row';
    const name = document.createElement('span');
    name.className = 'replay-row-name';
    name.textContent = (passageId || '').replace(/[-_]/g, ' ');
    row.append(name);
    for (const [item, i] of entries) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `replay-chip v-${item.outcome}` + (changes?.has(item.item_id) ? ' changed' : '') + (i === replay.index ? ' selected' : '');
      chip.textContent = `${replayMarks[item.outcome] || '·'} ${replayShort[item.category] || item.category}`;
      chip.setAttribute('aria-label', `${name.textContent}: ${challengeKinds[item.category] || item.category}, ${replayVerdicts[item.outcome] || item.outcome}` +
        (changes?.has(item.item_id) ? ', changed in the experiment' : ''));
      chip.setAttribute('aria-pressed', String(i === replay.index));
      chip.addEventListener('click', () => selectReplay(i, true));
      row.append(chip);
    }
    grid.append(row);
  }
  renderReplayDetail(changes);
}

function renderReplayDetail(changes) {
  const item = replay.data.items[replay.index];
  if (!item) return;
  const passageText = replay.data.passages[item.passage_id] || '';
  const passage = document.getElementById('replay-passage');
  const answer = arenaAnswerPreview(item.output || '');
  // Highlight only a quotation that appears exactly in the passage.
  let quote = '';
  try { quote = JSON.parse(item.output).quote || ''; } catch (_) {}
  const at = quote.length >= 8 ? passageText.indexOf(quote) : -1;
  if (at >= 0) {
    const mark = document.createElement('mark');
    mark.textContent = quote; mark.title = 'The sentence your AI quoted';
    passage.replaceChildren(passageText.slice(0, at), mark, passageText.slice(at + quote.length));
  } else {
    passage.textContent = passageText;
  }
  const position = `${replay.index + 1} of ${replay.data.items.length}`;
  document.getElementById('replay-kind').textContent = `${challengeKinds[item.category] || item.category} · ${position}`;
  document.getElementById('replay-question').textContent = item.question || '';
  document.getElementById('replay-answer').textContent = item.output ? answer : '(empty response)';
  const verdict = document.getElementById('replay-verdict');
  verdict.className = 'replay-verdict v-' + item.outcome;
  verdict.textContent = item.reason;
  const accepted = document.getElementById('replay-accepted');
  accepted.hidden = item.outcome === 'pass' || !item.accepted?.length;
  accepted.textContent = accepted.hidden ? '' : `Accepted answer${item.accepted.length > 1 ? 's' : ''}: ${item.accepted.join(' · ')}`;
  const before = document.getElementById('replay-before');
  const change = changes?.get(item.item_id);
  before.hidden = !change;
  if (change) {
    const label = document.createElement('strong');
    label.textContent = `Before the experiment (${replayVerdicts[change.baseline_outcome] || change.baseline_outcome}): `;
    const text = document.createElement('span');
    text.textContent = arenaAnswerPreview(change.baseline_output || '') || '(empty response)';
    before.replaceChildren(label, text);
  }
  document.getElementById('replay-raw').textContent = item.output || '';
  document.getElementById('replay-prev').disabled = replay.index === 0;
  document.getElementById('replay-next').disabled = replay.index === replay.data.items.length - 1;
  document.getElementById('replay-next-miss').disabled = !replayMisses().length;
}

function selectReplay(index, focus) {
  if (!replay.data) return;
  replay.index = Math.max(0, Math.min(index, replay.data.items.length - 1));
  for (const [i, chip] of document.querySelectorAll('#replay-grid .replay-chip').entries()) {
    chip.classList.toggle('selected', i === replay.index);
    chip.setAttribute('aria-pressed', String(i === replay.index));
  }
  renderReplayDetail(replayChanges());
  if (focus) document.querySelectorAll('#replay-grid .replay-chip')[replay.index]?.focus({preventScroll: true});
}

document.getElementById('replay-prev').addEventListener('click', () => selectReplay(replay.index - 1));
document.getElementById('replay-next').addEventListener('click', () => selectReplay(replay.index + 1));
document.getElementById('replay-next-miss').addEventListener('click', () => {
  const misses = replayMisses();
  if (misses.length) selectReplay(misses.find(i => i > replay.index) ?? misses[0]);
});
document.getElementById('replay').addEventListener('keydown', event => {
  if (event.target.closest('details, pre')) return;
  if (event.key === 'ArrowRight') { event.preventDefault(); selectReplay(replay.index + 1, true); }
  if (event.key === 'ArrowLeft') { event.preventDefault(); selectReplay(replay.index - 1, true); }
});

function decidedExperiments() {
  try { return JSON.parse(localStorage.getItem('argos_decided_experiments') || '[]'); } catch (_) { return []; }
}
function rememberDecided(candidateId) {
  try {
    const ids = decidedExperiments().filter(id => id !== candidateId).concat(candidateId).slice(-50);
    localStorage.setItem('argos_decided_experiments', JSON.stringify(ids));
  } catch (_) {}
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

// Recipe Experiment (J6b) Modal and Restore Controls
document.getElementById('recipe-close')?.addEventListener('click', () => {
  document.getElementById('recipe-modal')?.close();
});
document.getElementById('recipe-run')?.addEventListener('click', async () => {
  document.getElementById('recipe-modal')?.close();
  document.getElementById('lab-start').disabled = true;
  document.getElementById('lab-start-documents').disabled = true;
  document.getElementById('lab-status').textContent = 'Starting document trial with concise recipe…';
  try {
    const res = await fetch('/api/lab/start-documents', {
      method: 'POST',
      headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
      body: JSON.stringify({recipe: 'concise'}),
      cache: 'no-store'
    });
    if (!res.ok) {
      let msg = `Could not start recipe trial (HTTP ${res.status})`;
      try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
      throw new Error(msg);
    }
    await refreshLab();
  } catch (err) {
    document.getElementById('lab-status').textContent = err.message || 'Could not start recipe trial.';
  }
});
document.getElementById('recipe-select-only')?.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/lab/recipe/select', {
      method: 'POST',
      headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
      body: JSON.stringify({preset: 'concise'}),
      cache: 'no-store'
    });
    if (!res.ok) {
      let msg = `Could not select recipe (HTTP ${res.status})`;
      try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
      throw new Error(msg);
    }
    document.getElementById('recipe-modal')?.close();
    await refreshLab();
  } catch (err) {
    const note = document.getElementById('recipe-status-note');
    if (note) note.textContent = err.message || 'Could not select recipe.';
  }
});
async function restoreLabRecipe() {
  const res = await fetch('/api/lab/recipe/restore', {
    method: 'POST',
    headers: {'X-Argos-Token': token || ''},
    cache: 'no-store'
  });
  if (!res.ok) {
    let msg = `Recipe restore unavailable (HTTP ${res.status})`;
    try { const err = await res.json(); if (err?.error) msg = err.error; } catch (_) {}
    throw new Error(msg);
  }
  await refreshLab();
}
const handleRestoreRecipeClick = async () => {
  try {
    await restoreLabRecipe();
  } catch (err) {
    const status = document.getElementById('lab-status');
    if (status) status.textContent = 'Could not restore recipe: ' + err.message;
  }
};
document.getElementById('lab-recipe-restore')?.addEventListener('click', handleRestoreRecipeClick);
document.getElementById('receipt-restore-recipe')?.addEventListener('click', handleRestoreRecipeClick);
