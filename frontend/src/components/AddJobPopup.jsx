import { BannerSlim, Button, Flex, Modal, Spinner, Text, TextField } from 'gestalt';

const NOT_LINK_MESSAGE = "This doesn't look like a link. Check it and try again.";

const PRIMARY_LABEL = {
  ready: 'Add job',
  reading: 'Add job',
  not_link: 'Add job',
  duplicate: 'Show job',
  error: 'Try again',
};

// The popup opened by the board's plus button. JOZ-278 landed the shell
// (heading + Close); this fills in the rest per the AddJobPopup README:
// a link field, Cancel, Add job, and five states (ready, reading, not a
// link, already on your board, couldn't read). Wired to the existing
// POST /api/jobs/intake endpoint - see BUILD_NOTES.md for why the inline
// "Posting URL" field this replaces was removed, and for the one case
// this simplifies (a duplicate that is also eligible for promotion keeps
// using the separate duplicate dialog, since that flow needs more than
// this popup's single primary action).
export default function AddJobPopup({
  url,
  onUrlChange,
  status,
  errorMessage,
  duplicateTitle,
  onSubmit,
  onShowExisting,
  onAddAnyway,
  onDismiss,
}) {
  const reading = status === 'reading';
  const isDuplicate = status === 'duplicate';
  const primaryAction = isDuplicate ? onShowExisting : onSubmit;
  const primaryDisabled = reading || (!isDuplicate && !url.trim());

  return (
    <Modal
      accessibilityModalLabel="Add a job"
      heading="Add a job"
      size={480}
      onDismiss={onDismiss}
      footer={
        <Flex gap={2} justifyContent="end">
          <Button text="Cancel" onClick={onDismiss} />
          {/* "Add anyway" is not one of the README's five named states; it
              is kept here, alongside the "already on your board" info
              message the README does specify, because dropping it would
              silently regress a working capability the backend still
              offers (dedupe.duplicate_payload always includes
              add_anyway) - the same "do not remove working functionality
              with no replacement" reasoning BUILD_NOTES.md records for
              JOZ-278's kept badges and ingest-retry affordance. */}
          {isDuplicate ? <Button text="Add anyway" onClick={onAddAnyway} /> : null}
          <Button color="red" text={PRIMARY_LABEL[status]} disabled={primaryDisabled} onClick={primaryAction} />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        <TextField
          id="add-job-url"
          type="url"
          label="Posting link"
          placeholder="https://company.example/careers/role"
          value={url}
          disabled={reading}
          errorMessage={status === 'not_link' ? NOT_LINK_MESSAGE : undefined}
          onChange={({ value }) => onUrlChange(value)}
        />
        {reading ? (
          <Flex gap={2} alignItems="center">
            <Spinner show size="sm" accessibilityLabel="Reading this posting" />
            <Text>Reading this posting</Text>
          </Flex>
        ) : null}
        {isDuplicate ? <BannerSlim type="info" message={`"${duplicateTitle}" is already on your board.`} /> : null}
        {status === 'error' ? <BannerSlim type="error" message={errorMessage} /> : null}
      </Flex>
    </Modal>
  );
}
