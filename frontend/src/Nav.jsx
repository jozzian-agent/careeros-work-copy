import { Box, Button, Flex, Text, TapAreaLink } from 'gestalt';
import { FormattedMessage, useIntl } from 'react-intl';
import { LOGIN_PATH, logOut } from './api/client.js';

// The nav order, the slugs and the tab labels. This list used to be
// src/nav.js, a module that existed to hold the labels; CAREER-116 made the
// labels catalog keys (`shell.nav.*` in src/i18n/en.json), so the list moved
// here, beside the component that renders it, rather than being split across
// two files that both have to be edited to add a tab. Still mirrored by hand
// from careeros/web/theme.py NAV_PAGES; nothing here imports Python, and
// scripts/gen_docs.py reads this literal for docs/as-built/routes.md.
//
// Taxonomy and Notes have no Jinja page at all (React-only, like the
// Search/Experiences/Companies list pages before them), so they are not
// mirrored into theme.py's own NAV_PAGES -- the Jinja /jobs fallback's nav
// bar does not gain a dead link when the React build is unavailable.
//
// M2 (CAREER-39, decision D10): the section is My Jobs, because a board now
// holds the signed-in user's own postings and nobody else's. The slug stays
// "jobs": it is the route and the data attribute, not a word anybody reads.
// B2 (CAREER-89, owner decision 2026-10-19): "All jobs" sits next to My
// Jobs. It is the user word for what the backend calls the universe, which
// never appears in the interface (PROJECT.md, Frame). Its slug is its own
// URL segment rather than something under /jobs, because /jobs/<id> is the
// job detail page.
//
// Every id is a literal, never one built from the slug: that is what lets
// scripts/check_i18n.py see which catalog keys this file reads.
const NAV_PAGES = [
  ['search', <FormattedMessage key="search" id="shell.nav.search" />],
  ['experiences', <FormattedMessage key="experiences" id="shell.nav.experiences" />],
  ['jobs', <FormattedMessage key="jobs" id="shell.nav.jobs" />],
  ['all-jobs', <FormattedMessage key="all-jobs" id="shell.nav.allJobs" />],
  ['companies', <FormattedMessage key="companies" id="shell.nav.companies" />],
  ['notes', <FormattedMessage key="notes" id="shell.nav.notes" />],
  ['taxonomy', <FormattedMessage key="taxonomy" id="shell.nav.taxonomy" />],
];

// The shared app header: wordmark plus the CareerOS nav links, carried over
// from careeros/web/theme.py nav_html()/page_shell() so the React Jobs board
// keeps nav parity with the Jinja-rendered pages.
//
// M1 adds the logout affordance here, in the chrome every page already
// shows, rather than as a settings page or a menu that would exist for
// one action.
export default function Nav({ currentPage }) {
  const { formatMessage } = useIntl();

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
          {/* The wordmark is the product's own name, not a translatable
              string, so it stays out of the catalog. */}
          <Text weight="bold" size="400">
            CareerOS
          </Text>
        </TapAreaLink>
        <Flex.Item flex="grow">
          <nav aria-label={formatMessage({ id: 'shell.nav.ariaLabel' })}>
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
        <Button size="sm" color="transparent" text={formatMessage({ id: 'shell.logOut' })} onClick={handleLogOut} />
      </Flex>
    </Box>
  );
}
