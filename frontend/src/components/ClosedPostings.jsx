import { BannerSlim, Box, Button, Flex, Modal, Text } from 'gestalt';
import { countWord } from '../counts.js';

// The closed-postings banner and its review popup (D7).
//
// Both read the payload's own closed_review list, which is also what gives
// a card its warning chip, so the banner and the chips can never disagree
// and no threshold is recomputed in the browser.

function dayCount(days) {
  return `closed ${countWord(days, 'day')} ago`;
}

// Shown while at least one job the owner has not applied to has had a
// closed posting for over a week and has not been kept. "Not now" hides it
// until another job crosses the threshold, which is why the board
// remembers which ids were dismissed rather than a single hidden flag.
export function ClosedPostingsBanner({ count, short, onReview, onNotNow }) {
  const sentence = short
    ? `${countWord(count, 'closed posting')} to review`
    : `${countWord(count, 'job')} you have not applied to ${count === 1 ? 'has' : 'have'} had a closed posting for over a week.`;

  return (
    <Box marginBottom={4} data-testid="closed-postings-banner">
      <BannerSlim
        type="info"
        iconAccessibilityLabel="Information"
        message={
          <Flex gap={3} alignItems="center" wrap>
            <Text inline>{sentence}</Text>
            <Button size="sm" color="transparent" text="Not now" onClick={onNotNow} />
          </Flex>
        }
        primaryAction={{ label: 'Review', accessibilityLabel: 'Review closed postings', onClick: onReview, role: 'button' }}
      />
    </Box>
  );
}

// One row per job the banner asks about: the posting is gone, and the
// owner either keeps the job anyway or stops pursuing it. Keep only quiets
// the warning (it sets closed_reviewed_at); it never clears the flag,
// because the posting is still gone.
export function ClosedPostingsReview({ rows, busyId, onKeep, onStop, onDone }) {
  return (
    <Modal
      accessibilityModalLabel="Closed postings"
      heading="Closed postings"
      subHeading="These postings are gone. Keep the job anyway, or stop pursuing it."
      size={560}
      onDismiss={onDone}
      footer={
        <Flex justifyContent="end">
          <Button text="Done" color="red" onClick={onDone} />
        </Flex>
      }
    >
      <Flex direction="column" gap={4}>
        {rows.length === 0 ? (
          <Text color="subtle">Nothing left to review.</Text>
        ) : (
          rows.map(({ job, days }) => (
            <Flex
              key={job.id}
              data-testid={`closed-review-row-${job.id}`}
              alignItems="center"
              gap={3}
              wrap
            >
              <Flex direction="column" gap={1} flex="grow">
                <Text weight="bold">{job.title}</Text>
                <Text size="200" color="subtle">
                  {`${job.company_name || 'Company pending'}, ${dayCount(days)}`}
                </Text>
              </Flex>
              <Flex gap={2}>
                <Button
                  size="sm"
                  text="Keep"
                  disabled={busyId === job.id}
                  accessibilityLabel={`Keep ${job.title}`}
                  onClick={() => onKeep(job)}
                />
                <Button
                  size="sm"
                  color="gray"
                  text="Stop"
                  disabled={busyId === job.id}
                  accessibilityLabel={`Stop ${job.title}`}
                  onClick={() => onStop(job)}
                />
              </Flex>
            </Flex>
          ))
        )}
      </Flex>
    </Modal>
  );
}
