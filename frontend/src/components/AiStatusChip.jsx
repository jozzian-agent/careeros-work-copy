import { Button, Flex, Spinner } from 'gestalt';
import QuietChip from './QuietChip.jsx';
import { aiStatus } from '../aiStatus.js';

// What a card or a detail page says while a record's AI reading is still
// going, or once it failed (CAREER-37).
//
// Component gate: no new visible element. The chip is the board's own
// QuietChip, which design-system.md "Badge usage" (owner decision
// 2026-10-13) already reserves for exactly this -- a machine-state notice
// that must never alarm -- and the Retry beside a failure is the same
// gray Button the ingest indicator already offered. The motion the brief
// asks for while a reading runs is Gestalt's own Spinner rather than a
// keyframe added to QuietChip, because an adopted component is reused and
// never restyled for one surface.
//
// The words are the three the board already used for these states, so no
// second vocabulary exists for the same facts: a reading that has not
// started is enrichment pending, one that is under way is details filling
// in, and one that failed says what went wrong.
const QUEUED_TEXT = 'Enrichment pending';
const RUNNING_TEXT = 'Details filling in…';
const FAILED_TEXT = 'Extraction failed';

export default function AiStatusChip({ job, onRetry }) {
  const status = aiStatus(job);
  // Nothing for a reading that never ran, and nothing for one that
  // finished: success is already carried by the completion the reading
  // wrote (the enriched indicator, the filled sections), so a chip for it
  // would be a second element saying the same thing.
  if (status === 'absent' || status === 'done') {
    return null;
  }
  if (status === 'queued') {
    return <QuietChip text={QUEUED_TEXT} />;
  }
  if (status === 'running') {
    return (
      <Flex gap={2} alignItems="center">
        <QuietChip text={RUNNING_TEXT} />
        <Spinner show size="sm" delay={false} accessibilityLabel="" />
      </Flex>
    );
  }
  // A failure is a visible state with a reason, per the product rules, so
  // the reason is on the surface rather than behind a hover: a tooltip is
  // out of reach on a touch screen and for a keyboard, and the card
  // already shows an ingest failure's reason this way.
  return (
    <Flex gap={2} alignItems="center" wrap>
      <QuietChip text={job.ai_error ? `${FAILED_TEXT}, ${job.ai_error}` : FAILED_TEXT} />
      {onRetry ? <Button size="sm" color="gray" text="Retry" onClick={() => onRetry(job.id)} /> : null}
    </Flex>
  );
}
