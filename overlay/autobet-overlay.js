(function () {
  const config = window.AUTOBET_OVERLAY_CONFIG || {};
  const stateUrl = config.stateUrl;
  if (!stateUrl) return;

  const overlay = document.getElementById("overlay");
  const question = document.getElementById("bet-question");
  const timer = document.getElementById("bet-timer");
  const closed = document.getElementById("bet-closed");
  const leftTitle = document.getElementById("left-title");
  const rightTitle = document.getElementById("right-title");
  const leftFill = document.getElementById("left-fill");
  const rightFill = document.getElementById("right-fill");
  const leftPoints = document.getElementById("left-points");
  const rightPoints = document.getElementById("right-points");
  const leftChance = document.getElementById("left-chance");
  const rightChance = document.getElementById("right-chance");
  const bottomRow = document.querySelector(".bet-bottom-row");
  const leftTopName = document.getElementById("left-top-name");
  const rightTopName = document.getElementById("right-top-name");
  const leftTopCard = document.querySelector(".bet-top-card-left");
  const rightTopCard = document.querySelector(".bet-top-card-right");
  const leftChanceCard = document.querySelector(".bet-chance-left");
  const rightChanceCard = document.querySelector(".bet-chance-right");

  const RESULT_DISPLAY_MS = 10000;

  let activePrediction = null;
  let lastRenderablePrediction = null;
  let recentResult = null;
  let closesAtMs = 0;
  let resultShownAtMs = 0;
  let shownResultKey = "";
  let dismissedResultKey = "";
  let dismissedLockedPredictionId = "";

  function parseDateMs(value) {
    const raw = String(value || "").trim();
    if (!raw) return 0;
    const parsed = Date.parse(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number.isFinite(value) ? value : 0);
  }

  function formatCompact(value) {
    const amount = Number(value || 0);
    if (!Number.isFinite(amount)) return "0";
    if (amount >= 1000000) return `${(amount / 1000000).toFixed(amount >= 10000000 ? 0 : 1)}M`;
    if (amount >= 1000) return `${(amount / 1000).toFixed(amount >= 10000 ? 0 : 1)}K`;
    return formatNumber(amount);
  }

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return "00:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function formatPercent(value) {
    if (!Number.isFinite(value) || value <= 0) return "0%";
    return `${Math.round(value)}%`;
  }

  function showOverlay() {
    overlay.classList.remove("hidden");
  }

  function hideOverlay() {
    overlay.classList.add("hidden");
  }

  function setClosedText(value) {
    closed.textContent = String(value || "СТАВКА ЗАКРЫТА");
  }

  function clearResultEffect() {
    [leftTopCard, rightTopCard, leftChanceCard, rightChanceCard].forEach((node) => {
      if (!node) return;
      node.classList.remove("is-winner", "is-loser");
    });
  }

  function applyResultEffect(result, sourcePrediction) {
    clearResultEffect();

    const prediction = sourcePrediction || lastRenderablePrediction;
    if (!prediction) return;

    const normalizedWinner = String(result?.outcome_title || prediction?.winning_outcome_title || "").trim().toLowerCase();
    if (!normalizedWinner) return;

    const outcomes = Array.isArray(prediction.outcomes) ? prediction.outcomes : [];
    const leftLabel = String(outcomes[0]?.title || prediction?.win_outcome_title || "").trim().toLowerCase();
    const rightLabel = String(outcomes[1]?.title || prediction?.loss_outcome_title || "").trim().toLowerCase();

    if (normalizedWinner && leftLabel && normalizedWinner === leftLabel) {
      leftTopCard?.classList.add("is-winner");
      leftChanceCard?.classList.add("is-winner");
      rightTopCard?.classList.add("is-loser");
      rightChanceCard?.classList.add("is-loser");
      return;
    }

    if (normalizedWinner && rightLabel && normalizedWinner === rightLabel) {
      rightTopCard?.classList.add("is-winner");
      rightChanceCard?.classList.add("is-winner");
      leftTopCard?.classList.add("is-loser");
      leftChanceCard?.classList.add("is-loser");
    }
  }

  function getResultKey(result) {
    return String(result?.prediction_id || result?.id || result?.resolved_at || result?.title || "");
  }

  function renderPrediction(prediction) {
    const outcomes = Array.isArray(prediction?.outcomes) ? prediction.outcomes : [];
    const first = outcomes[0] || {};
    const second = outcomes[1] || {};
    const total = Number(prediction?.total_channel_points || 0);
    const firstPointsValue = Number(first.channel_points || 0);
    const secondPointsValue = Number(second.channel_points || 0);
    const firstPct = total > 0 ? (firstPointsValue / total) * 100 : 0;
    const secondPct = total > 0 ? (secondPointsValue / total) * 100 : 0;
    const leftWidthPct = total > 0 ? Math.max(18, firstPct) : 18;
    const rightWidthPct = total > 0 ? Math.max(18, secondPct) : 18;
    const combinedWidth = leftWidthPct + rightWidthPct;
    const normalizedLeftWidth = combinedWidth > 0 ? (leftWidthPct / combinedWidth) * 100 : 50;
    const normalizedRightWidth = combinedWidth > 0 ? (rightWidthPct / combinedWidth) * 100 : 50;

    question.textContent = prediction?.title || "Ставка";
    leftTitle.textContent = first.title || prediction?.win_outcome_title || "A";
    rightTitle.textContent = second.title || prediction?.loss_outcome_title || "B";

    leftFill.style.width = normalizedLeftWidth > 0 ? "100%" : "0%";
    rightFill.style.width = normalizedRightWidth > 0 ? "100%" : "0%";

    if (bottomRow) {
      bottomRow.style.setProperty("--left-share", `${normalizedLeftWidth}fr`);
      bottomRow.style.setProperty("--right-share", `${normalizedRightWidth}fr`);
    }

    leftPoints.textContent = formatCompact(firstPointsValue);
    rightPoints.textContent = formatCompact(secondPointsValue);
    leftChance.textContent = formatPercent(firstPct);
    rightChance.textContent = formatPercent(secondPct);
    leftTopName.textContent = String(first.top_predictor_display_name || first.top_predictor_login || "--");
    rightTopName.textContent = String(second.top_predictor_display_name || second.top_predictor_login || "--");

    showOverlay();
  }

  function renderClosedResult(result, sourcePrediction) {
    const resultKey = getResultKey(result);
    if (resultKey && resultKey !== shownResultKey) {
      shownResultKey = resultKey;
      resultShownAtMs = Date.now();
    }

    const basePrediction = sourcePrediction || lastRenderablePrediction;
    if (basePrediction && String(basePrediction.id || "") === String(result?.prediction_id || result?.id || "")) {
      renderPrediction(basePrediction);
    } else {
      renderPrediction({
        title: result?.title || "Ставка завершена",
        win_outcome_title: result?.outcome_title || "Победитель",
        loss_outcome_title: "",
        total_channel_points: 1,
        outcomes: [
          {
            title: result?.outcome_title || "Победитель",
            channel_points: 1,
            top_predictor_display_name: "--",
            top_predictor_login: "",
          },
          {
            title: "",
            channel_points: 0,
            top_predictor_display_name: "",
            top_predictor_login: "",
          },
        ],
      });
    }

    timer.classList.add("hidden");
    closed.classList.remove("hidden");
    if (String(result?.status || "").toUpperCase() === "CANCELED") {
      setClosedText("СТАВКА ОТМЕНЕНА");
    } else {
      setClosedText(`ПОБЕДА: ${String(result?.outcome_title || "—").toUpperCase()}`);
    }
    applyResultEffect(result, sourcePrediction);
    showOverlay();
  }

  function clearLiveState() {
    activePrediction = null;
    recentResult = null;
    lastRenderablePrediction = null;
    closesAtMs = 0;
    resultShownAtMs = 0;
    shownResultKey = "";
  }

  function applyPayload(payload) {
    const nextActive = payload && payload.active_prediction ? payload.active_prediction : null;
    const nextRecent = payload && payload.recent_result ? payload.recent_result : null;

    if (nextActive) {
      const predictionStatus = String(nextActive.status || "").toUpperCase();
      const predictionId = String(nextActive.id || "");

      if (["RESOLVED", "CANCELED"].includes(predictionStatus)) {
        dismissedLockedPredictionId = "";
        if (dismissedResultKey && predictionId === dismissedResultKey) {
          clearLiveState();
          hideOverlay();
          return;
        }

        activePrediction = nextActive;
        const winningTitle = String(nextActive.winning_outcome_title || nextRecent?.outcome_title || "");
        const closedResult = {
          id: nextActive.id,
          prediction_id: nextActive.id,
          title: nextActive.title,
          outcome_title: winningTitle,
          status: nextActive.status,
          resolved_at: nextRecent?.resolved_at || "",
        };

        recentResult = closedResult;
        renderClosedResult(closedResult, nextActive);
        return;
      }

      if (predictionId && predictionId !== dismissedResultKey) {
        dismissedResultKey = "";
      }
      if (predictionId && predictionId !== dismissedLockedPredictionId) {
        dismissedLockedPredictionId = "";
      }
      if (dismissedLockedPredictionId && predictionId === dismissedLockedPredictionId) {
        activePrediction = null;
        recentResult = null;
        hideOverlay();
        return;
      }

      activePrediction = nextActive;
      recentResult = nextRecent;
      lastRenderablePrediction = nextActive;
      resultShownAtMs = 0;
      const serverRemainingSeconds = Math.max(0, Number(nextActive.seconds_remaining || 0));
      const closesAtMsFromServerRemaining = serverRemainingSeconds > 0 ? Date.now() + serverRemainingSeconds * 1000 : 0;
      const closesAtMsFromPayload = parseDateMs(nextActive.closes_at);
      const locksAtMs = parseDateMs(nextActive.locks_at);
      closesAtMs = closesAtMsFromServerRemaining || closesAtMsFromPayload || locksAtMs || Date.now();
      renderPrediction(nextActive);
      clearResultEffect();
      return;
    }

    activePrediction = null;

    if (nextRecent) {
      const recentKey = getResultKey(nextRecent);
      if (dismissedResultKey && recentKey === dismissedResultKey) {
        recentResult = null;
        lastRenderablePrediction = null;
        hideOverlay();
        return;
      }
      recentResult = nextRecent;
      renderClosedResult(nextRecent, null);
      return;
    }

    if (recentResult && Date.now() - resultShownAtMs < RESULT_DISPLAY_MS) {
      renderClosedResult(recentResult, null);
      return;
    }

    clearLiveState();
    clearResultEffect();
    hideOverlay();
  }

  function updateStatus() {
    if (activePrediction && !["RESOLVED", "CANCELED"].includes(String(activePrediction.status || "").toUpperCase())) {
      const activeId = String(activePrediction.id || "");
      const remainingMs = Math.max(0, closesAtMs - Date.now());
      clearResultEffect();
      timer.classList.remove("hidden");
      closed.classList.add("hidden");
      timer.textContent = formatTime(Math.ceil(remainingMs / 1000));
      if (remainingMs <= 0) {
        timer.classList.add("hidden");
        closed.classList.remove("hidden");
        setClosedText("СТАВКА ЗАКРЫТА");
        if (activeId && Date.now() - closesAtMs >= RESULT_DISPLAY_MS) {
          dismissedLockedPredictionId = activeId;
          activePrediction = null;
          lastRenderablePrediction = null;
          hideOverlay();
        }
      }
      return;
    }

    if (recentResult) {
      if (Date.now() - resultShownAtMs >= RESULT_DISPLAY_MS) {
        dismissedResultKey = getResultKey(recentResult);
        clearLiveState();
        clearResultEffect();
        hideOverlay();
      }
      return;
    }

    if (!activePrediction) {
      clearResultEffect();
      hideOverlay();
    }
  }

  async function poll() {
    try {
      const response = await fetch(`${stateUrl}?ts=${Date.now()}`, {
        cache: "no-store",
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
        },
      });
      if (!response.ok) return;
      const payload = await response.json();
      applyPayload(payload);
    } catch (_error) {
      // Keep the last visible state on transient errors.
    }
  }

  window.setInterval(updateStatus, 100);
  window.setInterval(poll, 1000);
  poll();
})();
