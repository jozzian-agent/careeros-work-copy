import { BannerSlim, Flex, ModalAlert, Text } from 'gestalt';

const COPY = {
  job: { heading: 'Delete this job?', keep: 'Keep job', confirm: 'Delete job' },
  experience: { heading: 'Delete this position?', keep: 'Keep position', confirm: 'Delete position' },
  company: { heading: 'Delete this company?', keep: 'Keep company', confirm: 'Delete company' },
};

// The one delete-confirmation template for every detail page (BRIEF.md
// line ~27: Delete always opens a ModalAlert), per the approved JOZ-280
// Phase A wireframe. The company variant is the only one that can come
// back with a 409 ("still linked" guard, careeros/server.py company_api);
// that renders as a BannerSlim inside the same alert instead of closing
// it, so the owner sees why the delete did not happen (the brief's
// "failures are visible states" rule).
export default function DeleteConfirmModal({ kind, name, busy, error, onConfirm, onDismiss }) {
  const copy = COPY[kind];
  return (
    <ModalAlert
      accessibilityModalLabel={copy.heading}
      heading={copy.heading}
      onDismiss={onDismiss}
      primaryAction={{
        accessibilityLabel: copy.confirm,
        label: copy.confirm,
        onClick: onConfirm,
        disabled: busy,
      }}
      secondaryAction={{
        accessibilityLabel: copy.keep,
        label: copy.keep,
        onClick: onDismiss,
      }}
    >
      <Flex direction="column" gap={3}>
        <Text>
          This removes {name} from your{' '}
          {kind === 'job' ? 'jobs' : kind === 'experience' ? 'experience library' : 'companies'}.
        </Text>
        {error ? <BannerSlim type="error" message={error} /> : null}
      </Flex>
    </ModalAlert>
  );
}
