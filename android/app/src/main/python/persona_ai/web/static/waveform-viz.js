/**
 * Premium sine-wave visualizer for in-call UI (WebView-safe, no Tailwind).
 */
(function () {
  const DEFAULTS = {
    baseAmplitude: 6,
    maxAmplitude: 22,
    speed: 0.065,
    lineWidth: 2.25,
  };

  let canvas = null;
  let ctx = null;
  let rafId = 0;
  let phase = 0;
  let mode = "idle";
  let energy = 0.35;
  let targetEnergy = 0.35;
  let width = 0;
  let height = 0;
  let dpr = 1;

  const PALETTE = {
    idle: ["#64748b", "#94a3b8", "#cbd5e1"],
    connecting: ["#22d3ee", "#818cf8", "#c084fc"],
    user: ["#22d3ee", "#6366f1", "#a855f7"],
    agent: ["#34d399", "#10b981", "#6ee7b7"],
  };

  function resize() {
    if (!canvas) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = canvas.clientWidth || 200;
    height = canvas.clientHeight || 40;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function drawFrame() {
    if (!ctx || !canvas) return;
    energy += (targetEnergy - energy) * 0.12;
    const amp =
      DEFAULTS.baseAmplitude +
      energy * (DEFAULTS.maxAmplitude - DEFAULTS.baseAmplitude);
    const colors = PALETTE[mode] || PALETTE.idle;

    ctx.clearRect(0, 0, width, height);
    const gradient = ctx.createLinearGradient(0, 0, width, 0);
    gradient.addColorStop(0, colors[0]);
    gradient.addColorStop(0.5, colors[1]);
    gradient.addColorStop(1, colors[2]);

    ctx.beginPath();
    ctx.strokeStyle = gradient;
    ctx.lineWidth = DEFAULTS.lineWidth;
    ctx.shadowBlur = mode === "idle" ? 0 : 10;
    ctx.shadowColor = colors[1] + "88";

    const mid = height / 2;
    for (let x = 0; x <= width; x += 1) {
      const envelope = 0.55 + 0.45 * Math.sin(x * 0.018 + phase * 0.4);
      const y =
        mid +
        Math.sin(x * 0.045 + phase) * amp * envelope * Math.sin(x * 0.012 + 0.5);
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;

    phase += DEFAULTS.speed * (mode === "agent" ? 1.15 : 1);
    rafId = requestAnimationFrame(drawFrame);
  }

  function setVisualState(next) {
    if (!next) return;
    if (next.mode) mode = next.mode;
    if (typeof next.energy === "number") targetEnergy = Math.max(0, Math.min(1, next.energy));
    else if (next.mode === "idle") targetEnergy = 0.2;
    else if (next.mode === "connecting") targetEnergy = 0.45;
    else if (next.mode === "agent") targetEnergy = 0.85;
    else if (next.mode === "user") targetEnergy = 0.65;
  }

  function start(el) {
    stop();
    canvas = el;
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    resize();
    window.addEventListener("resize", resize);
    mode = "connecting";
    targetEnergy = 0.45;
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
    energy = targetEnergy = 0.25;
  }

  window.PersonaWaveform = { start, stop, pause, resume, setVisualState, resize };
})();
