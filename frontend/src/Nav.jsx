import { Box, Flex, Text, TapAreaLink } from 'gestalt';
import { NAV_PAGES } from './nav.js';

// The shared app header: wordmark plus the four CareerOS nav links, carried
// over from careeros/web/theme.py nav_html()/page_shell() so the React
// Jobs board keeps nav parity with the Jinja-rendered pages.
export default function Nav({ currentPage }) {
  return (
    <Box as="header" padding={4} marginBottom={4} borderStyle="raisedBottomShadow" color="default">
      <Flex gap={6} alignItems="center" wrap>
        <TapAreaLink href="/" target="self" fullWidth={false}>
          <Text weight="bold" size="400">
            CareerOS
          </Text>
        </TapAreaLink>
        <nav aria-label="Main">
          <Flex gap={4} wrap>
            {NAV_PAGES.map(([slug, label]) => {
              const isCurrent = slug === currentPage;
              // The Search tab's page lives at "/". Unlike every other
              // tab, its slug does not double as its own URL segment.
              const href = slug === 'search' ? '/' : `/${slug}`;
              return (
                <TapAreaLink
                  key={slug}
                  href={href}
                  target="self"
                  fullWidth={false}
                  accessibilityCurrent={isCurrent ? 'page' : undefined}
                >
                  <Text weight={isCurrent ? 'bold' : 'normal'} underline={isCurrent} color={isCurrent ? 'default' : 'subtle'}>
                    {label}
                  </Text>
                </TapAreaLink>
              );
            })}
          </Flex>
        </nav>
      </Flex>
    </Box>
  );
}
