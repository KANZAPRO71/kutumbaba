/**
 * Panel UI — text chat + Gemini Live voice (pipeline sendiri, bukan Retell).
 */

const API = "/api/chat";

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
const voiceTimer = document.getElementById("voiceTimer");
const onboarding = document.getElementById("onboarding");
const btnOnboardingNext = document.getElementById("btnOnboardingNext");
const btnOnboardingSkip = document.getElementById("btnOnboardingSkip");
const onboardingApiKey = document.getElementById("onboardingApiKey");
const onboardingError = document.getElementById("onboardingError");
const onboardingProgress = document.getElementById("onboardingProgress");
const resumeBanner = document.getElementById("resumeBanner");
const resumeBannerText = document.getElementById("resumeBannerText");
const btnResumeYes = document.getElementById("btnResumeYes");
const btnResumeNo = document.getElementById("btnResumeNo");
const postCallCard = document.getElementById("postCallCard");
const postCallSummary = document.getElementById("postCallSummary");
const postCallMood = document.getElementById("postCallMood");
const btnPostCallClose = document.getElementById("btnPostCallClose");
const btnTextToggle = document.getElementById("btnTextToggle");
const textCompose = document.getElementById("textCompose");
const companionStage = document.getElementById("companionStage");
const companionOrbWrap = document.getElementById("companionOrbWrap");
const btnSettings = document.getElementById("btnSettings");
const settings = document.getElementById("settings");
const btnSettingsClose = document.getElementById("btnSettingsClose");
const settingsApiKey = document.getElementById("settingsApiKey");
const settingsError = document.getElementById("settingsError");
const settingsKeyStatus = document.getElementById("settingsKeyStatus");
const btnSettingsSave = document.getElementById("btnSettingsSave");
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
let cachedDefaultVoice = "Sulafat";
const BYOK_STORAGE_KEY = "persona_gemini_api_key";
const ONBOARDING_KEY = "persona_onboarding_v2";
const ONBOARDING_STEPS = 4;
/** Voice-first UI — no chat bubbles; orb stays visible. */
const SHOW_CHAT_TEXT = false;
const RESUME_SKIP_KEY = "persona_resume_skip_id";

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
  if (!SHOW_CHAT_TEXT) {
    if (message && voiceStatus && inCall) {
      setVoiceStatus(message.slice(0, 80));
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
  const label = btnCall.querySelector("span");
  if (label) label.textContent = active ? "Sedang ngobrol" : "Ngobrol";
  voiceBars.classList.toggle("idle", !active);
  voiceBars.classList.remove("agent-talking", "user-turn");
  if (voiceTimer) voiceTimer.textContent = "0:00";
  if (voiceSelect) voiceSelect.disabled = active;
  voicePickerList?.classList.toggle("is-disabled", active);
  bgmPickerList?.classList.toggle("is-disabled", active);
  if (!active) {
    statusDot.classList.remove("call-active");
    setCompanionOrbState("idle");
  }
  updateCompanionStage();
}

function sentimentLabel(value) {
  const v = String(value || "").toLowerCase();
  if (v.includes("posit")) return "Mood: ceria / lega";
  if (v.includes("neg")) return "Mood: agak berat";
  return "Mood: netral";
}

function showPostCallCard(data) {
  if (!SHOW_CHAT_TEXT || !postCallCard || !data) return;
  const summary =
    data.call_summary ||
    data.summary ||
    "Obrolan singkat tadi — lanjut kapan saja ya.";
  postCallSummary.textContent = summary;
  if (postCallMood) {
    const mood = data.user_sentiment ? sentimentLabel(data.user_sentiment) : "";
    postCallMood.textContent = mood;
    postCallMood.classList.toggle("hidden", !mood);
  }
  postCallCard.classList.remove("hidden");
}

function hidePostCallCard() {
  postCallCard?.classList.add("hidden");
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
        return body.post_call;
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
      showPostCallCard(data.post_call);
    }
  } catch {
    /* empty */
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
  settings.classList.remove("hidden");
  settings.hidden = false;
  if (settingsApiKey) {
    settingsApiKey.value = loadByokKey();
  }
  initProsodySimControls();
  populateBgmOptions();
  if (cachedLiveVoices?.length) {
    renderVoicePickerList();
  } else {
    void loadHealth();
  }
  renderBgmPickerList();
  updateSettingsKeyStatus();
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
  return voiceSelect?.value || localStorage.getItem(VOICE_STORAGE_KEY) || "Sulafat";
}

function populateVoiceOptions(voices, defaultVoice) {
  if (!voiceSelect || !Array.isArray(voices) || !voices.length) return;
  cachedLiveVoices = voices;
  cachedDefaultVoice = defaultVoice || voices[0]?.name || "Sulafat";
  const saved = localStorage.getItem(VOICE_STORAGE_KEY);
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
    btn.textContent = `${v.name} — ${v.style.toLowerCase()}`;
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
  const data = await res.json();
  if (data.gemini_key_set === false) {
    throw new Error("API key belum siap — rebuild APK dengan GEMINI_API_KEY di .env");
  }
  return data;
}

async function startCall() {
  if (inCall || liveCall) return;
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
  stopTtsPlayback();
  if (!navigator.mediaDevices?.getUserMedia) {
    renderSystem(
      isEmbeddedApp
        ? "Mikrofon tidak tersedia — pastikan izin mic diizinkan di pengaturan app Papua AI."
        : "Browser ini tidak mendukung mikrofon. Buka di Chrome/Edge (HTTPS atau localhost)."
    );
    return;
  }

  setVoiceUi(true);
  setVoiceStatus("Menyambung…");
  voiceBars.classList.add("idle");
  hidePostCallCard();
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
        setCompanionOrbState("connecting");
      } else if (state === "active") {
        setLiveIndicator(true);
        voiceBars.classList.remove("idle");
        setVoiceStatus(agentSpeaking ? "Papua AI lagi ngomong…" : "Cerita aja");
        voiceBars.classList.toggle("agent-talking", agentSpeaking);
        voiceBars.classList.toggle("user-turn", !agentSpeaking);
        setCompanionOrbState(agentSpeaking ? "speaking" : "listening");
      } else if (state === "ending") {
        setVoiceStatus("Mengakhiri…");
        voiceBars.classList.add("idle");
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
      if (liveCall?.active) {
        setVoiceStatus(active ? "Papua AI lagi ngomong…" : "Cerita aja");
        setCompanionOrbState(active ? "speaking" : "listening");
      }
    },
    onPostCall(data) {
      showPostCallCard(data);
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
    if (postCall) showPostCallCard(postCall);
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
    btnEndCall() {
      void endCallUi();
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

btnPostCallClose?.addEventListener("click", hidePostCallCard);

btnTextToggle?.addEventListener("click", () => {
  textCompose?.classList.remove("hidden");
  btnTextToggle?.classList.add("hidden");
  input?.focus();
});

btnResumeYes?.addEventListener("click", async () => {
  const id = resumeBanner?.dataset.sessionId;
  if (!id) return;
  sessionId = id;
  persistSessionId(id);
  resumeBanner.classList.add("hidden");
  await loadSessionHistoryFrom(id);
});

btnResumeNo?.addEventListener("click", () => {
  const id = resumeBanner?.dataset.sessionId;
  if (id) {
    try {
      localStorage.setItem(RESUME_SKIP_KEY, id);
    } catch {
      /* ignore */
    }
  }
  resumeBanner?.classList.add("hidden");
  void ensureSessionId();
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
    statusDot.classList.toggle("offline", !connected);
    modelStatus.textContent = "Papua AI";
    defaultLanguage = data.default_language || "id-ID";
    populateVoiceOptions(data.live_voices, data.default_voice);
    populateBgmOptions();
    if (!serverReady && clientReady && isEmbeddedApp) {
      await ensureByokFromStorage();
    }
    updateCallButtonReady(serverReady || clientReady);
    if (!connected) {
      renderSystem(`${data.persona_name || "Papua AI"} belum tersambung — cek API key di pengaturan ⚙`);
    }
  } catch {
    statusDot.classList.add("offline");
    modelStatus.textContent = "Papua AI";
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
  } else {
    await loadSessionHistory();
  }
  showOnboardingIfNeeded();
  showWelcomeHint();
})();
