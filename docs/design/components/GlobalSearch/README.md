The search field in the header of every signed-in page, between the main links and the Account button.

- Rounded field, 300px wide, 40px high, magnifier at the left, a "/" key hint at the right. Placeholder "Search jobs, companies, notes". `/` focuses it from anywhere.
- **Results popover** under the field, 560px wide, `surface`, `radius-400`, floating shadow, rendered through FloatingPopover. Results are grouped: Jobs, Companies, Notes. A job row shows the title, then "Company · place" and its status badge; a company row shows its place and open jobs; a note row shows the note title and what it is on.
- The first row is active. Up and down move, Enter opens, Esc closes. The footer line repeats these keys and links to "See all results for the query".
- It searches what the person has added. The All jobs search band is a separate, richer search over jobs only (see SearchBand).
