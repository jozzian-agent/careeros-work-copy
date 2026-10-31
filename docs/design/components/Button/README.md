Gestalt Button, large (48px). Primary uses `brand`, secondary uses `fill-secondary`; the inverse variant sits on brand surfaces.

- One primary button per area. Label says what happens: "Join the waiting list".
- 16px radius, text 16px at weight 700 (Atkinson Hyperlegible has no 500), padding 8px 20px.
- Hover darkens: primary to `brand-hover`, secondary to `fill-secondary-hover`.
- Disabled uses `fill-secondary` with `text-disabled`.
- Links styled as buttons are `a` elements; actions are `button`.

- **Destructive:** the confirm button of a delete dialog is a solid `text-error` fill with `surface` text (hover: a darker red). It is the only red fill in the product and appears only inside a confirmation dialog. Triggers outside the dialog are gray with a red icon and label. The safe choice ("Keep company") stays gray.
