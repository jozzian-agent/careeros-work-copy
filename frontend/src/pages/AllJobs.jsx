import { useEffect, useMemo, useState } from 'react';
import { Box, Button, Flex, Layer, Text } from 'gestalt';
import { FormattedMessage, useIntl } from 'react-intl';
import { fetchUniverse, moveJobStatus, promoteJob } from '../api/jobs.js';
import JobCard from '../components/JobCard.jsx';
import FilterBar from '../components/FilterBar.jsx';
import FloatingMessage from '../components/Message.jsx';
import PageLayout from '../components/PageLayout.jsx';
import { EMPTY_JOB_FILTERS, JOB_FILTER_GROUPS, filterJobs, jobFilterOptions } from '../jobFilters.js';

// The All jobs tab (B2, CAREER-89): every job that is not private to
// another user -- the records the API and the feed pool add, plus this
// reader's own. The visibility rule is the server's; this page renders
// what it is given.
//
// It is the board's own parts: the same filter bar over the same facets
// (src/jobFilters.js), the same JobCard, the same page frame. What it is
// not is a second board: a kanban by status would be a column of empty
// promises for the postings nobody has added yet, so the cards sit in one
// grid, each either showing its status or offering "Add to my jobs".
// There is no "Add a job" here either -- intake lives on My Jobs, which
// is where a posting a person pastes belongs.
const GRID_STYLE = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
  gap: '16px',
};

const TOAST_LIFETIME_MS = 4000;

export default function AllJobs() {
  const { formatMessage } = useIntl();
  const [payload, setPayload] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [filters, setFilters] = useState(EMPTY_JOB_FILTERS);
  // Deliberately not remembered, like the board's own: "Hide closed
  // postings" starts off on every load (D7, owner decision).
  const [hideClosed, setHideClosed] = useState(false);
  const [addingId, setAddingId] = useState(null);
  const [toast, setToast] = useState(null);

  async function load() {
    try {
      setPayload(await fetchUniverse());
      setLoadError(null);
    } catch (err) {
      setLoadError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function showToast(kind, text) {
    setToast({ kind, text });
    if (kind !== 'error') {
      window.setTimeout(() => setToast(null), TOAST_LIFETIME_MS);
    }
  }

  function toggleFilterValue(group, value) {
    setFilters((current) => {
      const values = current[group];
      return {
        ...current,
        [group]: values.includes(value) ? values.filter((v) => v !== value) : [...values, value],
      };
    });
  }

  function clearFilterGroup(group) {
    setFilters((current) => ({ ...current, [group]: [] }));
  }

  function clearFilterGroups(groups) {
    setFilters((current) => {
      const next = { ...current };
      groups.forEach((group) => {
        next[group] = [];
      });
      return next;
    });
  }

  // "Add to my jobs" is the existing promote endpoint under the user's
  // own word. The whole tab is reloaded afterwards rather than patched:
  // the answer is a NEW record of this reader's own, so the list gains an
  // entry and the posting it came from keeps its own, which is more than
  // one card's worth of change.
  async function addToMyJobs(job) {
    setAddingId(job.id);
    try {
      await promoteJob(job.id);
      await load();
      showToast('success', formatMessage({ id: 'allJobs.toast.added' }, { title: job.title }));
    } catch (err) {
      showToast('error', err.message);
    } finally {
      setAddingId(null);
    }
  }

  // A card of mine keeps its working status select, so the tab is not a
  // read-only copy of the board for the jobs the reader does hold.
  function moveStatus(id, status) {
    moveJobStatus(id, status)
      .then(load)
      .catch((err) => showToast('error', err.message));
  }

  const optionsByGroup = useMemo(() => jobFilterOptions(payload), [payload]);
  const filtered = useMemo(
    () => (payload ? filterJobs(payload.entries, filters, { hideClosed }) : []),
    [payload, filters, hideClosed],
  );

  if (loadError) {
    return (
      <Box padding={6}>
        <Flex direction="column" gap={3} alignItems="start">
          <Text color="error">{loadError}</Text>
          <Button text={formatMessage({ id: 'common.retry' })} onClick={load} />
        </Flex>
      </Box>
    );
  }
  if (!payload) {
    return (
      <Box padding={6}>
        <Text>
          <FormattedMessage id="common.jobs.loading" />
        </Text>
      </Box>
    );
  }

  const isEmpty = payload.entries.length === 0;
  const noMatches = !isEmpty && filtered.length === 0;
  const closedCount = payload.entries.filter((job) => job.closed).length;
  const closedDaysById = Object.fromEntries(
    (payload.closed_review || []).map((row) => [row.id, row.days_closed]),
  );
  // The same split the board shows, over the universe's jobs.
  const summaryText = payload.counts
    ? formatMessage(
        { id: 'common.jobs.countSummary' },
        { open: payload.counts.open, ended: payload.counts.ended },
      )
    : undefined;

  // No main action on this page, so the header stack is the filter bar
  // alone (brief 2026-10-18, section 3).
  const header = isEmpty ? null : (
    <FilterBar
      groups={JOB_FILTER_GROUPS}
      countNoun="jobs"
      optionsByGroup={optionsByGroup}
      selected={filters}
      onToggleValue={toggleFilterValue}
      onClearGroup={clearFilterGroup}
      onClearGroups={clearFilterGroups}
      toggles={[
        {
          key: 'hide-closed',
          label: formatMessage({ id: 'common.jobs.hideClosed' }),
          count: closedCount,
          pressed: hideClosed,
          onToggle: () => setHideClosed((value) => !value),
        },
      ]}
      summaryText={summaryText}
      resultCount={filtered.length}
      totalCount={payload.entries.length}
    />
  );

  return (
    <PageLayout title={<FormattedMessage id="allJobs.title" />} header={header}>
      {isEmpty ? (
        <Text color="subtle">{payload.empty}</Text>
      ) : noMatches ? (
        <Text color="subtle">
          <FormattedMessage id="common.jobs.noMatches" />
        </Text>
      ) : (
        <Box dangerouslySetInlineStyle={{ __style: GRID_STYLE }}>
          {filtered.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              statuses={payload.statuses}
              statusLabels={payload.status_labels || {}}
              endedStatuses={payload.ended_statuses || []}
              closedDays={closedDaysById[job.id]}
              onMyBoard={job.on_my_board}
              onAdd={addToMyJobs}
              addBusy={addingId === job.id}
              onMove={moveStatus}
            />
          ))}
        </Box>
      )}
      {toast ? (
        <Layer>
          <Box position="fixed" bottom left right display="flex" justifyContent="center" padding={4}>
            <Box width={560} maxWidth="100%">
              <FloatingMessage kind={toast.kind} text={toast.text} onDismiss={() => setToast(null)} />
            </Box>
          </Box>
        </Layer>
      ) : null}
    </PageLayout>
  );
}
