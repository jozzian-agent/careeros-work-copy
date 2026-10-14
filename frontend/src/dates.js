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
