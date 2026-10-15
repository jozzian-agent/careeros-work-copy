import { useState } from 'react';
import { BannerSlim, Box, Button, Flex, Modal, Popover, RadioGroup, Text, TextArea } from 'gestalt';

// The three popups that end a job (D7). They are one file because they are
// one flow: the chooser asks how it ended, Won asks to be sure, and the
// reason popup is the optional sentence afterwards. Nothing here calls the
// API; the board owns every write, so the same flow serves a drop on the
// lane, a drop on a group and the status select.

// "How did it end?" at the drop point. The anchor is the lane strip the
// card was dropped on, which is as close to the drop point as a Popover
// can be anchored. role=dialog with shouldFocus, so the keyboard lands
// inside it and Escape dismisses, which is what makes dropping reachable
// without a mouse through the status select's own ended options.
export function EndingChooser({ anchor, jobTitle, endedStatuses, statusLabels, onPick, onDismiss }) {
  return (
    <Popover
      anchor={anchor}
      onDismiss={onDismiss}
      role="dialog"
      shouldFocus
      accessibilityLabel={`How did ${jobTitle} end?`}
      idealDirection="left"
      size="flexible"
    >
      <Box padding={4} width={240}>
        <Flex direction="column" gap={3}>
          <Text weight="bold">How did it end?</Text>
          {endedStatuses.map((status) => (
            <Button
              key={status}
              text={statusLabels[status] || status}
              color="gray"
              fullWidth
              onClick={() => onPick(status)}
            />
          ))}
        </Flex>
      </Box>
    </Popover>
  );
}

// Won always asks first, and nothing happens to any other job (D7). The
// second sentence is in the dialog because the owner's worry is exactly
// that: winning one job does not quietly close the others.
export function WonConfirm({ job, statusLabels, onConfirm, onCancel }) {
  const company = job.company_name ? ` at ${job.company_name}` : '';
  return (
    <Modal
      accessibilityModalLabel="Mark as won"
      heading="Mark as won?"
      role="alertdialog"
      size={420}
      onDismiss={onCancel}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onCancel} />
          <Button text="Mark as won" color="red" onClick={onConfirm} />
        </Flex>
      }
    >
      <Text>
        {`${job.title}${company} moves to ${statusLabels.won || 'Won'}. Your other jobs stay as they are.`}
      </Text>
    </Modal>
  );
}

// The reason, always optional. One suggestion or none, plus free text that
// is saved as an ordinary dated note under the title the payload names, so
// a reason never becomes a second notes store. Skip writes nothing at all.
export function ReasonPopup({ job, reasons, noteTitle, statusLabels, busy, error, onSave, onSkip }) {
  const [reason, setReason] = useState(job.end_reason || null);
  const [note, setNote] = useState('');
  const outcome = statusLabels[job.status] || job.status;

  return (
    <Modal
      accessibilityModalLabel="Add a reason"
      heading="Add a reason"
      subHeading={`${job.title} moved to ${outcome}. A reason is optional.`}
      size={480}
      onDismiss={onSkip}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Skip" disabled={busy} onClick={onSkip} />
          <Button
            text="Save"
            color="red"
            disabled={busy || (!reason && !note.trim())}
            onClick={() => onSave({ reason, note: note.trim() })}
          />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        {error ? <BannerSlim type="error" message={error} /> : null}
        <RadioGroup id={`end-reason-${job.id}`} legend="Why did it end?">
          {reasons.map((suggestion) => (
            <RadioGroup.RadioButton
              key={suggestion}
              id={`end-reason-${job.id}-${suggestion.replace(/\W+/g, '-')}`}
              name="end-reason"
              label={suggestion}
              value={suggestion}
              checked={reason === suggestion}
              onChange={() => setReason(suggestion)}
            />
          ))}
        </RadioGroup>
        <TextArea
          id={`end-note-${job.id}`}
          label="Anything else?"
          helperText={`Saved as a note titled "${noteTitle}".`}
          rows={4}
          value={note}
          onChange={({ value }) => setNote(value)}
        />
      </Flex>
    </Modal>
  );
}
