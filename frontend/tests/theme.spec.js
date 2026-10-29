import { expect, test } from '@playwright/test';
import {
  loadBoardFixture,
  loadFixture,
  mockBoard,
  mockCompanyPage,
  mockExperiencesPage,
  mockIntake,
  mockJobPage,
  mockJobTaxonomy,
} from './helpers.js';

const fixture = loadBoardFixture();

// The design tokens as of the 2026-10-26 handover: Matchacado green brand on a
// light green ground, light theme only. Values come from
// src/design/tokens.css, the repo's single source of truth.
const BRAND_PRIMARY = 'rgb(0, 135, 83)'; // #008753, matchacado 500
const BRAND_PRIMARY_STRONG = '#005f3e'; // brand-hover
const BRAND_WASH = 'rgb(227, 250, 225)'; // #e3fae1, the selected-toggle ground
const SECONDARY_BASE = 'rgb(232, 231, 225)'; // #e8e7e1, the neutral chip ground
const BRAND_PRIMARY_DARK = '#75bfff'; // dark tokens are untouched by this PR
const TEXT_SUBTLE = '#636361'; // raised from Gestalt's #767676
const TEXT_NEUTRAL = '#4c4c4a';
const BORDER_FOCUS = '#007db8'; // solid focus ring
const PAGE_LIGHT = 'rgb(246, 253, 245)'; // #f6fdf5
const CARD_DARK = '#191919';
const ON_COLOR_DARK = 'rgb(17, 17, 17)'; // #111111, dark foreground for brand fills
const ON_COLOR_LIGHT = 'rgb(255, 255, 255)';
const SURFACE = 'rgb(255, 255, 255)'; // #ffffff, --color-background-card
const INK = 'rgb(0, 0, 0)'; // #000000, --color-text-default
const DANGER = 'rgb(204, 0, 0)'; // #cc0000, --color-text-error
const DANGER_HOVER = '#a30000'; // --color-background-danger-hover

// Gestalt 177.0.12's own light info palette (skycicle), which is what the
// theme has to displace. Named here so the "no blue anywhere" assertions
// read as what they are rather than as three unexplained triples.
const GESTALT_INFO_BASE = 'rgb(0, 116, 232)'; // #0074e8
const GESTALT_INFO_WEAK = 'rgb(215, 237, 255)'; // #d7edff
const GESTALT_INFO_STRONG = 'rgb(0, 95, 203)'; // #005fcb

const jobFixture = loadFixture('job-detail');
const taxonomyFixture = loadFixture('job-taxonomy');
const companyFixture = loadFixture('company-detail');
const experiencesFixture = loadFixture('experiences-list');

// The app itself is pinned to colorScheme="light" (src/App.jsx), so the
// dark-mode tests mount tests/theme-harness.html instead, which drives a real
// ColorSchemeProvider transition through React state. See that file's comment
// for why flipping html[data-theme] by hand would not be a test of this.
const HARNESS = '/tests/theme-harness.html';

async function openBoard(page) {
  await mockBoard(page, fixture);
  await page.goto('/jobs');
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

// Brief 2026-10-18, section 1 (values per the 2026-10-26 handover): a
// selected toggle is a STATE, so it gets the wash ground and the brand border
// the Function filter always had, never the brand FILL. The fill belongs to
// the one main action on the screen, and "Add a job" is it.
test('a selected toggle is brand wash with a brand border, and only the main action is filled', async ({
  page,
}) => {
  const boardButton = await openBoard(page);

  const selected = await boardButton.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { background: cs.backgroundColor, border: cs.borderTopColor, width: cs.borderTopWidth };
  });
  expect(selected.background).toBe(BRAND_WASH);
  expect(selected.border).toBe(BRAND_PRIMARY);
  expect(selected.width).toBe('2px');

  // The unselected half of the pair keeps the neutral chip ground, and
  // its border is transparent so selecting one never reflows the row.
  const unselected = await page
    .getByRole('button', { name: 'List', exact: true })
    .evaluate((el) => {
      const cs = getComputedStyle(el);
      return { background: cs.backgroundColor, border: cs.borderTopColor, width: cs.borderTopWidth };
    });
  expect(unselected.background).toBe(SECONDARY_BASE);
  expect(unselected.border).toBe('rgba(0, 0, 0, 0)');
  expect(unselected.width).toBe('2px');

  // Nothing a person can act on above the board carries the brand fill
  // except "Add a job". A chip's count pill is left out on purpose: it is
  // aria-hidden decoration on the chip it sits in (FilterChip keeps each
  // chip's accessible name to its label), not an action and not a state.
  const filled = await page.evaluate((brand) => {
    const header = document.querySelector('[data-testid="page-header"]');
    return [...header.querySelectorAll('*')]
      .filter((el) => !el.closest('[aria-hidden="true"]'))
      .filter((el) => getComputedStyle(el).backgroundColor === brand)
      .map((el) => el.closest('button')?.textContent.trim() ?? el.textContent.trim());
  }, BRAND_PRIMARY);
  expect([...new Set(filled)]).toEqual(['Add a job']);

  // The Add job button is Button color="red": the brand reaches it through
  // the --color-background-button-primary-* tokens, with no change to its
  // markup. It is disabled until the field has a URL, so fill it first.
  await page.getByRole('button', { name: 'Add a job', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Add a job' });
  await dialog.getByLabel('Posting link').fill('https://example.com/job/1');
  const addBackground = await dialog
    .getByRole('button', { name: 'Add job', exact: true })
    .evaluate((el) => getComputedStyle(el.firstElementChild).backgroundColor);
  expect(addBackground).toBe(BRAND_PRIMARY);
});

test('links are ink-black and always underlined, and the page ground is the light green', async ({
  page,
}) => {
  await openBoard(page);

  // 2026-10-26 handover: --color-text-link is #000000 and links are always
  // underlined (the underline is what carries "this is a link", not colour).
  const link = await page.evaluate(() => {
    const el = document.querySelector('a[href^="/companies/"]');
    // Read the decoration off the anchor: text-decoration propagates to
    // descendants visually, but a child's computed value is its own (`none`),
    // so the assertion has to be on the element that carries the rule.
    const a = getComputedStyle(el);
    const cs = getComputedStyle(el.querySelector('div, span'));
    return { color: cs.color, decoration: a.textDecorationLine };
  });
  expect(link.color).toBe('rgb(0, 0, 0)');
  expect(link.decoration).toBe('underline');

  const pageBackground = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  );
  expect(pageBackground).toBe(PAGE_LIGHT);
});

// 2026-10-29 brief, B1: "chips and buttons excluded". A Gestalt ButtonLink
// is an <a> wearing a button's chrome, so the anchor-wide rule above drew an
// underline through the label of a filled pill. design/theme.css excludes
// Gestalt's own button class; this is the pair of assertions that keeps the
// exclusion exact - the button loses the underline and an ordinary link on
// the same page keeps it.
test('a ButtonLink is not underlined, and the links beside it still are', async ({ page }) => {
  await mockExperiencesPage(page, experiencesFixture);
  await page.goto('/experiences');

  const addPosition = page.getByRole('link', { name: 'Add position' });
  await expect(addPosition).toBeVisible();
  await expect(addPosition).toHaveCSS('text-decoration-line', 'none');

  // The row links on the same page, which are ordinary Gestalt Links.
  const decorations = await page.evaluate(() =>
    [...document.querySelectorAll('a[href^="/experiences/"]')]
      .filter((a) => a.getAttribute('href') !== '/experiences/new')
      .map((a) => getComputedStyle(a).textDecorationLine),
  );
  expect(decorations.length).toBeGreaterThan(0);
  expect([...new Set(decorations)]).toEqual(['underline']);
});

// 2026-10-29 brief, A1: the informational colour is the brand, and that has
// to hold for *every* info token Gestalt reads, not only the three base
// ones. Gestalt aliases box-info-* and badge-info-* to the base names in its
// own stylesheet, but DesignTokensProvider republishes every token as a
// resolved literal on :root, so the alias is not what is in force at
// runtime: the banner below rendered Gestalt's skycicle blue until all
// eight names were bound in design/theme.css.
test('the info banner renders in brand wash, and no info token resolves to blue', async ({
  page,
}) => {
  await openBoard(page);

  // The closed-postings banner is the check the brief names: a BannerSlim
  // type="info", whose ground is --color-background-box-info-weak.
  const banner = page.getByTestId('closed-postings-banner');
  await expect(banner).toBeVisible();

  const rendered = await banner.evaluate((el) => {
    // BannerSlim paints the ground on its own outermost Box, which is the
    // first descendant carrying a background at all.
    const ground = [...el.querySelectorAll('*')].find(
      (node) => getComputedStyle(node).backgroundColor !== 'rgba(0, 0, 0, 0)',
    );
    // The banner's own sentence: the longest leaf in it, so the assertion
    // does not depend on where BannerSlim puts its action buttons.
    const text = [...el.querySelectorAll('*')]
      .filter((node) => node.children.length === 0)
      .sort((a, b) => b.textContent.trim().length - a.textContent.trim().length)[0];
    return {
      ground: getComputedStyle(ground).backgroundColor,
      icon: getComputedStyle(el.querySelector('svg')).fill,
      text: getComputedStyle(text).color,
    };
  });
  expect(rendered.ground).toBe(BRAND_WASH);
  expect(rendered.icon).toBe(BRAND_PRIMARY);
  // The banner's own message on its own ground, measured rather than
  // assumed: the info wash has to carry body text at WCAG AA.
  expect(contrastRatio(rendered.text, rendered.ground)).toBeGreaterThanOrEqual(4.5);

  // All eight names Gestalt can reach for an "info" colour, resolved from
  // the live document. The five aliased ones are the point of the test.
  const tokens = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const names = [
      'background-info-base',
      'background-info-strong',
      'background-info-weak',
      'background-box-info-base',
      'background-box-info-weak',
      'background-badge-info-default',
      'background-badge-info-hover',
      'icon-info',
    ];
    return Object.fromEntries(
      names.map((name) => [name, cs.getPropertyValue(`--color-${name}`).trim()]),
    );
  });
  expect(tokens).toEqual({
    'background-info-base': '#008753',
    'background-info-strong': '#005f3e',
    'background-info-weak': '#e3fae1',
    'background-box-info-base': '#008753',
    'background-box-info-weak': '#e3fae1',
    'background-badge-info-default': '#008753',
    'background-badge-info-hover': '#005f3e',
    'icon-info': '#008753',
  });

  // And nothing on the page is painted in Gestalt's info blue.
  const blues = await page.evaluate((palette) => {
    const hit = (el) => {
      const cs = getComputedStyle(el);
      return palette.includes(cs.backgroundColor) || palette.includes(cs.fill);
    };
    return [...document.querySelectorAll('*')]
      .filter(hit)
      .map((el) => el.textContent.trim().slice(0, 40));
  }, [GESTALT_INFO_BASE, GESTALT_INFO_WEAK, GESTALT_INFO_STRONG]);
  expect(blues).toEqual([]);
});

// 2026-10-29 brief, A2. The primary-button tokens are the brand, so every
// Button color="red" is green - and the one button that really does destroy
// a record must not be. design/theme.css redeclares the three fill tokens on
// the alert dialog itself, which is the only place Gestalt builds a
// destructive confirmation.
test('the primary button is brand green and the destructive confirm is the only red fill', async ({
  page,
}) => {
  await mockJobPage(page, jobFixture);
  await mockJobTaxonomy(page, taxonomyFixture);
  await mockCompanyPage(page, companyFixture);
  await page.goto('/jobs/JOB-001');
  await expect(page.getByRole('heading', { name: jobFixture.job.title })).toBeVisible();

  // Outside the dialog the brand still owns the primary fill: Edit job is
  // the page's own Button, and the tokens resolve to the brand pair.
  const outside = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    return {
      fill: cs.getPropertyValue('--color-background-button-primary-default').trim(),
      hover: cs.getPropertyValue('--color-background-button-primary-hover').trim(),
    };
  });
  expect(outside.fill).toBe('#008753');
  expect(outside.hover).toBe(BRAND_PRIMARY_STRONG);

  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();

  const confirm = await dialog.evaluate((el) => {
    const read = (label) => {
      const button = [...el.querySelectorAll('button')].find(
        (node) => node.textContent.trim() === label,
      );
      const leaf = [...button.querySelectorAll('*')].find(
        (node) => node.children.length === 0 && node.textContent.trim() === label,
      );
      return {
        background: getComputedStyle(button.firstElementChild).backgroundColor,
        color: getComputedStyle(leaf).color,
      };
    };
    const cs = getComputedStyle(el);
    return {
      destructive: read('Delete job'),
      keep: read('Keep job'),
      hover: cs.getPropertyValue('--color-background-button-primary-hover').trim(),
      active: cs.getPropertyValue('--color-background-button-primary-active').trim(),
    };
  });

  // The handover's three values: the error red for the fill, the danger
  // hover under the pointer, and the surface for the label on it.
  expect(confirm.destructive.background).toBe(DANGER);
  expect(confirm.destructive.color).toBe(SURFACE);
  expect(confirm.hover).toBe(DANGER_HOVER);
  expect(confirm.active).toBe(DANGER_HOVER);
  expect(contrastRatio(confirm.destructive.color, confirm.destructive.background)).toBeGreaterThanOrEqual(4.5);

  // The red is the confirm's alone: "Keep job" is the gray secondary, and
  // it is not the brand fill either.
  expect(confirm.keep.background).not.toBe(DANGER);
  expect(confirm.keep.background).not.toBe(BRAND_PRIMARY);

  // Nothing else in the dialog carries the red fill.
  const reds = await dialog.evaluate(
    (el, danger) =>
      [...el.querySelectorAll('*')].filter(
        (node) => getComputedStyle(node).backgroundColor === danger,
      ).length,
    DANGER,
  );
  expect(reds).toBe(1);
});

// 2026-10-29 brief: AA for text on the brand wash and on the info wash.
// They are the same token (--color-brand-wash) by design, so the point of
// measuring both is that the *rendered* grounds agree: a selected chip and
// an info banner must not drift apart.
test('ink text clears WCAG AA on the brand wash and on the info wash alike', async ({ page }) => {
  await openBoard(page);

  const grounds = await page.evaluate(() => {
    const chip = document.querySelector('[data-testid="view-chip-board"]');
    const banner = document.querySelector('[data-testid="closed-postings-banner"]');
    const bannerGround = [...banner.querySelectorAll('*')].find(
      (node) => getComputedStyle(node).backgroundColor !== 'rgba(0, 0, 0, 0)',
    );
    const chipLabel = [...chip.querySelectorAll('*')].find(
      (node) => node.children.length === 0 && node.textContent.trim() === 'Board',
    );
    const bannerText = [...banner.querySelectorAll('*')]
      .filter((node) => node.children.length === 0)
      .sort((a, b) => b.textContent.trim().length - a.textContent.trim().length)[0];
    return {
      wash: getComputedStyle(chip).backgroundColor,
      washText: getComputedStyle(chipLabel).color,
      infoWash: getComputedStyle(bannerGround).backgroundColor,
      infoText: getComputedStyle(bannerText).color,
    };
  });

  expect(grounds.wash).toBe(BRAND_WASH);
  expect(grounds.infoWash).toBe(BRAND_WASH);
  expect(grounds.washText).toBe(INK);
  expect(contrastRatio(grounds.washText, grounds.wash)).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatio(grounds.infoText, grounds.infoWash)).toBeGreaterThanOrEqual(4.5);
  // Ink on the wash is the brightest pair in the system; pin it so a wash
  // that darkens shows up here with its real number.
  expect(contrastRatio(grounds.washText, grounds.wash)).toBeCloseTo(19.0, 0);
});

test('the deliberate departures from Gestalt are in force', async ({ page }) => {
  await openBoard(page);

  const tokens = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    return {
      subtle: cs.getPropertyValue('--color-text-subtle').trim(),
      neutral: cs.getPropertyValue('--color-text-neutral').trim(),
      focus: cs.getPropertyValue('--color-border-focus').trim(),
      brandStrong: cs.getPropertyValue('--color-brand-primary-strong').trim(),
      rounding100: cs.getPropertyValue('--rounding-100').trim(),
    };
  });
  // Gestalt's #767676 fails on the fills; its focus ring is a 50% blue.
  expect(tokens.subtle).toBe(TEXT_SUBTLE);
  expect(tokens.neutral).toBe(TEXT_NEUTRAL);
  expect(tokens.focus).toBe(BORDER_FOCUS);
  expect(tokens.brandStrong).toBe(BRAND_PRIMARY_STRONG);
  // The one token added by the 2026-10-26 package (badges, small chips).
  expect(tokens.rounding100).toBe('4px');
});

test('the four WCAG AA pairs from the handover hold on rendered values', async ({ page }) => {
  await openBoard(page);

  // Check the ratio helper against WCAG's reference pair and against what
  // dark mode looked like before the on-brand binding was fixed (white on
  // #75bfff), so a broken formula cannot pass the real assertions below.
  expect(contrastRatio('rgb(255, 255, 255)', 'rgb(0, 0, 0)')).toBeCloseTo(21, 1);
  expect(contrastRatio('rgb(255, 255, 255)', 'rgb(117, 191, 255)')).toBeCloseTo(1.97, 1);

  const pairs = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const token = (name) => root.getPropertyValue(name).trim();
    const hexToRgb = (hex) => {
      const h = hex.replace('#', '');
      return [0, 2, 4]
        .map((i) => parseInt(h.slice(i, i + 2), 16))
        .join(', ');
    };
    const asRgb = (value) =>
      value.startsWith('#') ? `rgb(${hexToRgb(value)})` : value;
    return {
      // brand on on-brand: white label on the green primary fill
      onBrand: asRgb(token('--color-brand-on-color')),
      brand: asRgb(token('--color-brand-primary')),
      // text-subtle on surface
      subtle: asRgb(token('--color-text-subtle')),
      surface: asRgb(token('--color-background-card')),
      // ink text on surface
      ink: asRgb(token('--color-text-default')),
      // ink text on the brand wash (selected-toggle ground, info strips)
      wash: asRgb(token('--color-brand-wash')),
      // text-neutral on surface, the handover's third acceptance pair
      neutral: asRgb(token('--color-text-neutral')),
    };
  });

  // Acceptance values from the 2026-10-26 handover: brand on on-brand
  // ~4.6:1, text-subtle on surface ~6:1, text-neutral on surface ~8.9:1,
  // ink on the wash the maximum. All must clear WCAG AA's 4.5:1.
  expect(contrastRatio(pairs.onBrand, pairs.brand)).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatio(pairs.subtle, pairs.surface)).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatio(pairs.ink, pairs.surface)).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatio(pairs.ink, pairs.wash)).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatio(pairs.neutral, pairs.surface)).toBeGreaterThanOrEqual(4.5);

  // Pin the measured ratios so a future token edit that quietly drops below
  // the handover's acceptance numbers fails here with the real value.
  expect(contrastRatio(pairs.onBrand, pairs.brand)).toBeCloseTo(4.57, 1);
  expect(contrastRatio(pairs.subtle, pairs.surface)).toBeCloseTo(6.02, 1);
  expect(contrastRatio(pairs.neutral, pairs.surface)).toBeCloseTo(8.61, 1);
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

  // The 2026-10-26 pairs: 12->16, 14->20, 16->22, 20->24, 28->31, 36->40.
  // Each line height belongs to a font *size* and not to a heading level,
  // which is why this is keyed on font-size: a Gestalt Heading renders the
  // same tag at two sizes depending on its `size`. The pairs are no longer
  // one formula, so they are carried by Gestalt's own typography classes in
  // design/theme.css (see that file's comment). Probe those classes inside
  // #root directly; the rendered-component assertions below cover the pairs
  // the board actually shows.
  const scale = await page.evaluate(() => {
    const host = document.createElement('div');
    document.querySelector('#root').appendChild(host);
    // [Gestalt Text fontSize class, Gestalt Heading fontSize class, expected]
    const probes = [
      ['dR0', 'rrU', '16px'], // 12px
      ['j1A', 'kNw', '20px'], // 14px
      ['sAJ', 'LUr', '22px'], // 16px
      ['bwj', 'JW7', '24px'], // 20px
      ['GTB', 'h4h', '31px'], // 28px
      ['R-d', 'X9y', '40px'], // 36px
    ];
    const out = {};
    for (const [textClass, headingClass, expected] of probes) {
      for (const cls of [textClass, headingClass]) {
        const el = document.createElement('span');
        el.className = cls;
        el.textContent = 'x';
        host.appendChild(el);
        const got = getComputedStyle(el).lineHeight;
        const size = getComputedStyle(el).fontSize;
        if (got !== expected) out[`FAIL:${cls}`] = `${size}/${got} != ${expected}`;
        el.remove();
      }
    }
    host.remove();
    return out;
  });
  expect(scale).toEqual({});

  // And the board's own rendered Gestalt components, which must land on the
  // same pairs. The page title is an h1 at 28px since the white band went
  // (brief 2026-10-18, section 3), now paired 28->31; a column title is
  // Heading size 400 at 20px paired 20->24; card text is Text size 200 at
  // 14px paired 14->20.
  const rendered = await page.evaluate(() => {
    const read = (sel) => {
      const cs = getComputedStyle(document.querySelector(sel));
      return { fontSize: cs.fontSize, lineHeight: cs.lineHeight, fontWeight: cs.fontWeight };
    };
    const card = document.querySelector('[data-testid^="job-card-"]');
    const cardText = [...card.querySelectorAll('div, span')].find(
      (el) => getComputedStyle(el).fontSize === '14px',
    );
    const cs = getComputedStyle(cardText);
    return {
      h1: read('h1'),
      h3: read('h3'),
      cardText: { fontSize: cs.fontSize, lineHeight: cs.lineHeight },
    };
  });
  // Only 400 and 700 exist in Atkinson Hyperlegible, so headings are bold.
  expect(rendered.h1).toEqual({ fontSize: '28px', lineHeight: '31px', fontWeight: '700' });
  expect(rendered.h3).toEqual({ fontSize: '20px', lineHeight: '24px', fontWeight: '700' });
  expect(rendered.cardText).toEqual({ fontSize: '14px', lineHeight: '20px' });
});

test('portal text gets the line heights too, not just text inside #root', async ({ page }) => {
  await mockIntake(page, [{ body: { id: 'JOB-NEW', duplicate: false } }]);
  await openBoard(page);

  await page.getByRole('button', { name: 'Add a job', exact: true }).click();
  await page.getByRole('dialog', { name: 'Add a job' }).getByLabel('Posting link').fill('https://example.com/careers/new-role');
  await page.getByRole('dialog', { name: 'Add a job' }).getByRole('button', { name: 'Add job', exact: true }).click();
  await expect(page.getByText('Added to New')).toBeVisible();

  const toast = await page.evaluate(() => {
    const el = [...document.querySelectorAll('*')].find(
      (node) => node.children.length === 0 && node.textContent.trim() === 'Added to New',
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
  expect(toast.lineHeight).toBe('22px'); // text-300, 2026-10-26 pair
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

  // The dark token block is deliberately untouched by the green PR (launch is
  // light-only): these are the pre-existing dark values, asserted so a future
  // dark rework is a visible decision. The dark block still defines the old
  // token names (wash-blue, wash-teal, accent) because renaming those is part
  // of the dark rework, not this PR.
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
  await openHarness(page);

  // Gestalt picks a Button's label colour in JS, from useColorScheme(): red
  // maps to Text color="inverse", except in dark mode, where it switches to
  // "default" on purpose for contrast against its own dark-mode red. With the
  // fill rebound to the brand green that exception inverts the problem,
  // because dark --color-text-default is #ffffff: the fix in design/theme.css
  // binds both tokens to the handover's color-brand-on-color inside the fill.
  const light = await readPrimaryButton(page);
  expect(light.background).toBe(BRAND_PRIMARY);
  expect(light.color).toBe(ON_COLOR_LIGHT);
  // White on #008753 measures 4.57:1 - AA, but not by much. If the brand
  // green ever lightens, this is the assertion that catches it.
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
  expect(cascade.resolvedPrimary).toBe('#008753');
});
