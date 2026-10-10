// Argos Live - Interactive Prototype Controller
(function() {
  'use strict';

  // State Management
  let currentScreen = 'screen-1';
  let streamingInterval = null;
  let elapsedSeconds = 0;
  let elapsedTimer = null;

  // Stream fixture content
  const sampleAnswer = '{"status": "answered", "answer": "35 minutes", "quote": "Crossings take 35 minutes."}';

  function init() {
    setupTabNavigation();
    setupFlowButtons();
    checkUrlParams();
  }

  function setScreen(screenId) {
    currentScreen = screenId;
    document.querySelectorAll('.screen-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === screenId);
    });
    document.querySelectorAll('.prototype-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.target === screenId);
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Handle screen-specific activations
    if (screenId === 'screen-2') {
      startWatchSimulation();
    } else {
      stopWatchSimulation();
    }
  }

  function setupTabNavigation() {
    document.querySelectorAll('.prototype-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        setScreen(btn.dataset.target);
      });
    });
  }

  function setupFlowButtons() {
    // Screen 1: Start Mission -> Screen 2
    const startMissionBtn = document.getElementById('proto-start-mission');
    if (startMissionBtn) {
      startMissionBtn.addEventListener('click', () => {
        setScreen('screen-2');
      });
    }

    // Screen 2: Stop Test / Complete -> Screen 3
    const stopTestBtn = document.getElementById('proto-stop-test');
    if (stopTestBtn) {
      stopTestBtn.addEventListener('click', () => {
        stopWatchSimulation();
        setScreen('screen-3');
      });
    }
    const viewResultBtn = document.getElementById('proto-view-result');
    if (viewResultBtn) {
      viewResultBtn.addEventListener('click', () => {
        setScreen('screen-3');
      });
    }

    // Screen 3: Try Improvement -> Screen 4
    const tryImprovementBtn = document.getElementById('proto-try-improvement');
    if (tryImprovementBtn) {
      tryImprovementBtn.addEventListener('click', () => {
        setScreen('screen-4');
      });
    }
    const tryModelBtn = document.getElementById('proto-try-model');
    if (tryModelBtn) {
      tryModelBtn.addEventListener('click', () => {
        setScreen('screen-5');
      });
    }

    // Screen 4: Keep or Restore
    const keepRecipeBtn = document.getElementById('proto-keep-recipe');
    if (keepRecipeBtn) {
      keepRecipeBtn.addEventListener('click', () => {
        keepRecipeBtn.textContent = '✓ Kept in Lab Recipe';
        keepRecipeBtn.style.background = 'var(--accent-emerald)';
        const note = document.getElementById('proto-decision-note');
        if (note) note.textContent = 'Strict format recipe retained for future Lab trials. Assistant personality remains unchanged.';
      });
    }
    const restoreStandardBtn = document.getElementById('proto-restore-standard');
    if (restoreStandardBtn) {
      restoreStandardBtn.addEventListener('click', () => {
        restoreStandardBtn.textContent = '✓ Restored Standard';
        const note = document.getElementById('proto-decision-note');
        if (note) note.textContent = 'Active Lab recipe reset to Standard calibration.';
      });
    }
    const openStorageFromCompBtn = document.getElementById('proto-open-storage-comp');
    if (openStorageFromCompBtn) {
      openStorageFromCompBtn.addEventListener('click', () => {
        setScreen('screen-5');
      });
    }

    // Screen 5: Storage Choice Simulation
    const selectDataBtn = document.getElementById('proto-select-data-btn');
    const footerConfirmBtn = document.getElementById('proto-footer-confirm-btn');
    const footerStatusText = document.getElementById('proto-footer-status');

    if (selectDataBtn) {
      selectDataBtn.addEventListener('click', () => {
        selectDataBtn.disabled = true;
        selectDataBtn.textContent = 'Running write check…';
        setTimeout(() => {
          selectDataBtn.textContent = '✓ Destination Verified';
          selectDataBtn.style.background = 'var(--accent-emerald)';
          selectDataBtn.style.color = '#ffffff';
          if (footerConfirmBtn) footerConfirmBtn.disabled = false;
          if (footerStatusText) {
            footerStatusText.innerHTML = '<strong>Selected:</strong> /mnt/argos-data/ArgosLive/Models/catalog &middot; Write verified';
            footerStatusText.style.color = 'var(--accent-cyan)';
          }
        }, 600);
      });
    }

    if (footerConfirmBtn) {
      footerConfirmBtn.addEventListener('click', () => {
        footerConfirmBtn.textContent = '✓ Confirmed for Download';
        alert('Model storage confirmed at /mnt/argos-data. Write check passed. You can now download curated models with persistent retention.');
      });
    }
  }

  function startWatchSimulation() {
    stopWatchSimulation();
    const streamContainer = document.getElementById('proto-stream-text');
    if (!streamContainer) return;

    streamContainer.textContent = '';
    let charIndex = 0;
    elapsedSeconds = 0;

    const elapsedEl = document.getElementById('proto-elapsed-val');
    if (elapsedEl) elapsedEl.textContent = '0s';

    elapsedTimer = setInterval(() => {
      elapsedSeconds++;
      if (elapsedEl) elapsedEl.textContent = `${elapsedSeconds}s`;
    }, 1000);

    streamingInterval = setInterval(() => {
      if (charIndex < sampleAnswer.length) {
        streamContainer.textContent += sampleAnswer[charIndex];
        charIndex++;
      } else {
        clearInterval(streamingInterval);
        streamingInterval = null;
        // Show result ready pill
        const viewResultBtn = document.getElementById('proto-view-result');
        if (viewResultBtn) viewResultBtn.hidden = false;
      }
    }, 35);
  }

  function stopWatchSimulation() {
    if (streamingInterval) {
      clearInterval(streamingInterval);
      streamingInterval = null;
    }
    if (elapsedTimer) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }

  function checkUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const screenParam = params.get('screen');
    if (screenParam && ['screen-1', 'screen-2', 'screen-3', 'screen-4', 'screen-5'].includes(screenParam)) {
      setScreen(screenParam);
    }
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
