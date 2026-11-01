import { useCallback, useEffect, useState } from 'react';
import { Box, Button, Flex, Link, Text } from 'gestalt';
import { fetchNotes } from '../api/notes.js';
import { DividerList } from '../components/SectionCard.jsx';
import { localDate } from '../dates.js';
import PageLayout from '../components/PageLayout.jsx';

// Every note in the vault, with the job or company it belongs to. The
// owner asked to see notes in one place and to see what each one is
// about, which containment already answers: a note lives in one record's
// file, so its row names that record and links to it.
//
// Read-only on purpose. A note is written in its own window on the page
// of the record that holds it, so this page has no second editing
// surface; the association link is how the owner gets to one.
export default function Notes() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const load = useCallback(() => {
    fetchNotes()
      .then((data) => {
        setPage(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loadError) {
    return (
      <Box padding={6}>
        <Flex direction="column" gap={3} alignItems="start">
          <Text color="error">{loadError}</Text>
          <Button text="Retry" onClick={load} />
        </Flex>
      </Box>
    );
  }
  if (!page) {
    return (
      <Box padding={6}>
        <Text>Loading notes…</Text>
      </Box>
    );
  }

  const { notes, empty } = page;

  return (
    <PageLayout title="Notes">
      <Flex direction="column" gap={4} maxWidth={720}>
        {notes.length ? (
          <DividerList
            items={notes.map((note) => ({ ...note, key: `${note.job_id || note.company_id}-${note.id}` }))}
            renderItem={(note) => (
              <Flex direction="column" gap={1}>
                <Text weight="bold">{note.title}</Text>
                {note.body_preview ? (
                  <Text color="subtle" lineClamp={1}>
                    {note.body_preview}
                  </Text>
                ) : null}
                <Flex gap={3} wrap alignItems="center">
                  {note.job_id ? (
                    <Link href={`/jobs/${encodeURIComponent(note.job_id)}`} display="inlineBlock">
                      <Text color="link" size="200">{`${note.job_id} ${note.job_title}`}</Text>
                    </Link>
                  ) : null}
                  {note.company_id ? (
                    <Link href={`/companies/${encodeURIComponent(note.company_id)}`} display="inlineBlock">
                      <Text color="link" size="200">{`${note.company_id} ${note.company_name}`}</Text>
                    </Link>
                  ) : null}
                  {/* A note migrated out of the legacy notes field has no
                      write-time, so its row carries no date rather than
                      an invented one. Updated is shown only once it says
                      something Added does not. */}
                  {localDate(note.created) ? (
                    <Text size="200" color="subtle">{`Added ${localDate(note.created)}`}</Text>
                  ) : null}
                  {note.updated && note.updated !== note.created ? (
                    <Text size="200" color="subtle">{`Updated ${localDate(note.updated)}`}</Text>
                  ) : null}
                </Flex>
              </Flex>
            )}
          />
        ) : (
          // The empty list, per the CollectionPage README: one
          // SectionCard-style box -- the card surface, a 1px container
          // border, 16px rounding, written as the Gestalt props that
          // resolve to those tokens, the way the Companies box is --
          // around the sentence the payload already sends, rather than
          // the shared dashed EmptyState this used to be.
          //
          // No button in it. The README's "gray button repeating the
          // action" would repeat a primary action this page does not
          // have: a note is written in its own window on the page of the
          // record that holds it, so this page is read-only by design
          // (see the note at the top of this file). Same reading as
          // Companies and All jobs, owner decision 2026-11-01. The
          // "Add a note" the README names for this page is planned work,
          // not a gap to fill here (docs/design/HANDOVER.md, PR 7);
          // notes.spec.js pins the button's absence meanwhile.
          //
          // SectionCard's own EmptyState is deliberately left alone: the
          // detail pages' empty sections still use its dashed pattern,
          // which is what the design system asks of a section inside a
          // card rather than of a whole collection page.
          <Box data-testid="notes-empty" color="default" borderStyle="sm" rounding={4} padding={6}>
            <Text color="subtle">{empty}</Text>
          </Box>
        )}
      </Flex>
    </PageLayout>
  );
}
