import { Button, Flex, Modal } from 'gestalt';

// The popup opened by the board's plus button. This ticket (JOZ-278) lands
// the shell only, per the component README's states (ready, reading, not a
// link, duplicate, couldn't read) being out of scope here: a title and a
// close affordance, no instructional copy or intake field yet (JOZ-279).
// Gestalt's plain Modal renders no dismiss button of its own (only
// ModalAlert does), so the footer Close button is the visible close
// affordance the ticket asks for; Escape and an outside click also call
// onDismiss via Modal's own behavior. The field, Cancel and Add job button
// land in a later batch; the existing posting-URL field below the board
// stays the working intake path until then.
export default function AddJobPopupShell({ onDismiss }) {
  return (
    <Modal
      accessibilityModalLabel="Add a job"
      heading="Add a job"
      size="sm"
      onDismiss={onDismiss}
      footer={
        <Flex justifyContent="end">
          <Button text="Close" onClick={onDismiss} />
        </Flex>
      }
    />
  );
}
