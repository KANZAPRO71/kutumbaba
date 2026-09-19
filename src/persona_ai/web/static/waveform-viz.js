/**
 * Real-time waveform — reacts to mic (in) and speaker/agent (out) via AnalyserNode.
 */
(function () {
  const BAR_COUNT = 32;
  const FFT_SIZE = 256;

  let canvas = null;
  let ctx = null;
  let rafId = 0;
  let phase = 0;
  let phase2 = 0;
  let modeHint = "idle";
  let micAnalyser = null;
  let playbackAnalyser = null;

  let micLevel = 0;
  let agentLevel = 0;
  let width = 0;
  let height = 0;
  let dpr = 1;

  const bars = new Float32Array(BAR_COUNT);
  const barTarget = new Float32Array(BAR_COUNT);
  const micBands = new Float32Array(BAR_COUNT);
  const agentBands = new Float32Array(BAR_COUNT);
  const freqScratch = new Uint8Array(FFT_SIZE / 2);

  const THEMES = {
    ocean: {
      idle: { a: "#0e7490", b: "#22d3ee", c: "#67e8f9", glow: "rgba(34,211,238,0.45)" },
      connecting: { a: "#155e75", b: "#22d3ee", c: "#a5f3fc", glow: "rgba(34,211,238,0.55)" },
      user: { a: "#0f766e", b: "#2dd4bf", c: "#67e8f9", glow: "rgba(45,212,191,0.5)" },
      agent: { a: "#0369a1", b: "#38bdf8", c: "#e0f2fe", glow: "rgba(56,189,248,0.5)" },
    },
    jade: {
      idle: { a: "#065f46", b: "#c5a059", c: "#e4c98a", glow: "rgba(197,160,89,0.4)" },
      connecting: { a: "#047857", b: "#34d399", c: "#c5a059", glow: "rgba(52,211,153,0.45)" },
      user: { a: "#064e3b", b: "#10b981", c: "#c5a059", glow: "rgba(16,185,129,0.45)" },
      agent: { a: "#14532d", b: "#86efac", c: "#e4c98a", glow: "rgba(134,239,172,0.4)" },
    },
  };

  function activePalette() {
    const key = document.body?.dataset?.theme || "ocean";
    return THEMES[key] || THEMES.ocean;
  }

  function resize() {
    if (!canvas) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = canvas.clientWidth || 200;
    height = canvas.clientHeight || 52;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function pullAnalyserBands(analyser, store, gain) {
    if (!analyser) {
      for (let i = 0; i < BAR_COUNT; i += 1) store[i] *= 0.82;
      return 0;
    }
    const bins = analyser.frequencyBinCount;
    if (freqScratch.length < bins) {
      /* keep static buffer large enough */
    }
    const data = freqScratch.subarray(0, bins);
    analyser.getByteFrequencyData(data);
    let energy = 0;
    for (let i = 0; i < BAR_COUNT; i += 1) {
      const i0 = Math.floor((i / BAR_COUNT) * bins);
      const i1 = Math.max(i0 + 1, Math.floor(((i + 1) / BAR_COUNT) * bins));
      let sum = 0;
      for (let j = i0; j < i1; j += 1) sum += data[j];
      const avg = sum / (i1 - i0);
      const v = (avg / 255) * gain;
      store[i] = store[i] * 0.5 + v * 0.5;
      energy += v;
    }
    return energy / BAR_COUNT;
  }

  function waveSample(x, layer, amp, mid, drive) {
    const l = layer + 1;
    const wobble = 0.7 + 0.3 * drive;
    const env = 0.5 + 0.5 * Math.sin(x * 0.014 + phase * 0.35 + l);
    const y =
      Math.sin(x * (0.038 + l * 0.012) + phase * (0.9 + l * 0.15)) * amp * env * wobble * 0.55 +
      Math.sin(x * (0.072 + l * 0.008) - phase2 * 1.1) * amp * wobble * 0.28 +
      Math.sin(x * 0.021 + phase * 2.2) * amp * 0.12 * Math.sin(x * 0.006 + drive * 2);
    return mid + y;
  }

  function pickDisplayMode(micE, agentE) {
    if (modeHint === "connecting") return "connecting";
    if (modeHint === "idle") return "idle";
    if (agentE > micE * 1.05 && agentE > 0.025) return "agent";
    if (micE > 0.02) return "user";
    return modeHint === "agent" || modeHint === "user" ? modeHint : "idle";
  }

  function tickBars(micE, agentE, displayMode) {
    for (let i = 0; i < BAR_COUNT; i += 1) {
      const m = micBands[i] * (displayMode === "user" ? 1.05 : 0.55);
      const a = agentBands[i] * (displayMode === "agent" ? 1.05 : 0.55);
      let target = Math.max(m, a);
      if (displayMode === "connecting") {
        target = Math.max(target, 0.12 + 0.08 * Math.sin(i * 0.5 + phase * 2));
      }
      if (displayMode === "idle") target *= 0.35;
      barTarget[i] = Math.max(barTarget[i] * 0.68, target);
      bars[i] += (barTarget[i] - bars[i]) * 0.28;
      barTarget[i] *= 0.92;
    }
    return Math.max(micE, agentE, 0.08);
  }

  function drawBars(colors, micE, agentE) {
    const barGap = 1.5;
    const barW = Math.max(1.5, (width - barGap * (BAR_COUNT - 1)) / BAR_COUNT);
    const maxH = height * 0.4;
    const baseY = height - 2;
    const userC = activePalette().user;
    const agentC = activePalette().agent;
    const denom = micE + agentE + 0.001;

    for (let i = 0; i < BAR_COUNT; i += 1) {
      const h = Math.max(2, bars[i] * maxH);
      const x = i * (barW + barGap);
      const mix = agentBands[i] / (micBands[i] + agentBands[i] + 0.02);
      const grad = ctx.createLinearGradient(x, baseY - h, x, baseY);
      grad.addColorStop(0, mix > 0.55 ? agentC.c : userC.c);
      grad.addColorStop(0.45, mix > 0.5 ? agentC.b : userC.b);
      grad.addColorStop(1, colors.a + "44");
      ctx.fillStyle = grad;
      const r = Math.min(barW / 2, 2);
      roundRect(ctx, x, baseY - h, barW, h, r);
      ctx.fill();
    }
    void denom;
  }

  function roundRect(context, x, y, w, h, r) {
    context.beginPath();
    context.moveTo(x + r, y);
    context.lineTo(x + w - r, y);
    context.quadraticCurveTo(x + w, y, x + w, y + r);
    context.lineTo(x + w, y + h - r);
    context.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    context.lineTo(x + r, y + h);
    context.quadraticCurveTo(x, y + h, x, y + h - r);
    context.lineTo(x, y + r);
    context.quadraticCurveTo(x, y, x + r, y);
    context.closePath();
  }

  function strokeWaveLayer(layer, amp, mid, colors, alpha, widthPx, drive) {
    ctx.beginPath();
    ctx.lineWidth = widthPx;
    const grad = ctx.createLinearGradient(0, 0, width, 0);
    grad.addColorStop(0, colors.a);
    grad.addColorStop(0.5, colors.b);
    grad.addColorStop(1, colors.c);
    ctx.strokeStyle = grad;
    ctx.globalAlpha = alpha;
    ctx.shadowBlur = layer === 0 ? 16 : 8;
    ctx.shadowColor = colors.glow;
    for (let x = 0; x <= width; x += 1) {
      const y = waveSample(x, layer, amp, mid, drive);
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }

  function fillWaveUnder(mid, amp, colors, drive) {
    const grad = ctx.createLinearGradient(0, mid - amp, 0, mid + amp);
    grad.addColorStop(0, colors.a + "00");
    grad.addColorStop(0.35, colors.b + "28");
    grad.addColorStop(0.5, colors.c + "35");
    grad.addColorStop(1, colors.a + "00");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    for (let x = 0; x <= width; x += 1) {
      ctx.lineTo(x, waveSample(x, 0, amp, mid, drive));
    }
    for (let x = width; x >= 0; x -= 1) {
      ctx.lineTo(x, waveSample(x, 1, amp * 0.65, mid, drive));
    }
    ctx.closePath();
    ctx.fill();
  }

  function drawFrame() {
    if (!ctx || !canvas) return;

    micLevel *= 0.88;
    agentLevel *= 0.9;

    let micE = pullAnalyserBands(micAnalyser, micBands, 1.25);
    let agentE = pullAnalyserBands(playbackAnalyser, agentBands, 1.05);
    micE = Math.max(micE, micLevel);
    agentE = Math.max(agentE, agentLevel);

    const displayMode = pickDisplayMode(micE, agentE);
    const PALETTE = activePalette();
    const colors = PALETTE[displayMode] || PALETTE.idle;
    const drive = Math.min(1.4, micE * 1.8 + agentE * 1.6);
    const activeLevel = tickBars(micE, agentE, displayMode);

    const amp = 3 + activeLevel * (height * 0.26) + drive * 4;
    const mid = height * 0.44;

    ctx.clearRect(0, 0, width, height);

    ctx.strokeStyle = colors.a + "22";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(width, mid);
    ctx.stroke();

    drawBars(colors, micE, agentE);
    fillWaveUnder(mid, amp, colors, drive);
    strokeWaveLayer(2, amp * 0.45, mid, colors, 0.35, 1.2, drive);
    strokeWaveLayer(1, amp * 0.72, mid, colors, 0.55, 1.6, drive);
    strokeWaveLayer(0, amp, mid, colors, 0.95, 2.4, drive);

    phase += 0.04 + drive * 0.05;
    phase2 += 0.038 + agentE * 0.04;
    rafId = requestAnimationFrame(drawFrame);
  }

  function setVisualState(next) {
    if (!next) return;
    if (next.mode) modeHint = next.mode;
  }

  function pushMicLevel(rms) {
    if (typeof rms !== "number" || !Number.isFinite(rms)) return;
    micLevel = Math.max(micLevel * 0.5, Math.min(1, rms * 12));
  }

  function pushAgentLevel(rms) {
    if (typeof rms !== "number" || !Number.isFinite(rms)) return;
    agentLevel = Math.max(agentLevel * 0.45, Math.min(1, rms * 9));
  }

  function attachAnalysers({ mic, playback } = {}) {
    micAnalyser = mic || null;
    playbackAnalyser = playback || null;
    if (micAnalyser) {
      micAnalyser.fftSize = FFT_SIZE;
      micAnalyser.smoothingTimeConstant = 0.62;
    }
    if (playbackAnalyser) {
      playbackAnalyser.fftSize = FFT_SIZE;
      playbackAnalyser.smoothingTimeConstant = 0.55;
    }
  }

  function detachAnalysers() {
    micAnalyser = null;
    playbackAnalyser = null;
  }

  function start(el) {
    stop();
    canvas = el;
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    bars.fill(0);
    barTarget.fill(0);
    micBands.fill(0);
    agentBands.fill(0);
    resize();
    window.addEventListener("resize", resize);
    modeHint = "connecting";
    rafId = requestAnimationFrame(drawFrame);
  }

  function pause() {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
  }

  function resume() {
    if (canvas && ctx && !rafId) {
      rafId = requestAnimationFrame(drawFrame);
    }
  }

  function stop() {
    pause();
    window.removeEventListener("resize", resize);
    detachAnalysers();
    if (ctx && canvas) ctx.clearRect(0, 0, width, height);
    canvas = null;
    ctx = null;
    modeHint = "idle";
    micLevel = agentLevel = 0;
    bars.fill(0);
    barTarget.fill(0);
    micBands.fill(0);
    agentBands.fill(0);
  }

  window.PersonaWaveform = {
    start,
    stop,
    pause,
    resume,
    setVisualState,
    pushMicLevel,
    pushAgentLevel,
    attachAnalysers,
    detachAnalysers,
    resize,
  };
})();
