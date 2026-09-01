/**
 * Gemini Live voice — full-duplex call over WS PCM.
 * Mic stays live during agent playback (AEC + barge-in grace).
 */

const INPUT_RATE = 16000;
const OUTPUT_RATE = 24000;
const WS_TIMEOUT_MS = 30000;
/** ~100 ms PCM @ 16 kHz — keeps WS/Gemini load sane vs AudioWorklet 128-sample quanta. */
const MIC_BATCH_SAMPLES = 1600;
/** Playback safety margin — absorbs WS/network jitter between audio chunks. */
const PLAYBACK_LOOKAHEAD_S = 0.10;
const PLAYBACK_UNDERRUN_SLIP_S = 0.012;
const MIN_PLAYABLE_PCM_BYTES = 480; // ~10 ms @ 24 kHz mono s16le
const BARGE_IN_SUSTAINED_FRAMES = 28;
const BARGE_IN_MIN_RMS = 0.042;
const BARGE_IN_GRACE_MS = 200;
const BARGE_IN_COOLDOWN_MS = 380;
const BARGE_IN_ECHO_GUARD = 1.22;
/** HP WebView: speaker lebih dekat ke mic — barge-in sedikit lebih ketat. */
const IS_EMBEDDED_APP =
  typeof location !== "undefined" &&
  new URLSearchParams(location.search).get("app") === "1";
const BARGE_IN_ECHO_GUARD_MOBILE = 1.28;
const MOBILE_BARGE_TIGHTEN = {
  rms_add: 0.008,
  grace_add_ms: 40,
  sustain_add_frames: 4,
  cooldown_add_ms: 60,
  min_rms: 0.048,
};
const MOBILE_MIC_TAIL_MS = 280;
const SOFT_BARGE_DUCK_MS = 480;
const DROP_AGENT_AUDIO_MS = 450;
const IGNORE_AGENT_FLOOR_MS = 900;
const SMART_BARGE_MIN_MS = 450;
const SMART_BARGE_CHALLENGES = [
  "ko tipu",
  "ko bohong",
  "stop sudah",
  "sudah cukup",
  "ganti mop",
  "tra lucu",
  "tra percaya",
  "bohong",
  "tipu sa",
  "diam sudah",
  "mop lain",
  "mop baru",
  "tunggu dulu",
  "tunggu",
  "stop",
  "diam",
  "eh ko",
  "cukup sudah",
  "potong",
  "tra usah",
];
const SMART_BARGE_FILLERS = new Set([
  "iyo", "iya", "ah", "eh", "em", "oh", "uh", "um", "hmm", "hm", "ee", "toh", "kah",
]);

const PROSODY_SIM_STORAGE_KEY = "papua_prosody_sim";

const MIC_WORKLET = `
class MicCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      const copy = new Float32Array(ch.length);
      copy.set(ch);
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}
registerProcessor("mic-capture", MicCaptureProcessor);
`;

const DEFAULT_VOICE_CONFIG = {
  responsiveness: 1,
  interruption_sensitivity: 1,
  enable_dynamic_responsiveness: true,
  enable_backchannel: true,
  backchannel_frequency: 0.8,
  start_speaker: "agent",
  barge_in_rms_threshold: 0.05,
  barge_in_grace_ms: 280,
  barge_in_sustain_frames: 36,
  barge_in_cooldown_ms: 450,
  smart_barge_min_ms: SMART_BARGE_MIN_MS,
};

function loadProsodySim() {
  try {
    const raw = localStorage.getItem(PROSODY_SIM_STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== "object") return null;
    return {
      speech_tempo: Number(data.speech_tempo) || 1,
      tone_pitch: Number(data.tone_pitch) || 1,
      mop_frequency: Number(data.mop_frequency) || 0.6,
    };
  } catch {
    return null;
  }
}

const BGM_STORAGE_KEY = "papua_bgm_mode";
const BGM_MODES = { off: "off", disko: "disko_tanah", hiphop: "hiphop_papua" };
const JEDAG_BURST_MS = 3000;

/** Musik latar tongkrongan — disko tanah pelan + jedag-jedug burst saat punchline. */
class TongkronganBgm {
  constructor(audioCtx) {
    this.ctx = audioCtx;
    this.mode = BGM_MODES.off;
    this.loopGain = null;
    this.burstGain = null;
    this.loopTimer = null;
    this.burstTimer = null;
    this.loopStep = 0;
    this.active = false;
  }

  _ensureGains() {
    if (!this.ctx) return;
    if (!this.loopGain) {
      this.loopGain = this.ctx.createGain();
      this.loopGain.gain.value = 0.15;
      this.loopGain.connect(this.ctx.destination);
    }
    if (!this.burstGain) {
      this.burstGain = this.ctx.createGain();
      this.burstGain.gain.value = 0.22;
      this.burstGain.connect(this.ctx.destination);
    }
  }

  setMode(mode) {
    this.mode = mode || BGM_MODES.off;
    if (this.mode === BGM_MODES.off) this.stopLoop();
    else if (this.active) this.startLoop(this.mode);
  }

  startLoop(mode) {
    if (!this.ctx) return;
    this.active = true;
    this.mode = mode || this.mode || BGM_MODES.disko;
    if (this.mode === BGM_MODES.off) return;
    this._ensureGains();
    this.stopLoop(false);
    const intervalMs = this.mode === BGM_MODES.hiphop ? 380 : 520;
    this.loopTimer = setInterval(() => this._tickLoop(), intervalMs);
  }

  stopLoop(clearActive = true) {
    if (this.loopTimer) {
      clearInterval(this.loopTimer);
      this.loopTimer = null;
    }
    if (clearActive) this.active = false;
  }

  _tickLoop() {
    if (!this.ctx || !this.loopGain) return;
    const t = this.ctx.currentTime;
    const isKick = this.loopStep % 2 === 0;
    const freq = this.mode === BGM_MODES.hiphop ? (isKick ? 90 : 180) : (isKick ? 110 : 220);
    this._playTone(this.loopGain, freq, 0.06, t, isKick ? 0.05 : 0.03);
    this.loopStep += 1;
  }

  playJedagBurst(durationMs = JEDAG_BURST_MS) {
    if (!this.ctx || this.mode === BGM_MODES.off) return;
    this._ensureGains();
    if (this.burstTimer) clearInterval(this.burstTimer);
    const start = performance.now();
    let beat = 0;
    this.burstTimer = setInterval(() => {
      const elapsed = performance.now() - start;
      if (elapsed >= durationMs) {
        clearInterval(this.burstTimer);
        this.burstTimer = null;
        return;
      }
      const t = this.ctx.currentTime;
      const kick = beat % 2 === 0;
      const freq = kick ? 95 : 200;
      this._playTone(this.burstGain, freq, kick ? 0.14 : 0.08, t, kick ? 0.07 : 0.04);
      beat += 1;
    }, 160);
  }

  _playTone(gainNode, freq, volume, when, duration) {
    if (!this.ctx || !gainNode) return;
    const osc = this.ctx.createOscillator();
    const env = this.ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    env.gain.setValueAtTime(0.0001, when);
    env.gain.exponentialRampToValueAtTime(Math.max(volume, 0.001), when + 0.008);
    env.gain.exponentialRampToValueAtTime(0.0001, when + duration);
    osc.connect(env);
    env.connect(gainNode);
    osc.start(when);
    osc.stop(when + duration + 0.02);
  }

  release() {
    this.stopLoop();
    if (this.burstTimer) {
      clearInterval(this.burstTimer);
      this.burstTimer = null;
    }
    try {
      this.loopGain?.disconnect();
      this.burstGain?.disconnect();
    } catch {
      /* ignore */
    }
    this.loopGain = null;
    this.burstGain = null;
  }
}

function loadBgmMode() {
  try {
    const raw = localStorage.getItem(BGM_STORAGE_KEY);
    if (raw === BGM_MODES.disko || raw === BGM_MODES.hiphop) return raw;
    if (raw === "off") return BGM_MODES.off;
    return BGM_MODES.off;
  } catch {
    return BGM_MODES.off;
  }
}

function saveBgmMode(mode) {
  try {
    localStorage.setItem(BGM_STORAGE_KEY, mode || BGM_MODES.off);
  } catch {
    /* ignore */
  }
}

class GeminiLiveCall {
  /** Warm AudioContext like Retell SDK preload on widget mount. */
  static async preload() {
    try {
      const ctx = new AudioContext({ latencyHint: "interactive" });
      const buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      src.start();
      if (ctx.state === "suspended") await ctx.resume();
      await ctx.close();
    } catch {
      /* private mode / autoplay policy */
    }
  }

  constructor({
    sessionId,
    voiceName,
    languageCode,
    onStatus,
    onTranscript,
    onError,
    onGovernance,
    onNotice,
    onPostCall,
    onAudioReady,
    onMicStatus,
    onAgentTalking,
    onCallTimer,
  }) {
    this.sessionId = sessionId;
    this.voiceName = voiceName || "Leda";
    this.languageCode = languageCode || "id-ID";
    this.onStatus = onStatus || (() => {});
    this.onTranscript = onTranscript || (() => {});
    this.onError = onError || (() => {});
    this.onGovernance = onGovernance || (() => {});
    this.onNotice = onNotice || (() => {});
    this.onPostCall = onPostCall || (() => {});
    this.onAudioReady = onAudioReady || (() => {});
    this.onMicStatus = onMicStatus || (() => {});
    this.onAgentTalking = onAgentTalking || (() => {});
    this.onCallTimer = onCallTimer || (() => {});

    this.ws = null;
    this.audioCtx = null;
    this.mediaStream = null;
    this.captureNode = null;
    this.source = null;
    this.playGain = null;
    this.playTime = 0;
    this.active = false;
    this._connected = false;
    this._isActive = false;
    this._stopping = false;
    this._voiceConfig = { ...DEFAULT_VOICE_CONFIG };
    this._callConfig = {
      enable_keypad_detection: false,
      keypad_timeout_ms: 2500,
      end_call_on_silence_ms: 600000,
      max_call_duration_ms: 3600000,
    };
    this._keypadListener = null;
    this._playbackSources = new Set();
    this._agentSpeaking = false;
    this._agentSpeakingSince = 0;
    this._bargeInCooldown = 0;
    this._bargeInHighFrames = 0;
    this._bargeSpeechSince = 0;
    this._audioReady = false;
    this._audioQueue = [];
    this._playbackChain = Promise.resolve();
    this._micEnabled = false;
    this._micFramesSent = 0;
    this._micBatch = new Float32Array(0);
    this._micFallbackTimer = null;
    this._micAfterPlaybackTimer = null;
    this._duckTimer = null;
    this._inputRate = INPUT_RATE;
    this._dropAgentAudioUntil = 0;
    this._ignoreAgentFloorUntil = 0;
    this._floor = "user";
    this._naturalS2S = true;
    this._callTimer = null;
    this._callSeconds = 0;
    this._agentTalking = false;
    this._lastLatency = null;
    this._connectStartedAt = 0;
    this._reconnectAttempts = 0;
    this._sawServerError = false;
    this._reconnectInFlight = false;
    this._reconnectTimer = null;
    this._disconnectNotified = false;
    this._bgm = null;
    this._wsGeneration = 0;
  }

  _detachSocket(ws) {
    if (!ws) return;
    ws.onopen = null;
    ws.onclose = null;
    ws.onerror = null;
    ws.onmessage = null;
  }

  _isGeminiSessionExpiry(message) {
    const text = String(message || "").toLowerCase();
    const compact = text.replace(/[\s_]/g, "");
    const code = (text.match(/^(\d{4})\b/) || [])[1];
    return (
      compact.includes("goaway") ||
      ["1000", "1001", "1005", "1006", "1008", "1011"].includes(code) ||
      text.includes("session durat") ||
      text.includes("sesi voice gemini habis") ||
      text.includes("sesi gemini habis")
    );
  }

  _wsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const host = location.host || "127.0.0.1:8765";
    return `${proto}//${host}/api/live/ws`;
  }

  async _openWebSocket(wsGeneration, pending, maxAttempts = 3) {
    let lastErr = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        await this._connectWebSocketOnce(wsGeneration, pending);
        return;
      } catch (err) {
        lastErr = err;
        if (attempt < maxAttempts) {
          await new Promise((r) => setTimeout(r, 600 * attempt));
        }
      }
    }
    throw lastErr || new Error("WebSocket gagal terhubung");
  }

  _connectWebSocketOnce(wsGeneration, pending) {
    return new Promise((resolve, reject) => {
      if (this.ws) {
        try {
          this.ws.onopen = null;
          this.ws.onerror = null;
          this.ws.onclose = null;
          this.ws.close();
        } catch {
          /* ignore */
        }
        this.ws = null;
      }

      this.ws = new WebSocket(this._wsUrl());
      this.ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (this._connected) {
          this._handleMessage(msg);
        } else {
          pending.push(msg);
        }
      };
      this.ws.onclose = () => this._onSocketClose(wsGeneration);

      const timer = setTimeout(() => {
        reject(new Error("Timeout — server voice tidak merespons"));
      }, WS_TIMEOUT_MS);

      this.ws.onopen = () => {
        clearTimeout(timer);
        const sessionPayload = {
          type: "session",
          session_id: this.sessionId,
          voice_name: this.voiceName,
          language_code: this.languageCode,
          dialect: "papua",
        };
        if (IS_EMBEDDED_APP) {
          sessionPayload.embedded_app = true;
          const sim = loadProsodySim();
          if (sim) sessionPayload.papua_prosody_sim = sim;
        }
        this.ws.send(JSON.stringify(sessionPayload));
        resolve();
      };

      this.ws.onerror = () => {
        clearTimeout(timer);
        reject(
          new Error(
            new URLSearchParams(location.search).get("app") === "1"
              ? "Koneksi suara gagal — tunggu sebentar lalu coba lagi"
              : "Koneksi suara gagal — pastikan server jalan lalu refresh halaman"
          )
        );
      };
    });
  }

  _applyVoiceConfig(cfg) {
    if (!cfg || typeof cfg !== "object") return;
    let merged = { ...DEFAULT_VOICE_CONFIG, ...cfg };
    if (IS_EMBEDDED_APP) {
      const t = MOBILE_BARGE_TIGHTEN;
      merged = {
        ...merged,
        barge_in_rms_threshold:
          (merged.barge_in_rms_threshold ?? DEFAULT_VOICE_CONFIG.barge_in_rms_threshold) +
          t.rms_add,
        barge_in_grace_ms:
          (merged.barge_in_grace_ms ?? DEFAULT_VOICE_CONFIG.barge_in_grace_ms) + t.grace_add_ms,
        barge_in_sustain_frames:
          (merged.barge_in_sustain_frames ?? DEFAULT_VOICE_CONFIG.barge_in_sustain_frames) +
          t.sustain_add_frames,
        barge_in_cooldown_ms:
          (merged.barge_in_cooldown_ms ?? DEFAULT_VOICE_CONFIG.barge_in_cooldown_ms) +
          t.cooldown_add_ms,
      };
    }
    this._voiceConfig = merged;
  }

  _applyCallConfig(cfg) {
    if (!cfg || typeof cfg !== "object") return;
    this._callConfig = { ...this._callConfig, ...cfg };
    if (this._callConfig.enable_keypad_detection) {
      this._enableKeypadListener();
    } else {
      this._disableKeypadListener();
    }
  }

  _enableKeypadListener() {
    if (this._keypadListener) return;
    this._keypadListener = (ev) => {
      if (!this.active || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
      const tag = (ev.target && ev.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      let digit = null;
      if (ev.key >= "0" && ev.key <= "9") digit = ev.key;
      else if (ev.key === "#" || ev.key === "*") digit = ev.key;
      if (!digit) return;
      ev.preventDefault();
      this.ws.send(JSON.stringify({ type: "keypad", digit }));
    };
    window.addEventListener("keydown", this._keypadListener);
  }

  _disableKeypadListener() {
    if (!this._keypadListener) return;
    window.removeEventListener("keydown", this._keypadListener);
    this._keypadListener = null;
  }

  _restorePlaybackGain() {
    if (this._duckTimer) {
      clearTimeout(this._duckTimer);
      this._duckTimer = null;
    }
    if (!this.playGain || !this.audioCtx) return;
    const t = this.audioCtx.currentTime;
    this.playGain.gain.cancelScheduledValues(t);
    this.playGain.gain.setValueAtTime(1, t);
    this.playGain.gain.value = 1;
  }

  _ensureFullPlaybackGain() {
    if (!this.playGain || !this.audioCtx) return;
    const v = this.playGain.gain.value;
    if (v >= 0.98 && !this._duckTimer) return;
    this._restorePlaybackGain();
  }

  _flushPlayback({ soft = false } = {}) {
    this.playTime = 0;
    this._bargeInHighFrames = 0;
    this._bargeSpeechSince = 0;
    this._audioQueue = [];
    if (!soft) {
      this._dropAgentAudioUntil = performance.now() + DROP_AGENT_AUDIO_MS;
    } else {
      this._dropAgentAudioUntil = 0;
    }
    for (const src of this._playbackSources) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this._playbackSources.clear();
    if (!soft) {
      this._agentSpeaking = false;
      this._agentSpeakingSince = 0;
      this._setAgentTalking(false);
    }
    this._playbackChain = Promise.resolve();
    this._restorePlaybackGain();
  }

  _duckPlayback(ms = SOFT_BARGE_DUCK_MS, onDone, { hardCut = false } = {}) {
    if (this._duckTimer) {
      clearTimeout(this._duckTimer);
      this._duckTimer = null;
    }
    if (!this.audioCtx || !this.playGain) {
      if (hardCut) this._flushPlayback({ soft: true });
      onDone?.();
      return;
    }
    const duckMs = Math.max(120, ms);
    const t0 = this.audioCtx.currentTime;
    const duckLevel = hardCut ? 0.05 : 0.35;
    this.playGain.gain.cancelScheduledValues(t0);
    this.playGain.gain.setValueAtTime(Math.max(this.playGain.gain.value, 0.2), t0);
    this.playGain.gain.linearRampToValueAtTime(duckLevel, t0 + duckMs / 2000);
    this.playGain.gain.linearRampToValueAtTime(1, t0 + duckMs / 1000 + 0.06);
    this._duckTimer = setTimeout(() => {
      this._duckTimer = null;
      if (hardCut) this._flushPlayback({ soft: true });
      this._restorePlaybackGain();
      onDone?.();
    }, duckMs + 80);
  }

  _setAgentTalking(active) {
    if (this._agentTalking === active) return;
    this._agentTalking = active;
    this.onAgentTalking(active);
  }

  _startCallTimer() {
    this._stopCallTimer();
    this._callSeconds = 0;
    this.onCallTimer(0);
    this._callTimer = setInterval(() => {
      this._callSeconds += 1;
      this.onCallTimer(this._callSeconds);
    }, 1000);
  }

  _stopCallTimer() {
    if (this._callTimer) {
      clearInterval(this._callTimer);
      this._callTimer = null;
    }
  }

  _isChallengeInterrupt(text) {
    const q = String(text || "")
      .trim()
      .toLowerCase();
    if (!q) return false;
    return SMART_BARGE_CHALLENGES.some((phrase) => q.includes(phrase));
  }

  _isFillerOnly(text) {
    const q = String(text || "")
      .trim()
      .toLowerCase();
    if (!q) return true;
    const words = q.split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    if (words.length === 1 && SMART_BARGE_FILLERS.has(words[0])) return true;
    return q.length <= 4 && SMART_BARGE_FILLERS.has(q);
  }

  _shouldSmartBarge(text) {
    const q = String(text || "").trim();
    if (!q) return false;
    if (this._isChallengeInterrupt(q)) return true;
    const words = q.split(/\s+/).filter(Boolean);
    return words.length >= 2 && !this._isFillerOnly(q);
  }

  _executeBargeIn(transcript = "") {
    const now = performance.now();
    this._bargeInCooldown = now;
    this._bargeInHighFrames = 0;
    this._bargeSpeechSince = 0;
    this._ignoreAgentFloorUntil = now + IGNORE_AGENT_FLOOR_MS;
    const hasTranscript = Boolean(String(transcript || "").trim());
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "barge_in", transcript: transcript || "" }));
    }
    const finish = () => this._applyFloor("user", "barge_in");
    if (IS_EMBEDDED_APP && !hasTranscript) {
      this._duckPlayback(SOFT_BARGE_DUCK_MS, finish, { hardCut: false });
      return;
    }
    this._duckPlayback(SOFT_BARGE_DUCK_MS, finish, { hardCut: hasTranscript });
  }

  _maybeSmartBargeIn(text, finished) {
    if (this._floor !== "agent" && !this._agentSpeaking && !this._playbackBusy()) return;
    if (!text) return;
    const q = String(text).trim();
    if (!this._shouldSmartBarge(q)) return;
    const challenge = this._isChallengeInterrupt(q);
    const minMs = challenge
      ? (this._voiceConfig.smart_barge_min_ms ?? SMART_BARGE_MIN_MS)
      : 520;
    const since = this._bargeSpeechSince || performance.now();
    const duration = performance.now() - since;
    if (duration < minMs && !finished && !challenge) return;
    if (typeof console !== "undefined" && console.info) {
      console.info("[persona smart barge-in]", { text: q.slice(0, 80), duration, challenge });
    }
    this._executeBargeIn(q);
  }

  _maybeBargeIn(input) {
    if (this._floor !== "agent" && !this._agentSpeaking && !this._playbackBusy()) return;
    const now = performance.now();
    const grace = this._voiceConfig.barge_in_grace_ms ?? BARGE_IN_GRACE_MS;
    const cooldown = this._voiceConfig.barge_in_cooldown_ms ?? BARGE_IN_COOLDOWN_MS;
    const sustain = this._voiceConfig.barge_in_sustain_frames ?? BARGE_IN_SUSTAINED_FRAMES;
    if (now - this._agentSpeakingSince < grace) return;
    if (now - this._bargeInCooldown < cooldown) return;

    let sum = 0;
    for (let i = 0; i < input.length; i++) {
      sum += input[i] * input[i];
    }
    const rms = Math.sqrt(sum / input.length);
    const minRms = IS_EMBEDDED_APP ? MOBILE_BARGE_TIGHTEN.min_rms : BARGE_IN_MIN_RMS;
    let threshold = Math.max(
      this._voiceConfig.barge_in_rms_threshold ??
        DEFAULT_VOICE_CONFIG.barge_in_rms_threshold,
      minRms
    );
    if (this._agentSpeaking || this._playbackBusy()) {
      threshold *= IS_EMBEDDED_APP ? BARGE_IN_ECHO_GUARD_MOBILE : BARGE_IN_ECHO_GUARD;
    }

    if (rms > threshold) {
      if (!this._bargeSpeechSince) this._bargeSpeechSince = now;
      this._bargeInHighFrames += 1;
      if (this._bargeInHighFrames < sustain) return;
      this._bargeInCooldown = now;
      this._bargeInHighFrames = 0;
      this._bargeSpeechSince = 0;
      if (typeof console !== "undefined" && console.info) {
        console.info("[persona barge-in]", { rms: rms.toFixed(3), threshold: threshold.toFixed(3) });
      }
      this._executeBargeIn();
    } else {
      this._bargeInHighFrames = 0;
      this._bargeSpeechSince = 0;
    }
  }

  async start() {
    if (this.active) return;
    this.active = true;
    this._stopping = false;
    this._reconnectAttempts = 0;
    this._sawServerError = false;
    this._reconnectInFlight = false;
    this._disconnectNotified = false;
    this._connectStartedAt = performance.now();
    this.onStatus("connecting");

    try {
      await this._acquireMicStream();
      await this._initAudioContext();
    } catch (err) {
      this.active = false;
      throw this._micError(err);
    }

    const pending = [];
    this._wsGeneration += 1;
    const wsGeneration = this._wsGeneration;

    try {
      await this._openWebSocket(wsGeneration, pending);

      this._connected = true;
      const activePromise = this._waitForActive();
      for (const msg of pending) {
        this._handleMessage(msg);
      }

      await activePromise;
      await this._connectMicPipeline();
      this._audioReady = true;
      await this._flushAudioQueue();
      this._enableMicSend("call_started");
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "client_ready", session_id: this.sessionId }));
      }
      this._armMicAfterPlayback();
      this._startCallTimer();
      this.onAudioReady();
      this.onStatus("active");
      this.onMicStatus({ active: true, reason: "call_started" });
      if (typeof console !== "undefined" && console.info) {
        console.info("[persona latency] client_connect_ms=", Math.round(performance.now() - this._connectStartedAt));
      }
    } catch (err) {
      this.active = false;
      this._teardown(false);
      throw err;
    }
  }

  _failDisconnected() {
    if (this._disconnectNotified || this._stopping) return;
    this._disconnectNotified = true;
    this._stopping = true;
    this.active = false;
    this.onError("Koneksi voice terputus");
    this._teardown(false);
    this.onStatus("idle");
  }

  _onSocketClose(generation) {
    if (generation != null && generation !== this._wsGeneration) return;
    if (!this.active || this._stopping) return;
    if (this._sawServerError) {
      this._teardown(false);
      this.onStatus("idle");
      return;
    }
    if (this._reconnectInFlight || this._reconnectTimer) return;
    if (this._reconnectAttempts < 3) {
      this._reconnectAttempts += 1;
      const delay = Math.min(800 * Math.pow(1.5, this._reconnectAttempts - 1), 4000);
      if (typeof console !== "undefined" && console.info) {
        console.info(`[persona live] soft reconnect attempt ${this._reconnectAttempts}/3 in ${Math.round(delay)}ms`);
      }
      this._reconnectTimer = setTimeout(() => {
        this._reconnectTimer = null;
        if (this.active && !this._stopping) void this._softReconnect();
      }, delay);
      return;
    }
    this._failDisconnected();
  }

  async _softReconnect() {
    if (!this.active || this._stopping || this._reconnectInFlight) return;
    this._reconnectInFlight = true;
    this.onStatus("connecting");
    this._connected = false;
    this._isActive = false;
    this._sawServerError = false;
    this._detachSocket(this.ws);
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
    this._wsGeneration += 1;
    const wsGeneration = this._wsGeneration;
    const pending = [];
    try {
      this.ws = new WebSocket(this._wsUrl());
      this.ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (this._connected) this._handleMessage(msg);
        else pending.push(msg);
      };
      this.ws.onclose = () => this._onSocketClose(wsGeneration);
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          reject(new Error("Timeout reconnect"));
        }, WS_TIMEOUT_MS);
        this.ws.onopen = () => {
          clearTimeout(timer);
          const sessionPayload = {
            type: "session",
            session_id: this.sessionId,
            voice_name: this.voiceName,
            language_code: this.languageCode,
            dialect: "papua",
          };
          if (IS_EMBEDDED_APP) {
            sessionPayload.embedded_app = true;
          }
          this.ws.send(JSON.stringify(sessionPayload));
          resolve();
        };
        this.ws.onerror = () => {
          clearTimeout(timer);
          reject(new Error("WebSocket reconnect gagal"));
        };
      });
      this._connected = true;
      const activePromise = this._waitForActive();
      for (const msg of pending) this._handleMessage(msg);
      await activePromise;
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "client_ready", session_id: this.sessionId }));
      }
      this._reconnectAttempts = 0;
      this._sawServerError = false;
      this._reconnectInFlight = false;
      this._armMicAfterPlayback();
      this.onStatus("active");
    } catch (err) {
      this._reconnectInFlight = false;
      if (this.active && !this._stopping) this._onSocketClose(wsGeneration);
    }
  }

  _micError(err) {
    const name = err?.name || "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return new Error("Izin mikrofon ditolak — izinkan akses mic di browser");
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return new Error("Mikrofon tidak ditemukan");
    }
    return err instanceof Error ? err : new Error(String(err));
  }

  async _acquireMicStream() {
    const base = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    };
    const attempts = [
      { ...base, sampleRate: 16000, voiceIsolation: true },
      { ...base, sampleRate: 16000 },
      base,
    ];
    let lastErr;
    for (const audio of attempts) {
      try {
        this.mediaStream = await navigator.mediaDevices.getUserMedia({
          audio,
          video: false,
        });
        return;
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr;
  }

  async _initAudioContext() {
    this.audioCtx = new AudioContext({ latencyHint: "interactive" });
    this._inputRate = this.audioCtx.sampleRate;
    this.playGain = this.audioCtx.createGain();
    this.playGain.gain.value = 1;
    this.playGain.connect(this.audioCtx.destination);
    await this._unlockAudioOutput();
    this._applyBgmSettings();
  }

  _applyBgmSettings() {
    if (!this.audioCtx) return;
    const bgmMode = loadBgmMode();
    const useNative =
      typeof PersonaAndroid !== "undefined" && PersonaAndroid.startBgm;
    if (bgmMode === BGM_MODES.off) {
      if (this._bgm) this._bgm.setMode(BGM_MODES.off);
      if (useNative && PersonaAndroid.stopBgm) {
        PersonaAndroid.stopBgm();
      }
      return;
    }
    // Android: one layer only — native mp3 when res/raw has assets (no ToneGenerator).
    if (useNative) {
      if (this._bgm) this._bgm.setMode(BGM_MODES.off);
      PersonaAndroid.startBgm(bgmMode);
      return;
    }
    if (!this._bgm) this._bgm = new TongkronganBgm(this.audioCtx);
    this._bgm.setMode(bgmMode);
    this._bgm.startLoop(bgmMode);
  }

  async _unlockAudioOutput() {
    if (!this.audioCtx) return;
    const buffer = this.audioCtx.createBuffer(1, 1, this.audioCtx.sampleRate);
    const src = this.audioCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.playGain);
    src.start();
    if (this.audioCtx.state === "suspended") {
      await this.audioCtx.resume();
    }
    if (this.audioCtx.state !== "running") {
      throw new Error(
        "Audio browser diblokir — pastikan tab tidak mute dan izinkan suara untuk situs ini"
      );
    }
  }

  _enableMicSend(reason) {
    if (this._micEnabled) return;
    this._micEnabled = true;
    if (this._micFallbackTimer) {
      clearTimeout(this._micFallbackTimer);
      this._micFallbackTimer = null;
    }
    // Flush any PCM captured while mic send was gated.
    if (this._micBatch.length >= MIC_BATCH_SAMPLES) {
      while (this._micBatch.length >= MIC_BATCH_SAMPLES) {
        const chunk = this._micBatch.slice(0, MIC_BATCH_SAMPLES);
        this._micBatch = this._micBatch.slice(MIC_BATCH_SAMPLES);
        this._flushMicChunk(chunk);
      }
    }
    this.onMicStatus({ active: true, reason, framesSent: this._micFramesSent });
  }

  _coerceFloat32(data) {
    if (data instanceof Float32Array) return data;
    if (data instanceof ArrayBuffer) return new Float32Array(data);
    if (ArrayBuffer.isView(data)) return new Float32Array(data.buffer, data.byteOffset, data.byteLength / 4);
    return null;
  }

  _playbackBusy() {
    if (!this.audioCtx) return false;
    if (this._playbackSources.size > 0) return true;
    return this.playTime > this.audioCtx.currentTime + 0.04;
  }

  _armMicAfterPlayback() {
    if (this._micAfterPlaybackTimer) {
      clearTimeout(this._micAfterPlaybackTimer);
      this._micAfterPlaybackTimer = null;
    }
    if (this._duckTimer) {
      clearTimeout(this._duckTimer);
      this._duckTimer = null;
    }
    const finish = () => {
      this._micAfterPlaybackTimer = null;
      if (!this.active || !this.audioCtx) return;
      this._agentSpeaking = false;
      this._agentSpeakingSince = 0;
      this._setAgentTalking(false);
      this._enableMicSend("playback_drained");
    };
    const wait = () => {
      this._micAfterPlaybackTimer = null;
      if (!this.active || !this.audioCtx) return;
      if (this._playbackBusy()) {
        this._micAfterPlaybackTimer = setTimeout(wait, 40);
        return;
      }
      if (IS_EMBEDDED_APP) {
        // One tail delay after agent audio — then re-enable mic (was looping forever).
        this._micAfterPlaybackTimer = setTimeout(finish, MOBILE_MIC_TAIL_MS);
        return;
      }
      finish();
    };
    wait();
  }

  _sendMicPcm(input) {
    if (!this._micEnabled) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this._isActive) return;
    // Natural S2S: full-duplex mic — server-side echo filter; needed for barge-in.
    if (!this._naturalS2S) {
      if (this._floor === "agent") return;
      if (IS_EMBEDDED_APP && this._agentSpeaking && this._floor === "agent") return;
      if (this._playbackBusy()) return;
    }
    const down = downsample(input, this._inputRate, INPUT_RATE);
    if (!down.length) return;

    const merged = new Float32Array(this._micBatch.length + down.length);
    merged.set(this._micBatch);
    merged.set(down, this._micBatch.length);
    this._micBatch = merged;

    while (this._micBatch.length >= MIC_BATCH_SAMPLES) {
      const chunk = this._micBatch.slice(0, MIC_BATCH_SAMPLES);
      this._micBatch = this._micBatch.slice(MIC_BATCH_SAMPLES);
      this._flushMicChunk(chunk);
    }
  }

  _flushMicChunk(float32) {
    if (!float32.length) return;
    const pcm = floatTo16BitPCM(float32);
    this.ws.send(
      JSON.stringify({
        type: "audio",
        session_id: this.sessionId,
        data: arrayBufferToBase64(pcm.buffer.slice(0, pcm.byteLength)),
      })
    );
    this._micFramesSent += 1;
    if (this._micFramesSent === 1) {
      this.onMicStatus({ active: true, framesSent: 1 });
    }
  }

  async _connectMicPipeline() {
    if (!this.mediaStream || !this.audioCtx || this.captureNode) return;

    const tracks = this.mediaStream.getAudioTracks();
    if (!tracks.length || !tracks[0].enabled) {
      throw new Error("Track mikrofon tidak aktif");
    }
    this.onMicStatus({ active: false, reason: "pipeline_connecting", label: tracks[0].label });

    try {
      const blob = new Blob([MIC_WORKLET], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      await this.audioCtx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      this.source = this.audioCtx.createMediaStreamSource(this.mediaStream);
      this.captureNode = new AudioWorkletNode(this.audioCtx, "mic-capture");
      const mute = this.audioCtx.createGain();
      mute.gain.value = 0;

      this.captureNode.port.onmessage = (ev) => {
        const input = this._coerceFloat32(ev.data);
        if (!input || !input.length) return;
        this._maybeBargeIn(input);
        this._sendMicPcm(input);
      };

      this.source.connect(this.captureNode);
      this.captureNode.connect(mute);
      mute.connect(this.audioCtx.destination);
      this.onMicStatus({ active: false, reason: "pipeline_ready", label: tracks[0].label });
    } catch (workletErr) {
      this._connectMicPipelineLegacy(workletErr);
    }
  }

  _connectMicPipelineLegacy(cause) {
    console.warn("AudioWorklet unavailable, falling back to ScriptProcessor", cause);
    if (!this.mediaStream || !this.audioCtx) return;

    const tracks = this.mediaStream.getAudioTracks();
    this.source = this.audioCtx.createMediaStreamSource(this.mediaStream);
    const processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
    const mute = this.audioCtx.createGain();
    mute.gain.value = 0;

    processor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      this._maybeBargeIn(input);
      this._sendMicPcm(input);
    };

    this.source.connect(processor);
    processor.connect(mute);
    mute.connect(this.audioCtx.destination);
    this.captureNode = processor;
    this.onMicStatus({
      active: false,
      reason: "pipeline_ready_legacy",
      label: tracks[0]?.label || "",
    });
  }

  async _ensureAudioReady() {
    if (!this.audioCtx) return;
    if (this.audioCtx.state === "suspended") {
      await this.audioCtx.resume();
    }
  }

  async _flushAudioQueue() {
    const queued = this._audioQueue.splice(0);
    for (const msg of queued) {
      await this._playPcm(msg.data, parseSampleRate(msg.mime) || OUTPUT_RATE);
    }
  }

  _queueOrPlayAudio(msg) {
    if (!msg?.data) return;
    if (performance.now() < this._dropAgentAudioUntil) return;
    this._dropAgentAudioUntil = 0;
    this._ensureFullPlaybackGain();
    if (!this._agentSpeaking) {
      this._agentSpeakingSince = performance.now();
      this._agentSpeaking = true;
      this._setAgentTalking(true);
    }
    if (!this._audioReady || !this.audioCtx) {
      this._audioQueue.push(msg);
      return;
    }
    this._playbackChain = this._playbackChain
      .then(() => this._playPcm(msg.data, parseSampleRate(msg.mime) || OUTPUT_RATE))
      .catch((err) => {
        console.warn("playback failed", err);
      });
  }

  _applyFloor(speaker, reason) {
    if (speaker !== "agent" && speaker !== "user") return;
    if (speaker === "agent" && performance.now() < (this._ignoreAgentFloorUntil || 0)) {
      if (typeof console !== "undefined" && console.info) {
        console.info("[persona floor] ignore agent after barge-in", reason || "");
      }
      return;
    }
    if (speaker === "agent") {
      this._floor = speaker;
      if (!this._naturalS2S) {
        this._micEnabled = false;
      }
      if (!this._agentSpeaking) this._agentSpeakingSince = performance.now();
      this._agentSpeaking = true;
      return;
    }
    if (reason === "barge_in") {
      this._floor = "user";
      this._agentSpeaking = false;
      this._agentSpeakingSince = 0;
      this._setAgentTalking(false);
      this._enableMicSend("barge_in");
      return;
    }
    // Keep floor=agent until playback drains — prevents echo ASR on governed mode.
    if (this._playbackBusy() && !this._naturalS2S) {
      this._armMicAfterPlayback();
      return;
    }
    this._floor = speaker;
    this._agentSpeaking = false;
    this._agentSpeakingSince = 0;
    this._setAgentTalking(false);
    this._armMicAfterPlayback();
  }

  _waitForActive() {
    if (this._isActive) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error("Timeout — suara Mince tidak aktif"));
      }, WS_TIMEOUT_MS);
      this._activeResolve = () => {
        clearTimeout(timer);
        resolve();
      };
      this._activeReject = (err) => {
        clearTimeout(timer);
        reject(err);
      };
    });
  }

  _handleMessage(msg) {
    switch (msg.type) {
      case "status":
        if (msg.voice_config) {
          this._applyVoiceConfig(msg.voice_config);
        }
        if (msg.live_mode?.mode === "natural") {
          this._naturalS2S = true;
        } else if (msg.live_mode?.mode === "governed") {
          this._naturalS2S = false;
        }
        if (msg.call_config) {
          this._applyCallConfig(msg.call_config);
        }
        if (msg.state === "active") {
          this._isActive = true;
          this._activeResolve?.();
        }
        if (msg.state === "ended") {
          this._activeReject?.(new Error("Sesi suara berakhir"));
          this.onStatus("idle");
        }
        break;
      case "audio":
        this._queueOrPlayAudio(msg);
        break;
      case "floor":
        this._applyFloor(msg.speaker, msg.reason);
        break;
      case "interrupt":
        if (msg.soft) {
          if (!this._duckTimer) {
            this._duckPlayback(msg.duck_ms || SOFT_BARGE_DUCK_MS);
          }
        } else {
          this._flushPlayback();
        }
        break;
      case "mic_enable":
        this._armMicAfterPlayback();
        break;
      case "governance":
        if (msg.backchannel && msg.text) {
          this.onGovernance({ ...msg, bdv: "ACK_ONLY" });
        } else if (msg.bdv !== "pending") {
          this.onGovernance(msg);
        }
        break;
      case "governance_preview":
        break;
      case "transcript":
        if (msg.role === "user" && msg.text) {
          this._maybeSmartBargeIn(msg.text, msg.finished);
        }
        if (msg.text && msg.finished) {
          this.onTranscript(msg.role, msg.text);
        }
        break;
      case "notice":
        if (msg.message) {
          this.onNotice(msg.message);
        }
        break;
      case "error":
        {
          const msgText = msg.message || "";
          if (this._isGeminiSessionExpiry(msgText)) {
            this._sawServerError = true;
            this._activeReject?.(new Error(msgText || "Suara error"));
            this.onError("Sesi Gemini habis — sambungkan ulang panggilan.");
            this.stop();
            break;
          }
          this._sawServerError = true;
          this._activeReject?.(new Error(msgText || "Suara error"));
          this.onError(msgText || "Suara error");
          this.stop();
        }
        break;
      case "turn_complete":
        this._bargeInHighFrames = 0;
        this._bargeSpeechSince = 0;
        if (this._playbackBusy()) {
          this._armMicAfterPlayback();
        } else if (this._floor !== "user") {
          this._applyFloor("user", msg.reason || "turn_complete");
        } else {
          this._armMicAfterPlayback();
        }
        if (
          msg.laugh_track &&
          loadBgmMode() !== BGM_MODES.off &&
          typeof PersonaAndroid !== "undefined" &&
          PersonaAndroid.playLaughTrack
        ) {
          PersonaAndroid.playLaughTrack();
        }
        if (msg.jedag_jedug && loadBgmMode() !== BGM_MODES.off) {
          if (
            typeof PersonaAndroid === "undefined" ||
            !PersonaAndroid.playJedagJedug
          ) {
            this._bgm?.playJedagBurst(JEDAG_BURST_MS);
          } else {
            PersonaAndroid.playJedagJedug();
          }
        }
        break;
      case "call_ended":
        if (msg.message) {
          this.onError(msg.message);
        }
        this.stop();
        break;
      case "post_call_data":
        if (msg.data) {
          this.onPostCall(msg.data);
        }
        if (typeof console !== "undefined" && console.info) {
          console.info("[persona post-call]", msg.data);
        }
        break;
      case "latency":
        if (msg.metrics) {
          this._lastLatency = msg.metrics;
          if (typeof console !== "undefined" && console.info) {
            console.info("[persona latency]", msg.metrics);
          }
        }
        break;
      default:
        break;
    }
  }

  async _playPcm(base64, rate) {
    if (!this.audioCtx || !this.playGain || !base64) return;
    this._ensureFullPlaybackGain();
    await this._ensureAudioReady();
    const bytes = base64ToArrayBuffer(base64);
    if (bytes.byteLength < MIN_PLAYABLE_PCM_BYTES) return;
    const samples = new Int16Array(bytes);
    const floats = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      floats[i] = samples[i] / (samples[i] < 0 ? 0x8000 : 0x7fff);
    }
    const buffer = this.audioCtx.createBuffer(1, floats.length, rate);
    buffer.copyToChannel(floats, 0);
    const src = this.audioCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.playGain);
    const hadQueue = this._playbackSources.size > 0 || this.playTime > this.audioCtx.currentTime + 0.01;
    this._playbackSources.add(src);
    src.onended = () => this._playbackSources.delete(src);

    const now = this.audioCtx.currentTime;
    // Keep a continuous timeline. Resetting playTime on turn_complete used to
    // insert a lookahead gap mid-sentence whenever Gemini split one reply.
    const start = hadQueue
      ? Math.max(this.playTime, now + PLAYBACK_UNDERRUN_SLIP_S)
      : now + PLAYBACK_LOOKAHEAD_S;
    src.start(start);
    this.playTime = start + buffer.duration;
  }

  async stop() {
    if (!this.active) return;
    this._stopping = true;
    this.onStatus("ending");
    this.active = false;
    this._flushPlayback();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: "stop" }));
      } catch {
        /* ignore */
      }
    }
    this._teardown(true);
    this.onStatus("idle");
  }

  _teardown(fromStop) {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._reconnectInFlight = false;
    this._stopCallTimer();
    this._disableKeypadListener();
    this._connected = false;
    this._isActive = false;
    this._activeResolve = null;
    this._activeReject = null;
    this._audioReady = false;
    this._audioQueue = [];
    this._micEnabled = false;
    this._micFramesSent = 0;
    this._micBatch = new Float32Array(0);
    this._bargeInHighFrames = 0;
    this._bargeSpeechSince = 0;
    this._dropAgentAudioUntil = 0;
    this._setAgentTalking(false);
    if (this._micFallbackTimer) {
      clearTimeout(this._micFallbackTimer);
      this._micFallbackTimer = null;
    }
    if (this._micAfterPlaybackTimer) {
      clearTimeout(this._micAfterPlaybackTimer);
      this._micAfterPlaybackTimer = null;
    }
    if (this._duckTimer) {
      clearTimeout(this._duckTimer);
      this._duckTimer = null;
    }
    this._flushPlayback();

    if (this.captureNode) {
      try {
        this.captureNode.disconnect();
        if (this.captureNode.port) this.captureNode.port.onmessage = null;
      } catch {
        /* ignore */
      }
      this.captureNode = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this._bgm) {
      this._bgm.release();
      this._bgm = null;
      if (
        typeof PersonaAndroid !== "undefined" &&
        PersonaAndroid.stopBgm
      ) {
        PersonaAndroid.stopBgm();
      }
    }
    if (this.playGain) {
      this.playGain.disconnect();
      this.playGain = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    if (this.ws) {
      this._detachSocket(this.ws);
      if (!fromStop && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.close();
        } catch {
          /* ignore */
        }
      }
      this.ws = null;
    }
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    this.playTime = 0;
  }
}

function downsample(buffer, inputRate, outputRate) {
  if (inputRate === outputRate) return buffer;
  const ratio = inputRate / outputRate;
  const len = Math.floor(buffer.length / ratio);
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    out[i] = buffer[Math.floor(i * ratio)];
  }
  return out;
}

function floatTo16BitPCM(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function parseSampleRate(mime) {
  if (!mime) return null;
  const m = /rate=(\d+)/.exec(mime);
  return m ? parseInt(m[1], 10) : null;
}
