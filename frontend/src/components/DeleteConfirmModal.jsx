import { BannerSlim, Flex, ModalAlert, Text } from 'gestalt';

// `from` names the place the record is removed from, so a fourth kind is
// one row here instead of another arm on a nested ternary below.
const COPY = {
  job: { heading: 'Delete this job?', keep: 'Keep job', confirm: 'Delete job', from: 'jobs' },
  experience: {
    heading: 'Delete this position?', keep: 'Keep position', confirm: 'Delete position',
    from: 'experience library',
  },
  company: {
    heading: 'Delete this company?', keep: 'Keep company', confirm: 'Delete company',
    from: 'companies',
  },
  note: { heading: 'Delete this note?', keep: 'Keep note', confirm: 'Delete note', from: 'notes' },
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
          This removes {name} from your {copy.from}.
        </Text>
        {error ? <BannerSlim type="error" message={error} /> : null}
      </Flex>
    </ModalAlert>
  );
}
