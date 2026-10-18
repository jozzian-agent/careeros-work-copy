// The owner's locale format for a stored timestamp, per the canvas:
// "14 Oct 2026, 14:10". Every surface that shows a stored time reads it
// through here, so two pages can never disagree about how a date looks.
// An absent or unparseable value renders as nothing rather than as
// "Invalid Date".
export function localDate(ts) {
  const parsed = new Date(ts);
  if (!ts || Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

// A stored day (the vault writes YYYY-MM-DD) as the board card says it:
// "14 Oct" this year, "14 Oct 2025" in any other, per the 2026-10-18
// board artboard. The year is what a reader needs only once it is not
// the obvious one, and the card has one line for location and date.
//
// Parsed from the date parts rather than by `new Date(value)`, which
// reads a bare YYYY-MM-DD as UTC midnight and so shows the day before
// for anyone west of UTC. An unparseable or absent value renders as
// nothing, the same rule localDate follows.
export function shortDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ''));
  if (!match) return '';
  const [, year, month, day] = match;
  const parsed = new Date(Number(year), Number(month) - 1, Number(day));
  if (Number.isNaN(parsed.getTime())) return '';
  const options = { day: 'numeric', month: 'short' };
  if (parsed.getFullYear() !== new Date().getFullYear()) options.year = 'numeric';
  return parsed.toLocaleDateString('en-GB', options);
}
