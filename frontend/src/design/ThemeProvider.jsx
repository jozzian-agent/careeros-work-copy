import { useLayoutEffect } from 'react';
import { ColorSchemeProvider, DesignTokensProvider, useColorScheme } from 'gestalt';

// Gestalt 177 split what 160 did in one component:
//
//   - ColorSchemeProvider is now pure React context. It injects no <style>
//     tag at all; it only publishes colorSchemeName ('lightMode'/'darkMode')
//     and, for colorScheme="userPreference", subscribes to the
//     prefers-color-scheme media query.
//   - DesignTokensProvider is the piece that renders the token stylesheet,
//     reading the scheme off that context to choose the light or dark token
//     set. It is NOT rendered by ColorSchemeProvider, so an app that only
//     wraps itself in ColorSchemeProvider (as this one did on 160) gets no
//     dark tokens whatsoever: gestalt/dist/gestalt.css ships five `:root`
//     blocks and every one of them is light.
//
// Both are therefore required, and DesignTokensProvider must stay without an
// `id` prop so its tokens land on `:root` globally; with an `id` it scopes
// them to a wrapper div and Layer/Popover/Tooltip portals (the board's Toast
// renders in a Layer) fall out of the theme.
function DataThemeAttribute() {
  const { colorSchemeName } = useColorScheme();

  // src/design/tokens.css keys dark off :root[data-theme="dark"], mirroring
  // the handoff's tokens.css. Syncing the attribute from Gestalt's own
  // context keeps ColorSchemeProvider the single control point for the
  // scheme, including the userPreference case, rather than having a second
  // source of truth for "is it dark".
  //
  // Layout effect, not plain effect: this runs before the browser paints, so
  // a dark mount never flashes the light token values first.
  useLayoutEffect(() => {
    const root = document.documentElement;
    if (colorSchemeName === 'darkMode') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
  }, [colorSchemeName]);

  return null;
}

export default function ThemeProvider({ colorScheme = 'light', children }) {
  return (
    <ColorSchemeProvider colorScheme={colorScheme}>
      <DesignTokensProvider>
        <DataThemeAttribute />
        {children}
      </DesignTokensProvider>
    </ColorSchemeProvider>
  );
}
