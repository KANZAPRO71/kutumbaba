import { test } from 'node:test';
import assert from 'node:assert/strict';

import { extractFacts } from '../public/js/core/extract.js';
import { parseDue, formatDay } from '../public/js/core/datetime.js';
import { buildMorningBrief } from '../public/js/core/brief.js';
import { mockReply } from '../public/js/core/reply.js';

// Fixed reference: Friday, Aug 7 2026, 09:00 local time.
const NOW = new Date(2026, 7, 7, 9, 0, 0);

test('parseDue understands "tomorrow"', () => {
  const due = parseDue('call the dentist tomorrow', NOW);
  assert.ok(due, 'expected a due date');
  assert.equal(due.label, 'Tomorrow');
  const d = new Date(due.iso);
  assert.equal(d.getDate(), 8);
  assert.equal(d.getMonth(), 7);
});

test('parseDue understands "in 3 days"', () => {
  const due = parseDue('submit the report in 3 days', NOW);
  assert.ok(due);
  assert.equal(new Date(due.iso).getDate(), 10);
});

test('parseDue returns null when no time reference exists', () => {
  assert.equal(parseDue('just a random thought', NOW), null);
});

test('extractFacts captures the user name', () => {
  const facts = extractFacts('Hi, my name is Alex.', NOW);
  assert.equal(facts.profile.name, 'Alex');
  assert.ok(
    facts.memories.some((m) => m.category === 'identity' && /Alex/.test(m.text)),
  );
});

test('extractFacts does not treat "I\'m tired" as a name', () => {
  const facts = extractFacts("I'm tired today", NOW);
  assert.equal(facts.profile.name, undefined);
});

test('extractFacts captures a preference', () => {
  const facts = extractFacts('I love spicy ramen', NOW);
  assert.ok(
    facts.memories.some(
      (m) => m.category === 'preference' && /ramen/i.test(m.text),
    ),
  );
});

test('extractFacts turns "remind me to…" into a dated reminder', () => {
  const facts = extractFacts('Remind me to call Sarah tomorrow', NOW);
  assert.equal(facts.reminders.length, 1);
  const r = facts.reminders[0];
  assert.match(r.text, /call sarah/i);
  assert.equal(r.dueLabel, 'Tomorrow');
  // Time reference stripped from the reminder text.
  assert.doesNotMatch(r.text, /tomorrow/i);
});

test('extractFacts handles bare action + time ("pay rent on Friday")', () => {
  const facts = extractFacts('Pay rent on Friday', NOW);
  assert.equal(facts.reminders.length, 1);
  assert.match(facts.reminders[0].text, /pay rent/i);
});

test('buildMorningBrief greets by name and lists items due today', () => {
  const state = {
    profile: { name: 'Alex' },
    memories: [{ text: "User's name is Alex.", category: 'identity' }],
    reminders: [
      { text: 'Call Sarah', dueISO: NOW.toISOString(), done: false },
      { text: 'Buy milk', dueISO: null, done: false },
    ],
  };
  const brief = buildMorningBrief(state, NOW);
  assert.match(brief, /Good morning, Alex/);
  assert.match(brief, /Due today/);
  assert.match(brief, /Call Sarah/);
});

test('mockReply recalls the saved name', () => {
  const state = {
    profile: { name: 'Alex' },
    memories: [{ text: "User's name is Alex.", category: 'identity' }],
    reminders: [],
  };
  const reply = mockReply("what's my name?", state, extractFacts('', NOW), NOW);
  assert.match(reply, /Alex/);
});

test('mockReply acknowledges a new reminder', () => {
  const extracted = extractFacts('Remind me to call Sarah tomorrow', NOW);
  const state = {
    profile: {},
    memories: [],
    reminders: extracted.reminders.map((r) => ({ ...r, done: false })),
  };
  const reply = mockReply(
    'Remind me to call Sarah tomorrow',
    state,
    extracted,
    NOW,
  );
  assert.match(reply, /remind you to/i);
  assert.match(reply, /tomorrow/i);
});

test('formatDay labels today and tomorrow', () => {
  assert.equal(formatDay(NOW, NOW), 'Today');
  const tomorrow = new Date(2026, 7, 8, 9, 0, 0);
  assert.equal(formatDay(tomorrow, NOW), 'Tomorrow');
});
