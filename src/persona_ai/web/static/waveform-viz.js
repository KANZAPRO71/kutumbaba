/**
 * Premium multi-layer waveform + spectrum bars (WebView / GPU-friendly canvas).
 */
(function () {
  const BAR_COUNT = 32;
  const LAYERS = 3;

  let canvas = null;
  let ctx = null;
  let rafId = 0;
  let phase = 0;
  let phase2 = 0;
  let mode = "idle";
  let energy = 0.35;
  let targetEnergy = 0.35;
  let micLevel = 0;
  let agentPulse = 0;
  let width = 0;
  let height = 0;
  let dpr = 1;

  const bars = new Float32Array(BAR_COUNT);
  const barTarget = new Float32Array(BAR_COUNT);

  const PALETTE = {
    idle: { a: "#64748b", b: "#94a3b8", c: "#cbd5e1", glow: "rgba(148,163,184,0.35)" },
    connecting: { a: "#22d3ee", b: "#818cf8", c: "#e879f9", glow: "rgba(129,140,248,0.55)" },
    user: { a: "#22d3ee", b: "#6366f1", c: "#c084fc", glow: "rgba(99,102,241,0.5)" },
    agent: { a: "#34d399", b: "#10b981", c: "#fde68a", glow: "rgba(52,211,153,0.45)" },
  };

  function resize() {
    if (!canvas) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = canvas.clientWidth || 200;
    height = canvas.clientHeight || 48;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function waveSample(x, layer, amp, mid) {
    const l = layer + 1;
    const env = 0.5 + 0.5 * Math.sin(x * 0.014 + phase * 0.35 + l);
    const y =
      Math.sin(x * (0.038 + l * 0.012) + phase * (0.9 + l * 0.15)) * amp * env * 0.55 +
      Math.sin(x * (0.072 + l * 0.008) - phase2 * 1.1) * amp * 0.28 +
      Math.sin(x * 0.021 + phase * 2.2) * amp * 0.12 * Math.sin(x * 0.006);
    return mid + y;
  }

  function tickBars(activeLevel) {
    if (mode === "agent") {
      agentPulse = 0.82 + 0.18 * Math.sin(phase * 2.4);
      const base = activeLevel * agentPulse;
      for (let i = 0; i < BAR_COUNT; i += 1) {
        const center = (i - BAR_COUNT / 2) / (BAR_COUNT / 2);
        const bell = Math.exp(-center * center * 1.8);
        const wobble = 0.65 + 0.35 * Math.sin(i * 0.55 + phase * 3.1);
        barTarget[i] = base * bell * wobble;
      }
    } else if (mode === "user" || mode === "connecting") {
      for (let i = 0; i < BAR_COUNT; i += 1) {
        const dist = 1 - Math.abs(i - BAR_COUNT / 2) / (BAR_COUNT / 2);
        const jitter = 0.55 + 0.45 * Math.sin(i * 0.7 + phase * 2.8);
        const target = activeLevel * dist * jitter;
        barTarget[i] = Math.max(barTarget[i] * 0.72, target);
      }
    } else {
      for (let i = 0; i < BAR_COUNT; i += 1) {
        barTarget[i] = barTarget[i] * 0.9 + 0.02 * Math.sin(i * 0.4 + phase);
      }
    }
    for (let i = 0; i < BAR_COUNT; i += 1) {
      bars[i] += (barTarget[i] - bars[i]) * 0.22;
    }
  }

  function drawBars(colors) {
    const barGap = 1.5;
    const barW = Math.max(1.5, (width - barGap * (BAR_COUNT - 1)) / BAR_COUNT);
    const maxH = height * 0.42;
    const baseY = height - 2;

    for (let i = 0; i < BAR_COUNT; i += 1) {
      const h = Math.max(2, bars[i] * maxH);
      const x = i * (barW + barGap);
      const grad = ctx.createLinearGradient(x, baseY - h, x, baseY);
      grad.addColorStop(0, colors.c);
      grad.addColorStop(0.45, colors.b);
      grad.addColorStop(1, colors.a + "44");
      ctx.fillStyle = grad;
      const r = Math.min(barW / 2, 2);
      roundRect(ctx, x, baseY - h, barW, h, r);
      ctx.fill();
    }
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

  function strokeWaveLayer(layer, amp, mid, colors, alpha, widthPx) {
    ctx.beginPath();
    ctx.lineWidth = widthPx;
    ctx.strokeStyle = colors.b;
    ctx.globalAlpha = alpha;
    ctx.shadowBlur = layer === 0 ? 14 : 6;
    ctx.shadowColor = colors.glow;
    for (let x = 0; x <= width; x += 1) {
      const y = waveSample(x, layer, amp, mid);
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }

  function fillWaveUnder(mid, amp, colors) {
    const grad = ctx.createLinearGradient(0, mid - amp, 0, mid + amp);
    grad.addColorStop(0, colors.a + "00");
    grad.addColorStop(0.35, colors.b + "28");
    grad.addColorStop(0.5, colors.c + "35");
    grad.addColorStop(1, colors.a + "00");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    for (let x = 0; x <= width; x += 1) {
      ctx.lineTo(x, waveSample(x, 0, amp, mid));
    }
    for (let x = width; x >= 0; x -= 1) {
      ctx.lineTo(x, waveSample(x, 1, amp * 0.65, mid));
    }
    ctx.closePath();
    ctx.fill();
  }

  function drawFrame() {
    if (!ctx || !canvas) return;

    energy += (targetEnergy - energy) * 0.14;
    micLevel *= 0.92;

    const colors = PALETTE[mode] || PALETTE.idle;
    const activeLevel =
      mode === "user"
        ? Math.min(1, 0.25 + micLevel * 2.2 + energy * 0.35)
        : mode === "agent"
          ? Math.min(1, 0.35 + energy * 0.55 + agentPulse * 0.25)
          : mode === "connecting"
            ? 0.4 + energy * 0.35
            : 0.15 + energy * 0.2;

    tickBars(activeLevel);

    const amp =
      4 + activeLevel * (height * 0.22) + (mode === "agent" ? 3 * Math.sin(phase * 1.8) : 0);
    const mid = height * 0.46;

    ctx.clearRect(0, 0, width, height);

    // Baseline glow
    ctx.strokeStyle = colors.a + "22";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(width, mid);
    ctx.stroke();

    drawBars(colors);
    fillWaveUnder(mid, amp, colors);
    strokeWaveLayer(2, amp * 0.45, mid, colors, 0.35, 1.2);
    strokeWaveLayer(1, amp * 0.72, mid, colors, 0.55, 1.6);
    strokeWaveLayer(0, amp, mid, colors, 0.95, 2.4);

    // Mirror ribbon (subtle)
    ctx.beginPath();
    ctx.strokeStyle = colors.c + "55";
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x += 2) {
      const y = mid + (waveSample(x, 0, amp, mid) - mid) * 0.35;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    phase += 0.07 * (mode === "agent" ? 1.25 : mode === "user" ? 1.05 : 0.85);
    phase2 += 0.043;
    rafId = requestAnimationFrame(drawFrame);
  }

  function setVisualState(next) {
    if (!next) return;
    if (next.mode) mode = next.mode;
    if (typeof next.energy === "number") {
      targetEnergy = Math.max(0, Math.min(1, next.energy));
    } else if (next.mode === "idle") targetEnergy = 0.18;
    else if (next.mode === "connecting") targetEnergy = 0.48;
    else if (next.mode === "agent") targetEnergy = 0.88;
    else if (next.mode === "user") targetEnergy = 0.62;
  }

  /** Live mic RMS from live.js (~30fps). */
  function pushMicLevel(rms) {
    if (typeof rms !== "number" || !Number.isFinite(rms)) return;
    const scaled = Math.min(1, rms * 11);
    micLevel = micLevel * 0.55 + scaled * 0.45;
    if (mode === "user" || mode === "connecting") {
      targetEnergy = Math.min(1, 0.35 + micLevel * 0.75);
    }
  }

  function start(el) {
    stop();
    canvas = el;
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    bars.fill(0);
    barTarget.fill(0);
    resize();
    window.addEventListener("resize", resize);
    mode = "connecting";
    targetEnergy = 0.48;
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
    if (ctx && canvas) ctx.clearRect(0, 0, width, height);
    canvas = null;
    ctx = null;
    mode = "idle";
    energy = targetEnergy = 0.2;
    micLevel = 0;
    bars.fill(0);
    barTarget.fill(0);
  }

  window.PersonaWaveform = {
    start,
    stop,
    pause,
    resume,
    setVisualState,
    pushMicLevel,
    resize,
  };
})();
