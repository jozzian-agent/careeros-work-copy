import { Flex, Heading, Icon, Link, Text } from 'gestalt';

// The shared frame every list page sits in: Jobs, Companies, Experiences,
// Notes, Taxonomy and Search.
//
// It exists because the title used to be Gestalt's PageHeader, which
// draws a white band with its own horizontal padding, so the title sat in
// a box and further in from the left than the content under it. The brief
// (2026-10-18, section 3) retires the band: the title is an H1 on the
// page ground, and the title, the toolbar and the content share one left
// edge. Making that edge a property of this one component is what keeps
// them sharing it -- a page cannot set its own padding and drift.
//
// Measurements from the approved "Jobs board" artboard: the header stack
// is 24px top, 32px sides, 16px bottom with 16px between its rows; the
// content is 32px sides and 32px bottom with no top padding of its own,
// because the header stack's bottom padding is the gap between them.
//
// `header` is the rows under the title (the main action, the view pair,
// the filter bar, a banner). A page with no main action simply passes its
// filters, or nothing at all.
//
// `backLink` is `{href, label}` for a page that is reached from one other
// page and goes back to it -- the Add position form, per its own artboard.
// It renders above the title, inside the same header stack, so it shares
// the one left edge like every other row. The same back link the detail
// pages draw in `DetailHeader`, which no list page has, and which is why
// it is an optional row here rather than a second header component.
const HEADER_STYLE = {
  display: 'flex',
  flexDirection: 'column',
  gap: '16px',
  padding: '24px 32px 16px',
};

const BODY_STYLE = { padding: '0 32px 32px' };

export default function PageLayout({ title, header, backLink, children }) {
  return (
    <>
      <div data-testid="page-header" style={HEADER_STYLE}>
        {backLink ? (
          <Link
            href={backLink.href}
            display="inlineBlock"
            accessibilityLabel={`Back to ${backLink.label}`}
          >
            <Flex gap={1} alignItems="center">
              <Icon icon="arrow-back" accessibilityLabel="" color="brandPrimary" size={12} />
              <Text color="link" weight="bold">
                {backLink.label}
              </Text>
            </Flex>
          </Link>
        ) : null}
        {/* accessibilityLevel is explicit: Gestalt maps size 600 to an h2
            by default, and this is the page's one top-level heading. */}
        <Heading accessibilityLevel={1} size="600">
          {title}
        </Heading>
        {header}
      </div>
      <main style={BODY_STYLE}>{children}</main>
    </>
  );
}
