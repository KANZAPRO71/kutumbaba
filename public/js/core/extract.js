// Pure extraction of durable facts (memories) and follow-ups (reminders) from
// what the user says. This is what lets Jarvis "remember what matters" even in
// offline/demo mode. No side effects — callers persist the returned data.
import { parseDue } from './datetime.js';

const NAME_STOPLIST = new Set([
  'not', 'so', 'just', 'really', 'still', 'also', 'the', 'good', 'great',
  'fine', 'tired', 'busy', 'sorry', 'here', 'back', 'sure', 'okay', 'ok',
  'done', 'ready', 'happy', 'sad', 'free', 'late', 'early', 'going', 'trying',
  'glad', 'doing', 'thinking', 'looking', 'working', 'feeling', 'about', 'a',
  'an', 'afraid', 'certain', 'hungry', 'excited', 'worried', 'curious',
]);

const DUE_PHRASE =
  /\b(the day after tomorrow|today|tonight|tomorrow|this weekend|this morning|this afternoon|next week|in\s+\d+\s+(?:day|days|week|weeks)|(?:on|next|this)\s+(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday)|(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday)|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b/gi;

function clean(str) {
  return str
    .replace(/\s+/g, ' ')
    .replace(/^[\s,.-]+|[\s,.;:!?-]+$/g, '')
    .trim();
}

function cap(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function titleCase(str) {
  return str.replace(/\b([a-z])/g, (_, c) => c.toUpperCase());
}

// Turn "call Sarah tomorrow at 5pm" into "Call Sarah" (strip trailing time refs).
function stripDue(str) {
  return clean(str.replace(DUE_PHRASE, ' '));
}

function extractName(originalText) {
  let m = originalText.match(
    /\b(?:my name is|i am called|i'm called|call me)\s+([A-Za-z][a-zA-Z'-]{1,30})/i,
  );
  if (m) return cap(m[1]);

  m = originalText.match(/\b(?:i am|i'm)\s+([A-Z][a-zA-Z'-]{1,30})\b/);
  if (m && !NAME_STOPLIST.has(m[1].toLowerCase())) return cap(m[1]);

  return null;
}

/**
 * Extract structured facts from a single user utterance.
 * @returns {{ profile: object, memories: Array, reminders: Array }}
 */
export function extractFacts(text, now = new Date()) {
  const result = { profile: {}, memories: [], reminders: [] };
  if (!text || !text.trim()) return result;

  const original = text.trim();
  const t = original.toLowerCase();

  // ---- Identity ----
  const name = extractName(original);
  if (name) {
    result.profile.name = name;
    result.memories.push({ text: `User's name is ${name}.`, category: 'identity' });
  }

  // ---- Location ----
  let m = t.match(/\bi (?:live|reside) in\s+([a-z0-9 ,.'-]{2,40})/i) ||
    t.match(/\bi'?m (?:based|located) in\s+([a-z0-9 ,.'-]{2,40})/i);
  if (m) {
    const place = titleCase(clean(m[1]));
    result.profile.location = place;
    result.memories.push({ text: `Lives in ${place}.`, category: 'location' });
  }

  // ---- Work ----
  m = t.match(/\bi work (?:at|for)\s+([a-z0-9 &,.'-]{2,40})/i);
  if (m) {
    result.memories.push({ text: `Works at ${cap(clean(m[1]))}.`, category: 'work' });
  }
  m = t.match(/\bi(?:'m| am)\s+a[n]?\s+([a-z ]{3,40}?)(?:\s+at\s+([a-z0-9 &,.'-]{2,40}))?$/i);
  if (m && !NAME_STOPLIST.has(clean(m[1]).split(' ')[0])) {
    const role = clean(m[1]);
    const where = m[2] ? ` at ${cap(clean(m[2]))}` : '';
    if (role.length > 2) {
      result.memories.push({ text: `Works as a ${role}${where}.`, category: 'work' });
    }
  }

  // ---- Preferences ----
  m = t.match(/\bi (like|love|enjoy|prefer|hate|dislike|can't stand)\s+([a-z0-9 ,.'-]{2,60})/i);
  if (m) {
    result.memories.push({
      text: `${cap(m[1])}s ${clean(m[2])}.`,
      category: 'preference',
    });
  }
  m = t.match(/\bmy (?:favou?rite|fav)\s+([a-z ]{2,25})\s+is\s+([a-z0-9 ,.'-]{2,40})/i);
  if (m) {
    result.memories.push({
      text: `Favourite ${clean(m[1])} is ${clean(m[2])}.`,
      category: 'preference',
    });
  }

  // ---- Relationships ----
  m = t.match(
    /\bmy (wife|husband|partner|boss|manager|friend|mother|mom|father|dad|son|daughter|sister|brother|colleague|coworker|co-worker|doctor|therapist)(?:'s name)? is\s+([a-z][a-z'-]{1,30})/i,
  );
  if (m) {
    result.memories.push({
      text: `${cap(m[2])} is their ${m[1].toLowerCase()}.`,
      category: 'relationship',
    });
  }

  // ---- Important dates ----
  m = t.match(
    /\b(?:my |the )?([a-z]+(?:'s)?)\s+(birthday|anniversary)\s+is\s+([a-z0-9 ,.'-]{2,40})/i,
  );
  if (m) {
    result.memories.push({
      text: `${cap(clean(m[1]))} ${m[2].toLowerCase()} is ${clean(m[3])}.`,
      category: 'date',
    });
  }

  // ---- Explicit "remember this" notes ----
  m = original.match(
    /\b(?:remember that|note that|don't forget that|for the record,?|keep in mind that)\s+(.+)/i,
  );
  if (m) {
    result.memories.push({ text: clean(m[1]) + '.', category: 'note' });
  }

  // ---- Reminders / follow-ups (at most one primary follow-up per utterance) ----
  const reminder = extractReminder(original, t, now);
  if (reminder) result.reminders.push(reminder);

  return result;
}

function makeReminder(action, fullText, now) {
  const due = parseDue(fullText, now);
  const text = cap(stripDue(action));
  if (!text) return null;
  return {
    text,
    dueISO: due ? due.iso : null,
    dueLabel: due ? due.label : null,
  };
}

function extractReminder(original, t, now) {
  let m = original.match(
    /\b(?:remind me to|remind me that i need to|i need to remember to)\s+(.+)/i,
  );
  if (m) return makeReminder(m[1], m[1], now);

  m = original.match(/\bdon'?t let me forget to\s+(.+)/i);
  if (m) return makeReminder(m[1], m[1], now);

  m = original.match(/\bi (?:need|have|want) to\s+(.+)/i);
  if (m) return makeReminder(m[1], m[1], now);

  // Bare action verbs like "call Sarah tomorrow", "pay rent on Friday".
  m = original.match(
    /\b((?:call|email|text|message|follow up with|meet|pay|buy|book|schedule|send|pick up|drop off|renew|cancel|submit|finish|review|read)\b.+)/i,
  );
  if (m && DUE_PHRASE.test(t)) {
    DUE_PHRASE.lastIndex = 0;
    return makeReminder(m[1], m[1], now);
  }
  DUE_PHRASE.lastIndex = 0;
  return null;
}
