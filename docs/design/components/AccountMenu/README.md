The Account button in the header and the pages behind it.

- **Button:** "Account" with a chevron, 40px, gray. On any account page it takes the selected style (`brand-wash`, 2px `brand` border). It replaces the old Profile link and Log out button. The main navigation is now Search, My Jobs, All jobs, Companies, Notes.
- **Menu:** Details, Professional experiences, Education, Certifications, Settings, FAQ, a divider, then Log out at the bottom. Items are 44px high; the popover is 280px wide (FloatingPopover).
- **Account pages** share a layout: a 220px list of the same links at the left (selected item with `brand-wash` and a 2px `brand` border; a row above the content on a phone) and a content column up to 880px. Every page puts 24px between its title and the next element, and 24px between blocks.
- **Details:** name, email, headline, location, About, and links (LinkedIn, GitHub, website, "Add another link"), with one Save changes bar.
- **Settings:** Password (opens the Change password dialog), Appearance (Light, Dark, Match device as a SegmentedControl), Your data (the AI note, Export my data, Delete account with a red label).
- **FAQ:** open-and-close sections: how CareerOS uses AI, your data and privacy, how companies are sorted (taxonomy). It replaces the Taxonomy page.
- Professional experiences, Education and Certifications follow CollectionPage. Education and Certifications show tiles or a table with a status badge (Completed, In progress; Valid, Expires in N months, Expired).
