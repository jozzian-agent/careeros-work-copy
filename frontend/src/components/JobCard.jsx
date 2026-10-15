import { Badge, Box, Button, Flex, Heading, Icon, Link, Text } from 'gestalt';
import QuietChip from './QuietChip.jsx';
import StatusSelect from './StatusSelect.jsx';
import { countWord } from '../counts.js';

// Label text only, per the owner's 2026-10-13 decision (design-system.md
// "Badge usage"): the board shows a size class, never a numeric range.
// Since 2026-10-15 the board's own Company size filter reads the same
// `company_size_class` this badge does, so the two cannot disagree.
const SIZE_CLASS_LABELS = { micro: 'Micro', small: 'Small', medium: 'Medium', large: 'Large' };

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
export function CompanyDisplay({ job }) {
  const hasCandidate = job.company_name && job.company_id;
  const companyLink = hasCandidate ? (
    <Link href={companyHref(job.company_id)} display="inlineBlock">
      <Text size="200" color="link">
        {job.company_name}
      </Text>
    </Link>
  ) : null;
  if (job.company_link_state === 'needs_review') {
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

// Also kept from the pre-rebuild board for the same reason: ingest retry is
// real functionality (not an informational badge) with no replacement
// surfaced anywhere else yet. Every state here renders as a quiet chip, not
// a colored badge (design-system.md "Badge usage"): a machine-state notice
// like a failed extraction must never alarm.
export function IngestIndicator({ job, onRetry }) {
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

// The card for one job on the board. Anatomy per the JobCard README,
// minus the fit chip the README's top row had (owner decision 2026-10-15:
// fit scoring is not built, nothing is written to `fit`, so every card
// read "Needs your input" for a rating nobody can give. The chip comes
// back with the scoring itself; the Job detail page keeps saying "Not
// calculated yet", which is the honest answer to the same question):
// 1. Top row: the status select, right-aligned.
// 2. Title (bold, two lines max) and the company link, 4px apart.
// 3. Location with a pin, then the dates, 6px apart.
// 4. The closed posting, when there is one (D7, ClosedChip above).
// The salary/industry/size/function badges and the ingest indicator are
// kept below those groups; see CompanyDisplay/IngestIndicator above. No
// source badge and no AI-generated badge here (design-system.md "Badge
// usage"): the company name already identifies the posting, and
// provenance badges are a detail-page-only signal, so JobDetail keeps its
// own AI-generated badge untouched.
//
// `compact` is the Ended lane's own card (D7): title, company, and the
// reason the job ended or the link that adds one. An ended job needs
// nothing said about its posting or its enrichment, but it keeps the
// status select, because dragging it back into an open column has to have
// a keyboard route too.
export default function JobCard({
  job,
  statuses,
  statusLabels,
  endedStatuses,
  functionLabels,
  closedDays,
  compact = false,
  canExplain = false,
  onMove,
  onRetry,
  onAddReason,
  dragHandlers,
  isDragging,
}) {
  const draggable = dragHandlers ? 'true' : 'false';

  return (
    <div
      data-testid={`job-card-${job.id}`}
      draggable={draggable}
      style={{ opacity: isDragging ? 0.4 : 1 }}
      {...dragHandlers}
    >
      <Box color="default" borderStyle="sm" rounding={4} padding={compact ? 3 : 4} marginBottom={3}>
        <Flex direction="column" gap={compact ? 2 : 3}>
          <Flex justifyContent="end" alignItems="center" gap={2}>
            <StatusSelect
              id={job.id}
              jobTitle={job.title}
              status={job.status}
              statuses={statuses}
              statusLabels={statusLabels}
              endedStatuses={endedStatuses}
              onChange={(status) => onMove(job.id, status)}
            />
          </Flex>
          <Flex direction="column" gap={1}>
            <Link href={jobHref(job.id)} display="inlineBlock">
              <Heading size="300" lineClamp={2}>
                {job.title}
              </Heading>
            </Link>
            <CompanyDisplay job={job} />
          </Flex>
          {compact ? <EndedReason job={job} canExplain={canExplain} onAddReason={onAddReason} /> : null}
          {compact ? null : (
            <>
              <Flex direction="column" gap={1.5}>
                <Flex gap={1} alignItems="center">
                  <Icon icon="location" accessibilityLabel="" color="subtle" size={14} />
                  <Text size="200" color="subtle">
                    {job.location || 'Location unknown'}, added {job.added}
                  </Text>
                </Flex>
                {job.posted_date ? (
                  <Text size="200" color="subtle">
                    Posted {job.posted_date}
                  </Text>
                ) : null}
              </Flex>
              <Flex gap={2} wrap>
                {job.salary_info ? <Badge type="neutral" text="Salary disclosed" /> : null}
                {job.company_industry ? <Badge type="neutral" text={job.company_industry} /> : null}
                {job.company_size_class ? (
                  <Badge type="neutral" text={SIZE_CLASS_LABELS[job.company_size_class] || job.company_size_class} />
                ) : null}
                {!job.company_industry && !job.company_size_class ? <QuietChip text="Company details pending" /> : null}
                {job.function.map((functionId) => (
                  <Badge key={functionId} type="neutral" text={functionLabels[functionId] || functionId} />
                ))}
              </Flex>
              <IngestIndicator job={job} onRetry={onRetry} />
              <ClosedChip job={job} closedDays={closedDays} />
            </>
          )}
        </Flex>
      </Box>
    </div>
  );
}
