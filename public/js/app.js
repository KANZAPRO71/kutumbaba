// Jarvis app controller — wires the store, providers, voice, and UI together.
import { Store } from './store.js';
import { DemoProvider, GeminiProvider } from './providers.js';
import { buildMorningBrief } from './core/brief.js';
import { formatDay, isPast } from './core/datetime.js';
import {
  createRecognizer,
  recognitionSupported,
  speak,
  stopSpeaking,
} from './voice.js';

const store = new Store();

const el = (id) => document.getElementById(id);
const dom = {
  messages: el('messages'),
  composer: el('composer'),
  input: el('composer-input'),
  sendBtn: el('send-btn'),
  micBtn: el('mic-btn'),
  hint: el('composer-hint'),
  suggestions: el('suggestions'),
  modeBadge: el('mode-badge'),
  memoryList: el('memory-list'),
  memoryEmpty: el('memory-empty'),
  memoryCount: el('memory-count'),
  reminderList: el('reminder-list'),
  reminderEmpty: el('reminder-empty'),
  reminderCount: el('reminder-count'),
  briefBody: el('brief-body'),
  briefBtn: el('brief-btn'),
  settingsBtn: el('settings-btn'),
  settingsModal: el('settings-modal'),
  settingsClose: el('settings-close'),
  settingsSave: el('settings-save'),
  resetBtn: el('reset-btn'),
  apiKeyInput: el('api-key-input'),
  modelInput: el('model-input'),
  emailInput: el('email-input'),
  voiceInput: el('voice-input'),
};

let provider = buildProvider();
let busy = false;
let recognizer = null;

function buildProvider() {
  const { apiKey, model } = store.settings;
  return apiKey
    ? new GeminiProvider({ apiKey, model })
    : new DemoProvider();
}

function refreshMode() {
  provider = buildProvider();
  const live = provider.mode === 'live';
  dom.modeBadge.textContent = live ? 'Live · Gemini' : 'Demo mode';
  dom.modeBadge.classList.toggle('live', live);
}

/* ---------------- Rendering ---------------- */

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderWelcome() {
  const name = store.state.profile.name;
  const div = document.createElement('div');
  div.className = 'welcome';
  div.innerHTML = `
    <h3>${name ? `Welcome back, ${escapeHtml(name)}.` : 'Hey, I’m Jarvis.'}</h3>
    <p>I’m your voice-first assistant that actually remembers you. Tell me about
    the people, projects, and details in your life — I’ll keep them and get more
    personal every time we talk. Tap the mic or just type below.</p>`;
  dom.messages.appendChild(div);
}

function renderMessage(msg) {
  const wrap = document.createElement('div');
  wrap.className = `msg ${msg.role}`;

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = msg.role === 'assistant' ? '◆' : '🧑';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = msg.text;

  if (msg.sources && msg.sources.length) {
    const src = document.createElement('div');
    src.className = 'sources';
    msg.sources.forEach((s) => {
      const a = document.createElement('a');
      a.className = 'source-link';
      a.href = s.uri;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = `🔗 ${s.title}`;
      src.appendChild(a);
    });
    bubble.appendChild(src);
  }

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  dom.messages.appendChild(wrap);
  dom.messages.scrollTop = dom.messages.scrollHeight;
  return wrap;
}

function renderConversation() {
  dom.messages.innerHTML = '';
  const turns = store.state.conversation;
  if (!turns.length) {
    renderWelcome();
    return;
  }
  turns.forEach(renderMessage);
}

function showTyping() {
  const wrap = document.createElement('div');
  wrap.className = 'msg assistant typing';
  wrap.id = 'typing-indicator';
  wrap.innerHTML =
    '<div class="avatar">◆</div><div class="bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
  dom.messages.appendChild(wrap);
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function hideTyping() {
  const t = el('typing-indicator');
  if (t) t.remove();
}

function renderMemory() {
  const mems = store.state.memories;
  dom.memoryCount.textContent = String(mems.length);
  dom.memoryList.innerHTML = '';
  dom.memoryEmpty.classList.toggle('hidden', mems.length > 0);
  mems
    .slice()
    .reverse()
    .forEach((m) => {
      const li = document.createElement('li');
      li.className = 'memory-item';
      li.innerHTML = `<span class="cat">${escapeHtml(m.category)}</span>
        <span class="txt">${escapeHtml(m.text)}</span>
        <button class="x-btn" title="Forget" data-mem="${m.id}">✕</button>`;
      dom.memoryList.appendChild(li);
    });
}

function renderReminders() {
  const rems = store.state.reminders;
  const open = rems.filter((r) => !r.done);
  dom.reminderCount.textContent = String(open.length);
  dom.reminderList.innerHTML = '';
  dom.reminderEmpty.classList.toggle('hidden', rems.length > 0);

  const sorted = rems.slice().sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    if (a.dueISO && b.dueISO) return new Date(a.dueISO) - new Date(b.dueISO);
    if (a.dueISO) return -1;
    if (b.dueISO) return 1;
    return 0;
  });

  sorted.forEach((r) => {
    const li = document.createElement('li');
    li.className = `reminder-item ${r.done ? 'done' : ''}`;
    const overdue = r.dueISO && !r.done && isPast(r.dueISO, new Date());
    const dueText = r.dueISO
      ? `<span class="r-due ${overdue ? 'overdue' : ''}">${
          overdue ? '⚠ ' : ''
        }${formatDay(r.dueISO, new Date())}</span>`
      : '';
    li.innerHTML = `
      <button class="r-check" data-toggle="${r.id}" title="Mark done">${
        r.done ? '✓' : ''
      }</button>
      <div class="r-body">
        <span class="r-text">${escapeHtml(r.text)}</span>
        ${dueText}
      </div>
      <button class="x-btn" title="Remove" data-rem="${r.id}">✕</button>`;
    dom.reminderList.appendChild(li);
  });
}

function renderBrief() {
  dom.briefBody.textContent = buildMorningBrief(store.snapshot(), new Date());
}

function renderAll() {
  renderConversation();
  renderMemory();
  renderReminders();
  renderBrief();
}

/* ---------------- Conversation flow ---------------- */

async function handleUserMessage(text) {
  const clean = (text || '').trim();
  if (!clean || busy) return;

  busy = true;
  dom.sendBtn.disabled = true;
  dom.input.value = '';
  setHint('');

  const userMsg = store.addMessage('user', clean);
  if (store.state.conversation.length === 1) dom.messages.innerHTML = '';
  renderMessage(userMsg);

  // Learn durable facts first so memory works in any mode.
  const now = new Date();
  const { extracted } = store.learnFrom(clean, now);
  renderMemory();
  renderReminders();
  renderBrief();

  showTyping();
  try {
    const { reply, sources } = await provider.generateReply({
      userText: clean,
      snapshot: store.snapshot(),
      turns: store.recentTurns(12).slice(0, -1),
      extracted,
      now,
    });
    hideTyping();
    const assistantMsg = store.addMessage('assistant', reply, { sources });
    renderMessage(assistantMsg);
    speak(reply, {
      enabled: store.settings.voice,
      onStart: () => dom.micBtn.classList.add('speaking'),
      onEnd: () => dom.micBtn.classList.remove('speaking'),
    });
  } catch (err) {
    hideTyping();
    const friendly = `⚠️ ${err.message}`;
    const assistantMsg = store.addMessage('assistant', friendly);
    renderMessage(assistantMsg);
    setHint(err.message, 'error');
  } finally {
    busy = false;
    dom.sendBtn.disabled = false;
    dom.input.focus();
  }
}

function setHint(text, kind = '') {
  dom.hint.textContent = text;
  dom.hint.className = `composer-hint ${kind}`;
}

/* ---------------- Voice ---------------- */

function initVoice() {
  if (!recognitionSupported()) {
    dom.micBtn.title = 'Voice input not supported in this browser — type instead';
    return;
  }
  recognizer = createRecognizer({
    onStart: () => {
      dom.micBtn.classList.add('listening');
      setHint('Listening… speak now', 'listening');
    },
    onResult: ({ interim, final }) => {
      dom.input.value = (final || interim || '').trim();
    },
    onEnd: () => {
      dom.micBtn.classList.remove('listening');
      setHint('');
      const text = dom.input.value.trim();
      if (text) handleUserMessage(text);
    },
    onError: (err) => {
      dom.micBtn.classList.remove('listening');
      const msg =
        err === 'not-allowed' || err === 'service-not-allowed'
          ? 'Microphone blocked. Allow mic access or type your message.'
          : err === 'no-speech'
            ? "Didn't catch that — try again or type."
            : `Voice error: ${err}. You can type instead.`;
      setHint(msg, 'error');
    },
  });
}

function toggleMic() {
  stopSpeaking();
  if (!recognizer || !recognizer.supported) {
    setHint('Voice input isn’t available here — just type below.', 'error');
    dom.input.focus();
    return;
  }
  if (recognizer.listening) recognizer.stop();
  else recognizer.start();
}

/* ---------------- Settings ---------------- */

function openSettings() {
  dom.apiKeyInput.value = store.settings.apiKey || '';
  dom.modelInput.value = store.settings.model || 'gemini-2.0-flash';
  dom.emailInput.value = store.state.profile.email || '';
  dom.voiceInput.checked = store.settings.voice !== false;
  dom.settingsModal.hidden = false;
}

function closeSettings() {
  dom.settingsModal.hidden = true;
}

function saveSettings() {
  store.updateSettings({
    apiKey: dom.apiKeyInput.value.trim(),
    model: dom.modelInput.value,
    voice: dom.voiceInput.checked,
  });
  store.updateProfile({ email: dom.emailInput.value.trim() });
  refreshMode();
  closeSettings();
  setHint(
    provider.mode === 'live'
      ? 'Connected to Gemini. Ask me anything — I’ll cite live sources.'
      : 'Running in offline demo mode. Add a Gemini key anytime for live answers.',
  );
}

/* ---------------- Events ---------------- */

dom.composer.addEventListener('submit', (e) => {
  e.preventDefault();
  handleUserMessage(dom.input.value);
});

dom.micBtn.addEventListener('click', toggleMic);
dom.briefBtn.addEventListener('click', renderBrief);
dom.settingsBtn.addEventListener('click', openSettings);
dom.settingsClose.addEventListener('click', closeSettings);
dom.settingsSave.addEventListener('click', saveSettings);
dom.settingsModal.addEventListener('click', (e) => {
  if (e.target === dom.settingsModal) closeSettings();
});

dom.resetBtn.addEventListener('click', () => {
  if (confirm('Erase everything Jarvis remembers about you? This cannot be undone.')) {
    store.reset();
    stopSpeaking();
    refreshMode();
    renderAll();
    closeSettings();
  }
});

dom.suggestions.addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  dom.input.value = chip.dataset.fill;
  dom.input.focus();
});

dom.memoryList.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-mem]');
  if (btn) {
    store.removeMemory(btn.dataset.mem);
    renderMemory();
    renderBrief();
  }
});

dom.reminderList.addEventListener('click', (e) => {
  const toggle = e.target.closest('[data-toggle]');
  if (toggle) {
    store.toggleReminder(toggle.dataset.toggle);
    renderReminders();
    renderBrief();
    return;
  }
  const remove = e.target.closest('[data-rem]');
  if (remove) {
    store.removeReminder(remove.dataset.rem);
    renderReminders();
    renderBrief();
  }
});

/* ---------------- Boot ---------------- */

function boot() {
  refreshMode();
  renderAll();
  initVoice();
  // First-run: open setup so the user can add a key (or continue in demo mode).
  if (!store.settings.apiKey && store.state.conversation.length === 0) {
    openSettings();
  }
  dom.input.focus();
}

boot();
