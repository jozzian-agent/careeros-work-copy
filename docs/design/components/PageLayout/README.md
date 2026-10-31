The frame every list page sits in: an H1 on the page ground, header rows under it, then `main`. Replaces Gestalt's `PageHeader` (a white band that pushed the title in from the content's left edge).

- Title: heading-md (28px bold), the page's one top-level heading.
- Header stack: 24px top, 32px sides, 16px bottom, 16px between rows. `main` has 32px sides and 32px bottom and no top padding of its own.
- The left edge is a property of this one component, which keeps the title, the toolbar and the content aligned.
- The primary fill appears at most once in the header: the page's one main action ("Add a job").
