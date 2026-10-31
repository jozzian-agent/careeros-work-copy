Gestalt's Popover inside a Layer. Every popover in the app renders through it, so it mounts after the page root and stacks above everything, with no explicit z-index.

- The ground is the `surface` colour in both themes, the caret follows the ground, and the shadow is the floating elevation.
- MoreFiltersPanel (an OverlayPanel) is mounted in a Layer for the same reason.
- Gestalt's Dropdown already uses a Layer and needs no wrapper.
