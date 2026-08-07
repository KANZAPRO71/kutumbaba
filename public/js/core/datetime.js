// Pure date/time helpers for reminder scheduling and display.
// No DOM or browser globals — safe to import in Node tests and the browser.

export const WEEKDAYS = [
  'sunday',
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
];

const MONTHS_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

export function startOfDay(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function addDays(date, days) {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

export function isSameDay(a, b) {
  const da = new Date(a);
  const db = new Date(b);
  return (
    da.getFullYear() === db.getFullYear() &&
    da.getMonth() === db.getMonth() &&
    da.getDate() === db.getDate()
  );
}

// Returns the next date (strictly today or later) that falls on `weekdayIndex`.
function nextWeekday(now, weekdayIndex, forceNext = false) {
  const base = startOfDay(now);
  let delta = (weekdayIndex - base.getDay() + 7) % 7;
  if (delta === 0 && forceNext) delta = 7;
  return addDays(base, delta);
}

/**
 * Parse a natural-language due phrase into a concrete date.
 * Returns `{ iso, label }` or `null` when no date reference is found.
 */
export function parseDue(text, now = new Date()) {
  if (!text) return null;
  const t = text.toLowerCase();
  const today = startOfDay(now);

  let due = null;
  let evening = false;

  if (/\b(the day after tomorrow)\b/.test(t)) {
    due = addDays(today, 2);
  } else if (/\btomorrow\b/.test(t)) {
    due = addDays(today, 1);
  } else if (/\btonight\b/.test(t)) {
    due = today;
    evening = true;
  } else if (/\b(today|this afternoon|this morning)\b/.test(t)) {
    due = today;
  } else if (/\bthis weekend\b/.test(t)) {
    due = nextWeekday(now, 6); // Saturday
  } else if (/\bnext week\b/.test(t)) {
    due = addDays(today, 7);
  } else {
    const inMatch = t.match(/\bin\s+(\d+)\s+(day|days|week|weeks)\b/);
    if (inMatch) {
      const n = parseInt(inMatch[1], 10);
      due = addDays(today, /week/.test(inMatch[2]) ? n * 7 : n);
    } else {
      const weekdayMatch = t.match(
        /\b(?:on\s+|next\s+|this\s+)?(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b/,
      );
      if (weekdayMatch) {
        const idx = WEEKDAYS.indexOf(weekdayMatch[1]);
        const forceNext = /\bnext\b/.test(t);
        due = nextWeekday(now, idx, forceNext);
      }
    }
  }

  if (!due) return null;

  if (evening) due.setHours(19, 0, 0, 0);

  return { iso: due.toISOString(), label: formatDay(due, now) };
}

/** Human-friendly day label relative to `now` (Today / Tomorrow / Mon, Aug 11). */
export function formatDay(date, now = new Date()) {
  const d = new Date(date);
  const today = startOfDay(now);
  const target = startOfDay(d);
  const diffDays = Math.round((target - today) / (24 * 60 * 60 * 1000));

  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Tomorrow';
  if (diffDays === -1) return 'Yesterday';

  const weekday = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  return `${weekday}, ${MONTHS_SHORT[d.getMonth()]} ${d.getDate()}`;
}

/** True when the reminder is due today or earlier (and not done). */
export function isDueBy(iso, now = new Date()) {
  if (!iso) return false;
  return startOfDay(iso) <= startOfDay(now);
}

export function isToday(iso, now = new Date()) {
  return isSameDay(iso, now);
}

export function isPast(iso, now = new Date()) {
  return startOfDay(iso) < startOfDay(now);
}
