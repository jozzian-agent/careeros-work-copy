// Blue/purple accent override for Gestalt (owner decision JOZ-273, option C).
//
// Gestalt 160.0.0 ships its full classic token set as :root custom
// properties inside gestalt/dist/gestalt.css (Pinterest red). It has no
// runtime "brand color" prop on its Provider, so the supported way to
// re-theme it is to redeclare the same custom properties afterward; a later
// :root rule at equal specificity wins the cascade.
//
// Values are the accent pair already in use by the Flask dashboard
// (careeros/web/theme.py): --accent-indigo for primary actions,
// --accent-violet (the page accent used for links) for link color and hover.
export const ACCENT_INDIGO = '#5e6ad2';
export const ACCENT_VIOLET = '#7170ff';

const TOKEN_OVERRIDES = {
  '--color-background-button-primary-default': ACCENT_INDIGO,
  '--color-background-button-primary-hover': ACCENT_VIOLET,
  '--color-background-button-primary-active': ACCENT_INDIGO,
  // ButtonToggle's selected state (Board/List, Needs attention) reads this
  // token instead of the button-primary-* trio above, regardless of its
  // own color prop; see gestalt/src/ButtonToggle.css .selected.
  '--color-background-button-selected-default': ACCENT_INDIGO,
  '--color-text-link': ACCENT_VIOLET,
};

export function applyTheme() {
  const existing = document.getElementById('gestalt-theme-overrides');
  if (existing) return;
  const style = document.createElement('style');
  style.id = 'gestalt-theme-overrides';
  // The real competing rule is not stylesheet chunk order: ColorSchemeProvider
  // (wrapping the app in App.jsx) renders its own <style> tag with a fresh
  // `:root { ... }` block containing gestalt's default (pink/red) tokens,
  // every time it renders. That tag lives inside #root in <body>, which is
  // always later in document order than this <head> style, so without
  // !important it would win the cascade on every mount and on every
  // ColorSchemeProvider re-render (e.g. a prefers-color-scheme change).
  // !important makes this override win regardless of render order.
  const declarations = Object.entries(TOKEN_OVERRIDES)
    .map(([name, value]) => `  ${name}: ${value} !important;`)
    .join('\n');
  style.textContent = `:root {\n${declarations}\n}`;
  document.head.appendChild(style);
}
