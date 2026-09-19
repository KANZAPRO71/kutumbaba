/**
 * Panel UI — text chat + Gemini Live voice (pipeline sendiri, bukan Retell).
 */

const API = "/api/chat";

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const messages = document.getElementById("messages");
const input = document.getElementById("input");
const charCount = document.getElementById("charCount");
const btnSend = document.getElementById("btnSend");
const btnClose = document.getElementById("btnClose");
const btnCall = document.getElementById("btnCall");
const voiceSelect = document.getElementById("voiceSelect");
const voicePickerList = document.getElementById("voicePickerList");
const bgmSelect = document.getElementById("bgmSelect");
const bgmPickerList = document.getElementById("bgmPickerList");
const btnEndCall = document.getElementById("btnEndCall");
const panel = document.getElementById("panel");
const statusDot = document.getElementById("statusDot");
const modelStatus = document.getElementById("modelStatus");
const textFoot = document.getElementById("textFoot");
const voiceFoot = document.getElementById("voiceFoot");
const voiceStatus = document.getElementById("voiceStatus");
const voiceBars = document.getElementById("voiceBars");
const voiceWaveCanvas = document.getElementById("voiceWaveCanvas");
const voiceModeStrip = document.getElementById("voiceModeStrip");
const voiceTimer = document.getElementById("voiceTimer");
const onboarding = document.getElementById("onboarding");
const btnOnboardingNext = document.getElementById("btnOnboardingNext");
const btnOnboardingSkip = document.getElementById("btnOnboardingSkip");
const onboardingApiKey = document.getElementById("onboardingApiKey");
const onboardingError = document.getElementById("onboardingError");
const onboardingProgress = document.getElementById("onboardingProgress");
const resumeBanner = document.getElementById("resumeBanner");
const resumeBannerText = document.getElementById("resumeBannerText");
const dailyCheckInBanner = document.getElementById("dailyCheckInBanner");
const dailyCheckInText = document.getElementById("dailyCheckInText");
const btnDailyCheckInCall = document.getElementById("btnDailyCheckInCall");
const btnDailyCheckInDismiss = document.getElementById("btnDailyCheckInDismiss");
const DAILY_CHECKIN_DISMISS_KEY = "papua_daily_checkin_dismiss";
const btnResumeYes = document.getElementById("btnResumeYes");
const btnResumeNo = document.getElementById("btnResumeNo");
const ragEnabledToggle = document.getElementById("ragEnabledToggle");
const ragMinScore = document.getElementById("ragMinScore");
const ragMinScoreVal = document.getElementById("ragMinScoreVal");
const ragGeminiToggle = document.getElementById("ragGeminiToggle");
const sessionFeedbackStats = document.getElementById("sessionFeedbackStats");
let lastPostCallSessionId = null;
let prefsSaveTimer = null;
const btnTextToggle = document.getElementById("btnTextToggle");
const textCompose = document.getElementById("textCompose");
const companionStage = document.getElementById("companionStage");
const companionOrbWrap = document.getElementById("companionOrbWrap");
const experienceModeList = document.getElementById("experienceModeList");
const experienceTagline = document.getElementById("experienceTagline");
const heroTagline = document.getElementById("heroTagline");

function syncExperienceTagline(text) {
  const t = text || "";
  if (experienceTagline) experienceTagline.textContent = t;
  if (heroTagline) heroTagline.textContent = t;
}

function syncWaveform(state) {
  if (window.PersonaWaveform?.setVisualState) {
    window.PersonaWaveform.setVisualState(state);
  }
}

function startWaveformViz() {
  if (voiceWaveCanvas && window.PersonaWaveform?.start) {
    window.PersonaWaveform.start(voiceWaveCanvas);
    syncWaveform({ mode: "connecting" });
  }
}

function stopWaveformViz() {
  if (window.PersonaWaveform?.stop) window.PersonaWaveform.stop();
}
const btnSettings = document.getElementById("btnSettings");
const settings = document.getElementById("settings");
const btnSettingsClose = document.getElementById("btnSettingsClose");
const settingsApiKey = document.getElementById("settingsApiKey");
const settingsError = document.getElementById("settingsError");
const settingsKeyStatus = document.getElementById("settingsKeyStatus");
const btnSettingsSave = document.getElementById("btnSettingsSave");
const behaviorDebugDay = document.getElementById("behaviorDebugDay");
const behaviorDebugDetails = document.getElementById("behaviorDebugDetails");
const companionAchievementsWrap = document.getElementById("companionAchievementsWrap");
let behaviorDebugLoaded = false;
const behaviorRecentDecisions = document.getElementById("behaviorRecentDecisions");
const behaviorModeEvalTable = document.getElementById("behaviorModeEvalTable");
const behaviorBdvByModeTable = document.getElementById("behaviorBdvByModeTable");
const behaviorDecisionOutcomesTable = document.getElementById("behaviorDecisionOutcomesTable");
const behaviorMopByTypeTable = document.getElementById("behaviorMopByTypeTable");
const behaviorPlannedHoldTable = document.getElementById("behaviorPlannedHoldTable");
const behaviorPlannedHoldNote = document.getElementById("behaviorPlannedHoldNote");
const behaviorModeHealth = document.getElementById("behaviorModeHealth");
const behaviorSessionDistTable = document.getElementById("behaviorSessionDistTable");
const behaviorExpMode = document.getElementById("behaviorExpMode");
const behaviorExpLever = document.getElementById("behaviorExpLever");
const behaviorExpValues = document.getElementById("behaviorExpValues");
const behaviorExpHypothesis = document.getElementById("behaviorExpHypothesis");
const btnBehaviorExpStart = document.getElementById("btnBehaviorExpStart");
const behaviorExperimentsList = document.getElementById("behaviorExperimentsList");
const behaviorConfigRevision = document.getElementById("behaviorConfigRevision");
const btnBehaviorConfigBump = document.getElementById("btnBehaviorConfigBump");
const btnBehaviorDebugRefresh = document.getElementById("btnBehaviorDebugRefresh");
const BEHAVIOR_MODE_LABELS = {
  nongkrong: "Nongkrong",
  mop: "Mop",
  cerita_tong: "Cerita Tong",
  teman_malam: "Teman Malam",
  teman_jalan: "Teman Jalan",
};
const memoryStats = document.getElementById("memoryStats");
const companionAchievements = document.getElementById("companionAchievements");
const achievementToast = document.getElementById("achievementToast");
const ACHIEVEMENT_UNLOCK_KEY = "papua_achievement_unlocked_ids";
let achievementToastTimer = null;
const memoryReviewList = document.getElementById("memoryReviewList");
const memoryList = document.getElementById("memoryList");
const openLoopList = document.getElementById("openLoopList");
const btnMemoryRefresh = document.getElementById("btnMemoryRefresh");
const btnMemoryExport = document.getElementById("btnMemoryExport");
const btnMemoryReindex = document.getElementById("btnMemoryReindex");
const btnMemoryImport = document.getElementById("btnMemoryImport");
const memoryImportFile = document.getElementById("memoryImportFile");
const RAG_IDLE_REINDEX_KEY = "papua_rag_idle_reindex_ms";
const RAG_IDLE_REINDEX_INTERVAL_MS = 24 * 60 * 60 * 1000;
const btnMemoryClearAll = document.getElementById("btnMemoryClearAll");
const dailyReminderToggle = document.getElementById("dailyReminderToggle");
const btnMemoryAdd = document.getElementById("btnMemoryAdd");
const memoryManualInput = document.getElementById("memoryManualInput");
const memoryAddError = document.getElementById("memoryAddError");
const settingsMopCount = document.getElementById("settingsMopCount");
const settingsMopPreview = document.getElementById("settingsMopPreview");
const settingsKamusCount = document.getElementById("settingsKamusCount");
const settingsKamusPreview = document.getElementById("settingsKamusPreview");
/* PROSODY_SIM_STORAGE_KEY + BGM_STORAGE_KEY — dari live.js (load lebih dulu) */
const simPitch = document.getElementById("simPitch");
const simMopFreq = document.getElementById("simMopFreq");
const simTempoVal = document.getElementById("simTempoVal");
const simPitchVal = document.getElementById("simPitchVal");
const simMopVal = document.getElementById("simMopVal");

const SESSION_STORAGE_KEY = "persona_session_id";
const VOICE_STORAGE_KEY = "persona_live_voice";
/* BGM_STORAGE_KEY — dari live.js (load lebih dulu) */
const BGM_OPTIONS = [
  { value: "off", label: "Mati — tanpa BGM (disarankan untuk voice)" },
  { value: "disko_tanah", label: "Disko Tanah — pelan ala tongkrongan" },
  { value: "hiphop_papua", label: "Hip-Hop Papua — tempo cepat" },
];
let cachedLiveVoices = null;
let cachedDefaultVoice = "Leda";
let cachedPersonaName = "Papua Ai";
const LEGACY_VOICE_ALIASES = { Sulafat: "Leda", Puck: "Leda", Tinus: "Leda" };
const BYOK_STORAGE_KEY = "persona_gemini_api_key";
const ONBOARDING_KEY = "persona_onboarding_v2";
const ONBOARDING_STEPS = 4;
/** Voice-first UI — no chat bubbles; orb stays visible. */
const SHOW_CHAT_TEXT = false;
const RESUME_SKIP_KEY = "persona_resume_skip_id";

function personaLabel() {
  return cachedPersonaName || "Papua Ai";
}

function normalizeSavedVoice(saved, defaultVoice) {
  const fallback = defaultVoice || cachedDefaultVoice || "Leda";
  if (!saved) return fallback;
  return LEGACY_VOICE_ALIASES[saved] || saved;
}

const isEmbeddedApp = new URLSearchParams(location.search).get("app") === "1";

function ensureUiInteractive() {
  if (isEmbeddedApp) {
    if (settings) {
      settings.classList.add("hidden");
      settings.hidden = true;
    }
    if (onboarding) {
      onboarding.classList.add("hidden");
      onboarding.hidden = true;
    }
  }
  if (btnCall && !inCall) btnCall.disabled = false;
  if (btnSettings) btnSettings.disabled = false;
}

window.__personaUnlockUi = () => {
  if (isEmbeddedApp) {
    if (onboarding) {
      onboarding.classList.add("hidden");
      onboarding.hidden = true;
    }
    if (settings) {
      settings.classList.add("hidden");
      settings.hidden = true;
    }
  }
  ensureUiInteractive();
  void refreshAppHealth();
};

/** Called from MainActivity.onPause — stop canvas RAF, save CPU/battery in background. */
window.__personaPauseUi = () => {
  try {
    window.PersonaWaveform?.pause?.();
  } catch {
    /* ignore */
  }
};

/** Called from MainActivity.onResume — resume visualizer if call UI active. */
window.__personaResumeUi = () => {
  try {
    if (inCall) window.PersonaWaveform?.resume?.();
  } catch {
    /* ignore */
  }
};

function loadByokKey() {
  try {
    return localStorage.getItem(BYOK_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function saveByokKey(key) {
  try {
    localStorage.setItem(BYOK_STORAGE_KEY, key.trim());
  } catch {
    /* ignore */
  }
}

async function syncByokKey(key) {
  const trimmed = (key || "").trim();
  if (trimmed.length < 8) return false;
  saveByokKey(trimmed);
  if (window.PersonaAndroid?.setApiKey) {
    window.PersonaAndroid.setApiKey(trimmed);
  }
  try {
    const res = await fetch("/api/byok", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: trimmed }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

function updateCallButtonReady(_ready) {
  if (!btnCall || inCall) return;
  btnCall.disabled = false;
}

async function ensureByokFromStorage() {
  const key = loadByokKey();
  if (key.length >= 8) {
    await syncByokKey(key);
    return true;
  }
  return hasByokKey();
}

function loadSessionIdFromStorage() {
  try {
    const existing = localStorage.getItem(SESSION_STORAGE_KEY);
    if (existing && /^[\w.-]{1,128}$/.test(existing)) return existing;
  } catch {
    /* ignore quota / private mode */
  }
  return "";
}

function persistSessionId(id) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    /* ignore */
  }
}

let sessionId = loadSessionIdFromStorage();
let defaultLanguage = "id-ID";
let busy = false;
let liveCall = null;
let inCall = false;
let endingCall = false;
let ttsAudio = null;
let prosodySimBound = false;

function setCompanionOrbState(state) {
  if (!companionOrbWrap) return;
  companionOrbWrap.classList.remove(
    "state-idle",
    "state-connecting",
    "state-listening",
    "state-speaking"
  );
  companionOrbWrap.classList.add(`state-${state || "idle"}`);
}

function updateCompanionStage() {
  if (!companionStage) return;
  companionStage.classList.remove("hidden");
  companionStage.classList.toggle("in-call", inCall);
  if (!inCall) {
    setCompanionOrbState("idle");
  }
}

function renderUser(text) {
  if (!SHOW_CHAT_TEXT) return;
  const row = document.createElement("div");
  row.className = "msg-row user";
  row.dataset.role = "user";
  row.innerHTML = `<div class="msg-bubble user">${escape(text)}</div>`;
  messages.appendChild(row);
  scrollDown();
}

function renderAssistantText(text, meta) {
  if (!text || !SHOW_CHAT_TEXT) return;
  const row = document.createElement("div");
  row.className = "msg-row";
  row.dataset.role = "assistant";
  if (meta) row.dataset.meta = meta;
  row.innerHTML = `
    <div class="msg-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/></svg></div>
    <div class="msg-bubble assistant">${escape(text)}</div>`;
  messages.appendChild(row);
  scrollDown();
}

function renderGovernance(meta, text) {
  if (!SHOW_CHAT_TEXT) return;
  if (meta === "SILENCE" || meta === "DEFER") {
    const row = document.createElement("div");
    row.className = "msg-system";
    row.textContent = meta === "SILENCE" ? "· diam ·" : "· tunggu ·";
    messages.appendChild(row);
    scrollDown();
    return;
  }
  if (text) renderAssistantText(text, meta);
}

function renderAssistant(payload) {
  if (!payload.text && payload.bdv && (payload.bdv === "SILENCE" || payload.bdv === "DEFER")) {
    renderGovernance(payload.bdv, null);
    return;
  }
  renderAssistantText(payload.text, payload.bdv || "text");
}

function renderSystem(message) {
  if (!message) return;
  if (!SHOW_CHAT_TEXT) {
    if (inCall && voiceStatus) {
      setVoiceStatus(message.slice(0, 80));
    } else {
      showUiToast(message);
    }
    return;
  }
  const row = document.createElement("div");
  row.className = "msg-system";
  row.textContent = message;
  messages.appendChild(row);
  scrollDown();
}

function setPending(active) {
  if (!SHOW_CHAT_TEXT) return;
  let el = document.getElementById("pendingRow");
  if (active && !el) {
    el = document.createElement("div");
    el.className = "msg-row";
    el.id = "pendingRow";
    el.innerHTML = `
      <div class="msg-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/></svg></div>
      <div class="typing"><span></span><span></span><span></span></div>`;
    messages.appendChild(el);
    scrollDown();
  } else if (!active) {
    el?.remove();
  }
}

function scrollDown() {
  messages.scrollTop = messages.scrollHeight;
}

function escape(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

function formatCallTimer(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function setVoiceUi(active) {
  inCall = active;
  textFoot.classList.toggle("hidden", active);
  voiceFoot.classList.toggle("hidden", !active);
  btnCall.classList.toggle("in-call", active);
  const label = btnCall.querySelector(".btn-call-label");
  if (label) label.textContent = active ? "Sedang ngobrol" : "Buka Suara";
  voiceBars.classList.toggle("idle", !active);
  voiceBars.classList.remove("agent-talking", "user-turn");
  if (voiceTimer) voiceTimer.textContent = "0:00";
  if (voiceSelect) voiceSelect.disabled = active;
  voicePickerList?.classList.toggle("is-disabled", active);
  bgmPickerList?.classList.toggle("is-disabled", active);
  if (active) {
    startWaveformViz();
    renderVoiceModeStrip();
  } else {
    stopWaveformViz();
    voiceModeStrip?.classList.add("hidden");
  }
  if (!active) {
    statusDot.classList.remove("call-active");
    setCompanionOrbState("idle");
  }
  updateCompanionStage();
}

/** Post-call hook after voice sessions (memory card UI removed). */
function handlePostCallData(data) {
  if (!data) return;
  lastPostCallSessionId = data.session_id || sessionId || null;
  void syncAchievementsAfterCall();
}

async function finalizeSessionMemory(sid) {
  const id = sid || sessionId;
  if (!id) return null;
  if (
    isEmbeddedApp &&
    typeof PersonaAndroid !== "undefined" &&
    PersonaAndroid.finalizeSessionMemory
  ) {
    try {
      PersonaAndroid.finalizeSessionMemory(id);
    } catch {
      /* ignore */
    }
    return null;
  }
  try {
    const res = await fetch(
      `/api/session/${encodeURIComponent(id)}/extract-memory`,
      { method: "POST", cache: "no-store" }
    );
    if (!res.ok) return null;
    const body = await res.json();
    if (body?.post_call) {
      handlePostCallData({
        session_id: body.session_id,
        ...body.post_call,
        memory_card: body.memory_card,
      });
    }
    void syncAchievementsAfterCall();
    return body?.post_call || null;
  } catch {
    return null;
  }
}

async function fetchPostCallWithRetry(maxAttempts = 8, delayMs = 1500) {
  if (!sessionId) return null;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetch(
        `/api/session/${encodeURIComponent(sessionId)}/post-call`,
        { cache: "no-store" }
      );
      if (!res.ok) continue;
      const body = await res.json();
      if (body?.post_call && Object.keys(body.post_call).length) {
        return {
          session_id: body.session_id,
          ...body.post_call,
          memory_card: body.memory_card,
        };
      }
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return null;
}

function clearMessages() {
  messages.innerHTML = "";
  updateCompanionStage();
}

async function loadSessionHistoryFrom(id) {
  if (!id || !SHOW_CHAT_TEXT) return;
  try {
    const res = await fetch(`/api/session/${encodeURIComponent(id)}`);
    if (!res.ok) return;
    const data = await res.json();
    clearMessages();
    for (const msg of data.messages || []) {
      if (!msg?.text) continue;
      if (msg.role === "user") renderUser(msg.text);
      else renderAssistantText(msg.text, "history");
    }
    if (data.post_call) {
      handlePostCallData(data.post_call);
    }
  } catch {
    /* empty */
  }
}

function dailyCheckInDismissedToday() {
  try {
    return localStorage.getItem(DAILY_CHECKIN_DISMISS_KEY) === new Date().toDateString();
  } catch {
    return false;
  }
}

function syncDailyReminderToggle() {
  if (!dailyReminderToggle) return;
  if (typeof PersonaAndroid !== "undefined" && PersonaAndroid.getDailyRemindersEnabled) {
    try {
      dailyReminderToggle.checked = PersonaAndroid.getDailyRemindersEnabled();
    } catch {
      dailyReminderToggle.checked = true;
    }
  } else {
    dailyReminderToggle.checked = true;
    dailyReminderToggle.disabled = true;
  }
}

function onDailyReminderToggleChange() {
  if (!dailyReminderToggle) return;
  if (typeof PersonaAndroid !== "undefined" && PersonaAndroid.setDailyRemindersEnabled) {
    PersonaAndroid.setDailyRemindersEnabled(Boolean(dailyReminderToggle.checked));
  }
}

function dismissDailyCheckInForToday() {
  try {
    localStorage.setItem(DAILY_CHECKIN_DISMISS_KEY, new Date().toDateString());
  } catch {
    /* ignore */
  }
  dailyCheckInBanner?.classList.add("hidden");
}

async function checkDailyCheckInBanner() {
  if (!dailyCheckInBanner || inCall) return;
  if (dailyCheckInDismissedToday()) return;
  if (resumeBanner && !resumeBanner.classList.contains("hidden")) return;
  try {
    const res = await fetch("/api/companion/check-in", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.show || !data.message) return;
    if (dailyCheckInText) dailyCheckInText.textContent = data.message;
    dailyCheckInBanner.classList.remove("hidden");
  } catch {
    /* ignore */
  }
}

async function checkResumeBanner() {
  if (!resumeBanner || sessionId) return;
  try {
    const res = await fetch("/api/sessions/latest", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const latestId = data.session_id;
    const msgs = data.messages || [];
    if (!latestId || !msgs.length) return;
    let skipId = "";
    try {
      skipId = localStorage.getItem(RESUME_SKIP_KEY) || "";
    } catch {
      /* ignore */
    }
    if (skipId === latestId) return;

    const preview = msgs
      .slice(-2)
      .map((m) => m.text)
      .filter(Boolean)
      .join(" · ");
    resumeBannerText.textContent = preview
      ? `Lanjut obrolan kemarin? "${preview.slice(0, 80)}${preview.length > 80 ? "…" : ""}"`
      : "Lanjut obrolan kemarin?";
    resumeBanner.dataset.sessionId = latestId;
    resumeBanner.classList.remove("hidden");
  } catch {
    /* ignore */
  }
}

function hasByokKey() {
  const key = loadByokKey();
  if (key.length >= 8) return true;
  if (window.PersonaAndroid?.hasApiKey?.()) return true;
  return false;
}

let onboardingStep = 0;

function onboardingStepEls() {
  return onboarding?.querySelectorAll(".onboarding-step") ?? [];
}

function onboardingDotEls() {
  return onboardingProgress?.querySelectorAll(".onboarding-dot") ?? [];
}

function setOnboardingStep(step) {
  onboardingStep = Math.max(0, Math.min(ONBOARDING_STEPS - 1, step));
  onboardingStepEls().forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.step) === onboardingStep);
  });
  onboardingDotEls().forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.step) === onboardingStep);
  });
  btnOnboardingSkip?.classList.toggle("hidden", onboardingStep === ONBOARDING_STEPS - 1);
  if (btnOnboardingNext) {
    if (onboardingStep === ONBOARDING_STEPS - 1) {
      btnOnboardingNext.textContent = hasByokKey() ? "Mulai ngobrol" : "Simpan & mulai";
    } else {
      btnOnboardingNext.textContent = "Lanjutkan";
    }
  }
  onboardingError?.classList.add("hidden");
  if (onboardingStep === ONBOARDING_STEPS - 1 && onboardingApiKey) {
    const existing = loadByokKey();
    if (existing.length >= 8 && !onboardingApiKey.value) {
      onboardingApiKey.value = existing;
    }
    onboardingApiKey.focus();
  }
}

function showOnboardingIfNeeded() {
  if (!onboarding) return;
  if (isEmbeddedApp) {
    dismissOnboarding();
    if (!hasByokKey()) {
      renderSystem("Tap ⚙ Pengaturan → masukkan Gemini API key, lalu tekan Ngobrol.");
    }
    return;
  }
  const needsKey = !hasByokKey();
  try {
    if ((localStorage.getItem(ONBOARDING_KEY) === "1" || hasByokKey()) && !needsKey) return;
  } catch {
    if (hasByokKey() && !needsKey) return;
  }
  setOnboardingStep(needsKey ? ONBOARDING_STEPS - 1 : 0);
  onboarding.classList.remove("hidden");
  onboarding.hidden = false;
}

function dismissOnboarding() {
  try {
    localStorage.setItem(ONBOARDING_KEY, "1");
  } catch {
    /* ignore */
  }
  if (onboarding) {
    onboarding.classList.add("hidden");
    onboarding.hidden = true;
  }
}

async function finishOnboarding() {
  if (onboardingStep < ONBOARDING_STEPS - 1) {
    setOnboardingStep(onboardingStep + 1);
    return;
  }

  const key = (onboardingApiKey?.value || loadByokKey() || "").trim();
  if (key.length < 8) {
    onboardingError?.classList.remove("hidden");
    onboardingApiKey?.focus();
    return;
  }

  if (btnOnboardingNext) {
    btnOnboardingNext.disabled = true;
    btnOnboardingNext.textContent = "Menyimpan…";
  }
  const ok = await syncByokKey(key);
  if (btnOnboardingNext) {
    btnOnboardingNext.disabled = false;
    btnOnboardingNext.textContent = "Simpan & mulai";
  }
  if (!ok) {
    onboardingError?.classList.remove("hidden");
    if (onboardingError) {
      onboardingError.textContent = "Gagal simpan key — coba lagi ko.";
    }
    return;
  }
  dismissOnboarding();
  updateCallButtonReady(true);
  await loadHealth();
}

function skipOnboarding() {
  if (onboardingStep >= ONBOARDING_STEPS - 1) return;
  if (isEmbeddedApp && !hasByokKey()) {
    setOnboardingStep(ONBOARDING_STEPS - 1);
    return;
  }
  dismissOnboarding();
}

const MEMORY_TYPE_LABELS = {
  semantic: "fakta",
  preference: "suka/tidak",
  episodic: "obrolan lalu",
  manual: "ko simpan",
  open_loop: "urusan",
};

function readStoredAchievementIds() {
  try {
    const raw = localStorage.getItem(ACHIEVEMENT_UNLOCK_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function writeStoredAchievementIds(ids) {
  try {
    localStorage.setItem(ACHIEVEMENT_UNLOCK_KEY, JSON.stringify(ids));
  } catch {
    /* ignore quota */
  }
}

function showUiToast(message, durationMs = 4200) {
  if (!achievementToast || !message) return;
  achievementToast.textContent = message;
  achievementToast.classList.remove("hidden");
  if (achievementToastTimer) clearTimeout(achievementToastTimer);
  achievementToastTimer = setTimeout(() => {
    achievementToast.classList.add("hidden");
    achievementToastTimer = null;
  }, durationMs);
}

function showAchievementToast(message) {
  showUiToast(message);
}

function celebrateNewAchievements(achievements, { seedOnly = false } = {}) {
  if (!Array.isArray(achievements)) return;
  const unlocked = achievements.filter((a) => a.unlocked).map((a) => a.id);
  const prev = new Set(readStoredAchievementIds());
  const newly = unlocked.filter((id) => !prev.has(id));
  writeStoredAchievementIds(unlocked);
  if (seedOnly || newly.length === 0) return;
  const labels = newly
    .map((id) => {
      const row = achievements.find((a) => a.id === id);
      if (!row) return null;
      return `${row.emoji || "🏅"} ${row.title || id}`;
    })
    .filter(Boolean);
  if (!labels.length) return;
  const msg =
    labels.length === 1
      ? `Lencana baru: ${labels[0]}`
      : `Lencana baru: ${labels.join(" · ")}`;
  showAchievementToast(msg);
}

function applyCompanionPrefsToForm(prefs, effective) {
  if (!prefs) return;
  if (ragEnabledToggle) ragEnabledToggle.checked = Boolean(prefs.rag_enabled);
  if (ragMinScore && prefs.rag_min_score != null) {
    ragMinScore.value = String(prefs.rag_min_score);
    if (ragMinScoreVal) ragMinScoreVal.textContent = Number(prefs.rag_min_score).toFixed(2);
  }
  if (ragGeminiToggle) {
    ragGeminiToggle.checked = Boolean(prefs.rag_use_gemini);
    ragGeminiToggle.disabled = effective?.embedder !== "gemini" && !prefs.rag_use_gemini;
  }
}

function scheduleCompanionPrefsSave() {
  if (prefsSaveTimer) clearTimeout(prefsSaveTimer);
  prefsSaveTimer = setTimeout(() => void saveCompanionPrefsFromForm(), 400);
}

async function saveCompanionPrefsFromForm() {
  if (!ragEnabledToggle && !ragMinScore) return;
  const body = {
    rag_enabled: ragEnabledToggle ? Boolean(ragEnabledToggle.checked) : true,
    rag_min_score: ragMinScore ? Number(ragMinScore.value) : 0.18,
    rag_use_gemini: ragGeminiToggle ? Boolean(ragGeminiToggle.checked) : false,
  };
  try {
    const res = await fetch("/api/companion/prefs", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return;
    const data = await res.json();
    applyCompanionPrefsToForm(data.prefs, data.effective);
  } catch {
    /* ignore */
  }
}

async function syncAchievementsAfterCall() {
  try {
    const res = await fetch("/api/companion/stats", { cache: "no-store" });
    if (!res.ok) return;
    const body = await res.json();
    celebrateNewAchievements(body.stats?.achievements || []);
    void loadMemoryDashboard();
  } catch {
    /* ignore */
  }
}

function behaviorStatRow(label, value) {
  const li = document.createElement("li");
  const l = document.createElement("span");
  l.className = "behavior-stat-label";
  l.textContent = label;
  const v = document.createElement("span");
  v.textContent = String(value ?? "—");
  li.append(l, v);
  return li;
}

function fillEvalTable(table, headers, rows, emptyMsg) {
  if (!table) return;
  table.innerHTML = "";
  if (!rows?.length) {
    const cap = document.createElement("caption");
    cap.className = "behavior-eval-empty";
    cap.textContent = emptyMsg || "Belum ada data.";
    table.appendChild(cap);
    return;
  }
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  headers.forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h.label;
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    headers.forEach((h) => {
      const td = document.createElement("td");
      const val = row[h.key];
      td.textContent = val == null ? "—" : String(val);
      if (h.num) td.classList.add("num");
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
}

function formatDistBand(dist) {
  if (!dist || !dist.n) return "—";
  if (dist.n === 1) return `${dist.median}`;
  return `${dist.p25}–${dist.p75} (n=${dist.n})`;
}

function renderBehaviorEval(data) {
  const ev = data?.eval;
  if (!ev) return;

  fillEvalTable(
    behaviorModeEvalTable,
    [
      { key: "display_name", label: "Mode" },
      { key: "turns", label: "Turns", num: true },
      { key: "avg_assistant_s", label: "Avg assistant", num: true },
      { key: "listening_percent", label: "Listening", num: true },
      { key: "questions", label: "Questions", num: true },
      { key: "mop_percent", label: "MOP %", num: true },
      { key: "tuning_status", label: "G" },
    ],
    (ev.mode_table || []).map((r) => ({
      ...r,
      avg_assistant_s: r.turns ? `${r.avg_assistant_s} s` : "—",
      listening_percent: r.turns ? `${r.listening_percent}%` : "—",
      mop_percent: r.turns ? `${r.mop_percent}%` : "—",
      tuning_status:
        r.tuning_status === "ok"
          ? "OK"
          : r.tuning_status === "needs_tuning"
            ? "TUNE"
            : "…",
    })),
    "Ngobrol live dulu — eval muncul setelah ada turn tercatat.",
  );

  fillEvalTable(
    behaviorSessionDistTable,
    [
      { key: "display_name", label: "Mode" },
      { key: "sessions", label: "Sesi", num: true },
      { key: "listen_band", label: "Listen %", num: true },
      { key: "asst_band", label: "Asst (s)", num: true },
      { key: "mop_band", label: "MOP %", num: true },
      { key: "cb_band", label: "Callback", num: true },
    ],
    (ev.mode_table || [])
      .filter((r) => r.turns > 0)
      .map((r) => {
        const d = r.distributions || {};
        const sess = d.sessions || {};
        return {
          display_name: r.display_name,
          sessions: d.session_count ?? 0,
          listen_band: formatDistBand(sess.listening_percent),
          asst_band: formatDistBand(sess.avg_assistant_s),
          mop_band: formatDistBand(sess.mop_percent),
          cb_band: formatDistBand(sess.callback_surfaced),
        };
      }),
    "Butuh ≥2 sesi per mode untuk band p25–p75 yang bermakna.",
  );

  const bdvRows = (ev.mode_table || [])
    .filter((r) => r.turns > 0)
    .map((r) => {
      const d = r.bdv_distribution || {};
      return {
        display_name: r.display_name,
        respond: d.RESPOND ?? 0,
        ack: d.ACK_ONLY ?? 0,
        defer: d.DEFER ?? 0,
        silence: d.SILENCE ?? 0,
      };
    });
  fillEvalTable(
    behaviorBdvByModeTable,
    [
      { key: "display_name", label: "Mode" },
      { key: "respond", label: "Respond", num: true },
      { key: "ack", label: "Ack", num: true },
      { key: "defer", label: "Defer", num: true },
      { key: "silence", label: "Silence", num: true },
    ],
    bdvRows,
    "BDV per mode muncul setelah turn experience tercatat.",
  );

  fillEvalTable(
    behaviorDecisionOutcomesTable,
    [
      { key: "decision", label: "Decision" },
      { key: "count", label: "Count", num: true },
      { key: "followed", label: "Followed / engaged", num: true },
    ],
    (ev.decision_outcomes || []).map((r) => ({
      decision: r.decision,
      count: r.count,
      followed:
        r.count > 0 && r.followed_label !== "—"
          ? `${r.followed_count} (${r.followed_percent}%) ${r.followed_label}`
          : r.followed_label === "—"
            ? "—"
            : "0",
    })),
    "Belum ada keputusan BDV/callback/MOP.",
  );

  fillEvalTable(
    behaviorMopByTypeTable,
    [
      { key: "mop_type", label: "MOP type" },
      { key: "selected", label: "Selected", num: true },
      { key: "engaged", label: "Engaged", num: true },
      { key: "ignored", label: "Ignored", num: true },
      { key: "redirected", label: "Redirected", num: true },
    ],
    ev.mop_by_type || [],
    "Belum ada MOP setup/outcome.",
  );

  if (behaviorPlannedHoldNote && ev.planned_hold_label) {
    behaviorPlannedHoldNote.textContent = ev.planned_hold_label;
  }
  fillEvalTable(
    behaviorPlannedHoldTable,
    [
      { key: "planned_hold_ms", label: "Planned hold" },
      { key: "total", label: "N", num: true },
      { key: "engaged_percent", label: "Engaged %", num: true },
    ],
    (ev.planned_hold_outcomes || []).map((r) => ({
      planned_hold_ms: `${r.planned_hold_ms} ms`,
      total: r.total,
      engaged_percent: r.total ? `${r.engaged_percent}%` : "—",
    })),
    "Butuh mop_outcome dengan planned_hold_ms.",
  );

  if (behaviorModeHealth) {
    behaviorModeHealth.innerHTML = "";
    const healthRows = ev.mode_health || [];
    if (!healthRows.some((h) => h.turns > 0)) {
      const li = document.createElement("li");
      li.className = "behavior-eval-empty";
      li.textContent = "Mode health butuh ≥3 turn per mode untuk kontrak penuh.";
      behaviorModeHealth.appendChild(li);
    }
    healthRows.forEach((h) => {
      if (h.turns <= 0) return;
      const li = document.createElement("li");
      const modeRow = (ev.mode_table || []).find((r) => r.mode === h.mode);
      const g = modeRow?.tuning_status || "…";
      const title = document.createElement("div");
      title.className = "behavior-health-title";
      title.textContent = `${h.display_name || h.mode} · G=${g}`;
      li.appendChild(title);
      const tuneNote = modeRow?.tuning_note || "";
      const contract = document.createElement("div");
      contract.className = "behavior-health-contract";
      if (h.contract_ok === true) {
        contract.classList.add("ok");
        contract.textContent = tuneNote || "Kontrak OK";
      } else if (h.contract_ok === false) {
        contract.classList.add("warn");
        contract.textContent = tuneNote || "Perlu tuning";
        (h.checks || []).forEach((c) => {
          if (c.ok !== false) return;
          const line = document.createElement("div");
          line.className = "behavior-decision-line";
          line.textContent = `✗ ${c.label} — ${c.detail}`;
          li.appendChild(line);
        });
      } else {
        contract.classList.add("na");
        contract.textContent = tuneNote || "Butuh lebih banyak sesi";
      }
      li.appendChild(contract);
      behaviorModeHealth.appendChild(li);
    });
  }
}

function renderBehaviorDebugDashboard(data) {
  if (!data) return;
  const day = data.day || "";
  if (behaviorDebugDay) {
    behaviorDebugDay.textContent = day ? `HARI INI · ${day}` : "HARI INI";
  }

  renderBehaviorEval(data);

  if (behaviorRecentDecisions) {
    behaviorRecentDecisions.innerHTML = "";
    const rows = data.recent_decisions || [];
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "settings-memory-empty";
      li.textContent = "Belum ada keputusan — ngobrol live dulu ya.";
      behaviorRecentDecisions.appendChild(li);
    } else {
      rows.forEach((row) => {
        const li = document.createElement("li");
        const modeLabel =
          BEHAVIOR_MODE_LABELS[row.experience_mode] ||
          row.experience_mode ||
          "?";
        const head = document.createElement("div");
        head.className = "behavior-decision-head";
        head.textContent = `${row.time || "—"}  ${modeLabel.toUpperCase().replace(/\s+/g, "_")}`;
        const bdvLine = document.createElement("div");
        bdvLine.className = "behavior-decision-line";
        bdvLine.textContent = `BDV: ${row.bdv || "?"}`;
        li.appendChild(head);
        li.appendChild(bdvLine);
        if (row.callback_status && row.callback_status !== "none") {
          const cl = document.createElement("div");
          cl.className = "behavior-decision-line";
          cl.textContent = `CALLBACK: ${row.callback_status}${row.callback_reason ? ` (${row.callback_reason})` : ""}`;
          li.appendChild(cl);
        }
        if (row.mop_status && row.mop_status !== "none") {
          const ml = document.createElement("div");
          ml.className = "behavior-decision-line";
          let mopText = `MOP: ${row.mop_status}`;
          if (row.mop_phase) mopText += ` · Phase: ${row.mop_phase}`;
          if (row.mop_type) mopText += ` · Type: ${row.mop_type}`;
          if (row.hold_ms) mopText += ` · Hold: ${row.hold_ms} ms`;
          if (row.reaction && row.reaction !== "none") {
            mopText += ` · Reaction: ${row.reaction}`;
          }
          ml.textContent = mopText;
          li.appendChild(ml);
        }
        if (row.reason) {
          const rl = document.createElement("div");
          rl.className = "behavior-decision-line";
          rl.textContent = `Reason: ${row.reason}`;
          li.appendChild(rl);
        }
        behaviorRecentDecisions.appendChild(li);
      });
    }
  }
}

function formatMetricCompare(label, before, after, suffix = "") {
  const b = before == null ? "—" : `${before}${suffix}`;
  const a = after == null ? "—" : `${after}${suffix}`;
  return `${label}: ${b} → ${a}`;
}

function renderBehaviorExperiments(experiments) {
  if (!behaviorExperimentsList) return;
  behaviorExperimentsList.innerHTML = "";
  if (!experiments?.length) {
    const li = document.createElement("li");
    li.className = "behavior-eval-empty";
    li.textContent = "Belum ada eksperimen — catat baseline sebelum mengubah satu lever.";
    behaviorExperimentsList.appendChild(li);
    return;
  }
  experiments.forEach((exp) => {
    const li = document.createElement("li");
    const title = document.createElement("div");
    title.className = "behavior-exp-title";
    const modeLabel = BEHAVIOR_MODE_LABELS[exp.mode] || exp.mode;
    const before = exp.before_metrics || {};
    const after = exp.after_metrics || {};
    const expId = exp.experiment_id || exp.id;
    const revBefore = exp.config_revision_before || before.config_revision || "—";
    const revAfter = exp.config_revision_after || after.config_revision || "—";
    title.textContent = `${expId} · ${modeLabel} · ${exp.lever} · ${exp.status}`;
    li.appendChild(title);
    const hyp = document.createElement("div");
    hyp.className = "behavior-decision-line";
    hyp.textContent = exp.hypothesis || "";
    li.appendChild(hyp);
    const lever = document.createElement("div");
    lever.className = "behavior-decision-line";
    lever.textContent = `Lever: ${exp.before_value} → ${exp.after_value}`;
    li.appendChild(lever);
    const revLine = document.createElement("div");
    revLine.className = "behavior-decision-line";
    revLine.textContent = `Config: ${revBefore} → ${revAfter}`;
    li.appendChild(revLine);
    const lines = [
      formatMetricCompare("Listen median", before.listening_median, after.listening_median, "%"),
      formatMetricCompare("Listen p25", before.listening_p25, after.listening_p25, "%"),
      formatMetricCompare("Questions median", before.questions_median, after.questions_median),
      formatMetricCompare("MOP median", before.mop_median, after.mop_median, "%"),
    ];
    lines.forEach((text) => {
      const d = document.createElement("div");
      d.className = "behavior-decision-line";
      d.textContent = text;
      li.appendChild(d);
    });
    if (exp.status === "active") {
      const actions = document.createElement("div");
      actions.className = "behavior-exp-actions";
      const completeBtn = document.createElement("button");
      completeBtn.type = "button";
      completeBtn.className = "settings-memory-refresh";
      completeBtn.textContent = "Snapshot after (sesi baru selesai)";
      completeBtn.addEventListener("click", () => void completeBehaviorExperiment(exp.id));
      actions.appendChild(completeBtn);
      li.appendChild(actions);
    }
    behaviorExperimentsList.appendChild(li);
  });
}

async function refreshBehaviorConfigRevision() {
  try {
    const res = await fetch("/api/behavior-config/revision", { cache: "no-store" });
    if (!res.ok) return;
    const body = await res.json();
    if (behaviorConfigRevision) {
      behaviorConfigRevision.textContent = `Config revision: ${body.revision || "g.001"}`;
    }
  } catch {
    /* ignore */
  }
}

async function bumpBehaviorConfigRevision() {
  try {
    const res = await fetch("/api/behavior-config/bump", { method: "POST" });
    if (!res.ok) return;
    await refreshBehaviorConfigRevision();
  } catch {
    /* ignore */
  }
}

async function loadBehaviorExperiments() {
  try {
    await refreshBehaviorConfigRevision();
    const res = await fetch("/api/behavior-experiments", { cache: "no-store" });
    if (!res.ok) return;
    const body = await res.json();
    renderBehaviorExperiments(body.experiments || []);
  } catch {
    /* ignore */
  }
}

async function startBehaviorExperiment() {
  const mode = behaviorExpMode?.value || "cerita_tong";
  const lever = (behaviorExpLever?.value || "").trim();
  const values = (behaviorExpValues?.value || "").trim();
  const hypothesis = (behaviorExpHypothesis?.value || "").trim();
  if (!lever || !values || !hypothesis) return;
  const parts = values.split("→").map((s) => s.trim());
  const before_value = parts[0] || "?";
  const after_value = parts[1] || parts[0] || "?";
  try {
    const res = await fetch("/api/behavior-experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        lever,
        before_value,
        after_value,
        hypothesis,
      }),
    });
    if (!res.ok) return;
    await loadBehaviorExperiments();
  } catch {
    /* ignore */
  }
}

async function completeBehaviorExperiment(id) {
  try {
    const res = await fetch(`/api/behavior-experiments/${encodeURIComponent(id)}/complete`, {
      method: "POST",
    });
    if (!res.ok) return;
    await loadBehaviorExperiments();
    void loadBehaviorDebugDashboard(true);
  } catch {
    /* ignore */
  }
}

function ensureBehaviorDebugLoadHook() {
  if (!behaviorDebugDetails || behaviorDebugDetails.dataset.hook === "1") return;
  behaviorDebugDetails.dataset.hook = "1";
  behaviorDebugDetails.addEventListener("toggle", () => {
    if (behaviorDebugDetails.open) void loadBehaviorDebugDashboard(true);
  });
}

async function loadBehaviorDebugDashboard(force) {
  if (!behaviorModeEvalTable && !behaviorRecentDecisions && !behaviorDebugDay) {
    return;
  }
  if (!force && behaviorDebugDetails && !behaviorDebugDetails.open) {
    return;
  }
  try {
    const res = await fetch("/api/behavior-debug/today", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    renderBehaviorDebugDashboard(data);
    behaviorDebugLoaded = true;
    void loadBehaviorExperiments();
  } catch {
    /* ignore */
  }
}

async function loadMemoryDashboard() {
  if (!memoryStats && !memoryReviewList && !memoryList && !openLoopList) return;
  if (memoryStats) memoryStats.textContent = "Memuat…";
  try {
    const [privacyRes, memRes, loopRes, statsRes, reviewRes] = await Promise.all([
      fetch("/api/privacy"),
      fetch("/api/memory"),
      fetch("/api/open-loops"),
      fetch("/api/companion/stats"),
      fetch("/api/memory/review"),
    ]);
    const privacy = privacyRes.ok ? await privacyRes.json() : {};
    const memData = memRes.ok ? await memRes.json() : { memories: [] };
    const loopData = loopRes.ok ? await loopRes.json() : { open_loops: [] };
    const memories = memData.memories || [];
    const loops = loopData.open_loops || [];
    const reviewData = reviewRes.ok ? await reviewRes.json() : { items: [] };
    const reviews = reviewData.items || [];

    const statsBody = statsRes.ok ? await statsRes.json() : {};
    let ragHint = "";
    try {
      const prefsRes = await fetch("/api/companion/prefs", { cache: "no-store" });
      if (prefsRes.ok) {
        const prefsBody = await prefsRes.json();
        const eff = prefsBody.effective;
        if (eff?.enabled) {
          const embed = eff.embedder === "gemini" ? "Gemini embed" : "embed lokal";
          ragHint = ` · RAG ${embed} (min ${eff.min_score})`;
        } else {
          ragHint = " · RAG mati";
        }
        applyCompanionPrefsToForm(prefsBody.prefs, eff);
      }
    } catch {
      /* ignore */
    }
    const streak = statsBody.stats?.streak_days ?? 0;
    const sessions = statsBody.stats?.total_sessions ?? 0;
    if (memoryStats) {
      const reviewN = privacy.review_count ?? reviews.length;
      const reviewLine = reviewN > 0 ? ` · ${reviewN} konfirmasi` : "";
      const streakLine = streak > 0 ? ` · streak ${streak}d` : "";
      memoryStats.textContent =
        `${privacy.memory_count ?? memories.length} ingatan · ${privacy.open_loop_count ?? loops.length} open loop${reviewLine}${streakLine}`;
    }

    if (memoryReviewList) {
      memoryReviewList.innerHTML = "";
      if (!reviews.length) {
        const li = document.createElement("li");
        li.className = "settings-memory-empty";
        li.textContent = "Kosong.";
        memoryReviewList.appendChild(li);
      } else {
        reviews.forEach((item) => {
          const li = document.createElement("li");
          li.className = "settings-memory-item";
          const text = document.createElement("span");
          text.className = "settings-memory-text";
          const label = MEMORY_TYPE_LABELS[item.memory_type] || item.memory_type;
          text.textContent = `[${label}] ${item.content}`;
          const confirmBtn = document.createElement("button");
          confirmBtn.type = "button";
          confirmBtn.className = "btn-memory-delete";
          confirmBtn.setAttribute("aria-label", "Simpan ingatan");
          confirmBtn.textContent = "✓";
          confirmBtn.addEventListener("click", () => void confirmReviewItem(item.id));
          const dismissBtn = document.createElement("button");
          dismissBtn.type = "button";
          dismissBtn.className = "btn-memory-delete";
          dismissBtn.setAttribute("aria-label", "Buang saran");
          dismissBtn.textContent = "×";
          dismissBtn.addEventListener("click", () => void dismissReviewItem(item.id));
          li.append(text, confirmBtn, dismissBtn);
          memoryReviewList.appendChild(li);
        });
      }
    }

    const achievements = statsBody.stats?.achievements || [];
    const unlockedN = achievements.filter((a) => a.unlocked).length;
    if (companionAchievementsWrap) {
      const show = unlockedN > 0;
      companionAchievementsWrap.classList.toggle("hidden", !show);
      companionAchievementsWrap.hidden = !show;
    }
    const fb = statsBody.stats?.session_feedback;
    if (sessionFeedbackStats && fb) {
      const up = fb.up || 0;
      const down = fb.down || 0;
      sessionFeedbackStats.textContent =
        up + down > 0
          ? `Feedback obrolan (lokal): 👍 ${up} · 👎 ${down}`
          : "Feedback obrolan: belum ada — tandai setelah ngobrol.";
    }
    celebrateNewAchievements(achievements, { seedOnly: true });
    if (companionAchievements) {
      companionAchievements.innerHTML = "";
      achievements.forEach((badge) => {
        const li = document.createElement("li");
        li.className = badge.unlocked
          ? "settings-achievement-item settings-achievement-unlocked"
          : "settings-achievement-item settings-achievement-locked";
        li.title = badge.description || "";
        li.textContent = `${badge.emoji || "🏅"} ${badge.title || badge.id}`;
        companionAchievements.appendChild(li);
      });
    }

    if (memoryList) {
      memoryList.innerHTML = "";
      if (!memories.length) {
        const li = document.createElement("li");
        li.className = "settings-memory-empty";
        li.textContent = "Kosong.";
        memoryList.appendChild(li);
      } else {
        memories.forEach((m) => {
          const li = document.createElement("li");
          li.className = "settings-memory-item";
          const label = MEMORY_TYPE_LABELS[m.memory_type] || m.memory_type;
          const text = document.createElement("span");
          text.className = "settings-memory-text";
          text.textContent = `[${label}] ${m.content}`;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-memory-delete";
          btn.setAttribute("aria-label", "Hapus ingatan");
          btn.textContent = "×";
          btn.addEventListener("click", () => void deleteMemoryItem(m.id));
          li.append(text, btn);
          memoryList.appendChild(li);
        });
      }
    }

    if (openLoopList) {
      openLoopList.innerHTML = "";
      if (!loops.length) {
        const li = document.createElement("li");
        li.className = "settings-memory-empty";
        li.textContent = "Kosong.";
        openLoopList.appendChild(li);
      } else {
        loops.forEach((loop) => {
          const li = document.createElement("li");
          li.className = "settings-memory-item";
          const text = document.createElement("span");
          text.className = "settings-memory-text";
          const hint = loop.time_hint ? ` (${loop.time_hint})` : "";
          text.textContent = `${loop.topic}${hint}: ${loop.content}`;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn-memory-delete";
          btn.setAttribute("aria-label", "Tandai selesai");
          btn.textContent = "✓";
          btn.addEventListener("click", () => void resolveOpenLoopItem(loop.id));
          li.append(text, btn);
          openLoopList.appendChild(li);
        });
      }
    }
  } catch {
    if (memoryStats) memoryStats.textContent = "Tra bisa muat ingatan — coba lagi.";
  }
}

async function confirmReviewItem(id) {
  if (!id) return;
  try {
    const res = await fetch(
      `/api/memory/review/${encodeURIComponent(id)}/confirm`,
      { method: "POST" }
    );
    if (!res.ok) return;
    await loadMemoryDashboard();
  } catch {
    /* ignore */
  }
}

async function dismissReviewItem(id) {
  if (!id) return;
  try {
    const res = await fetch(
      `/api/memory/review/${encodeURIComponent(id)}/dismiss`,
      { method: "POST" }
    );
    if (!res.ok) return;
    await loadMemoryDashboard();
  } catch {
    /* ignore */
  }
}

async function deleteMemoryItem(id) {
  if (!id) return;
  try {
    const res = await fetch(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!res.ok) return;
    await loadMemoryDashboard();
  } catch {
    /* ignore */
  }
}

async function resolveOpenLoopItem(id) {
  if (!id) return;
  try {
    const res = await fetch(`/api/open-loops/${encodeURIComponent(id)}/resolve`, { method: "POST" });
    if (!res.ok) return;
    await loadMemoryDashboard();
  } catch {
    /* ignore */
  }
}

async function addManualMemory() {
  const text = (memoryManualInput?.value || "").trim();
  memoryAddError?.classList.add("hidden");
  if (text.length < 2) {
    memoryAddError?.classList.remove("hidden");
    return;
  }
  try {
    const res = await fetch("/api/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text, memory_type: "manual" }),
    });
    if (!res.ok) {
      memoryAddError?.classList.remove("hidden");
      return;
    }
    if (memoryManualInput) memoryManualInput.value = "";
    await loadMemoryDashboard();
  } catch {
    memoryAddError?.classList.remove("hidden");
  }
}

async function reindexMemoryEmbeddings() {
  if (memoryStats) memoryStats.textContent = "Rebuild index RAG…";
  try {
    const res = await fetch("/api/memory/reindex-embeddings", { method: "POST" });
    if (!res.ok) return;
    const body = await res.json();
    const n = body.reindexed?.memories ?? 0;
    const loops = body.reindexed?.open_loops ?? 0;
    showAchievementToast(`Index RAG diperbarui (${n} ingatan, ${loops} loop).`);
    await loadMemoryDashboard();
  } catch {
    if (memoryStats) memoryStats.textContent = "Gagal rebuild index — coba lagi.";
  }
}

function maybeIdleReindexEmbeddings() {
  if (inCall) return;
  let last = 0;
  try {
    last = Number(localStorage.getItem(RAG_IDLE_REINDEX_KEY) || "0");
  } catch {
    /* ignore */
  }
  if (Date.now() - last < RAG_IDLE_REINDEX_INTERVAL_MS) return;
  fetch("/api/memory/reindex-embeddings", { method: "POST" })
    .then(() => {
      try {
        localStorage.setItem(RAG_IDLE_REINDEX_KEY, String(Date.now()));
      } catch {
        /* ignore */
      }
    })
    .catch(() => {});
}

async function importMemoryJsonFile(file) {
  if (!file) return;
  const text = await file.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    showAchievementToast("File JSON tra valid.");
    return;
  }
  const replace = window.confirm(
    "Import backup?\n\nOK = ganti semua ingatan di HP dengan isi file.\nCancel = gabung (skip duplikat)."
  );
  const mode = replace ? "replace" : "merge";
  try {
    const res = await fetch("/api/memory/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload, mode }),
    });
    if (!res.ok) {
      showAchievementToast("Import gagal — cek format file.");
      return;
    }
    const body = await res.json();
    const imp = body.imported || {};
    showAchievementToast(
      `Import selesai: ${imp.memories ?? 0} ingatan, ${imp.open_loops ?? 0} loop.`
    );
    await loadMemoryDashboard();
  } catch {
    showAchievementToast("Import gagal — coba lagi.");
  }
}

async function exportMemoryJson() {
  try {
    const res = await fetch("/api/memory/export");
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "papua-ai-memory-export.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch {
    /* ignore */
  }
}

async function clearAllMemory() {
  if (
    typeof window !== "undefined" &&
    !window.confirm("Hapus semua ingatan & urusan belum selesai di HP ini? Tra bisa undo.")
  ) {
    return;
  }
  try {
    const res = await fetch("/api/memory/all", { method: "DELETE" });
    if (!res.ok) return;
    writeStoredAchievementIds([]);
    await loadMemoryDashboard();
  } catch {
    /* ignore */
  }
}

function updateSettingsKeyStatus() {
  if (!settingsKeyStatus) return;
  if (hasByokKey()) {
    const k = loadByokKey();
    const tail = k.length >= 4 ? k.slice(-4) : "****";
    settingsKeyStatus.textContent = `Key tersimpan (…${tail})`;
    settingsKeyStatus.classList.remove("empty");
  } else {
    settingsKeyStatus.textContent = "Belum ada API key";
    settingsKeyStatus.classList.add("empty");
  }
}

async function loadMopPreview() {
  if (!settingsMopCount && !settingsMopPreview) return;
  try {
    const res = await fetch("/api/papua/mops");
    const data = await res.json();
    if (!res.ok) throw new Error("mops failed");
    const count = data.count ?? 0;
    if (settingsMopCount) {
      settingsMopCount.textContent = `${count} Mop siap dipakai AI ko`;
    }
    if (settingsMopPreview) {
      settingsMopPreview.innerHTML = "";
      const items = Array.isArray(data.preview) ? data.preview : [];
      for (const text of items) {
        const li = document.createElement("li");
        li.textContent = text;
        settingsMopPreview.appendChild(li);
      }
      if (!items.length) {
        const li = document.createElement("li");
        li.textContent = "Belum ada contoh — coba refresh.";
        settingsMopPreview.appendChild(li);
      }
    }
  } catch {
    if (settingsMopCount) settingsMopCount.textContent = "Koleksi Mop Papua";
    if (settingsMopPreview) {
      settingsMopPreview.innerHTML = "<li>Tra bisa muat sekarang — coba lagi nanti.</li>";
    }
  }
}

async function loadKamusPreview() {
  const kamusCountEl = settingsKamusCount || document.getElementById("settingsKamusCount");
  const kamusPreviewEl = settingsKamusPreview || document.getElementById("settingsKamusPreview");
  if (!kamusCountEl && !kamusPreviewEl) return;
  try {
    const res = await fetch("/api/papua/kamus");
    const data = await res.json();
    if (!res.ok) throw new Error("kamus failed");
    const count = data.count ?? 0;
    if (kamusCountEl) {
      kamusCountEl.textContent = `${count} kata siap dijelasin AI ko`;
    }
    if (kamusPreviewEl) {
      kamusPreviewEl.innerHTML = "";
      const items = Array.isArray(data.preview) ? data.preview : [];
      for (const text of items) {
        const li = document.createElement("li");
        li.textContent = text;
        kamusPreviewEl.appendChild(li);
      }
      if (!items.length) {
        const li = document.createElement("li");
        li.textContent = "Belum ada contoh — coba refresh.";
        kamusPreviewEl.appendChild(li);
      }
    }
  } catch {
    if (kamusCountEl) kamusCountEl.textContent = "Kamus Bahasa Papua";
    if (kamusPreviewEl) {
      kamusPreviewEl.innerHTML = "<li>Tra bisa muat sekarang — coba lagi nanti.</li>";
    }
  }
}

function loadProsodySimSettings() {
  try {
    const raw = localStorage.getItem(PROSODY_SIM_STORAGE_KEY);
    if (!raw) return { speech_tempo: 1, tone_pitch: 1, mop_frequency: 0.6 };
    const data = JSON.parse(raw);
    return {
      speech_tempo: Number(data.speech_tempo) || 1,
      tone_pitch: Number(data.tone_pitch) || 1,
      mop_frequency: Number(data.mop_frequency) || 0.6,
    };
  } catch {
    return { speech_tempo: 1, tone_pitch: 1, mop_frequency: 0.6 };
  }
}

function saveProsodySimSettings() {
  if (!simTempo || !simPitch || !simMopFreq) return;
  const payload = {
    speech_tempo: Number(simTempo.value),
    tone_pitch: Number(simPitch.value),
    mop_frequency: Number(simMopFreq.value),
  };
  try {
    localStorage.setItem(PROSODY_SIM_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* ignore */
  }
}

function syncProsodySimLabels() {
  if (simTempoVal && simTempo) simTempoVal.textContent = Number(simTempo.value).toFixed(2);
  if (simPitchVal && simPitch) simPitchVal.textContent = Number(simPitch.value).toFixed(2);
  if (simMopVal && simMopFreq) simMopVal.textContent = Number(simMopFreq.value).toFixed(2);
}

function initProsodySimControls() {
  if (prosodySimBound) return;
  prosodySimBound = true;
  const cfg = loadProsodySimSettings();
  if (simTempo) simTempo.value = String(cfg.speech_tempo);
  if (simPitch) simPitch.value = String(cfg.tone_pitch);
  if (simMopFreq) simMopFreq.value = String(cfg.mop_frequency);
  syncProsodySimLabels();
  for (const el of [simTempo, simPitch, simMopFreq]) {
    el?.addEventListener("input", () => {
      syncProsodySimLabels();
      saveProsodySimSettings();
    });
  }
}

function openSettings() {
  if (!settings) return;
  document.body.classList.add("settings-modal-open");
  settings.classList.remove("hidden");
  settings.hidden = false;
  if (settingsApiKey) {
    settingsApiKey.value = loadByokKey();
  }
  initProsodySimControls();
  populateBgmOptions();
  void populateModeOptions();
  if (cachedLiveVoices?.length) {
    renderVoicePickerList();
  } else {
    void loadHealth();
  }
  renderBgmPickerList();
  updateSettingsKeyStatus();
  void loadMemoryDashboard();
  ensureBehaviorDebugLoadHook();
  if (behaviorDebugDetails?.open) {
    void loadBehaviorDebugDashboard(true);
  }
  syncDailyReminderToggle();
  settingsError?.classList.add("hidden");
  if (settingsError) {
    settingsError.textContent = "Key tra valid — cek lagi ya ko.";
  }
  setTimeout(() => settingsApiKey?.focus(), 120);
}

function closeSettings() {
  if (!settings) return;
  settings.classList.add("hidden");
  settings.hidden = true;
  document.body.classList.remove("settings-modal-open");
}

async function saveSettings() {
  const key = (settingsApiKey?.value || "").trim();
  if (key.length < 8) {
    settingsError?.classList.remove("hidden");
    settingsApiKey?.focus();
    return;
  }

  if (voiceSelect?.value) {
    try {
      localStorage.setItem(VOICE_STORAGE_KEY, voiceSelect.value);
    } catch {
      /* ignore */
    }
  }

  if (bgmSelect?.value) {
    try {
      localStorage.setItem(BGM_STORAGE_KEY, bgmSelect.value);
    } catch {
      /* ignore */
    }
  }

  if (btnSettingsSave) {
    btnSettingsSave.disabled = true;
    btnSettingsSave.textContent = "Menyimpan…";
  }
  const ok = await syncByokKey(key);
  if (btnSettingsSave) {
    btnSettingsSave.disabled = false;
    btnSettingsSave.textContent = "Simpan";
  }
  if (!ok) {
    if (settingsError) {
      settingsError.textContent = "Gagal simpan key — coba lagi ko.";
    }
    settingsError?.classList.remove("hidden");
    return;
  }

  updateSettingsKeyStatus();
  statusDot.classList.remove("offline");
  updateCallButtonReady(true);
  closeSettings();
  await loadHealth();
}

function selectedVoiceName() {
  const saved = normalizeSavedVoice(
    localStorage.getItem(VOICE_STORAGE_KEY),
    cachedDefaultVoice
  );
  return voiceSelect?.value || saved || cachedDefaultVoice || "Leda";
}

function populateVoiceOptions(voices, defaultVoice) {
  if (!voiceSelect || !Array.isArray(voices) || !voices.length) return;
  cachedLiveVoices = voices;
  cachedDefaultVoice = defaultVoice || voices[0]?.name || "Leda";
  const saved = normalizeSavedVoice(localStorage.getItem(VOICE_STORAGE_KEY), cachedDefaultVoice);
  voiceSelect.innerHTML = "";
  for (const v of voices) {
    const opt = document.createElement("option");
    opt.value = v.name;
    opt.textContent = `${v.name} — ${v.style.toLowerCase()}`;
    voiceSelect.appendChild(opt);
  }
  const pick = saved || cachedDefaultVoice || voices[0].name;
  if ([...voiceSelect.options].some((o) => o.value === pick)) {
    voiceSelect.value = pick;
  }
  renderVoicePickerList();
}

function setSelectedVoice(name) {
  if (!name) return;
  if (voiceSelect && [...voiceSelect.options].some((o) => o.value === name)) {
    voiceSelect.value = name;
  }
  try {
    localStorage.setItem(VOICE_STORAGE_KEY, name);
  } catch {
    /* ignore */
  }
  voicePickerList?.querySelectorAll(".settings-picker-option[data-voice]").forEach((el) => {
    el.classList.toggle("is-selected", el.dataset.voice === name);
    el.setAttribute("aria-selected", el.dataset.voice === name ? "true" : "false");
  });
}

function renderVoicePickerList() {
  if (!voicePickerList) return;
  const voices = cachedLiveVoices;
  if (!Array.isArray(voices) || !voices.length) {
    voicePickerList.innerHTML =
      '<p class="settings-picker-empty">Memuat daftar suara…</p>';
    return;
  }
  const current = selectedVoiceName();
  voicePickerList.innerHTML = "";
  for (const v of voices) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "settings-picker-option";
    btn.dataset.voice = v.name;
    btn.textContent =
      v.name === "Leda"
        ? `${v.name} — ${v.style.toLowerCase()} (default Papua Ai)`
        : `${v.name} — ${v.style.toLowerCase()}`;
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", v.name === current ? "true" : "false");
    if (v.name === current) btn.classList.add("is-selected");
    btn.addEventListener("click", () => setSelectedVoice(v.name));
    voicePickerList.appendChild(btn);
  }
}

function selectedBgmMode() {
  return bgmSelect?.value || localStorage.getItem(BGM_STORAGE_KEY) || "off";
}

function populateBgmOptions() {
  if (!bgmSelect) return;
  const saved = localStorage.getItem(BGM_STORAGE_KEY) || "off";
  if ([...bgmSelect.options].some((o) => o.value === saved)) {
    bgmSelect.value = saved;
  }
  try {
    localStorage.setItem(BGM_STORAGE_KEY, bgmSelect.value || saved);
  } catch {
    /* ignore */
  }
  renderBgmPickerList();
}

function setSelectedBgm(mode) {
  if (!mode) return;
  if (bgmSelect && [...bgmSelect.options].some((o) => o.value === mode)) {
    bgmSelect.value = mode;
  }
  try {
    localStorage.setItem(BGM_STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
  bgmPickerList?.querySelectorAll(".settings-picker-option[data-bgm]").forEach((el) => {
    el.classList.toggle("is-selected", el.dataset.bgm === mode);
    el.setAttribute("aria-selected", el.dataset.bgm === mode ? "true" : "false");
  });
}

let cachedConversationModes = null;
let cachedExperienceModes = null;

const LEGACY_MODE_ALIASES = {
  casual_chat: "nongkrong",
  funny: "mop",
  curhat: "cerita_tong",
};

function migrateStoredConversationMode() {
  try {
    const raw = localStorage.getItem(CONVERSATION_MODE_KEY);
    if (!raw) return;
    const mapped = LEGACY_MODE_ALIASES[raw];
    if (mapped) localStorage.setItem(CONVERSATION_MODE_KEY, mapped);
  } catch {
    /* ignore */
  }
}

function selectedConversationMode() {
  try {
    migrateStoredConversationMode();
    return localStorage.getItem(CONVERSATION_MODE_KEY) || "nongkrong";
  } catch {
    return "nongkrong";
  }
}

async function loadExperienceModesFromApi() {
  if (cachedExperienceModes?.length) return cachedExperienceModes;
  try {
    const res = await fetch("/api/experience-modes");
    if (!res.ok) return null;
    const data = await res.json();
    cachedExperienceModes = Array.isArray(data.modes) ? data.modes : [];
    return cachedExperienceModes;
  } catch {
    return null;
  }
}

async function loadConversationModesFromApi() {
  const experience = await loadExperienceModesFromApi();
  if (experience?.length) {
    cachedConversationModes = experience;
    return experience;
  }
  if (cachedConversationModes?.length) return cachedConversationModes;
  try {
    const res = await fetch("/api/conversation-modes");
    if (!res.ok) return null;
    const data = await res.json();
    cachedConversationModes = Array.isArray(data.modes) ? data.modes : [];
    return cachedConversationModes;
  } catch {
    return null;
  }
}

function applyExperienceAudioHints(modeMeta) {
  if (!modeMeta?.audio_bgm) return;
  const bgm = String(modeMeta.audio_bgm).trim();
  if (!bgm) return;
  if (BGM_OPTIONS.some((o) => o.value === bgm)) {
    setSelectedBgm(bgm);
  }
}

function renderVoiceModeStrip() {
  if (!voiceModeStrip) return;
  const list = (cachedExperienceModes || []).filter((m) => m?.id);
  if (list.length < 2) {
    voiceModeStrip.classList.add("hidden");
    voiceModeStrip.innerHTML = "";
    return;
  }
  const pick = list.slice(0, 3);
  const current = selectedConversationMode();
  voiceModeStrip.classList.remove("hidden");
  voiceModeStrip.innerHTML = "";
  for (const m of pick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "voice-mode-pill";
    btn.dataset.mode = m.id;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", m.id === current ? "true" : "false");
    btn.textContent = m.display_name || m.id;
    if (m.id === current) btn.classList.add("is-active");
    btn.addEventListener("click", () => setSelectedConversationMode(m.id, m));
    voiceModeStrip.appendChild(btn);
  }
}

function renderExperienceHome(modes) {
  if (!experienceModeList) return;
  const list =
    modes ||
    cachedExperienceModes || [
      { id: "nongkrong", display_name: "Nongkrong", emoji: "🎙️", tagline: "Ngobrol santai." },
    ];
  const current = selectedConversationMode();
  experienceModeList.innerHTML = "";
  for (const m of list) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "experience-mode-btn";
    btn.dataset.mode = m.id;
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", m.id === current ? "true" : "false");
    if (m.id === current) btn.classList.add("is-selected");
    btn.innerHTML = `<span class="mode-emoji">${m.emoji || "🎙️"}</span><span class="mode-copy"><span class="mode-name">${m.display_name || m.id}</span><span class="mode-sub">${m.tagline || ""}</span></span>`;
    btn.addEventListener("click", () => setSelectedConversationMode(m.id, m));
    experienceModeList.appendChild(btn);
  }
  const active = list.find((x) => x.id === current) || list[0];
  if (active) syncExperienceTagline(active.tagline || "");
}

function renderModePickerList(modes) {
  if (!modePickerList) return;
  const list =
    modes ||
    cachedConversationModes || [
      { id: "casual_chat", display_name: "Ngobrol santai", emoji: "🗣️" },
    ];
  const current = selectedConversationMode();
  modePickerList.innerHTML = "";
  for (const m of list) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "settings-picker-option";
    btn.dataset.mode = m.id;
    btn.textContent = `${m.emoji || ""} ${m.display_name || m.id}`.trim();
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", m.id === current ? "true" : "false");
    if (m.id === current) btn.classList.add("is-selected");
    btn.addEventListener("click", () => setSelectedConversationMode(m.id));
    modePickerList.appendChild(btn);
  }
}

function setSelectedConversationMode(modeId, modeMeta) {
  if (!modeId) return;
  if (modeSelect && [...modeSelect.options].some((o) => o.value === modeId)) {
    modeSelect.value = modeId;
  }
  try {
    localStorage.setItem(CONVERSATION_MODE_KEY, modeId);
  } catch {
    /* ignore */
  }
  modePickerList?.querySelectorAll(".settings-picker-option[data-mode]").forEach((el) => {
    el.classList.toggle("is-selected", el.dataset.mode === modeId);
    el.setAttribute("aria-selected", el.dataset.mode === modeId ? "true" : "false");
  });
  experienceModeList?.querySelectorAll(".experience-mode-btn[data-mode]").forEach((el) => {
    el.classList.toggle("is-selected", el.dataset.mode === modeId);
    el.setAttribute("aria-selected", el.dataset.mode === modeId ? "true" : "false");
  });
  voiceModeStrip?.querySelectorAll(".voice-mode-pill[data-mode]").forEach((el) => {
    el.classList.toggle("is-active", el.dataset.mode === modeId);
    el.setAttribute("aria-selected", el.dataset.mode === modeId ? "true" : "false");
  });
  const meta =
    modeMeta ||
    cachedExperienceModes?.find((m) => m.id === modeId) ||
    cachedConversationModes?.find((m) => m.id === modeId);
  if (meta?.tagline) syncExperienceTagline(meta.tagline);
  applyExperienceAudioHints(meta);
  if (inCall && liveCall?.active) {
    liveCall.setConversationMode(modeId);
  } else {
    notifyNativeExperienceMode(modeId);
  }
}

function notifyNativeExperienceMode(modeId) {
  if (!modeId) return;
  try {
    if (typeof PersonaAndroid !== "undefined" && PersonaAndroid.onModeChanged) {
      PersonaAndroid.onModeChanged(modeId);
      return;
    }
    if (typeof Android !== "undefined" && Android.onModeChanged) {
      Android.onModeChanged(modeId);
    }
  } catch {
    /* embedded bridge optional */
  }
}

async function populateModeOptions() {
  const modes = await loadConversationModesFromApi();
  if (modeSelect && modes?.length) {
    modeSelect.innerHTML = "";
    for (const m of modes) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.emoji || ""} ${m.display_name || m.id}`.trim();
      modeSelect.appendChild(opt);
    }
    const saved = selectedConversationMode();
    if ([...modeSelect.options].some((o) => o.value === saved)) {
      modeSelect.value = saved;
    }
  }
  renderModePickerList(modes);
  renderExperienceHome(modes);
  if (inCall) renderVoiceModeStrip();
}

function renderBgmPickerList() {
  if (!bgmPickerList) return;
  const current = selectedBgmMode();
  bgmPickerList.innerHTML = "";
  for (const opt of BGM_OPTIONS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "settings-picker-option";
    btn.dataset.bgm = opt.value;
    btn.textContent = opt.label;
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", opt.value === current ? "true" : "false");
    if (opt.value === current) btn.classList.add("is-selected");
    btn.addEventListener("click", () => setSelectedBgm(opt.value));
    bgmPickerList.appendChild(btn);
  }
}

voiceSelect?.addEventListener("change", () => {
  localStorage.setItem(VOICE_STORAGE_KEY, voiceSelect.value);
});

dailyReminderToggle?.addEventListener("change", onDailyReminderToggleChange);

bgmSelect?.addEventListener("change", () => {
  try {
    localStorage.setItem(BGM_STORAGE_KEY, bgmSelect.value);
  } catch {
    /* ignore */
  }
});

function setLiveIndicator(on) {
  statusDot.classList.toggle("call-active", on);
  statusDot.classList.remove("offline");
}

function setVoiceStatus(text) {
  voiceStatus.textContent = text;
  if (voiceStatus) {
    voiceStatus.classList.toggle(
      "is-resuming",
      typeof text === "string" && text.includes("Menyambung ulang"),
    );
  }
}

function stopTtsPlayback() {
  if (!ttsAudio) return;
  try {
    ttsAudio.pause();
    ttsAudio.currentTime = 0;
  } catch {
    /* ignore */
  }
  if (ttsAudio._objectUrl) {
    URL.revokeObjectURL(ttsAudio._objectUrl);
    ttsAudio._objectUrl = null;
  }
  ttsAudio = null;
}

async function speakAssistantText(text) {
  if (!text || inCall) return;
  stopTtsPlayback();
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        voice_name: selectedVoiceName(),
        language_code: defaultLanguage,
      }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!data?.data) return;

    const binary = atob(data.data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: data.mime || "audio/wav" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio._objectUrl = url;
    ttsAudio = audio;
    await audio.play();
    audio.onended = () => stopTtsPlayback();
    audio.onerror = () => stopTtsPlayback();
  } catch {
    stopTtsPlayback();
  }
}

async function send() {
  const text = input.value.trim();
  if (!text || busy || inCall) return;
  await ensureSessionId();

  renderUser(text);
  input.value = "";
  input.style.height = "36px";
  charCount.textContent = "0";
  btnSend.disabled = true;
  busy = true;
  setPending(true);

  try {
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || res.statusText || `HTTP ${res.status}`);
    }
    renderAssistant(data);
    if (data.text && data.bdv !== "SILENCE" && data.bdv !== "DEFER") {
      void speakAssistantText(data.text);
    }
  } catch (e) {
    renderSystem(`Gagal kirim: ${e.message}`);
  } finally {
    setPending(false);
    busy = false;
    btnSend.disabled = !input.value.trim();
  }
}

async function ensureVoiceBackend() {
  const res = await fetch("/api/health", { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Backend belum siap — tunggu sebentar lalu coba lagi");
  }
  let data = await res.json();
  if (data.gemini_key_set === false && hasByokKey()) {
    await ensureByokFromStorage();
    const retry = await fetch("/api/health", { cache: "no-store" });
    if (retry.ok) {
      data = await retry.json();
    }
  }
  if (data.gemini_key_set === false) {
    if (!hasByokKey()) {
      throw new Error("Masukkan Gemini API key dulu — tap ⚙ Pengaturan.");
    }
    throw new Error("API key belum ke server lokal — tunggu sebentar lalu coba lagi.");
  }
  return data;
}

async function startCall() {
  if (inCall || liveCall) return;
  if (isEmbeddedApp) {
    await ensureByokFromStorage();
  }
  if (isEmbeddedApp && !hasByokKey()) {
    openSettings();
    renderSystem("Masukkan Gemini API key dulu ko — di pengaturan ⚙.");
    return;
  }
  try {
    await ensureVoiceBackend();
  } catch (e) {
    renderSystem(e.message || "Backend voice belum siap");
    return;
  }
  await ensureSessionId();
  dailyCheckInBanner?.classList.add("hidden");
  stopTtsPlayback();
  if (!navigator.mediaDevices?.getUserMedia) {
    renderSystem(
      isEmbeddedApp
        ? `Mikrofon tidak tersedia — pastikan izin mic diizinkan di pengaturan app ${personaLabel()}.`
        : "Browser ini tidak mendukung mikrofon. Buka di Chrome/Edge (HTTPS atau localhost)."
    );
    return;
  }

  setVoiceUi(true);
  setVoiceStatus("Menyambung…");
  voiceBars.classList.add("idle");
  syncWaveform({ mode: "connecting" });
  resumeBanner?.classList.add("hidden");
  onboarding?.classList.add("hidden");
  setCompanionOrbState("connecting");
  updateCompanionStage();

  let agentSpeaking = false;

  liveCall = new GeminiLiveCall({
    sessionId,
    voiceName: selectedVoiceName(),
    languageCode: defaultLanguage,
    onStatus(state) {
      if (state === "connecting") {
        setVoiceStatus("Menyambung…");
        setLiveIndicator(false);
        voiceBars.classList.add("idle");
        syncWaveform({ mode: "connecting" });
        setCompanionOrbState("connecting");
      } else if (state === "active") {
        setLiveIndicator(true);
        voiceBars.classList.remove("idle");
        setVoiceStatus(agentSpeaking ? `${personaLabel()} lagi ngomong…` : "Cerita aja");
        voiceBars.classList.toggle("agent-talking", agentSpeaking);
        voiceBars.classList.toggle("user-turn", !agentSpeaking);
        syncWaveform({ mode: agentSpeaking ? "agent" : "user" });
        setCompanionOrbState(agentSpeaking ? "speaking" : "listening");
      } else if (state === "ending") {
        setVoiceStatus("Mengakhiri…");
        voiceBars.classList.add("idle");
        syncWaveform({ mode: "idle" });
      } else if (state === "idle") {
        resetCallUi();
      }
    },
    onCallTimer(seconds) {
      if (voiceTimer) voiceTimer.textContent = formatCallTimer(seconds);
    },
    onAgentTalking(active) {
      agentSpeaking = active;
      if (!inCall) return;
      voiceBars.classList.toggle("agent-talking", active);
      voiceBars.classList.toggle("user-turn", !active);
      syncWaveform({ mode: active ? "agent" : "user" });
      if (liveCall?.active) {
        setVoiceStatus(active ? `${personaLabel()} lagi ngomong…` : "Cerita aja");
        setCompanionOrbState(active ? "speaking" : "listening");
      }
    },
    onPostCall(data) {
      handlePostCallData(data);
    },
    onAudioReady() {
      /* mic already live on active — full-duplex call pattern */
    },
    onMicStatus() {
      /* full-duplex: no separate mic status line */
    },
    onTranscript(role, text) {
      if (role === "user") renderUser(text);
      else renderAssistantText(text, "voice");
    },
    onGovernance(msg) {
      if (msg.bdv === "ACK_ONLY" || msg.bdv === "RESPOND" || msg.bdv === "pending") {
        return;
      }
      if ((msg.bdv === "SILENCE" || msg.bdv === "DEFER") && !msg.text) {
        return;
      }
      renderGovernance(msg.bdv, msg.text);
    },
    onNotice(msg) {
      renderSystem(msg);
      if (inCall && liveCall?.active) {
        setVoiceStatus("Cerita aja");
      }
    },
    onLinkState(state) {
      if (!inCall) return;
      if (state === "resuming" || state === "suspended") {
        setVoiceStatus("Menyambung ulang…");
        voiceBars.classList.add("idle");
        syncWaveform({ mode: "connecting", energy: 0.35 });
        setCompanionOrbState("connecting");
        return;
      }
      if (state === "disconnected") {
        setVoiceStatus("Koneksi putus");
        voiceBars.classList.add("idle");
        syncWaveform({ mode: "idle" });
        setCompanionOrbState("idle");
        renderSystem("Koneksi voice ke server putus — coba tutup dan mulai lagi.");
        return;
      }
      if ((state === "live" || state === "connected") && liveCall?.active) {
        voiceBars.classList.remove("idle");
        setLiveIndicator(true);
        setVoiceStatus(agentSpeaking ? `${personaLabel()} lagi ngomong…` : "Cerita aja");
        syncWaveform({ mode: agentSpeaking ? "agent" : "user" });
        setCompanionOrbState(agentSpeaking ? "speaking" : "listening");
      }
    },
    onConversationMode(modeId, changed) {
      if (!modeId) return;
      voiceModeStrip?.querySelectorAll(".voice-mode-pill[data-mode]").forEach((el) => {
        el.classList.toggle("is-active", el.dataset.mode === modeId);
        el.setAttribute("aria-selected", el.dataset.mode === modeId ? "true" : "false");
      });
      if (!changed) return;
      const meta =
        cachedExperienceModes?.find((m) => m.id === modeId) ||
        cachedConversationModes?.find((m) => m.id === modeId);
      const label = meta?.display_name || modeId;
      renderSystem(`Mode: ${label}`);
      if (meta?.tagline) syncExperienceTagline(meta.tagline);
    },
    onError(msg) {
      renderSystem(`Suara: ${msg}`);
      endCallUi();
    },
  });

  try {
    await liveCall.start();
  } catch (e) {
    renderSystem(`Suara: ${e.message}`);
    endCallUi();
  }
}

function resetCallUi() {
  setVoiceUi(false);
  setVoiceStatus("Menyambung…");
}

async function endCallUi() {
  if (endingCall) return;
  endingCall = true;
  setVoiceStatus("Mengakhiri…");
  const call = liveCall;
  liveCall = null;
  try {
    if (call) await call.stop();
  } finally {
    resetCallUi();
    endingCall = false;
    const postCall = await fetchPostCallWithRetry();
    if (postCall) handlePostCallData(postCall);
    else await syncAchievementsAfterCall();
  }
}

function bindPanelActions() {
  window.__personaActions = {
    btnCall() {
      if (inCall) void endCallUi();
      else void startCall();
    },
    btnSettings() {
      openSettings();
    },
    btnOnboardingNext() {
      void finishOnboarding();
    },
    btnOnboardingSkip() {
      skipOnboarding();
    },
    btnSettingsClose() {
      closeSettings();
    },
    btnSettingsSave() {
      void saveSettings();
    },
    btnBehaviorDebugRefresh() {
      void loadBehaviorDebugDashboard(true);
    },
    btnBehaviorExpStart() {
      void startBehaviorExperiment();
    },
    btnBehaviorConfigBump() {
      void bumpBehaviorConfigRevision();
    },
    btnMemoryRefresh() {
      void loadMemoryDashboard();
    },
    btnMemoryAdd() {
      void addManualMemory();
    },
    btnMemoryExport() {
      void exportMemoryJson();
    },
    btnMemoryReindex() {
      void reindexMemoryEmbeddings();
    },
    btnMemoryImport() {
      memoryImportFile?.click();
    },
    btnMemoryClearAll() {
      void clearAllMemory();
    },
    btnEndCall() {
      void endCallUi();
    },
    btnTextToggle() {
      textCompose?.classList.remove("hidden");
      btnTextToggle?.classList.add("hidden");
      input?.focus();
    },
  };
  const pending = window.__personaPendingTaps;
  if (Array.isArray(pending) && pending.length) {
    window.__personaPendingTaps = [];
    pending.forEach((id) => window.__personaTap(id));
  }
}

bindPanelActions();
ensureUiInteractive();

input?.addEventListener("input", () => {
  charCount.textContent = String(input.value.length);
  btnSend.disabled = !input.value.trim() || busy || inCall;
  input.style.height = "36px";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

input?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

if (isEmbeddedApp) {
  btnClose?.classList.add("hidden-in-app");
}

btnSend?.addEventListener("click", send);
btnClose?.addEventListener("click", () => {
  if (!isEmbeddedApp) panel.classList.add("hidden");
});

onboardingApiKey?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    void finishOnboarding();
  }
});

settings?.addEventListener("click", (e) => {
  if (e.target === settings) closeSettings();
});

settingsApiKey?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    void saveSettings();
  }
});

memoryImportFile?.addEventListener("change", () => {
  const file = memoryImportFile.files?.[0];
  if (memoryImportFile) memoryImportFile.value = "";
  if (file) void importMemoryJsonFile(file);
});
ragEnabledToggle?.addEventListener("change", scheduleCompanionPrefsSave);
ragGeminiToggle?.addEventListener("change", scheduleCompanionPrefsSave);
ragMinScore?.addEventListener("input", () => {
  if (ragMinScoreVal && ragMinScore) {
    ragMinScoreVal.textContent = Number(ragMinScore.value).toFixed(2);
  }
  scheduleCompanionPrefsSave();
});


btnResumeYes?.addEventListener("click", async () => {
  const id = resumeBanner?.dataset.sessionId;
  if (!id) return;
  sessionId = id;
  persistSessionId(id);
  resumeBanner.classList.add("hidden");
  await loadSessionHistoryFrom(id);
});

btnDailyCheckInCall?.addEventListener("click", () => {
  dismissDailyCheckInForToday();
  if (!inCall) void startCall();
});

btnDailyCheckInDismiss?.addEventListener("click", () => {
  dismissDailyCheckInForToday();
});

btnResumeNo?.addEventListener("click", () => {
  const id = resumeBanner?.dataset.sessionId;
  if (id) {
    void finalizeSessionMemory(id);
    try {
      localStorage.setItem(RESUME_SKIP_KEY, id);
    } catch {
      /* ignore */
    }
  }
  resumeBanner?.classList.add("hidden");
  void ensureSessionId();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && sessionId && !inCall) {
    void finalizeSessionMemory(sessionId);
  }
  if (document.visibilityState === "visible" && !inCall) {
    maybeIdleReindexEmbeddings();
  }
});

function showWelcomeHint() {
  updateCompanionStage();
}

async function loadHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (!res.ok) throw new Error("health failed");
    const serverReady = data.gemini_key_set !== false;
    const clientReady = hasByokKey();
    const connected = serverReady || (isEmbeddedApp && clientReady);
    cachedPersonaName = data.persona_name || "Papua Ai";
    statusDot.classList.toggle("offline", !connected);
    modelStatus.textContent = "PAPUA AI";
    defaultLanguage = data.default_language || "id-ID";
    populateVoiceOptions(data.live_voices, data.default_voice);
    populateBgmOptions();
    if (!serverReady && clientReady && isEmbeddedApp) {
      await ensureByokFromStorage();
    }
    updateCallButtonReady(serverReady || clientReady);
    if (!connected) {
      renderSystem(`${personaLabel()} belum tersambung — cek API key di pengaturan ⚙`);
    }
  } catch {
    cachedPersonaName = "Papua Ai";
    statusDot.classList.add("offline");
    modelStatus.textContent = "PAPUA AI";
    updateCallButtonReady(hasByokKey());
    renderSystem("Backend belum siap — tunggu sebentar lalu refresh");
  }
}

async function refreshAppHealth() {
  if (isEmbeddedApp) {
    await ensureByokFromStorage();
  }
  await loadHealth();
}

window.__personaRetryHealth = () => {
  void refreshAppHealth();
};

async function ensureSessionId() {
  if (sessionId) return sessionId;
  const suffix =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  sessionId = `web-${suffix}`;
  persistSessionId(sessionId);
  return sessionId;
}

async function loadSessionHistory() {
  await loadSessionHistoryFrom(sessionId);
}

(async () => {
  void GeminiLiveCall.preload();
  if (isEmbeddedApp) {
    await ensureByokFromStorage();
    if (!hasByokKey()) {
      await new Promise((resolve) => setTimeout(resolve, 350));
      await ensureByokFromStorage();
    }
  }
  await loadHealth();
  if (!sessionId) {
    await checkResumeBanner();
    await checkDailyCheckInBanner();
  } else {
    await loadSessionHistory();
  }
  showOnboardingIfNeeded();
  showWelcomeHint();
})();
