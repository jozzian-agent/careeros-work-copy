import { Box, Button, Flex, Text, TapAreaLink } from 'gestalt';
import { NAV_PAGES } from './nav.js';
import { LOGIN_PATH, logOut } from './api/client.js';

// The shared app header: wordmark plus the four CareerOS nav links, carried
// over from careeros/web/theme.py nav_html()/page_shell() so the React
// Jobs board keeps nav parity with the Jinja-rendered pages.
//
// M1 adds the logout affordance here, in the chrome every page already
// shows, rather than as a settings page or a menu that would exist for
// one action.
export default function Nav({ currentPage }) {
  async function handleLogOut() {
    // Clearing the session is the server's act, so there is nothing to
    // show on a failure: if the POST did not land, the person is still
    // signed in and the login page sends them straight back to the board,
    // which is the truth rather than a hidden error.
    await logOut().catch(() => {});
    window.location.assign(LOGIN_PATH);
  }

  return (
    <Box as="header" padding={4} marginBottom={4} borderStyle="raisedBottomShadow" color="default">
      <Flex gap={6} alignItems="center" wrap>
        <TapAreaLink href="/" target="self" fullWidth={false}>
          <Text weight="bold" size="400">
            CareerOS
          </Text>
        </TapAreaLink>
        <Flex.Item flex="grow">
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
        </Flex.Item>
        <Button size="sm" color="transparent" text="Log out" onClick={handleLogOut} />
      </Flex>
    </Box>
  );
}
