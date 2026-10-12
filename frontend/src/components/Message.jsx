import { Box, BannerSlim } from 'gestalt';

// One component for the board's floating toasts (success/error), per the
// Message README: BannerSlim for the message itself, a bordered + shadowed
// Box around it for the "floating" treatment, since Gestalt's own Toast is
// not used (BannerSlim covers both banners and toasts with the same look).
export default function FloatingMessage({ kind, text, actionLabel, onAction, onDismiss }) {
  return (
    <Box rounding={3} borderStyle="sm" dangerouslySetInlineStyle={{ __style: { boxShadow: 'var(--elevation-floating)' } }}>
      <BannerSlim
        type={kind}
        message={text}
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
