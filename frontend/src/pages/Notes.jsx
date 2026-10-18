import { useCallback, useEffect, useState } from 'react';
import { Box, Button, Flex, Link, Text } from 'gestalt';
import { fetchNotes } from '../api/notes.js';
import { DividerList, EmptyState } from '../components/SectionCard.jsx';
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
          <EmptyState text={empty} />
        )}
      </Flex>
    </PageLayout>
  );
}
