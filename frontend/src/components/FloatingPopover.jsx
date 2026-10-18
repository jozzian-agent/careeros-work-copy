import { Layer, Popover } from 'gestalt';

// Every Popover in the app renders through here, so the reason lives in
// one place instead of beside each call.
//
// Gestalt's Popover defaults to `disablePortal: true`, which renders the
// panel inline in the DOM of whatever opened it, as `position: absolute`
// with NO z-index. That is the whole of the "see-through filter popover"
// bug (brief 2026-10-18, section 2): the panel was never transparent, it
// was underneath the page.
//
// What beat it was Gestalt's own Table: `gestalt.css` gives the `<table>`
// element `isolation: isolate`, which makes the table a stacking context,
// and a z-index:auto stacking context is painted in the same pass as
// z-index:auto positioned boxes, in tree order. The table comes after the
// filter bar, so the table, its cells and its sticky header all painted
// over the panel, which reads exactly like seeing the table through it.
// Any later stacking context would have done the same, which is why this
// is fixed once, here, rather than by a z-index aimed at the table.
//
// Gestalt's Layer is the fix the library already has: it mounts its
// children in a div appended to document.body, after #root, so a popover
// is always later in tree order than anything the page itself draws.
// Dropdown (the card status select) does this for itself already;
// Popover does not. No explicit zIndex: Layer-mounted overlays then stack
// among themselves in mount order, so a modal opened over a popover is
// above it, and nothing has to keep a scale of numbers in step.
export default function FloatingPopover(props) {
  return (
    <Layer>
      <Popover {...props} />
    </Layer>
  );
}
