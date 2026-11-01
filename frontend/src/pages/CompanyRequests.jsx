import { useCallback, useEffect, useState } from 'react';
import { Box, Button, Flex, Table, Text, TextField } from 'gestalt';
import {
  approveCompanyRequest,
  fetchCompanyRequests,
  rejectCompanyRequest,
} from '../api/companyRequests.js';
import { localDate } from '../dates.js';
import PageLayout from '../components/PageLayout.jsx';

// The admin's queue of company requests (owner ruling 2026-11-01).
//
// A user who may not write a shared company asks for the one their
// posting names, and the nightly pass
// (scripts/resolve_company_requests.py) answers every request it can
// match by name. What it cannot -- a name nothing on file is, or a name
// more than one company is -- it parks as `needs_admin`, and this page is
// where those are answered.
//
// Admin only. The nav tab is absent for everybody else and all three
// endpoints behind this page answer 403, which is what this page renders
// when it gets one: the server is the authority, and this page does not
// reimplement the rule in order to show a nicer sentence.
//
// Deliberately plain. No filtering, no paging, no sorting: the queue is
// what one nightly pass could not settle, which is a handful of rows, and
// a control that exists for a list this short is an element with nothing
// to do. Strings are inline, like the detail pages and the shared
// components (frontend/src/i18n/README.md says which surfaces keep their
// English in the code).
//
// Three actions per row, which are the three answers there are:
//   * Approve -- create a company with the requested name and link it.
//   * a suggestion chip -- approve, linking to that company instead.
//   * Reject -- refuse the ask, with an optional note.
// Every one of them settles every open request asking for the same
// company, not only this row, because the same name gets asked for by
// several people; the server does that and the page reloads after.
export default function CompanyRequests() {
  const [rows, setRows] = useState(null);
  const [loadError, setLoadError] = useState(null);
  // The id of the row a write is in flight for, so only that row's
  // buttons go quiet rather than the whole table.
  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);
  // The row whose Reject is open, and the note typed into it.
  const [rejecting, setRejecting] = useState(null);
  const [note, setNote] = useState('');

  const load = useCallback(() => {
    fetchCompanyRequests()
      .then((data) => {
        setRows(data.requests || []);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(id, work) {
    setBusyId(id);
    setActionError(null);
    try {
      await work();
      setRejecting(null);
      setNote('');
      load();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (loadError) {
    return (
      <PageLayout title="Company requests">
        <Flex direction="column" gap={3} alignItems="start">
          <Text color="error">{loadError}</Text>
          <Button text="Retry" onClick={load} />
        </Flex>
      </PageLayout>
    );
  }
  if (!rows) {
    return (
      <PageLayout title="Company requests">
        <Text>Loading company requests…</Text>
      </PageLayout>
    );
  }

  return (
    <PageLayout title="Company requests">
      <Flex direction="column" gap={4}>
        {actionError ? <Text color="error">{actionError}</Text> : null}
        {rows.length === 0 ? (
          // The same empty box the other collection pages draw, with the
          // sentence this page's own emptiness means: the queue is clear,
          // which is the normal state and not a gap to fill.
          <Box data-testid="company-requests-empty" color="default" borderStyle="sm" rounding={4} padding={6}>
            <Text color="subtle">No company requests are waiting for you.</Text>
          </Box>
        ) : (
          <Table accessibilityLabel="Company requests waiting for review">
            <Table.Header>
              <Table.Row>
                <Table.HeaderCell>
                  <Text weight="bold">Requested name</Text>
                </Table.HeaderCell>
                <Table.HeaderCell>
                  <Text weight="bold">From</Text>
                </Table.HeaderCell>
                <Table.HeaderCell>
                  <Text weight="bold">Asked</Text>
                </Table.HeaderCell>
                <Table.HeaderCell>
                  <Text weight="bold">Already on file</Text>
                </Table.HeaderCell>
                <Table.HeaderCell>
                  <Text weight="bold">Answer</Text>
                </Table.HeaderCell>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {rows.map((row) => (
                <Table.Row key={row.id}>
                  <Table.Cell>
                    <Text weight="bold">{row.name}</Text>
                  </Table.Cell>
                  <Table.Cell>
                    <Flex direction="column" gap={1}>
                      <Text size="200">{row.requester?.name || row.requester?.id || 'Unknown'}</Text>
                      {/* The job id, and its title only where the payload
                          carries one. A request comes from somebody
                          else's private posting, and the admin reaches no
                          part of it (decision D3), so the server sends the
                          title only when the job is one this reader may
                          read. The id is how the row names the posting. */}
                      <Text size="200" color="subtle">
                        {row.job?.title ? `${row.job.id} ${row.job.title}` : row.job?.id}
                      </Text>
                    </Flex>
                  </Table.Cell>
                  <Table.Cell>
                    <Text size="200">{localDate(row.created_at) || row.created_at}</Text>
                  </Table.Cell>
                  <Table.Cell>
                    {row.suggestions?.length ? (
                      <Flex gap={2} wrap>
                        {row.suggestions.map((suggestion) => (
                          <Button
                            key={suggestion.company_id}
                            size="sm"
                            text={`${suggestion.name} (${suggestion.score})`}
                            disabled={busyId === row.id}
                            onClick={() => run(row.id, () => approveCompanyRequest(row.id, suggestion.company_id))}
                          />
                        ))}
                      </Flex>
                    ) : (
                      <Text size="200" color="subtle">Nothing close</Text>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    <Flex direction="column" gap={2}>
                      <Flex gap={2} wrap>
                        <Button
                          size="sm"
                          color="red"
                          text="Approve"
                          disabled={busyId === row.id}
                          onClick={() => run(row.id, () => approveCompanyRequest(row.id))}
                        />
                        <Button
                          size="sm"
                          text="Reject"
                          disabled={busyId === row.id}
                          onClick={() => {
                            setRejecting(rejecting === row.id ? null : row.id);
                            setNote('');
                          }}
                        />
                      </Flex>
                      {rejecting === row.id ? (
                        <Flex direction="column" gap={2}>
                          <TextField
                            id={`reject-note-${row.id}`}
                            label="Why (optional)"
                            value={note}
                            onChange={({ value }) => setNote(value)}
                          />
                          <Button
                            size="sm"
                            text="Confirm reject"
                            disabled={busyId === row.id}
                            onClick={() => run(row.id, () => rejectCompanyRequest(row.id, note.trim()))}
                          />
                        </Flex>
                      ) : null}
                    </Flex>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Flex>
    </PageLayout>
  );
}
