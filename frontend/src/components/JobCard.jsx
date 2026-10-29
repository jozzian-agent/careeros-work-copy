import { Badge, Box, Button, Flex, Heading, Icon, Link, Text } from 'gestalt';
import QuietChip from './QuietChip.jsx';
import AiStatusChip from './AiStatusChip.jsx';
import StatusSelect from './StatusSelect.jsx';
import { aiStatus } from '../aiStatus.js';
import { countWord } from '../counts.js';
import { shortDate } from '../dates.js';
import { displayLocation } from '../location.js';

function jobHref(id) {
  return `/jobs/${encodeURIComponent(id)}`;
}

function companyHref(id) {
  return `/companies/${encodeURIComponent(id)}`;
}

// The company link is either confirmed (company_name + company_id, no
// review pending), tentative-but-still-in-review (company_link_state
// "needs_review" with a candidate name + id already attached), stuck in
// the owner-review queue with no candidate yet (needs_review, no name),
// or genuinely unresolved ("pending", no candidate at all). A tentative
// name alongside needs_review renders BOTH the link and the review chip
// together, since the link is informative even though it is not yet the
// owner's confirmed decision. Kept from the pre-rebuild board: the
// JobCard README's anatomy has no slot for company-match review state,
// but dropping it would silently remove a working feature unrelated to
// this ticket's fit/status rebuild.
// `withReviewChip` is false on a board card since 2026-10-18: the card's
// top row carries one "Needs your input" chip for every reason a job
// needs the owner (see NeedsInputChip), so repeating it beside the
// company link would say the same thing twice. The list view, which has
// no such row, still shows it here.
export function CompanyDisplay({ job, withReviewChip = true }) {
  const hasCandidate = job.company_name && job.company_id;
  const companyLink = hasCandidate ? (
    <Link href={companyHref(job.company_id)} display="inlineBlock">
      <Text size="200" weight="bold" color="link">
        {job.company_name}
      </Text>
    </Link>
  ) : null;
  if (job.company_link_state === 'needs_review' && withReviewChip) {
    return (
      <Flex gap={2} alignItems="center" wrap>
        {companyLink}
        <Badge type="recommendation" text="Needs your input" />
      </Flex>
    );
  }
  if (hasCandidate) {
    return companyLink;
  }
  return <Badge type="neutral" text="Company: pending" />;
}

// The card's one "this job is waiting on you" chip, top left (artboard
// 2026-10-18): the violet wash with a violet ring, not a filled badge, so
// it informs without alarming (design-system.md "Badge usage").
//
// It reads the payload's own `needs_attention`, which is the same flag the
// filter bar's "Needs attention" chip counts (careeros/web/pages/jobs.py
// needs_attention): an unresolved company link, an ingest that got stuck,
// or a posting whose title the reading could not find. One source, so the
// chip and the filter can never disagree about which cards they mean.
function NeedsInputChip({ job }) {
  if (!job.needs_attention) return null;
  return (
    <span
      data-testid="needs-input-chip"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        height: 24,
        padding: '0 10px',
        borderRadius: 999,
        background: 'var(--color-brand-wash-violet)',
        color: 'var(--color-text-default)',
        fontSize: 12,
        lineHeight: '16px',
        fontWeight: 700,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: 8,
          height: 8,
          border: '2px solid var(--color-brand-violet)',
          borderRadius: '50%',
          flex: 'none',
        }}
      />
      Needs your input
    </span>
  );
}

// Also kept from the pre-rebuild board for the same reason: ingest retry is
// real functionality (not an informational badge) with no replacement
// surfaced anywhere else yet. Every state here renders as a quiet chip, not
// a colored badge (design-system.md "Badge usage"): a machine-state notice
// like a failed extraction must never alarm.
export function IngestIndicator({ job, onRetry }) {
  // CAREER-37: when the record carries an AI status of its own, that is
  // the reading's own report and it wins. A record with none (absent, so
  // every job written before the field existed) falls through to what
  // this indicator always inferred from ingest_state, which is what keeps
  // an old vault reading exactly as it did.
  const reading = aiStatus(job);
  if (reading !== 'absent' && reading !== 'done') {
    return <AiStatusChip job={job} onRetry={onRetry} />;
  }
  if (job.ingest_state === 'fetch_failed' || job.ingest_state === 'extract_failed') {
    const label = job.ingest_state === 'fetch_failed' ? 'Fetch failed' : 'Extraction failed';
    const reason = job.ingest_error?.reason;
    return (
      <Flex gap={2} alignItems="center" wrap>
        <QuietChip text={reason ? `${label}, ${reason}` : label} />
        <Button size="sm" color="gray" text="Retry" onClick={() => onRetry(job.id)} />
      </Flex>
    );
  }
  if (!job.enriched && (job.ingest_state === 'stub' || job.ingest_state === 'fetched')) {
    return <QuietChip text="Details filling in…" />;
  }
  if (!job.enriched) {
    return <QuietChip text="Enrichment pending" />;
  }
  return null;
}

// The closed posting, as the card's last row (D7). A posting that is gone
// is a fact about the posting and never the owner's decision, so it is
// this chip rather than a status.
//
// Two states, and which one shows is NOT decided here. `closedDays` is the
// payload's own closed_review day count for this job, present only for the
// jobs the banner asks about as well (a status before Applied, gone more
// than a week, not kept). So the chip and the banner read one list and
// cannot disagree, and no date arithmetic happens in the browser.
//
// The warning state is a recorded exception to design-system.md "Badge
// usage" (a machine-state notice must never alarm): the canvas asks for
// warning-weak ground and an alert icon here, because a posting going
// stale for a week on a job the owner never applied to is the one closed
// posting that wants their attention.
export function ClosedChip({ job, closedDays }) {
  if (!job.closed) return null;
  if (closedDays === null || closedDays === undefined) {
    return <QuietChip text="Posting closed" />;
  }
  return (
    <Box
      display="inlineBlock"
      rounding="pill"
      paddingX={3}
      dangerouslySetInlineStyle={{
        __style: {
          background: 'var(--color-background-warning-weak)',
          height: 'var(--space-600)',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 'var(--space-100)',
        },
      }}
    >
      <Icon icon="alert" accessibilityLabel="" color="warning" size={12} />
      <Text size="100" color="warning">
        {`Closed ${countWord(closedDays, 'day')} ago`}
      </Text>
    </Box>
  );
}

// An ended card says why the job ended, or offers to say it. A reason is
// always optional (D7), so the link is an offer and never a task left open.
function EndedReason({ job, canExplain, onAddReason }) {
  if (job.end_reason) {
    return (
      <Text size="200" color="subtle">
        {job.end_reason}
      </Text>
    );
  }
  // Won has no reason vocabulary, so nothing offers to pick one for it.
  if (!canExplain) return null;
  return (
    <Box>
      <Button
        size="sm"
        color="transparent"
        text="Add a reason"
        accessibilityLabel={`Add a reason ${job.title} ended`}
        onClick={() => onAddReason(job)}
      />
    </Box>
  );
}

// The card for one job on the board, per the approved artboard
// (2026-10-18):
// 1. Top row, 32px tall: the "Needs your input" chip on the left when the
//    job is waiting on the owner, the compact status select on the right.
// 2. Title (16px bold, two lines max) and the company link (14px bold,
//    ink-black and underlined, --color-text-link), 4px apart.
// 3. One meta line: a pin and the location, then "Added 14 Oct".
// 4. The closed posting, when there is one (D7, ClosedChip above).
//
// What the artboard removed, and why. The sector, size, salary and
// function badges are gone: four of them on one 320px card wrapped past
// its edge, and every one of them is a filter above the board or a line
// on the detail page, so the card was repeating what the owner already
// has a way to ask for. "Posted" is gone for the same reason -- the card
// says when the job entered the board, which is the date the owner reads
// it by, and the posting's own date is on the detail page. The fit chip
// went in 2026-10-15 (fit scoring is not built). No source badge and no
// AI-generated badge either (design-system.md "Badge usage").
//
// The ingest indicator stays. It is not a badge: a failed read is a
// visible state with a Try again beside it, and the board has no other
// route to that retry (product rule: a failure is visible with a way to
// retry). The location line is deduped for display only, by
// src/location.js.
//
// `compact` is the Ended lane's own card (D7): title, company, and the
// reason the job ended or the link that adds one. An ended job needs
// nothing said about its posting or its enrichment, but it keeps the
// status select, because dragging it back into an open column has to have
// a keyboard route too.
//
// `onMyBoard` false is the All jobs tab's own card (B2, CAREER-89): a
// posting the reader has not added yet, so the top row offers "Add to my
// jobs" where a card of theirs shows its status. Three things go with the
// status, because each of them is about a record this reader does not
// hold: the "Needs your input" chip (somebody else is being asked), the
// ingest indicator and its Try again (the retry is owner-scoped and would
// answer not-found), and any drag (there is no column to drop it in). The
// posting itself reads exactly as it does on the board.
export default function JobCard({
  job,
  statuses,
  statusLabels,
  endedStatuses,
  closedDays,
  compact = false,
  canExplain = false,
  onMyBoard = true,
  onAdd,
  addBusy = false,
  onMove,
  onRetry,
  onAddReason,
  dragHandlers,
  isDragging,
}) {
  const draggable = dragHandlers ? 'true' : 'false';
  const location = displayLocation(job.location);
  const added = shortDate(job.added);

  return (
    <div
      data-testid={`job-card-${job.id}`}
      draggable={draggable}
      style={{ opacity: isDragging ? 0.4 : 1 }}
      {...dragHandlers}
    >
      <Box color="default" borderStyle="sm" rounding={4} padding={compact ? 3 : 4} marginBottom={3}>
        <Flex direction="column" gap={compact ? 2 : 3}>
          {/* The row keeps its 32px height with no chip in it, so the
              status select sits on one line across a column of cards. */}
          <Box minHeight={32} display="flex" alignItems="center">
            <Flex flex="grow" justifyContent="between" alignItems="center" gap={2}>
              <span>{compact || !onMyBoard ? null : <NeedsInputChip job={job} />}</span>
              {onMyBoard ? (
                <StatusSelect
                  id={job.id}
                  jobTitle={job.title}
                  status={job.status}
                  statuses={statuses}
                  statusLabels={statusLabels}
                  endedStatuses={endedStatuses}
                  onChange={(status) => onMove(job.id, status)}
                />
              ) : (
                <Button
                  size="sm"
                  color="gray"
                  text="Add to my jobs"
                  accessibilityLabel={`Add ${job.title} to my jobs`}
                  disabled={addBusy}
                  onClick={() => onAdd(job)}
                />
              )}
            </Flex>
          </Box>
          <Flex direction="column" gap={1}>
            <Link href={jobHref(job.id)} display="inlineBlock">
              <Heading size="300" lineClamp={2}>
                {job.title}
              </Heading>
            </Link>
            <CompanyDisplay job={job} withReviewChip={compact} />
          </Flex>
          {compact ? <EndedReason job={job} canExplain={canExplain} onAddReason={onAddReason} /> : null}
          {compact ? null : (
            <>
              <Flex gap={3} alignItems="center" wrap>
                <Flex gap={1} alignItems="center">
                  <Icon icon="location" accessibilityLabel="" color="subtle" size={14} />
                  <Text size="200" color="subtle">
                    {location || 'Location unknown'}
                  </Text>
                </Flex>
                {added ? (
                  <Text size="200" color="subtle">
                    {`Added ${added}`}
                  </Text>
                ) : null}
              </Flex>
              {onMyBoard ? <IngestIndicator job={job} onRetry={onRetry} /> : null}
              <ClosedChip job={job} closedDays={closedDays} />
            </>
          )}
        </Flex>
      </Box>
    </div>
  );
}
