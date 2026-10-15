import { BannerSlim, Box, Button, Flex, Text } from 'gestalt';

// One component for the board's floating toasts (success/error), per the
// Message README: BannerSlim for the message itself, a bordered + shadowed
// Box around it for the "floating" treatment, since Gestalt's own Toast is
// not used (BannerSlim covers both banners and toasts with the same look).
//
// D7 adds the two-action row the brief draws, "Moved to Stopped [Add a
// reason] [Undo]". BannerSlim takes exactly one primaryAction, so the
// second action rides inside the message element (which BannerSlim accepts
// as a node) rather than a second banner component existing for one row.
export default function FloatingMessage({
  kind,
  text,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondaryAction,
  onDismiss,
}) {
  const message = secondaryLabel ? (
    <Flex gap={3} alignItems="center" wrap>
      <Text inline>{text}</Text>
      <Button size="sm" color="transparent" text={secondaryLabel} onClick={onSecondaryAction} />
    </Flex>
  ) : (
    text
  );

  return (
    <Box rounding={3} borderStyle="sm" dangerouslySetInlineStyle={{ __style: { boxShadow: 'var(--elevation-floating)' } }}>
      <BannerSlim
        type={kind}
        message={message}
        onDismiss={onDismiss}
        primaryAction={
          actionLabel
            ? { label: actionLabel, accessibilityLabel: actionLabel, onClick: onAction, role: 'button' }
            : undefined
        }
      />
    </Box>
  );
}
