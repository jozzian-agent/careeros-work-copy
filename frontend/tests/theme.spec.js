import { expect, test } from '@playwright/test';
import { loadBoardFixture, mockBoard, mockIntake } from './helpers.js';

const fixture = loadBoardFixture();

// The handoff design tokens, version 3 (JOZ-277). These replace the former
// ad-hoc indigo/violet accent (#5e6ad2 / #7170ff) that src/theme.js used to
// inject. Values come from src/design/tokens.css, which is the repo's single
// source of truth and a verbatim port of the handoff's design-system/tokens.css.
const BRAND_PRIMARY = 'rgb(0, 95, 203)'; // #005fcb, blue-skycicle 600
const BRAND_PRIMARY_DARK = '#75bfff'; // blue-skycicle 300
const TEXT_SUBTLE = '#5f5f5f'; // raised from Gestalt's #767676
const BORDER_FOCUS = '#004ba9'; // solid, replacing Gestalt's 50% blue
const PAGE_LIGHT = 'rgb(247, 251, 255)'; // #f7fbff
const CARD_DARK = '#191919';
const ON_COLOR_DARK = 'rgb(17, 17, 17)'; // #111111, the handoff's dark foreground for brand fills
const ON_COLOR_LIGHT = 'rgb(255, 255, 255)';

// The app itself is pinned to colorScheme="light" (src/App.jsx), so the
// dark-mode tests mount tests/theme-harness.html instead, which drives a real
// ColorSchemeProvider transition through React state. See that file's comment
// for why flipping html[data-theme] by hand would not be a test of this.
const HARNESS = '/tests/theme-harness.html';

async function openBoard(page) {
  await mockBoard(page, fixture);
  await page.goto('/');
  const boardButton = page.getByRole('button', { name: 'Board', exact: true });
  await expect(boardButton).toHaveAttribute('aria-pressed', 'true');
  return boardButton;
}

async function openHarness(page) {
  await page.goto(HARNESS);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toBeVisible();
}

// Which token set DesignTokensProvider is publishing right now. The provider
// writes this itself alongside the tokens, so it is the scheme React is in,
// independent of our own data-theme attribute.
function schemeMarker(page) {
  return page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--gestalt-color-scheme').trim(),
  );
}

// WCAG 2.x relative luminance and contrast ratio, computed from the rgb()
// strings the browser reports, so the assertion is about what is really on
// screen rather than about which token was named.
function relativeLuminance(rgb) {
  const channels = rgb
    .match(/[\d.]+/g)
    .slice(0, 3)
    .map((value) => {
      const srgb = Number(value) / 255;
      return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
    });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(a, b) {
  const [lighter, darker] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}

// The rendered foreground and background of a Button color="red". Gestalt
// classic puts the colour class on the button's inner div, and the label is
// the leaf Text inside it.
function readPrimaryButton(page) {
  return page.evaluate(() => {
    const button = [...document.querySelectorAll('button')].find(
      (el) => el.textContent.trim() === 'Add',
    );
    const label = [...button.querySelectorAll('*')].find(
      (el) => el.children.length === 0 && el.textContent.trim() === 'Add',
    );
    return {
      background: getComputedStyle(button.firstElementChild).backgroundColor,
      color: getComputedStyle(label).color,
    };
  });
}

test('selected toggle and primary button both render the brand blue', async ({ page }) => {
  const boardButton = await openBoard(page);

  // ButtonToggle's selected state reads --color-background-button-selected-default,
  // which Gestalt 177 defaults to near-black rather than to its own red.
  const selectedBackground = await boardButton.evaluate(
    (el) => getComputedStyle(el.firstElementChild).backgroundColor,
  );
  expect(selectedBackground).toBe(BRAND_PRIMARY);

  // The Add button is Button color="red": the brand reaches it through the
  // --color-background-button-primary-* tokens, with no change to its markup.
  // It is disabled until the field has a URL, so fill it first.
  await page.getByLabel('Posting URL').fill('https://example.com/job/1');
  const addBackground = await page
    .getByRole('button', { name: 'Add', exact: true })
    .evaluate((el) => getComputedStyle(el.firstElementChild).backgroundColor);
  expect(addBackground).toBe(BRAND_PRIMARY);
});

test('links use the brand blue and the page uses the cool near-white ground', async ({ page }) => {
  await openBoard(page);

  const linkColor = await page.evaluate(() => {
    const link = document.querySelector('a[href^="/companies/"]');
    return getComputedStyle(link.querySelector('div, span')).color;
  });
  expect(linkColor).toBe(BRAND_PRIMARY);

  const pageBackground = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  );
  expect(pageBackground).toBe(PAGE_LIGHT);
});

test('the deliberate departures from Gestalt are in force', async ({ page }) => {
  await openBoard(page);

  const tokens = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    return {
      subtle: cs.getPropertyValue('--color-text-subtle').trim(),
      focus: cs.getPropertyValue('--color-border-focus').trim(),
    };
  });
  // Gestalt's #767676 fails on gray fills; its focus ring is a 50% blue.
  expect(tokens.subtle).toBe(TEXT_SUBTLE);
  expect(tokens.focus).toBe(BORDER_FOCUS);
});

test('Atkinson Hyperlegible is registered from the bundled woff2 and applied app-wide', async ({
  page,
}) => {
  await openBoard(page);
  await page.evaluate(() => document.fonts.ready);

  const fonts = await page.evaluate(() => {
    const faces = [...document.fonts].filter((f) => f.family === 'Atkinson Hyperlegible');
    return {
      weights: faces.map((f) => f.weight).sort(),
      statuses: faces.map((f) => f.status),
      // Only 400 and 700 exist, so nothing should claim another weight.
      count: faces.length,
      regularUsable: document.fonts.check('400 16px "Atkinson Hyperlegible"'),
      boldUsable: document.fonts.check('700 16px "Atkinson Hyperlegible"'),
      bodyFamily: getComputedStyle(document.body).fontFamily,
      headingFamily: getComputedStyle(document.querySelector('h1')).fontFamily,
      cardTextFamily: getComputedStyle(
        document.querySelector('[data-testid^="job-card-"] div'),
      ).fontFamily,
    };
  });

  expect(fonts.count).toBe(2);
  expect(fonts.weights).toEqual(['400', '700']);
  expect(fonts.statuses).toEqual(['loaded', 'loaded']);
  expect(fonts.regularUsable).toBe(true);
  expect(fonts.boldUsable).toBe(true);
  // Applied to the page, to Gestalt Heading and to Gestalt Text alike: the
  // last two come via the --font-family-default-latin override.
  expect(fonts.bodyFamily).toContain('Atkinson Hyperlegible');
  expect(fonts.headingFamily).toContain('Atkinson Hyperlegible');
  expect(fonts.cardTextFamily).toContain('Atkinson Hyperlegible');
});

test('line heights pair with font size across the whole type scale', async ({ page }) => {
  await openBoard(page);

  // The brief's 44/36/28/24/20, plus text-100's 16. Each line height belongs
  // to a font *size*, not to a heading level: Gestalt's PageHeader renders its
  // title as an h1 at 20px, which is why this is keyed on font-size.
  const scale = await page.evaluate(() => {
    const host = document.createElement('div');
    document.querySelector('#root').appendChild(host);
    const out = {};
    for (const size of [12, 14, 16, 20, 28, 36]) {
      const el = document.createElement('span');
      el.textContent = 'x';
      el.style.fontSize = `${size}px`;
      host.appendChild(el);
      out[size] = getComputedStyle(el).lineHeight;
    }
    host.remove();
    return out;
  });
  expect(scale).toEqual({
    12: '16px', // text-100
    14: '20px', // text-200
    16: '24px', // text-300 / heading-300
    20: '28px', // heading-400
    28: '36px', // heading-600
    36: '44px', // heading-700
  });

  // And the board's own rendered Gestalt components, which must land on the
  // same pairs. PageHeader's title is an h1 at 20px; a column title is
  // Heading size 400, also 20px; card text is Text size 200 at 14px.
  const rendered = await page.evaluate(() => {
    const read = (sel) => {
      const cs = getComputedStyle(document.querySelector(sel));
      return { fontSize: cs.fontSize, lineHeight: cs.lineHeight, fontWeight: cs.fontWeight };
    };
    return { h1: read('h1'), h3: read('h3') };
  });
  // Only 400 and 700 exist in Atkinson Hyperlegible, so headings are bold.
  expect(rendered.h1).toEqual({ fontSize: '20px', lineHeight: '28px', fontWeight: '700' });
  expect(rendered.h3).toEqual({ fontSize: '20px', lineHeight: '28px', fontWeight: '700' });
});

test('portal text gets the line heights too, not just text inside #root', async ({ page }) => {
  await mockIntake(page, [{ body: { id: 'JOB-NEW', duplicate: false } }]);
  await openBoard(page);

  await page.getByLabel('Posting URL').fill('https://example.com/careers/new-role');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByText('Job added')).toBeVisible();

  const toast = await page.evaluate(() => {
    const el = [...document.querySelectorAll('*')].find(
      (node) => node.children.length === 0 && node.textContent.trim() === 'Job added',
    );
    const cs = getComputedStyle(el);
    return {
      insideRoot: document.querySelector('#root').contains(el),
      fontSize: cs.fontSize,
      lineHeight: cs.lineHeight,
    };
  });

  // Gestalt's Layer mounts its children in a div it creates and appends to
  // document.body, so the board's Toast is not inside #root at all: a
  // #root-scoped rule left its text at `normal`.
  expect(toast.insideRoot).toBe(false);
  expect(toast.fontSize).toBe('16px');
  expect(toast.lineHeight).toBe('24px'); // text-300
});

test('the app stays light: ThemeProvider never marks the document dark', async ({ page }) => {
  await openBoard(page);
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'dark');
  expect(await schemeMarker(page)).toBe('lightMode');
});

test('a provider-driven switch to dark swaps in the dark token set', async ({ page }) => {
  await openHarness(page);

  // Mounted light. ThemeProvider syncs data-theme from Gestalt's own context,
  // so both halves have to agree before and after the switch.
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'dark');
  expect(await schemeMarker(page)).toBe('lightMode');

  await page.getByTestId('to-dark').click();

  // The transition is a React re-render of ColorSchemeProvider, which is what
  // makes DesignTokensProvider publish the dark set and ThemeProvider's layout
  // effect set the attribute. Neither is poked by hand here.
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await schemeMarker(page)).toBe('darkMode');

  // DesignTokensProvider is deliberately given no `id`: with one it scopes its
  // tokens to a `__gestaltTheme*` wrapper div and Layer portals fall out of the
  // theme. So there must be no such wrapper, and nothing may be putting a
  // scheme class on html either - data-theme is the one switch.
  expect(await page.locator('[class*="__gestaltTheme"]').count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.className)).toBe('');

  const dark = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const values = {
      page: cs.getPropertyValue('--color-background-page').trim(),
      card: cs.getPropertyValue('--color-background-card').trim(),
      // The Gestalt bridge: Box color="default" must follow the card token,
      // so cards and the nav are #191919 in dark rather than staying white.
      backgroundDefault: cs.getPropertyValue('--color-background-default').trim(),
      brandPrimary: cs.getPropertyValue('--color-brand-primary').trim(),
      brandAccent: cs.getPropertyValue('--color-brand-accent').trim(),
      brandViolet: cs.getPropertyValue('--color-brand-violet').trim(),
      brandOnColor: cs.getPropertyValue('--color-brand-on-color').trim(),
      textDefault: cs.getPropertyValue('--color-text-default').trim(),
      textSubtle: cs.getPropertyValue('--color-text-subtle').trim(),
      borderFocus: cs.getPropertyValue('--color-border-focus').trim(),
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      // Gestalt's own dark set, which only DesignTokensProvider can supply:
      // gestalt/dist/gestalt.css ships five :root blocks and all five are
      // light, where the dark set has inverse as the dark ink.
      gestaltTextInverse: cs.getPropertyValue('--color-text-inverse').trim(),
    };
    return values;
  });

  expect(dark.page).toBe('#111111');
  expect(dark.card).toBe(CARD_DARK);
  expect(dark.backgroundDefault).toBe(CARD_DARK);
  expect(dark.brandPrimary).toBe(BRAND_PRIMARY_DARK);
  expect(dark.brandAccent).toBe('#48d5c6');
  expect(dark.brandViolet).toBe('#b190ff');
  expect(dark.brandOnColor).toBe('#111111');
  expect(dark.textDefault).toBe('#ffffff');
  expect(dark.textSubtle).toBe('#cdcdcd');
  expect(dark.borderFocus).toBe('#abdbff');
  expect(dark.bodyBackground).toBe('rgb(17, 17, 17)');
  expect(dark.gestaltTextInverse).toBe('#111111');

  // And back: the attribute is removed, not just overwritten, so the plain
  // :root light block applies again.
  await page.getByTestId('to-light').click();
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'dark');
  expect(await schemeMarker(page)).toBe('lightMode');
  expect(
    await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
  ).toBe(PAGE_LIGHT);
});

test('the primary button keeps a legible foreground on the brand fill in both schemes', async ({
  page,
}) => {
  // Check the ratio helper against WCAG's reference pair and against what
  // dark mode actually looked like before this was fixed (white on the dark
  // brand blue), so a broken formula cannot pass the real assertions below.
  expect(contrastRatio('rgb(255, 255, 255)', 'rgb(0, 0, 0)')).toBeCloseTo(21, 1);
  expect(contrastRatio('rgb(255, 255, 255)', 'rgb(117, 191, 255)')).toBeCloseTo(1.97, 1);

  await openHarness(page);

  // Gestalt picks a Button's label colour in JS, from useColorScheme(): red
  // maps to Text color="inverse", except in dark mode, where it switches to
  // "default" on purpose for contrast against its own dark-mode red. With the
  // fill rebound to the brand blue that exception inverts the problem, because
  // dark --color-text-default is #ffffff: the fix in design/theme.css binds
  // both tokens to the handoff's color-brand-on-color inside the fill.
  const light = await readPrimaryButton(page);
  expect(light.background).toBe(BRAND_PRIMARY);
  expect(light.color).toBe(ON_COLOR_LIGHT);
  expect(contrastRatio(light.color, light.background)).toBeGreaterThanOrEqual(4.5);

  await page.getByTestId('to-dark').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  const dark = await readPrimaryButton(page);
  expect(dark.background).toBe('rgb(117, 191, 255)'); // #75bfff
  expect(dark.color).toBe(ON_COLOR_DARK);
  // Without the binding this is white on #75bfff: 1.97:1.
  expect(contrastRatio(dark.color, dark.background)).toBeGreaterThanOrEqual(4.5);
});

test('the token override still beats the provider stylesheet injected below it', async ({
  page,
}) => {
  await openBoard(page);

  // The cascade trap carried over from Gestalt 160, with a new source: in 177
  // it is DesignTokensProvider, not ColorSchemeProvider, that renders a
  // `:root { ... }` style tag inside #root. That tag is later in document
  // order than the stylesheets in <head>, so without !important Gestalt's
  // stock values would win on every render. Assert both halves: the provider
  // tag really is there and really is later, and our value still wins.
  const cascade = await page.evaluate(() => {
    const tags = [...document.querySelectorAll('style')];
    const providerIndex = tags.findIndex((t) =>
      (t.textContent || '').includes('--gestalt-color-scheme'),
    );
    const tokensIndex = tags.findIndex((t) => (t.textContent || '').includes('--color-brand-primary'));
    return {
      providerIndex,
      tokensIndex,
      providerDeclaresBrandRed: (tags[providerIndex]?.textContent || '').includes(
        '--color-background-primary-base',
      ),
      resolvedPrimary: getComputedStyle(document.documentElement)
        .getPropertyValue('--color-background-primary-base')
        .trim(),
    };
  });

  expect(cascade.providerIndex).toBeGreaterThan(-1);
  expect(cascade.tokensIndex).toBeGreaterThan(-1);
  expect(cascade.providerIndex).toBeGreaterThan(cascade.tokensIndex);
  expect(cascade.providerDeclaresBrandRed).toBe(true);
  // Resolves through the bridge to --color-brand-primary, not Gestalt's red.
  expect(cascade.resolvedPrimary).toBe('#005fcb');
});
