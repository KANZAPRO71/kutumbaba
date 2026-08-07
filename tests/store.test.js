import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Store } from '../public/js/store.js';

class MemStorage {
  constructor() {
    this.map = new Map();
  }
  getItem(k) {
    return this.map.has(k) ? this.map.get(k) : null;
  }
  setItem(k, v) {
    this.map.set(k, String(v));
  }
  removeItem(k) {
    this.map.delete(k);
  }
}

const NOW = new Date(2026, 7, 7, 9, 0, 0);

test('learnFrom persists memories and reminders', () => {
  const store = new Store(new MemStorage());
  const { newMemories, newReminders } = store.learnFrom(
    'My name is Alex and remind me to call Sarah tomorrow',
    NOW,
  );
  assert.ok(newMemories.length >= 1);
  assert.equal(newReminders.length, 1);
  assert.equal(store.state.profile.name, 'Alex');
});

test('memory persists across store reloads (survives closing the app)', () => {
  const storage = new MemStorage();
  const first = new Store(storage);
  first.learnFrom('I live in Austin', NOW);

  const second = new Store(storage);
  assert.equal(second.state.profile.location, 'Austin');
  assert.ok(second.state.memories.some((m) => /Austin/i.test(m.text)));
});

test('duplicate memories are not stored twice', () => {
  const store = new Store(new MemStorage());
  store.learnFrom('I love spicy ramen', NOW);
  store.learnFrom('I love spicy ramen', NOW);
  const ramen = store.state.memories.filter((m) => /ramen/i.test(m.text));
  assert.equal(ramen.length, 1);
});

test('a new name replaces the previous identity memory', () => {
  const store = new Store(new MemStorage());
  store.learnFrom('My name is Alex', NOW);
  store.learnFrom('Actually my name is Jordan', NOW);
  const identity = store.state.memories.filter((m) => m.category === 'identity');
  assert.equal(identity.length, 1);
  assert.match(identity[0].text, /Jordan/);
  assert.equal(store.state.profile.name, 'Jordan');
});

test('reminders can be toggled done and removed', () => {
  const store = new Store(new MemStorage());
  const { newReminders } = store.learnFrom('Remind me to buy milk tomorrow', NOW);
  const id = newReminders[0].id;
  store.toggleReminder(id);
  assert.equal(store.state.reminders.find((r) => r.id === id).done, true);
  store.removeReminder(id);
  assert.equal(store.state.reminders.length, 0);
});
