Every popup in the app (Gestalt Modal). One pattern.

- `surface`, `radius-600`, floating shadow, over a 62% black scrim. Title left in heading-sm with a close button at the right; the body scrolls and the footer stays; footer buttons right-aligned, 24px padding.
- **One primary per dialog,** always enabled unless a field is required. The safe choice is gray and sits to its left.
- **Destructive confirm:** a solid `text-error` red button with `surface` text, hover `danger-hover`, and a gray "Keep ..." button beside it. Delete triggers outside the dialog are gray with a red icon and label.
- **Context line:** a dialog that saves something to an item says where, at the top: "Saved to" and a gray tag such as "Company · Threema AG" or "Job · Senior Growth Marketing Manager at Threema AG". A delete dialog names the item in its sentence.
- Widths: 440 for confirmations, 480 for short forms, 560 to 640 for long forms and the Original posting dialog.
- Add a reason: reasons are radio buttons, "No reason given" is selected by default, so Save is always a primary.
- Original posting dialog: source, posted date, Check if still online, the posting text in a scrolling box, how it was extracted (when it was read, what was not found), Re-extract, and a primary "Open the posting at its source".
