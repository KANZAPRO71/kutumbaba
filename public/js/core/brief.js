// Pure "morning brief" generator — the summary of what you can't afford to forget.
import { formatDay, isDueBy, isPast, startOfDay } from './datetime.js';

function greeting(now) {
  const h = new Date(now).getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

function longDate(now) {
  return new Date(now).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

/**
 * Build a plain-text brief from the current memory/reminder state.
 * @param {{profile:object, memories:Array, reminders:Array}} state
 */
export function buildMorningBrief(state, now = new Date()) {
  const name = state.profile && state.profile.name ? `, ${state.profile.name}` : '';
  const lines = [];
  lines.push(`${greeting(now)}${name}. Today is ${longDate(now)}.`);

  const openReminders = (state.reminders || []).filter((r) => !r.done);
  const overdue = openReminders
    .filter((r) => r.dueISO && isPast(r.dueISO, now))
    .sort((a, b) => new Date(a.dueISO) - new Date(b.dueISO));
  const dueToday = openReminders.filter(
    (r) => r.dueISO && !isPast(r.dueISO, now) && isDueBy(r.dueISO, now),
  );
  const upcoming = openReminders
    .filter((r) => r.dueISO && startOfDay(r.dueISO) > startOfDay(now))
    .sort((a, b) => new Date(a.dueISO) - new Date(b.dueISO))
    .slice(0, 3);
  const someday = openReminders.filter((r) => !r.dueISO);

  if (overdue.length) {
    lines.push('');
    lines.push(`⚠️ Overdue (${overdue.length}):`);
    overdue.forEach((r) => lines.push(`• ${r.text} (was ${formatDay(r.dueISO, now)})`));
  }

  if (dueToday.length) {
    lines.push('');
    lines.push(`📌 Due today (${dueToday.length}):`);
    dueToday.forEach((r) => lines.push(`• ${r.text}`));
  }

  if (upcoming.length) {
    lines.push('');
    lines.push('🗓️ Coming up:');
    upcoming.forEach((r) => lines.push(`• ${r.text} — ${formatDay(r.dueISO, now)}`));
  }

  if (someday.length) {
    lines.push('');
    lines.push('📝 On your list:');
    someday.slice(0, 3).forEach((r) => lines.push(`• ${r.text}`));
  }

  if (!overdue.length && !dueToday.length && !upcoming.length && !someday.length) {
    lines.push('');
    lines.push("You're all clear — no follow-ups on the calendar. ✅");
  }

  const memCount = (state.memories || []).length;
  if (memCount) {
    lines.push('');
    lines.push(
      `I'm keeping ${memCount} thing${memCount === 1 ? '' : 's'} in mind about you. Ask me anytime what I remember.`,
    );
  }

  return lines.join('\n');
}
