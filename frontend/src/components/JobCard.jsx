import { Badge, Box, Button, Flex, Heading, Icon, Link, Text } from 'gestalt';
import FitChip from './FitChip.jsx';
import QuietChip from './QuietChip.jsx';
import StatusSelect from './StatusSelect.jsx';

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

// The card for one job on the board. Anatomy per the JobCard README:
// 1. Top row: fit chip (or needs-input) on the left, status select on the
//    right.
// 2. Title (bold, two lines max) and the company link, 4px apart.
// 3. Location with a pin, then the dates, 6px apart.
// The salary/industry/size/function badges and ingest indicator are kept
// below those three groups; see CompanyDisplay/IngestIndicator above. No
// source badge and no AI-generated badge here (design-system.md "Badge
// usage"): the company name already identifies the posting, and
// provenance badges are a detail-page-only signal -- JobDetail keeps its
// own AI-generated badge untouched.
export default function JobCard({ job, statuses, functionLabels, onMove, onRetry, dragHandlers, isDragging }) {
  return (
    <div
      data-testid={`job-card-${job.id}`}
      draggable="true"
      style={{ opacity: isDragging ? 0.4 : 1 }}
      {...dragHandlers}
    >
      <Box color="default" borderStyle="sm" rounding={4} padding={4} marginBottom={3}>
        <Flex direction="column" gap={3}>
          <Flex justifyContent="between" alignItems="center" gap={2}>
            <FitChip fit={job.fit} />
            <StatusSelect
              id={job.id}
              jobTitle={job.title}
              status={job.status}
              statuses={statuses}
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
        </Flex>
      </Box>
    </div>
  );
}
