const categoryEl = document.getElementById('category');
const hintEl = document.getElementById('hint');
const answerEl = document.getElementById('masked-answer');
const timerEl = document.getElementById('timer');
const topListEl = document.getElementById('top-list');
const topPanelEl = document.getElementById('top-panel');
const winToastEl = document.getElementById('win-toast');
const overlayEl = document.querySelector('.overlay');
const overlayConfig = window.OVERLAY_CONFIG || {};
const isObsBrowser = Boolean(window.obsstudio) || /OBS|CEF/i.test(navigator.userAgent);
const pollIntervalMs = isObsBrowser ? 3000 : 15000;
const reconnectDelayMs = isObsBrowser ? 1000 : 2000;

let latestState = null;
let timerIntervalId = null;
let pollIntervalId = null;
let pingIntervalId = null;
let socketConnected = false;

function isPassiveResultVisible(state) {
  if (!state || !state.passive_mode || state.is_active) return false;
  return Number(state.passive_result_seconds_left || 0) > 0;
}

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60).toString().padStart(2, '0');
  const secs = (seconds % 60).toString().padStart(2, '0');
  return `${mins}:${secs}`;
}

function renderTop(players) {
  if (!players || players.length === 0) {
    if (topPanelEl) topPanelEl.classList.add('hidden');
    topListEl.innerHTML = '';
    return;
  }
  if (topPanelEl) topPanelEl.classList.remove('hidden');
  topListEl.innerHTML = players
    .map(
      (item) => `
        <div class="top-item">
          <span class="name">${item.username}</span>
          <span class="points">${item.points}</span>
        </div>
      `
    )
    .join('');
}

function renderTimer(state) {
  if (!state) {
    timerEl.textContent = '00:00';
    return;
  }

  if (state.paused) {
    timerEl.textContent = 'Пауза';
    return;
  }

  if (state.passive_mode && !state.is_active) {
    timerEl.textContent = '';
    return;
  }

  if (!state.is_active && state.last_winner) {
    const seconds = Math.max(0, state.next_round_in || 0);
    timerEl.textContent = `До нового раунда ${formatTime(seconds)}`;
    return;
  }

  timerEl.textContent = formatTime(Math.max(0, state.seconds_left || 0));
}

function startLocalTimer() {
  if (timerIntervalId) return;

  timerIntervalId = setInterval(() => {
    if (!latestState || latestState.paused) {
      renderTimer(latestState);
      return;
    }

    if (latestState.passive_mode && !latestState.is_active) {
      if (!isPassiveResultVisible(latestState)) {
        if (overlayEl) overlayEl.classList.add('hidden');
        hideWinToast();
        return;
      }
      latestState = {
        ...latestState,
        passive_result_seconds_left: Math.max(0, Number(latestState.passive_result_seconds_left || 0) - 1),
      };
      renderTimer(latestState);
      return;
    }

    if (latestState.is_active) {
      latestState = {
        ...latestState,
        seconds_left: Math.max(0, (latestState.seconds_left || 0) - 1),
      };
    } else if (latestState.last_winner) {
      latestState = {
        ...latestState,
        next_round_in: Math.max(0, (latestState.next_round_in || 0) - 1),
      };
    }

    renderTimer(latestState);
  }, 1000);
}

function applyState(state) {
  latestState = { ...state };
  const isPassive = Boolean(state.passive_mode);
  const showPassiveResult = isPassiveResultVisible(state);
  const shouldHidePassiveOverlay = isPassive && !state.is_active && !showPassiveResult;

  if (overlayEl) {
    overlayEl.classList.toggle('hidden', shouldHidePassiveOverlay);
    overlayEl.classList.toggle('passive-active', isPassive && state.is_active);
  }

  if (shouldHidePassiveOverlay) {
    categoryEl.textContent = '—';
    hintEl.textContent = '';
    answerEl.innerHTML = '';
    timerEl.textContent = '';
    hideWinToast();
    renderTop([]);
    return;
  }

  categoryEl.textContent = state.category || '—';
  hintEl.textContent = state.hint || 'Ожидание раунда…';
  answerEl.innerHTML = renderMaskedAnswer(state.masked_answer || '—');
  renderTimer(latestState);

  if (isPassive) {
    if (showPassiveResult) {
      if (state.last_winner) {
        showWinToast(`Победитель: ${state.last_winner.username} (+${state.last_winner.points})`);
      } else if (state.last_no_winner) {
        showWinToast('Никто не угадал');
      } else {
        hideWinToast();
      }
    } else {
      hideWinToast();
    }
  } else if (!state.is_active) {
    if (state.last_winner) {
      showWinToast(`Победитель: ${state.last_winner.username} (+${state.last_winner.points})`);
    } else if (state.last_no_winner) {
      showWinToast('Никто не угадал');
    } else {
      hideWinToast();
    }
  } else {
    hideWinToast();
  }

  if (isPassive) {
    renderTop([]);
  } else {
    renderTop(state.top_players || []);
  }
}

function renderMaskedAnswer(text) {
  if (!text) return '—';
  const parts = text.split('|').map((part) => `<span class="word">${escapeHtml(part)}</span>`);
  return parts.join('<span class="word-gap"></span>');
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function showWinToast(text) {
  if (!winToastEl) return;
  winToastEl.textContent = text;
  winToastEl.classList.remove('hidden');
}

function hideWinToast() {
  if (!winToastEl) return;
  winToastEl.classList.add('hidden');
}

async function fetchInitialState() {
  const res = await fetch(overlayConfig.stateUrl || '/api/state');
  const data = await res.json();
  applyState(data);
}

async function pollState() {
  try {
    await fetchInitialState();
  } catch (_) {
    // Keep the last known state on screen and retry on the next poll.
  }
}

function ensurePolling() {
  if (pollIntervalId) return;
  pollIntervalId = setInterval(() => {
    if (!isObsBrowser && socketConnected && document.visibilityState === 'visible') {
      return;
    }
    pollState();
  }, pollIntervalMs);
}

function connectSocket() {
  const wsUrl = overlayConfig.wsUrl
    ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${overlayConfig.wsUrl}`
    : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    socketConnected = true;
    ws.send('ping');
    pollState();
    if (pingIntervalId) clearInterval(pingIntervalId);
    pingIntervalId = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 15000);
  };

  ws.onmessage = (event) => {
    applyState(JSON.parse(event.data));
  };

  ws.onclose = () => {
    socketConnected = false;
    if (pingIntervalId) {
      clearInterval(pingIntervalId);
      pingIntervalId = null;
    }
    setTimeout(connectSocket, reconnectDelayMs);
  };
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && (!socketConnected || isObsBrowser)) {
    pollState();
  }
});

fetchInitialState();
startLocalTimer();
ensurePolling();
connectSocket();
