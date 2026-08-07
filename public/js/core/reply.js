// Pure offline "brain" used in demo mode (no API key configured).
// It gives Jarvis a genuinely useful conversation loop — acknowledging new facts,
// recalling what it knows, and listing follow-ups — without any network calls.
import { buildMorningBrief } from './brief.js';
import { formatDay, isPast } from './datetime.js';

function pick(arr, seed = 0) {
  return arr[seed % arr.length];
}

function listMemories(state) {
  const mems = state.memories || [];
  if (!mems.length) return "I don't have anything saved about you yet. Tell me about yourself and I'll remember.";
  const bullets = mems.slice(-8).map((m) => `• ${m.text}`);
  return `Here's what I remember about you:\n${bullets.join('\n')}`;
}

function listReminders(state, now) {
  const open = (state.reminders || []).filter((r) => !r.done);
  if (!open.length) return "You have no open follow-ups right now. I'll track anything you ask me to remember.";
  const bullets = open.map((r) => {
    if (!r.dueISO) return `• ${r.text}`;
    const when = formatDay(r.dueISO, now);
    const flag = isPast(r.dueISO, now) ? ' (overdue)' : '';
    return `• ${r.text} — ${when}${flag}`;
  });
  return `Here are your follow-ups:\n${bullets.join('\n')}`;
}

function acknowledge(extracted, now) {
  const parts = [];
  if (extracted.profile && extracted.profile.name) {
    parts.push(`Nice to meet you, ${extracted.profile.name}!`);
  }
  const otherMems = (extracted.memories || []).filter(
    (m) => m.category !== 'identity',
  );
  if (otherMems.length === 1) {
    parts.push(`Got it — I'll remember that.`);
  } else if (otherMems.length > 1) {
    parts.push(`Got it — I've noted ${otherMems.length} things about that.`);
  }
  (extracted.reminders || []).forEach((r) => {
    if (r.dueLabel) {
      parts.push(`I'll remind you to ${lower(r.text)} — ${r.dueLabel.toLowerCase()}.`);
    } else {
      parts.push(`Added "${r.text}" to your follow-ups.`);
    }
  });
  return parts.join(' ');
}

function lower(str) {
  return str.charAt(0).toLowerCase() + str.slice(1);
}

/**
 * Generate an assistant reply for demo mode.
 * @param {string} userText
 * @param {object} state   memory/reminder state AFTER this turn's facts were applied
 * @param {object} extracted  the facts extracted from this turn
 */
export function mockReply(userText, state, extracted, now = new Date()) {
  const t = (userText || '').toLowerCase().trim();

  // ---- Recall questions ----
  if (/\b(what('?s| is) my name|who am i|do you (know|remember) my name)\b/.test(t)) {
    const name = state.profile && state.profile.name;
    return name
      ? `You're ${name} — of course I remember. 🙂`
      : "I don't know your name yet. Tell me and I'll never forget it.";
  }

  if (/\b(what do you (know|remember)|what have you (saved|remembered)|tell me what you know)\b/.test(t)) {
    return listMemories(state);
  }

  if (/\b(my )?(reminders|follow[- ]?ups|to[- ]?do|tasks|what do i (need|have) to do|what'?s on my (list|plate))\b/.test(t)) {
    return listReminders(state, now);
  }

  if (/\b(morning brief|daily brief|catch me up|what'?s today|brief me)\b/.test(t)) {
    return buildMorningBrief(state, now);
  }

  // ---- Live-web questions need a real key ----
  if (/\b(weather|forecast|news|headlines|score|stock|price of|who won|latest)\b/.test(t)) {
    const ack = acknowledge(extracted, now);
    return (
      (ack ? ack + '\n\n' : '') +
      "For live answers with sources — weather, news, facts — I use Google Search through Gemini. Add your free Gemini API key in Settings and I'll pull that in real time. Right now I'm running in offline demo mode."
    );
  }

  // ---- Greetings ----
  if (/^(hi|hey|hello|yo|good (morning|afternoon|evening)|jarvis)\b/.test(t) && !extracted.memories.length && !extracted.reminders.length) {
    const name = state.profile && state.profile.name ? ` ${state.profile.name}` : '';
    return pick([
      `Hey${name}! I'm listening. Tell me what's on your mind, or ask me what I remember about you.`,
      `Hi${name} — I'm here. You can tell me things to remember, set follow-ups, or ask for your morning brief.`,
    ], t.length);
  }

  // ---- Default: acknowledge what we learned ----
  const ack = acknowledge(extracted, now);
  if (ack) {
    const openCount = (state.reminders || []).filter((r) => !r.done).length;
    const tail = openCount
      ? ` You've got ${openCount} follow-up${openCount === 1 ? '' : 's'} on your list.`
      : '';
    return ack + tail;
  }

  // Nothing structured — reflect and keep the conversation going.
  return pick([
    "I hear you. I've logged this to our conversation. Tell me anything you want me to remember, or ask me to set a reminder.",
    "Noted. If there's a name, date, or task in there you want me to hold onto, just say \u201cremember\u2026\u201d or \u201cremind me to\u2026\u201d.",
    'Understood. Want me to add a follow-up or give you your morning brief?',
  ], t.length);
}
