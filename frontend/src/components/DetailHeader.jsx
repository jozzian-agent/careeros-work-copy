import { Box, Button, Flex, Heading, Icon, Link, Text } from 'gestalt';

// The shared skeleton header for every detail page (Job, Experience,
// Company), per the DetailHeader README: back link, a small-caps type
// label (with the page's one chip inline), title, subtitle, a line of
// location/dates/`meta`, then Edit and Delete on the right.
//
// 2026-10-14 canvas: Delete is a gray secondary button, the same weight as
// Edit. It used to be color="red", which this theme binds to the brand
// fill (see design/theme.css), so the most destructive action on the page
// rendered as its primary one.
export default function DetailHeader({
  type,
  backHref,
  backLabel,
  chip,
  title,
  subtitle,
  location,
  dates,
  meta,
  editLabel,
  onEdit,
  onDelete,
  showActions = true,
}) {
  return (
    <Flex direction="column" gap={3}>
      <Link href={backHref} display="inlineBlock" accessibilityLabel={`Back to ${backLabel}`}>
        <Flex gap={1} alignItems="center">
          <Icon icon="arrow-back" accessibilityLabel="" color="brandPrimary" size={12} />
          <Text color="link" weight="bold">
            {backLabel}
          </Text>
        </Flex>
      </Link>
      <Flex gap={3} alignItems="start" justifyContent="between" wrap>
        <Flex direction="column" gap={1}>
          <Flex gap={2} alignItems="center">
            <Box
              dangerouslySetInlineStyle={{
                __style: { textTransform: 'uppercase', letterSpacing: '0.06em' },
              }}
            >
              <Text size="100" weight="bold" color="subtle">
                {type}
              </Text>
            </Box>
            {chip}
          </Flex>
          <Heading size="600">{title}</Heading>
          {subtitle ? <Text color="subtle">{subtitle}</Text> : null}
          {location || dates || meta ? (
            <Flex gap={2} alignItems="center" wrap>
              {location ? (
                <Flex gap={1} alignItems="center">
                  <Icon icon="location" accessibilityLabel="" color="subtle" size={12} />
                  <Text color="subtle">{location}</Text>
                </Flex>
              ) : null}
              {dates ? <Text color="subtle">{dates}</Text> : null}
              {meta}
            </Flex>
          ) : null}
        </Flex>
        {showActions ? (
          <Flex gap={2}>
            <Button text={editLabel || 'Edit'} color="gray" onClick={onEdit} iconEnd="edit" />
            <Button text="Delete" color="gray" onClick={onDelete} iconEnd="trash-can" />
          </Flex>
        ) : null}
      </Flex>
    </Flex>
  );
}
