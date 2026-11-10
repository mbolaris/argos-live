// Proctor match view: one round you can follow live, then replay and compare.
// Loaded after app.js; uses its api() and renderProctorLiveEvaluation(). Everything
// shown here is already-sanitized watch data or a saved-run projection. Verdicts are
// the saved ones; nothing in this file scores or decides.
(function () {
  const $ = id => document.getElementById(id);
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const REASONS = {
    pass: 'Counted correct by the fixed scorer for this question.',
    wrong_answer: 'Readable reply, but not what the fixed scorer accepts. The answer key stays hidden.',
    format_error: 'Not in the required answer format, so it counts as a miss.',
    unscored: 'Recorded without a score.'};
  const NOT_COMPARABLE = {
    'no-baseline': 'No earlier complete round of this exact test is saved, so there is nothing to compare yet. This round can serve as the baseline next time.',
    'incomplete-round': 'This round did not finish, so it is not compared with anything.',
    'different-test-version': 'The saved baseline used a different test version.',
    'different-questions': 'The saved baseline asked different questions.',
    'same-run': 'This is the baseline run itself.'};
  const ACTIONS = {start: 'Start', 'retry-recovery': 'Retry recovery', 'ssh-recovery-approval': 'SSH recovery approval'};
  const state = {live: null, connected: true, lostAt: null, reconnectedUntil: 0, matches: new Map(),
    pending: new Map(), failed: new Map(), replay: null, tick: null, lastPoll: 0, revealed: null, recentLoaded: 0};

  const short = id => (typeof id === 'string' ? id.slice(0, 8) : '?');
  const clock = seconds => {
    const whole = Math.max(0, Math.floor(seconds || 0));
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
  };
  const secondsText = value => Number.isFinite(value) ? `${value.toFixed(value < 10 ? 2 : 1)} s` : 'not recorded';
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function runLink(id, label) {
    const link = el('a', 'proctor-match-run-link', label || `run ${short(id)}`);
    link.href = `#replay=${id}`;
    link.title = `Saved run ${id}`;
    return link;
  }

  async function loadMatch(runId) {
    if (state.matches.has(runId)) return state.matches.get(runId);
    if (!state.pending.has(runId)) {
      state.pending.set(runId, api(`/api/proctor-match/run/${runId}`).then(value => {
        state.matches.set(runId, value);
        return value;
      }).finally(() => state.pending.delete(runId)));
    }
    return state.pending.get(runId);
  }

  // ---- shared pieces -------------------------------------------------------
  function setStage(stage) {
    for (const item of document.querySelectorAll('#proctor-match-stages li')) {
      const order = ['setup', 'round', 'score', 'compare'];
      const position = order.indexOf(item.dataset.stage), now = order.indexOf(stage);
      item.dataset.state = position < now ? 'done' : position === now ? 'current' : 'pending';
      if (position === now) item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
    }
  }
  function setNotice(kind, text) {
    const node = $('proctor-match-notice');
    if (!node) return;
    node.hidden = !text;
    node.dataset.kind = kind || '';
    if (node.textContent !== (text || '')) node.textContent = text || '';
  }
  function renderPips(total, items, currentId, onPick) {
    const list = $('proctor-match-pips');
    if (!list) return;
    const count = Math.min(Math.max(total || 0, items.length), 100);
    list.hidden = !count;
    list.replaceChildren(...Array.from({length: count}, (_, index) => {
      const item = items[index];
      const pip = el(onPick ? 'button' : 'span', 'proctor-match-pip');
      const kind = item ? (item.outcome === 'pass' ? 'pass' : item.outcome === 'unscored' || !item.outcome ? 'unscored' : 'miss')
        : 'pending';
      pip.dataset.kind = kind;
      if (item && item.item_id === currentId) pip.dataset.current = 'true';
      else if (!item && index === items.length && currentId) pip.dataset.current = 'true';
      pip.title = item ? `${index + 1}. ${item.item_id} · ${kind === 'pass' ? 'correct' : kind === 'miss' ? 'miss' : 'not scored'}`
        : `${index + 1}. not asked yet`;
      if (onPick) {
        pip.type = 'button';
        pip.setAttribute('aria-label', pip.title);
        pip.disabled = !item;
        pip.addEventListener('click', () => onPick(index));
      }
      const wrap = el('li');
      wrap.append(pip);
      return wrap;
    }));
  }
  function setReason(text) {
    const node = $('proctor-match-reason');
    if (!node) return;
    node.hidden = !text;
    node.textContent = text || '';
  }
  function countUp(node, target, suffix) {
    if (reduceMotion || !Number.isFinite(target) || target <= 0) {
      node.textContent = `${Number.isFinite(target) ? target : '–'}${suffix}`;
      return;
    }
    const started = performance.now(), duration = 900;
    const step = now => {
      const part = Math.min(1, (now - started) / duration);
      node.textContent = `${Math.round(target * part)}${suffix}`;
      if (part < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ---- score reveal and comparison ------------------------------------------
  function ownerSteps(actions) {
    if (!Array.isArray(actions)) return null;
    const box = el('div', 'proctor-match-owner');
    box.append(el('h6', '', 'Your steps'));
    const names = actions.map(action => `${ACTIONS[action.action] || 'Click'} at ${clock(action.at_seconds)}`);
    box.append(el('p', '', `${actions.length} dashboard ${actions.length === 1 ? 'click' : 'clicks'} during this campaign` +
      (names.length ? `: ${names.join(', ')}.` : '.')));
    box.append(el('small', '', 'Counted from clicks this dashboard accepted. Physical steps, SSH sessions and anything typed elsewhere are not observed here.'));
    return box;
  }
  function renderReveal(match, options = {}) {
    const panel = $('proctor-match-reveal');
    if (!panel) return;
    const round = match.round, comparison = match.comparison || {}, decision = match.decision;
    // Polling calls this every few seconds; rebuild only when something changed.
    const key = `${round.run_id}:${options.replay ? 'replay' : 'live'}:${JSON.stringify(options.ownerActions || null)}`;
    if (state.revealed === key && !panel.hidden) return;
    const animate = !(state.revealed || '').startsWith(`${round.run_id}:`);
    state.revealed = key;
    panel.dataset.animate = String(animate);
    panel.hidden = false;
    panel.dataset.state = round.state;
    const parts = [];
    const head = el('div', 'proctor-match-score');
    const label = el('p', 'mission-label', round.state === 'completed' ? 'Round result' :
      round.state === 'cancelled' ? 'Round cancelled' : 'Round failed');
    const big = el('p', 'proctor-match-score-value');
    const total = Number.isFinite(round.scored_total) ? round.scored_total : round.total;
    if (round.state !== 'completed') big.textContent = `${round.completed} of ${round.total} answered`;
    else if (animate) countUp(big, round.correct, ` / ${total}`);
    else big.textContent = `${Number.isFinite(round.correct) ? round.correct : '–'} / ${total}`;
    const detail = el('p', 'proctor-match-score-detail');
    detail.textContent = round.state === 'completed'
      ? `${round.suite || 'fixed test'} · median reply ${secondsText(round.median_latency_seconds)} · ${round.model || 'model not recorded'}`
      : `Stopped after ${round.completed} of ${round.total} questions${round.failure_code ? ` (${round.failure_code})` : ''}` +
        `${Number.isFinite(round.correct) ? `, ${round.correct} of them correct` : ''}. ` +
        'The partial tally is for the record only; an unfinished round is never compared or counted as a result.';
    const saved = el('p', 'proctor-match-saved');
    saved.append('Saved as ', runLink(round.run_id, `run ${round.run_id}`));
    head.append(label, big, detail, saved);
    parts.push(head);

    const partitions = Object.entries(round.partitions || {});
    if (partitions.length) {
      const split = el('div', 'proctor-match-partitions');
      for (const [name, value] of partitions) {
        const chip = el('div', 'proctor-match-partition');
        chip.dataset.partition = name;
        chip.append(el('strong', '', name === 'heldout' ? 'Held-out questions' : 'Practice questions'),
          el('span', '', `${value.correct} / ${value.total}`));
        const change = comparison.partitions?.[name];
        if (change) chip.append(el('small', '', `baseline ${change.baseline_correct} / ${change.total} · ` +
          `${change.wins} won, ${change.regressions} lost`));
        split.append(chip);
      }
      split.append(el('small', 'proctor-match-fineprint', 'Practice and held-out questions are tallied separately and never merged. Bundled held-out items are an internal transfer signal, not independent validation.'));
      parts.push(split);
    }

    const compare = el('div', 'proctor-match-compare');
    compare.append(el('h6', '', 'What changed against the baseline'));
    if (comparison.comparable) {
      const delta = comparison.correct_delta;
      const line = el('p', 'proctor-match-delta');
      line.dataset.direction = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
      line.append(el('span', 'proctor-match-side', `${comparison.baseline_correct}`), el('span', 'proctor-match-arrow', '→'),
        el('span', 'proctor-match-side', `${comparison.correct}`),
        el('strong', '', delta > 0 ? `+${delta} correct` : delta < 0 ? `${delta} correct` : 'no change in score'));
      compare.append(line);
      const source = el('p', 'proctor-match-fineprint');
      source.append('Baseline: ', runLink(comparison.baseline_id),
        comparison.baseline_source === 'journal' ? ' (the baseline the host journal recorded for this trial)'
          : ' (the latest earlier complete round of this exact test)',
        comparison.same_model ? '' : ' · different model',
        comparison.same_instructions === false ? ' · instructions differed' :
          comparison.same_instructions === true ? ' · same instructions' : '');
      compare.append(source);
      const lists = el('div', 'proctor-match-lists');
      for (const [title, ids, kind] of [['Wins', comparison.wins, 'win'], ['Regressions', comparison.regressions, 'regression']]) {
        const box = el('div', 'proctor-match-list');
        box.dataset.kind = kind;
        box.append(el('strong', '', `${title} · ${ids.length}`));
        if (!ids.length) box.append(el('span', '', kind === 'win' ? 'No question flipped to correct.' : 'No question flipped to a miss.'));
        for (const id of ids) {
          const jump = el('button', 'proctor-match-jump', id);
          jump.type = 'button';
          jump.addEventListener('click', () => startReplay(round.run_id, {itemId: id}));
          box.append(jump);
        }
        lists.append(box);
      }
      compare.append(lists);
      const speed = comparison.median_latency_delta_seconds;
      compare.append(el('p', 'proctor-match-speed', Number.isFinite(speed)
        ? `Median reply time ${secondsText(comparison.baseline_median_latency_seconds)} → ${secondsText(comparison.median_latency_seconds)} ` +
          `(${Math.abs(speed) < 0.05 ? 'about the same' : speed < 0 ? `${Math.abs(speed).toFixed(2)} s faster` : `${speed.toFixed(2)} s slower`}).`
        : 'Reply times were not recorded for both rounds.'));
    } else {
      compare.append(el('p', 'proctor-match-fineprint', NOT_COMPARABLE[comparison.reason] || 'No comparable baseline is saved.'));
    }
    parts.push(compare);

    const verdict = el('div', 'proctor-match-decision');
    verdict.append(el('h6', '', 'Kept or rolled back'));
    if (decision) {
      verdict.dataset.action = decision.action;
      const title = {restore: 'Rolled back by the host keep policy', keep: 'Kept by the host keep policy',
        'adopted-external': 'Outside edit recorded · not a qualified experiment'}[decision.action];
      verdict.append(el('p', 'proctor-match-decision-title', title));
      const runs = Array.isArray(decision.runs) ? decision.runs : [];
      const scoreOf = id => {
        const found = runs.find(run => run.run_id === id);
        return found && Number.isFinite(found.correct) ? `${found.correct}/${found.scored_total}` : 'score unavailable';
      };
      const evidence = el('p', 'proctor-match-evidence');
      evidence.append('Baseline runs: ');
      decision.baseline_ids.forEach((id, index) => evidence.append(index ? ', ' : '', runLink(id), ` ${scoreOf(id)}`));
      evidence.append(' · Trial runs: ');
      if (!decision.candidate_ids.length) evidence.append('none accepted');
      decision.candidate_ids.forEach((id, index) => evidence.append(index ? ', ' : '', runLink(id), ` ${scoreOf(id)}`));
      verdict.append(evidence);
      const rule = [];
      if (Number.isFinite(decision.required_correct_delta)) rule.push(`The preset bar for this test is +${decision.required_correct_delta} correct on repeated runs.`);
      if (decision.action === 'restore') rule.push('The trial did not clear it, so the earlier instructions were restored.');
      if (decision.rejected_evidence_code) rule.push(`Evidence not accepted: ${decision.rejected_evidence_code}.`);
      rule.push(decision.independent_gain_verified ? 'Independent gain verified.' : 'No independent gain is claimed.');
      verdict.append(el('p', 'proctor-match-fineprint', rule.join(' ')));
    } else {
      verdict.append(el('p', 'proctor-match-fineprint', 'The host journal has no instruction or model experiment that names this run, so nothing was kept or rolled back on its account.'));
    }
    parts.push(verdict);
    const steps = ownerSteps(options.ownerActions);
    if (steps) parts.push(steps);
    if (!options.replay) {
      const again = el('button', 'proctor-match-replay-button', 'Watch the replay');
      again.type = 'button';
      again.addEventListener('click', () => startReplay(round.run_id));
      parts.push(again);
    }
    panel.replaceChildren(...parts);
  }
  function hideReveal() {
    const panel = $('proctor-match-reveal');
    if (panel) { panel.hidden = true; panel.replaceChildren(); }
    state.revealed = null;
  }

  // ---- live ----------------------------------------------------------------
  function liveRun(progress) {
    const runs = Array.isArray(progress?.evaluation_runs) ? progress.evaluation_runs : [];
    return runs.find(run => run.run_id === progress?.current?.run_id) || runs.at(-1) || null;
  }
  function savedStep(progress, runId) {
    return (progress?.campaign_steps || []).find(step => step.result_id === runId) || null;
  }
  function renderLive() {
    const data = state.live;
    if (!data || state.replay) return;
    const progress = data.progress, watch = data.watch, current = progress?.current;
    renderProctorLiveEvaluation(progress);
    const panel = $('proctor-live-evaluation');
    const showing = panel && !panel.hidden;
    const run = liveRun(progress);
    const finishedStep = run ? savedStep(progress, run.run_id) : null;
    const roundDone = Boolean(run && (finishedStep || (run.total && run.completed === run.total && current?.state !== 'thinking')));
    $('proctor-match-controls').hidden = true;
    $('proctor-match-mode').textContent = data.active ? 'LIVE' : 'FINAL';
    $('proctor-match-mode').dataset.mode = data.active ? 'live' : 'final';
    $('proctor-match-run').textContent = watch ? `watch ${short(watch.id)}${run ? ` · run ${short(run.run_id)}` : ''}` : '';
    $('proctor-match-run').title = watch ? `Campaign watch ${watch.id}${run ? ` · evaluation run ${run.run_id}` : ''}` : '';
    renderPips(run?.total, run?.items || [], current?.state === 'thinking' ? current.item_id : null, null);
    setReason(current?.state === 'scored' ? REASONS[current.outcome] : '');
    if (current?.state === 'thinking' && typeof current.answer_partial === 'string' && current.answer_partial) {
      $('proctor-live-answer').textContent = current.answer_partial;
      $('proctor-live-status').textContent = 'Argos’s visible answer is arriving…';
    }
    $('proctor-live-answer').dataset.pending = String(current?.state === 'thinking' && !current.answer_partial);
    let stage = 'setup';
    if (run && !roundDone) stage = 'round';
    else if (roundDone) stage = state.matches.get(run.run_id)?.round.state === 'completed' ? 'compare' : 'score';
    setStage(stage);
    if (!data.active && showing) $('proctor-live-title').textContent = !run ? 'Campaign finished · no round was run'
      : stage === 'compare' ? 'Round finished · result and comparison below' : 'Round stopped before it finished';
    if (roundDone) {
      // The saved run exists once its step reports a result ID (or the campaign has ended).
      // Ask then, and after a miss wait a while before asking again.
      const retryAt = state.failed.get(run.run_id) || 0;
      if (state.matches.has(run.run_id)) renderReveal(state.matches.get(run.run_id), {ownerActions: watch?.owner_actions});
      else if ((finishedStep || !data.active) && Date.now() >= retryAt) {
        loadMatch(run.run_id).then(renderLive).catch(() => state.failed.set(run.run_id, Date.now() + 10000));
      }
    } else hideReveal();

    let notice = '', kind = '';
    if (!state.connected) {
      kind = 'offline';
      notice = `Lost contact with the dashboard ${clock((Date.now() - state.lostAt) / 1000)} ago. Retrying every few seconds. ` +
        'A campaign in progress keeps running; this page rejoins the same run when the dashboard answers.';
    } else if (data.phase === 'recovery-failed') {
      kind = 'failed';
      notice = 'The campaign stopped and Argos did not come back. Other work stays blocked until recovery succeeds. Use “Retry Argos recovery”.';
    } else if (data.phase === 'failed') {
      kind = 'failed';
      notice = `The campaign stopped${data.failure_code ? ` (${data.failure_code})` : ''}. Argos is back at its verified model. Nothing from this campaign counts as a result.`;
    } else if (finishedStep && ['cancelled', 'failed'].includes(finishedStep.run_state)) {
      kind = 'failed';
      notice = `This round was ${finishedStep.run_state} before it finished. It is saved for the record and is not compared or counted.`;
    } else if (current?.state === 'interrupted') {
      kind = 'failed';
      notice = 'The round ended while a question was still open. That question has no answer or score.';
    } else if (watch?.stall === 'slow-answer') {
      kind = 'stall';
      notice = `This answer is taking longer than usual (over ${clock(watch.slow_answer_seconds)}). The page is still connected; the host’s own time limit decides what happens to the question.`;
    } else if (watch?.stall === 'quiet') {
      kind = 'stall';
      notice = `No new event for ${clock(watch.seconds_since_event)}. Argos can be quiet while it works between questions; the host stops the turn at its own limit.`;
    } else if (Date.now() < state.reconnectedUntil && watch) {
      kind = 'ok';
      notice = `Reconnected to the same run (watch ${short(watch.id)}).`;
    } else if (data.active && stage === 'setup') {
      kind = 'info';
      notice = ({pausing: 'Setup: pausing everyday chat so Argos can focus.', restarting: 'Wrapping up: restarting Argos and checking that its model replies.'})[data.phase] ||
        'Setup: Argos is reading its instructions and journal before the first question.';
    } else if (data.active && data.phase === 'restarting') {
      kind = 'info';
      notice = 'Wrapping up: restarting Argos and checking that its model replies.';
    } else if (data.active && watch && !watch.answer_streaming && current?.state === 'thinking') {
      kind = 'info';
      notice = 'This runtime returns each answer when the turn finishes, so the answer appears all at once. The clock is live.';
    }
    setNotice(kind, showing || !state.connected ? notice : '');
    state.lastPoll = performance.now();
    tickClock();
  }
  function tickClock() {
    const node = $('proctor-match-clock');
    if (!node) return;
    if (state.replay) return;
    const data = state.live;
    if (!data) return;
    const drift = data.active && state.connected ? (performance.now() - state.lastPoll) / 1000 : 0;
    const current = data.progress?.current;
    const question = current?.state === 'thinking' ? (data.progress.current_elapsed_seconds || 0) + drift : null;
    const total = Number.isFinite(data.elapsed_seconds) ? data.elapsed_seconds + drift : null;
    node.textContent = question !== null ? clock(question) : total !== null ? clock(total) : '0:00';
    $('proctor-match-clock-label').textContent = question !== null ? 'on this question'
      : data.active ? 'campaign time' : 'total time';
    $('proctor-match-total').textContent = question !== null && total !== null ? `campaign ${clock(total)}` : '';
    const time = $('proctor-live-time');
    if (time && question !== null) time.textContent = `Thinking · ${Math.floor(question)} s`;
  }

  // ---- replay ----------------------------------------------------------------
  function replayProgress() {
    const replay = state.replay, round = replay.match.round;
    const item = round.items[replay.index];
    const shown = round.items.slice(0, replay.index + (replay.phase === 'scored' ? 1 : 0));
    const base = {run_id: round.run_id, total: round.items.length, completed: shown.length, items: shown,
      round_number: 1, suite: round.suite ? round.suite.replace(/^openclaw-/, '') : null,
      suite_version: round.suite_version, model: round.model};
    return {phase: 'campaign', stage: replay.phase === 'scored' ? 'evaluation-scored' : 'evaluation-question',
      evaluation_runs: [base], campaign_steps: [],
      current: item ? {...item, run_id: round.run_id, state: replay.phase === 'scored' ? 'scored' : 'thinking'} : null,
      current_elapsed_seconds: replay.shownSeconds || 0};
  }
  function renderReplay() {
    const replay = state.replay;
    if (!replay) return;
    const round = replay.match.round, item = round.items[replay.index];
    renderProctorLiveEvaluation(replayProgress());
    $('proctor-live-evaluation').hidden = false;
    $('proctor-live-title').textContent = `Replay · ${round.suite || 'saved round'}`;
    $('proctor-match-mode').textContent = 'REPLAY';
    $('proctor-match-mode').dataset.mode = 'replay';
    $('proctor-match-run').textContent = `run ${short(round.run_id)}`;
    $('proctor-match-run').title = `Saved run ${round.run_id}`;
    $('proctor-match-controls').hidden = false;
    $('proctor-match-play').textContent = replay.playing ? 'Pause' : replay.ended ? 'Play again' : 'Play';
    $('proctor-match-position').textContent = round.items.length
      ? `Question ${Math.min(replay.index + 1, round.items.length)} of ${round.items.length}` : 'No questions saved';
    $('proctor-match-live-return').hidden = !(state.live?.active);
    renderPips(round.items.length, round.items.slice(0, replay.index + 1).map((entry, index) =>
      index === replay.index && replay.phase !== 'scored' ? null : entry).filter(Boolean),
      replay.phase !== 'scored' && item ? item.item_id : null, index => seek(index));
    // In a replay every question is reachable, including ones not played yet.
    for (const [index, pip] of [...document.querySelectorAll('#proctor-match-pips button')].entries()) {
      pip.disabled = index >= round.items.length;
      if (index === replay.index) pip.dataset.current = 'true';
    }
    setReason(replay.phase === 'scored' && item ? item.reason : '');
    if (item && replay.phase !== 'scored') {
      $('proctor-live-status').textContent = 'Replay: Argos was working on this one…';
      $('proctor-live-answer').textContent = 'The recorded answer appears when the recorded reply time is up.';
    }
    $('proctor-live-answer').dataset.pending = String(Boolean(item) && replay.phase !== 'scored');
    $('proctor-match-clock').textContent = clock(replay.shownSeconds || 0);
    $('proctor-match-clock-label').textContent = 'recorded reply time';
    $('proctor-match-total').textContent = replay.playing ? `${replay.speed}× speed` : 'paused';
    const time = $('proctor-live-time');
    if (time && item && replay.phase !== 'scored') time.textContent = `Thinking · ${Math.floor(replay.shownSeconds || 0)} s`;
    const stopped = round.state !== 'completed';
    setNotice(stopped ? 'failed' : round.questions_available ? '' : 'info',
      stopped ? `This saved round was ${round.state}${round.failure_code ? ` (${round.failure_code})` : ''} after ${round.completed} of ${round.total} questions. It is kept for the record and is not compared or counted.`
        : round.questions_available ? '' : 'The question text for this older test version is not bundled with this build, so only the saved answers and verdicts are shown.');
    if (replay.ended || !round.items.length) {
      setStage(round.state === 'completed' ? 'compare' : 'score');
      renderReveal(replay.match, {replay: true, ownerActions: replay.ownerActions});
    } else {
      setStage('round');
      hideReveal();
    }
  }
  function stopTimer() {
    if (state.replay?.timer) { clearTimeout(state.replay.timer); state.replay.timer = null; }
  }
  function schedule() {
    const replay = state.replay;
    stopTimer();
    if (!replay || !replay.playing || replay.ended) return;
    const item = replay.match.round.items[replay.index];
    if (!item) { replay.ended = true; replay.playing = false; renderReplay(); return; }
    if (replay.phase === 'scored') {
      replay.timer = setTimeout(() => {
        if (replay.index + 1 >= replay.match.round.items.length) { replay.ended = true; replay.playing = false; }
        else { replay.index += 1; replay.phase = 'thinking'; replay.shownSeconds = 0; }
        renderReplay(); schedule();
      }, 2200 / replay.speed);
      return;
    }
    // Long recorded waits are compressed; the clock still lands on the recorded time.
    const recorded = Number.isFinite(item.latency_seconds) ? item.latency_seconds : 0;
    const wall = Math.min(Math.max(recorded, 0.6), 5) * 1000 / replay.speed;
    const started = performance.now();
    const step = () => {
      const part = Math.min(1, (performance.now() - started) / wall);
      replay.shownSeconds = recorded * part;
      if (part >= 1) { replay.phase = 'scored'; replay.shownSeconds = recorded; renderReplay(); schedule(); return; }
      $('proctor-match-clock').textContent = clock(replay.shownSeconds);
      const time = $('proctor-live-time');
      if (time) time.textContent = `Thinking · ${Math.floor(replay.shownSeconds)} s`;
      replay.timer = setTimeout(step, 100);
    };
    step();
  }
  function seek(index) {
    const replay = state.replay;
    if (!replay) return;
    const count = replay.match.round.items.length;
    if (!count) return;
    stopTimer();
    replay.index = Math.max(0, Math.min(count - 1, index));
    replay.phase = 'scored';
    replay.playing = false;
    replay.ended = false;
    replay.shownSeconds = replay.match.round.items[replay.index].latency_seconds || 0;
    renderReplay();
  }
  async function startReplay(runId, options = {}) {
    try {
      const match = await loadMatch(runId);
      stopTimer();
      const workbench = $('workbench');
      if (workbench) workbench.open = true;
      $('proctor-campaign-card').hidden = false;
      state.replay = {match, index: 0, phase: 'thinking', playing: true, ended: false, speed: 1, shownSeconds: 0,
        timer: null, ownerActions: options.ownerActions};
      $('proctor-match-speed').value = '1';
      if (window.location.hash !== `#replay=${runId}`) history.replaceState(null, '', `${window.location.search}#replay=${runId}`);
      if (options.itemId) {
        const index = match.round.items.findIndex(item => item.item_id === options.itemId);
        if (index >= 0) { seek(index); $('proctor-live-evaluation').scrollIntoView({block: 'start'}); return; }
      }
      if (options.showResult) { state.replay.ended = true; state.replay.playing = false; state.replay.index = Math.max(0, match.round.items.length - 1); state.replay.phase = 'scored'; }
      renderReplay();
      schedule();
      $('proctor-live-evaluation').scrollIntoView({block: 'start'});
    } catch (error) {
      setPickerStatus(error.message || 'That saved round is unavailable.');
    }
  }
  function closeReplay() {
    stopTimer();
    state.replay = null;
    history.replaceState(null, '', window.location.search);
    hideReveal();
    setNotice('', '');
    $('proctor-match-controls').hidden = true;
    if (state.live) renderLive();
    else $('proctor-live-evaluation').hidden = true;
  }

  // ---- saved campaigns and the picker ----------------------------------------
  function setPickerStatus(text) {
    const node = $('proctor-match-picker-status');
    if (node) node.textContent = text || '';
  }
  async function showCampaign(id) {
    try {
      const record = await api(`/api/proctor-match/campaign/${id}`);
      const lastRound = (record.rounds || []).at(-1);
      if (lastRound?.run_id) {
        try {
          await loadMatch(lastRound.run_id);
          await startReplay(lastRound.run_id, {ownerActions: record.owner_actions, showResult: true});
          return;
        } catch (_) { /* fall through to the campaign summary */ }
      }
      stopTimer();
      state.replay = null;
      const panel = $('proctor-match-reveal');
      $('proctor-live-evaluation').hidden = false;
      for (const part of ['proctor-match-pips', 'proctor-match-controls']) $(part).hidden = true;
      $('proctor-live-title').textContent = 'Saved campaign · no round to replay';
      $('proctor-match-mode').textContent = 'SAVED';
      $('proctor-match-mode').dataset.mode = 'replay';
      $('proctor-match-run').textContent = `watch ${short(record.id)}`;
      $('proctor-match-clock').textContent = clock(record.elapsed_seconds);
      $('proctor-match-clock-label').textContent = 'total time';
      $('proctor-match-total').textContent = '';
      setStage('setup');
      setNotice('failed', `This campaign ended as “${record.phase}”${record.failure_code ? ` (${record.failure_code})` : ''} ` +
        `after ${clock(record.elapsed_seconds)} without a saved round. Nothing from it counts as a result.`);
      const parts = [];
      if (record.interrupted?.question) {
        const open = el('div', 'proctor-match-compare');
        open.append(el('h6', '', 'Question that was open when it stopped'), el('p', '', record.interrupted.question));
        parts.push(open);
      }
      const steps = ownerSteps(record.owner_actions);
      if (steps) parts.push(steps);
      panel.hidden = false;
      panel.dataset.state = 'failed';
      panel.replaceChildren(...parts);
    } catch (error) {
      setPickerStatus(error.message || 'That saved campaign is unavailable.');
    }
  }
  async function refreshPicker(force) {
    const select = $('proctor-match-picker');
    if (!select || (!force && Date.now() - state.recentLoaded < 15000)) return;
    state.recentLoaded = Date.now();
    try {
      const value = await api('/api/proctor-match/recent');
      const chosen = select.value;
      const options = [new Option('Choose a saved round or campaign…', '')];
      const rounds = el('optgroup');
      rounds.label = 'Saved rounds';
      for (const round of value.rounds || []) {
        const when = round.created ? new Date(round.created).toLocaleString() : 'time unknown';
        const score = round.state === 'completed' ? `${round.correct}/${round.scored_total}` : round.state;
        rounds.append(new Option(`${when} · ${round.suite || 'test'} · ${score} · ${short(round.run_id)}`, `run:${round.run_id}`));
      }
      const campaigns = el('optgroup');
      campaigns.label = 'Campaigns watched here';
      for (const campaign of value.campaigns || []) {
        const when = campaign.finished_at ? new Date(campaign.finished_at).toLocaleString() : 'time unknown';
        campaigns.append(new Option(`${when} · ${campaign.phase}${campaign.failure_code ? ` (${campaign.failure_code})` : ''} · ` +
          `${(campaign.rounds || []).length} round${(campaign.rounds || []).length === 1 ? '' : 's'} · ${short(campaign.id)}`, `campaign:${campaign.id}`));
      }
      select.replaceChildren(...options, ...(rounds.children.length ? [rounds] : []), ...(campaigns.children.length ? [campaigns] : []));
      if ([...select.options].some(option => option.value === chosen)) select.value = chosen;
      $('proctor-match-replays').hidden = !(rounds.children.length || campaigns.children.length);
    } catch (_) { /* the picker simply stays as it was */ }
  }

  // ---- wiring ---------------------------------------------------------------
  window.proctorMatch = {
    onLive(data) {
      const wasOffline = !state.connected;
      const finishedNow = state.live?.active && !data.active;
      state.connected = true;
      if (wasOffline) state.reconnectedUntil = Date.now() + 8000;
      state.live = data;
      if (state.replay) {
        $('proctor-match-live-return').hidden = !data.active;
        state.lastPoll = performance.now();
      } else renderLive();
      refreshPicker(finishedNow);
    },
    onDisconnect() {
      if (state.connected) { state.connected = false; state.lostAt = Date.now(); }
      if (!state.replay && state.live) renderLive();
    },
    startReplay, closeReplay,
  };
  function fromHash() {
    const found = /^#replay=([a-f0-9]{32})$/.exec(window.location.hash);
    if (found && state.replay?.match.round.run_id !== found[1]) startReplay(found[1]);
  }
  $('proctor-match-play')?.addEventListener('click', () => {
    const replay = state.replay;
    if (!replay) return;
    if (replay.ended) { replay.ended = false; replay.index = 0; replay.phase = 'thinking'; replay.shownSeconds = 0; replay.playing = true; }
    else replay.playing = !replay.playing;
    if (!replay.playing) stopTimer();
    renderReplay();
    schedule();
  });
  $('proctor-match-prev')?.addEventListener('click', () => state.replay && seek(state.replay.index - 1));
  $('proctor-match-next')?.addEventListener('click', () => state.replay && seek(state.replay.index + (state.replay.phase === 'scored' ? 1 : 0)));
  $('proctor-match-result')?.addEventListener('click', () => {
    const replay = state.replay;
    if (!replay) return;
    stopTimer();
    replay.index = Math.max(0, replay.match.round.items.length - 1);
    replay.phase = 'scored'; replay.playing = false; replay.ended = true;
    renderReplay();
  });
  $('proctor-match-speed')?.addEventListener('change', event => {
    if (!state.replay) return;
    state.replay.speed = Number(event.target.value) || 1;
    renderReplay();
    schedule();
  });
  $('proctor-match-close')?.addEventListener('click', closeReplay);
  $('proctor-match-live-return')?.addEventListener('click', closeReplay);
  $('proctor-match-open')?.addEventListener('click', () => {
    const [kind, id] = ($('proctor-match-picker').value || '').split(':');
    setPickerStatus('');
    if (kind === 'run') startReplay(id);
    else if (kind === 'campaign') showCampaign(id);
    else setPickerStatus('Choose a saved round or campaign first.');
  });
  window.addEventListener('hashchange', fromHash);
  setInterval(tickClock, 250);
  refreshPicker(true);
  fromHash();
})();
