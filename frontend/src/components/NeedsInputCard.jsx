import { useState } from 'react';
import { Button, Flex, RadioGroup, Text, TextField } from 'gestalt';
import SectionCard from './SectionCard.jsx';

// The Job detail page's one ask, rendered in the violet needs-input
// SectionCard. Which ask it is comes from the backend's `needs_input`
// (careeros/web/pages/jobs.py job_needs_input), never from this component:
// precedence between an unresolved company and a posting that never
// arrived is a product decision, decided in one place.
//
// The header's "Needs your input" chip links to ANCHOR, so the chip and
// the card are always the same ask.
export const NEEDS_INPUT_ANCHOR = 'needs-your-input';
export const NEEDS_INPUT_TITLE = 'Needs your input';

// Owner-facing words for the stored failure reasons that are product
// decisions rather than exception class names. Anything else falls back to
// the stage: an unreachable page and an unreadable one are different
// facts, and neither is ever reported as a raw reason code.
const READ_FAILURE_REASONS = {
  empty_content: 'The page loaded, but it held no posting text.',
  source_url_changed: 'The posting link changed, so the text that was read no longer belongs to it.',
  worker_start_failed: 'Reading the posting could not be started.',
  refresh_worker_start_failed: 'Reading the posting could not be started.',
};

function readFailureText(reason, stage) {
  return READ_FAILURE_REASONS[reason]
    || (stage === 'fetch' ? 'The posting page could not be reached.' : 'The posting text could not be read.');
}

export default function NeedsInputCard({
  needsInput, employerName, errorStage, busy, onLink, onCreate, onPaste, onRetry,
}) {
  const candidates = needsInput.kind === 'company' ? needsInput.review?.candidates || [] : [];
  const [picked, setPicked] = useState(candidates[0]?.company_id || '');
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState(employerName || '');

  if (needsInput.kind === 'read_failed') {
    return (
      <SectionCard
        title={NEEDS_INPUT_TITLE}
        variant="needs-input"
        anchorId={NEEDS_INPUT_ANCHOR}
        actions={[
          <Button key="paste" text="Paste the posting text" color="red" onClick={onPaste} />,
          <Button key="retry" text="Try again" color="gray" disabled={busy} onClick={onRetry} />,
        ]}
      >
        <Flex direction="column" gap={2}>
          <Text>Nothing could be read from this posting yet.</Text>
          <Text color="subtle">{readFailureText(needsInput.error_reason, errorStage)}</Text>
        </Flex>
      </SectionCard>
    );
  }

  // The company ask. A needs_review job with no candidates at all is still
  // a job whose company is unresolved, so the card stays and offers the
  // one thing left to do: name the company.
  const createRow = creating || !candidates.length;
  return (
    <SectionCard
      title={NEEDS_INPUT_TITLE}
      variant="needs-input"
      anchorId={NEEDS_INPUT_ANCHOR}
      actions={createRow
        ? [
          <Button
            key="create"
            text="Create and link"
            color="red"
            disabled={busy || !newName.trim()}
            onClick={() => onCreate(newName.trim())}
          />,
          candidates.length
            ? <Button key="back" text="Back to the matches" color="gray" onClick={() => setCreating(false)} />
            : null,
        ].filter(Boolean)
        : [
          <Button
            key="link"
            text="Link to this company"
            color="red"
            disabled={busy || !picked}
            onClick={() => onLink(picked)}
          />,
          <Button
            key="none"
            text="None of these, create new"
            color="gray"
            disabled={busy}
            onClick={() => setCreating(true)}
          />,
        ]}
    >
      <Flex direction="column" gap={3}>
        <Text>
          {employerName
            ? `This posting names ${employerName}. Which of your companies is that?`
            : 'This job is not linked to one of your companies yet.'}
        </Text>
        {candidates.length && !creating ? (
          <RadioGroup id="company-review-candidates" legend="Pick the company this job is at" direction="column">
            {candidates.map((candidate) => (
              <RadioGroup.RadioButton
                key={candidate.company_id}
                id={`company-candidate-${candidate.company_id}`}
                name="company-candidate"
                label={candidate.name || candidate.company_id}
                helperText={candidate.basis && candidate.basis !== candidate.name
                  ? `Known here as ${candidate.basis}`
                  : undefined}
                value={candidate.company_id}
                checked={picked === candidate.company_id}
                onChange={() => setPicked(candidate.company_id)}
              />
            ))}
          </RadioGroup>
        ) : null}
        {createRow ? (
          <TextField
            id="company-review-new-name"
            label="Company name"
            value={newName}
            onChange={({ value }) => setNewName(value)}
          />
        ) : null}
      </Flex>
    </SectionCard>
  );
}
