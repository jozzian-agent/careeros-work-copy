# HANDOVER: implementing the CareerOS design

For the Hermes agent. Updated 2026-10-26. Target repo: the careeros work copy (`frontend/src/design/` and `frontend/src/components/`). Read **README** for what was decided and why, **BLUEPRINT** for the page map and data model, and the component guidelines for each pattern. Every value is from `tokens.json`. Mark anything you cannot verify as ASSUMED. The designs live in the Design canvas "CareerOS" (one artboard per screen, named below).

## Working rules (from the project)

- Small PRs named `feat/`, `fix/`, `ci/`. One PR at a time; wait for the owner's "go".
- List every file in each PR and anything outside scope. Report GitHub check results, not local ones.
- Never commit straight to `main`. Never invent values or data fields: if something is missing, stop and ask.
- No VPS access and no secrets. Static landing files are delivered as files in the repo; the owner deploys them.
- Do not work around a guard or the credential-redaction layer; report and stop.
- Do not promise matching or fit scores anywhere public. Fit stays hidden in the product ("not built").
- Public copy never mentions the academic taxonomies (ISIC, ISCO, ESCO). The FAQ and this doc may, internally.
- Anything sent to the AI provider (postings, notes, imported CVs) must be disclosed in plain words. The copy exists on the landing page, the Settings page and the FAQ; keep them identical and confirm the wording with the owner.

## Decision summary

- Landing system values everywhere. Font (Atkinson Hyperlegible 400 and 700) and dark mode come from the old product system, and so does the component set. Brand is Matchacado green 500.
- Brand fills the one main action on a screen, never a selected state. Selected view or filter: `brand-wash` and a 2px brand border (on the green search band: solid black).
- Destructive actions carry red: the confirm button in a delete dialog is a solid red fill; delete triggers are gray with a red icon and label. Red appears nowhere else as a fill.
- Links are black and underlined. Chips are 32px high, 14px bold. View switches are one SegmentedControl, never two chips.
- List pages share one layout (CollectionPage): heading with one primary action, one toolbar row, tiles or a table. Cards and tiles in a grid have a fixed height and cut long text.
- Bookmark means "keep an eye on this": on a job it saves to New, on a company it follows.
- No logos, pictures or ratings anywhere for now.

## PR plan (one at a time)

**PR 1: tokens** (`frontend/src/design/tokens.css`). Keep token NAMES, replace values, keep `!important`. Light then dark:

| Repo token | Design token | Light | Dark |
|---|---|---|---|
| `--color-brand-primary` | brand | `#008753` | `#6bec8c` (derived) |
| `--color-brand-primary-strong` | brand-hover | `#005f3e` | `#a4f9ac` (derived) |
| `--color-brand-on-color` | on-brand | `#ffffff` | `#111111` |
| `--color-brand-wash-blue` (RENAME `--color-brand-wash`) | brand-wash | `#e3fae1` | `#003020` (derived) |
| `--color-background-page` | ground | `#f6fdf5` | `#111111` |
| `--color-background-card` | surface | `#ffffff` | `#191919` |
| `--color-text-default` | ink | `#000000` | `#ffffff` |
| `--color-text-neutral` (new if absent) | text-neutral | `#4c4c4a` | `#e0e0e0` (derived) |
| `--color-text-subtle` | text-subtle | `#636361` | `#cdcdcd` |
| `--color-text-link` | ink | `#000000` | `#ffffff` (always underlined) |
| `--color-border-container` | border-decorative | `#c7c6c1` | `#4a4a4a` |
| `--color-border-default` | border-interactive | `#757570` | `#a5a5a5` |
| `--color-border-focus` | focus-ring | `#007db8` | `#abdbff` |
| `--color-background-secondary-base` | fill-secondary | `#e8e7e1` | `#2b2b2b` |
| `--color-background-secondary-weak` | fill-secondary-hover | `#d6d4cd` | `#3a3a3a` (derived) |
| `--color-brand-violet` | violet | `#6b16ca` | `#b190ff` |
| `--color-brand-wash-violet` | violet-wash | `#f0edff` | `#2c0066` |
| `--color-background-warning-weak` | warning-weak | `#ffe4c1` | `#7c2d00` |
| `--color-text-warning` | text-warning | `#bd5b00` | `#e18d00` |
| `--color-background-error-weak` | error-weak | `#ffe0e0` | `#660000` |
| `--color-text-error` | text-error | `#cc0000` | `#f47171` |
| `--color-background-danger-hover` (new) | danger-hover | `#a30000` | `#ffa3a3` (derived) |

Remove `--color-brand-accent` and `--color-brand-wash-teal`; rename every use of `--color-brand-wash-blue`. Add `--rounding-100: 4px`. Font unchanged. Line heights by font size on leaf elements only: 12 to 16, 14 to 20, 16 to 22, 20 to 24, 28 to 31, 36 to 40 (setting it on structural wrappers breaks job-card drag and drop; `tests/jobs-board.spec.js` catches it). Acceptance: `tests/theme.spec.js` contrast pairs pass in both schemes; add brand on on-brand (about 4.6:1) and text-subtle on surface.

**PR 2: Gestalt bridge** (`theme.css`). Primary button follows the brand tokens (check `color="red"` renders green). Keep `--color-background-button-selected-default` unused for view switches. Back-link arrow uses the brand icon token. Info tokens are bound to brand: ASSUMED, OWNER TO CONFIRM green or Gestalt blue. The `.Il7` hashed class depends on `gestalt` 177.0.12; keep the pin.

**PR 3: restyle existing components** with the new tokens: company link black underlined; FilterChip selected style and 32px size; LevelTag; EndedLane drag-over; links underlined everywhere; Message and popups. Update `docs/decisions/design-system.md` (no more "brand blue", token overrides, line heights).

**PR 4: shared pieces.** SegmentedControl (replaces Board/List and Tiles/List chip pairs), Dialog pattern with the red destructive confirm and the "Saved to" context line, CollectionPage heading and toolbar, the fixed-height card rule. See components `SegmentedControl`, `Dialog`, `CollectionPage`, `Button`.

**PR 5: shell.** New header: wordmark, main links (Search, My Jobs, All jobs, Companies, Notes), GlobalSearch field, Account button and menu (Details, Professional experiences, Education, Certifications, Settings, FAQ, Log out at the bottom). Removes the Profile link, the Log out button and the Experiences and Taxonomy links. Needs a search endpoint (see below). Artboards: Account menu, Global search.

**PR 6: jobs.** New JobCard (fixed height, footer with time and control, "Save to New" bookmark button for unsaved jobs); All jobs with the SearchBand and unsaved cards; My Jobs two-row toolbar and the Ended lane; Job detail without the provenance line, Original posting and Details cards, plus an "Original posting" dialog; Add a reason with "No reason given" preselected; Mark as won. Artboards: All jobs, My Jobs, My Jobs Ended lane, Job detail, Edit job, Original posting, Add a note, Mark as won, Add a reason.

**PR 7: companies and notes.** CompanyTile with Follow, Companies toolbar (Following filter), Company detail without the duplicate sector and size line (Classification card only), notes dialogs with the "Saved to" line, Notes page as CollectionPage with Add a note. Artboards: Companies, Company detail, Edit company, Delete company, Edit note, Delete note, Notes.

**PR 8: account area.** Account layout with left list, Details, Professional experiences (and the redesigned Add position form), Education, Certifications, Settings (Change password dialog, Appearance, Your data), FAQ (absorbs Taxonomy). Artboards: Details (Profile.dc), Add position, Education, Certifications, Settings, Change password, FAQ. 24px between a title and the next element on every account page.

**PR 9: sign-in recovery.** Forgot password link on Log in, Reset your password, Choose a new password. Needs outbound email and a reset token table (see below). The message never reveals whether an address has an account.

**PR 10: onboarding and import.** Step 2 "Add your background", Upload, and "Here is what we found". Needs file upload and AI extraction (see below). Steps 1 and 3 are not designed: ask.

**PR 11: landing page.** One static responsive page from the canvas artboard "Landing page": header, hero with waiting-list form, three steps, data note, timeline, invite-only login, closing banner, footer. Deliver as `landing/` (`index.html`, one CSS file, no framework), light theme only. Never claim an email was stored until a backend exists. Ask for the form endpoint and the Imprint and Privacy pages.

## Backend and data this design needs

Verify each against the current schema before building; the BLUEPRINT data model is derived from the screens, not from the repo.

| Need | Used by |
|---|---|
| Search endpoint over jobs, companies, notes | GlobalSearch |
| Job search with keywords, place, added since, workload, function, company, industry, saved | SearchBand on All jobs |
| `saved` state per job and user; save creates status New | Bookmark, unsaved cards |
| Follow per user and company | CompanyTile, Following filter |
| Note with exactly one parent (company or job) | Notes, dialogs, Notes page |
| Workload field on a job (from the posting, may be empty) | Job card, filter |
| Relative "added" time from the add time | Job card |
| Education, Certification, User links, profile fields (headline, location, about) | Account pages |
| Theme preference (light, dark, system) | Settings |
| Password change, password reset token, outbound email | Settings, Reset flow |
| Export my data, delete account | Settings |
| Import run: upload, AI extraction, review, apply | Onboarding, "Import from a CV" |
| Extraction state per job: read at, not found fields, failed | Original posting dialog |
| Status history events | Job detail History |

## Out of scope

Invites, backups, production, anything on the VPS. Do not change business logic or API payloads except where a row above asks. Fit scoring, job discovery, logos and ratings are not designed.

## Open decisions for the owner

1. Dark-mode green and the other "derived" values; info colour (green or blue).
2. Whether account menu pages beyond those listed are wanted (Education and Certifications fields are proposals).
3. FAQ and privacy wording, including "nothing else leaves the app" and "what you add is yours".
4. Password rules and reset link lifetime (the design states none).
5. Delete account and Delete job confirmations, Add education, Add certification and Add a company forms, onboarding steps 1 and 3: not designed.
6. Whether Follow stays visible before jobs are discovered automatically.
7. Contract type and Language filters from jobs.ch need new extracted fields.

## Verification checklist for each PR

1. `ci` and `frontend-dist` green (rebuild and commit `frontend/dist` per the repo rule).
2. File list matches the PR description.
3. Light and dark screenshots of each changed screen, plus a phone width.
4. Contrast results for both schemes; keyboard path through each dialog and menu.
