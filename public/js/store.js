// Browser-side persistent store. Everything lives in localStorage, so Jarvis
// remembers you across sessions and nothing is sent to any server but Google's
// (via your own API key). "Private by design."
import { extractFacts } from './core/extract.js';

const KEY = 'jarvis.state.v1';

const DEFAULT_STATE = {
  profile: { name: '', location: '', email: '' },
  settings: { apiKey: '', model: 'gemini-2.0-flash', voice: true, autoListen: false },
  memories: [],
  reminders: [],
  conversation: [],
};

function uid() {
  if (globalThis.crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'id-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function normalize(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

export class Store {
  constructor(storage = globalThis.localStorage) {
    this.storage = storage;
    this.state = this._load();
  }

  _load() {
    try {
      const raw = this.storage.getItem(KEY);
      if (!raw) return structuredClone(DEFAULT_STATE);
      const parsed = JSON.parse(raw);
      return {
        ...structuredClone(DEFAULT_STATE),
        ...parsed,
        profile: { ...DEFAULT_STATE.profile, ...(parsed.profile || {}) },
        settings: { ...DEFAULT_STATE.settings, ...(parsed.settings || {}) },
      };
    } catch {
      return structuredClone(DEFAULT_STATE);
    }
  }

  save() {
    try {
      this.storage.setItem(KEY, JSON.stringify(this.state));
    } catch {
      /* storage may be unavailable (private mode) — degrade gracefully */
    }
  }

  // Snapshot used by pure core functions.
  snapshot() {
    return {
      profile: this.state.profile,
      memories: this.state.memories,
      reminders: this.state.reminders,
    };
  }

  get settings() {
    return this.state.settings;
  }

  updateSettings(patch) {
    Object.assign(this.state.settings, patch);
    this.save();
  }

  updateProfile(patch) {
    Object.assign(this.state.profile, patch);
    this.save();
  }

  addMessage(role, text, extra = {}) {
    const msg = { id: uid(), role, text, ts: Date.now(), ...extra };
    this.state.conversation.push(msg);
    if (this.state.conversation.length > 200) {
      this.state.conversation = this.state.conversation.slice(-200);
    }
    this.save();
    return msg;
  }

  recentTurns(limit = 12) {
    return this.state.conversation.slice(-limit);
  }

  addMemory(text, category = 'note') {
    const clean = text.trim();
    if (!clean) return null;
    const exists = this.state.memories.some(
      (m) => normalize(m.text) === normalize(clean),
    );
    if (exists) return null;
    // Identity is singular — replace any existing name memory.
    if (category === 'identity') {
      this.state.memories = this.state.memories.filter(
        (m) => m.category !== 'identity',
      );
    }
    const mem = { id: uid(), text: clean, category, createdAt: Date.now() };
    this.state.memories.push(mem);
    this.save();
    return mem;
  }

  removeMemory(id) {
    this.state.memories = this.state.memories.filter((m) => m.id !== id);
    this.save();
  }

  addReminder({ text, dueISO = null, dueLabel = null }) {
    const clean = (text || '').trim();
    if (!clean) return null;
    const dup = this.state.reminders.some(
      (r) => !r.done && normalize(r.text) === normalize(clean) && r.dueISO === dueISO,
    );
    if (dup) return null;
    const rem = {
      id: uid(),
      text: clean,
      dueISO,
      dueLabel,
      done: false,
      createdAt: Date.now(),
    };
    this.state.reminders.push(rem);
    this.save();
    return rem;
  }

  toggleReminder(id) {
    const r = this.state.reminders.find((x) => x.id === id);
    if (r) {
      r.done = !r.done;
      this.save();
    }
  }

  removeReminder(id) {
    this.state.reminders = this.state.reminders.filter((r) => r.id !== id);
    this.save();
  }

  /**
   * Extract facts from a user utterance and persist them.
   * @returns {{extracted:object, newMemories:Array, newReminders:Array}}
   */
  learnFrom(text, now = new Date()) {
    const extracted = extractFacts(text, now);
    if (extracted.profile.name) this.updateProfile({ name: extracted.profile.name });
    if (extracted.profile.location)
      this.updateProfile({ location: extracted.profile.location });

    const newMemories = [];
    for (const m of extracted.memories) {
      const added = this.addMemory(m.text, m.category);
      if (added) newMemories.push(added);
    }
    const newReminders = [];
    for (const r of extracted.reminders) {
      const added = this.addReminder(r);
      if (added) newReminders.push(added);
    }
    return { extracted, newMemories, newReminders };
  }

  reset() {
    this.state = structuredClone(DEFAULT_STATE);
    this.save();
  }
}
