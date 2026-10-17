// Where a record's own AI reading stands (CAREER-36/37). The words are
// the backend's, from careeros/vault.py AI_STATUSES, and this module is
// the one place the front end reads them, so the chip and the polling
// cannot disagree about what counts as still in flight.
//
// A record with no ai_status at all never tried, which is every record
// written before the field existed. That absence is read here as its own
// word rather than treated as a reading in flight, so an old vault does
// not come up covered in chips for work nobody started.
const KNOWN = ['queued', 'running', 'done', 'failed'];

// The two statuses that mean work is still owed, so something is going to
// change on its own and the page has a reason to look again.
export const AI_UNSETTLED = ['queued', 'running'];

export function aiStatus(job) {
  const value = job && job.ai_status;
  return KNOWN.includes(value) ? value : 'absent';
}

// True while any of these jobs still has a reading owed. What the board
// and the job page both use to decide whether to keep polling, and the
// reason polling stops on its own once every reading has landed.
export function anyReading(jobs) {
  return (jobs || []).some((job) => AI_UNSETTLED.includes(aiStatus(job)));
}
