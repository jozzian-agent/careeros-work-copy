# CareerOS

A personal job-hunt OS. Paste a job link and it arrives linked to its company, filled in and ready to triage on your board.

This system consolidates two earlier ones: the **landing page system** and the **old product system**. The rule used: the landing system's values win everywhere, except the **font** and **dark mode**, which come from the old system, and the **component set**, which comes from the old system. The old system's source is the repo's `frontend/src/design/tokens.css`, `theme.css` and its decision record.

## What came from where

| Area | Source | Result |
|---|---|---|
| Brand, ground, greys, text, borders (light) | Landing | Matchacado green 500 brand, light green ground, warm Gestalt greys, black text |
| Spacing, radii, type sizes and line heights | Landing | 4px spacing scale, 4 / 16 / 24px radii, heading and text styles |
| Font | Old product | Atkinson Hyperlegible, 400 and 700 only |
| Dark mode | Old product | Same structure and values, with brand translated from blue to green |
| Components | Old product | Its whole set, restyled with the landing tokens |
| Primitives (Button, Badge, TextField, Card, Link, Divider) | Landing | Kept as the base Gestalt layer |
| Dropped from the old system | | Brand blue, the teal accent, the blue and teal washes |
| Carried because components need them | Old product | Violet and violet wash, warning and error greys, 8px radius, pill radius |

See **HANDOVER** for exactly what changes in the repo.

## Principle

CareerOS builds on Pinterest's **Gestalt**, pinned at 177. Colours are theme tokens, not literals. Gestalt's defaults for primary (red) and links (blue) are replaced: the brand is **Matchacado green 500** and links stay black and underlined.

## Colour

- **Brand:** `#008753`, hover `#005f3e`. White on 500 is about 4.6:1, so text on brand is bold or 16px and up.
- **Ground:** `#f6fdf5`. Cards are white on it.
- **Neutrals:** `ink`, `text-neutral`, `text-subtle`, `fill-secondary`. Chips are either solid brand with white text or `fill-secondary` with black text.
- **No pastel panels.** Pastel fills and grey-on-grey chips were tried and rejected.
- **Functional washes only:** `brand-wash` (selected filter, drag-over), `violet-wash` ("Needs your input"), `warning-weak` and `error-weak`. These mark states; they are never decoration.
- **Not chosen:** Spabattical teal 700, Mysticool purple 700, Caramellow amber 700 as brand. Red, pink and blue are excluded as brand colours.
- **Dark mode:** `brand` becomes Matchacado 300 `#6bec8c` with `on-brand` `#111111`; surfaces are the old product's `#111111` and `#191919`. Values marked "derived" in the token notes were not in the old system and need a visual and contrast check.

## Typography

**Atkinson Hyperlegible**, weights 400 and 700 only (the old product ships a latin subset). Anything that was weight 500 in the landing system is now 700. Sizes 12, 14, 16, 20, 28 and 36px. Line heights come from the landing styles: 16, 20, 22, 24, 28, 31 and 40.

## Shape and spacing

16px radius for buttons, fields, cards and the Ended lane; 24px for large panels; 8px for the status select; 4px for badges; pill for chips. Spacing follows the 4px scale. Cards: 1px `border-decorative`, no shadow, 24px padding.

## Components

Gestalt primitives: **Button, Badge, TextField, Card, Link, Divider, SegmentedControl.** Patterns added in the product design pass: **CollectionPage, CompanyTile, GlobalSearch, SearchBand, AccountMenu, Dialog, OnboardingImport.** Product components from the old system: **PageLayout, FilterBar, FilterChip, QuietChip, NeedsInputChip, FitChip, AiLabel, LevelTag, SectionCard, StatusSelect, JobCard, KanbanBoard, EndedLane, Message, DetailHeader, FloatingPopover.** Each component's guideline carries the old system's rule, with blue replaced by brand green.

## Rules added in the product design pass

- Destructive: red appears only as the fill of the confirm button in a delete dialog; triggers are gray with a red icon and label.
- Selected filters on a brand panel are solid black; everywhere else `brand-wash` with a 2px brand border.
- View switches use SegmentedControl, not chips. Chips are 32px high with 14px bold text.
- Lists use CollectionPage; cards and tiles in a grid have a fixed height and cut long text.
- No logo, picture or rating until the product has them.
- See **BLUEPRINT** for the page map, flows and data model, and **HANDOVER** for the build plan.

## Rules that survive from the old system

- Brand is the fill of the one main action on a screen, never of a selected state. A selected view or filter uses `brand-wash` with a 2px brand border.
- Coloured badges in the product are reserved for an owner-action signal ("Needs your input") and provenance ("AI-generated"). A machine-state notice is a quiet chip and never alarms. Solid brand badges are for marketing surfaces such as the landing page.
- Colour never carries must-have versus nice-to-have.
- Fit scoring is not built: the product says "Not calculated yet" and the public site promises no matching.
- A board card states what identifies the posting and what the owner must act on, and nothing a filter or the detail page already says.

## Content fundamentals

Plain, direct, second person. Say what happens. Be plain about data: text a person adds is processed by an AI model through a third-party provider, and the landing page says so before sign-in. Do not mention the academic taxonomies in public copy. Sample data is labelled "Example" and uses invented companies.

## Accessibility

Body text 4.5:1 or better on its ground in both themes. Real `button`, `a` and `input` with visible labels. Selected states carry `aria-pressed` and never rely on colour alone. Targets are 44px or taller on phones.

## Assumptions to confirm

- Dark mode brand: Matchacado 300 and the other "derived" values.
- Links are black and underlined in the product too (the old system used brand-coloured links).
- Info badges: the old system bound Gestalt's info type to the brand colour. With green as brand, decide whether info stays green or returns to Gestalt blue.
- The status select's 8px radius, pill chips and violet are carried from the old system although they are not on the landing page.
