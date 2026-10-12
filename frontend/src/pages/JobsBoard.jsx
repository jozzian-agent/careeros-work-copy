import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  ButtonToggle,
  Flex,
  Heading,
  Layer,
  Link,
  Modal,
  PageHeader,
  SelectList,
  Table,
  Text,
  TextField,
  Toast,
} from 'gestalt';
import { fetchBoard, intakeJob, moveJobStatus, promoteJob, retryIngest } from '../api/jobs.js';

const VIEW_KEY = 'careerJobsView';
const NEEDS_ATTENTION_KEY = 'careerNeedsAttention';
const LIST_COLUMNS = ['Title', 'Company', 'Source', 'Status', 'Location', 'Posted', 'Added'];
const AUTO_REFRESH_AFTER_MS = 30000;
const TOAST_LIFETIME_MS = 4000;

function readStoredView() {
  try {
    return window.localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'board';
  } catch {
    return 'board';
  }
}

function readStoredNeedsAttention() {
  try {
    return window.localStorage.getItem(NEEDS_ATTENTION_KEY) === 'true';
  } catch {
    return false;
  }
}

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function jobHref(id) {
  return `/jobs/${encodeURIComponent(id)}`;
}

function companyHref(id) {
  return `/companies/${encodeURIComponent(id)}`;
}

// The company link is either confirmed (company_name + company_id, no
// review pending), tentative-but-still-in-review (company_link_state
// "needs_review" with a candidate name + id already attached), stuck in
// the owner-review queue with no candidate yet (needs_review, no name),
// or genuinely unresolved ("pending", no candidate at all). Per contract
// point 7, a tentative name alongside needs_review renders BOTH the link
// and the review chip together, since the link is informative even though
// it is not yet the owner's confirmed decision.
function CompanyDisplay({ job }) {
  const hasCandidate = job.company_name && job.company_id;
  const companyLink = hasCandidate ? (
    <Link href={companyHref(job.company_id)} display="inlineBlock">
      <Text weight="bold" color="link">
        {job.company_name}
      </Text>
    </Link>
  ) : null;
  if (job.company_link_state === 'needs_review') {
    return (
      <Flex gap={2} alignItems="center" wrap>
        {companyLink}
        <Badge type="recommendation" text="Needs your input" />
      </Flex>
    );
  }
  if (hasCandidate) {
    return companyLink;
  }
  return <Badge type="neutral" text="Company: pending" />;
}

function IngestIndicator({ job, onRetry }) {
  if (job.ingest_state === 'fetch_failed' || job.ingest_state === 'extract_failed') {
    const label = job.ingest_state === 'fetch_failed' ? 'Fetch failed' : 'Extraction failed';
    const reason = job.ingest_error?.reason;
    return (
      <Flex gap={2} alignItems="center" wrap>
        <Badge type="error" text={reason ? `${label}, ${reason}` : label} />
        <Button size="sm" color="red" text="Retry" onClick={() => onRetry(job.id)} />
      </Flex>
    );
  }
  if (!job.enriched && (job.ingest_state === 'stub' || job.ingest_state === 'fetched')) {
    return <Badge type="warning" text="Details filling in…" />;
  }
  if (!job.enriched) {
    return <Badge type="neutral" text="Enrichment pending" />;
  }
  return null;
}

function JobCard({ job, statuses, functionLabels, onMove, onRetry, draggable }) {
  function handleDragStart(event) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', job.id);
  }

  return (
    // Gestalt Box has no drag-event props; this plain div only carries drag
    // wiring (contract point 2), all visuals stay on the Box inside it.
    <div data-testid={`job-card-${job.id}`} draggable={draggable} onDragStart={handleDragStart}>
      <Box color="default" borderStyle="sm" rounding={3} padding={3} marginBottom={3}>
        <Flex direction="column" gap={2}>
          <Flex justifyContent="between" alignItems="center" gap={2}>
            <Link href={jobHref(job.id)} display="inlineBlock">
              <Text weight="bold" overflow="normal">
                {job.title}
              </Text>
            </Link>
            <SelectList
              id={`status-${job.id}`}
              label={`Move ${job.title} to`}
              labelDisplay="hidden"
              size="md"
              value={job.status}
              onChange={({ value }) => onMove(job.id, value)}
            >
              {statuses.map((status) => (
                <SelectList.Option key={status} label={titleCase(status)} value={status} />
              ))}
            </SelectList>
          </Flex>
          <CompanyDisplay job={job} />
          <Text size="200" color="subtle">
            {job.location || 'Location unknown'}, added {job.added}
          </Text>
          {job.posted_date ? (
            <Text size="200" color="subtle">
              Posted {job.posted_date}
            </Text>
          ) : null}
          <Flex gap={2} wrap>
            <Badge type="neutral" text={job.source || 'Unknown source'} />
            {job.salary_info ? <Badge type="success" text="Salary disclosed" /> : null}
            {job.summary_source === 'ai' ? <Badge type="info" text="AI-generated" /> : null}
            {job.function.map((functionId) => (
              <Badge key={functionId} type="info" text={functionLabels[functionId] || functionId} />
            ))}
          </Flex>
          <IngestIndicator job={job} onRetry={onRetry} />
        </Flex>
      </Box>
    </div>
  );
}

function BoardColumn({ status, entries, statuses, functionLabels, onMove, onRetry }) {
  function handleDragOver(event) {
    event.preventDefault();
  }

  function handleDrop(event) {
    event.preventDefault();
    const id = event.dataTransfer.getData('text/plain');
    if (id) onMove(id, status);
  }

  return (
    <div data-testid={`board-column-${status}`} onDragOver={handleDragOver} onDrop={handleDrop}>
      <Box minWidth={240} flex="grow" marginEnd={3}>
        <Box marginBottom={2}>
          <Flex alignItems="center" gap={2}>
            <Heading size="400">{titleCase(status)}</Heading>
            <Badge type="neutral" text={String(entries.length)} />
          </Flex>
        </Box>
        {entries.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            statuses={statuses}
            functionLabels={functionLabels}
            onMove={onMove}
            onRetry={onRetry}
            draggable
          />
        ))}
      </Box>
    </div>
  );
}

function sortEntries(entries, column, ascending) {
  if (column === null) return entries;
  const getField = [
    (job) => job.title,
    (job) => job.company_name || '',
    (job) => job.source || '',
    (job) => job.status,
    (job) => job.location || '',
    (job) => job.posted_date || '',
    (job) => job.added || '',
  ][column];
  const copy = [...entries];
  copy.sort((a, b) => getField(a).localeCompare(getField(b), undefined, { numeric: true }) * (ascending ? 1 : -1));
  return copy;
}

// Table.SortableHeaderCell never sets aria-sort on its <th> (still true in
// gestalt@177.0.12: the string "aria-sort" appears nowhere in the bundle);
// it only swaps the visible sort icon. This adapter sets the attribute
// directly on the ancestor <th> after render, which is the minimal fix
// since Table.HeaderCell does not accept extra DOM attributes either.
function SortableHeaderCell({ label, status, sortOrder, onSortChange }) {
  const markerRef = useRef(null);

  useEffect(() => {
    const th = markerRef.current?.closest('th');
    if (!th) return;
    th.setAttribute('aria-sort', status === 'active' ? (sortOrder === 'desc' ? 'descending' : 'ascending') : 'none');
  }, [status, sortOrder]);

  return (
    <Table.SortableHeaderCell status={status} sortOrder={sortOrder} onSortChange={onSortChange}>
      <span ref={markerRef} style={{ display: 'contents' }}>
        <Text weight="bold">{label}</Text>
      </span>
    </Table.SortableHeaderCell>
  );
}

function ListView({ entries, onRetry }) {
  const [sortColumn, setSortColumn] = useState(null);
  const [ascending, setAscending] = useState(true);
  const sorted = useMemo(() => sortEntries(entries, sortColumn, ascending), [entries, sortColumn, ascending]);

  function sortBy(column, direction) {
    setSortColumn(column);
    setAscending(direction);
  }

  return (
    <Box>
      <Box display="block" mdDisplay="none" marginBottom={3} maxWidth={280}>
        <SelectList
          id="job-sort"
          label="Sort by"
          placeholder="Choose order"
          value={sortColumn === null ? null : `${sortColumn}:${ascending ? 'asc' : 'desc'}`}
          onChange={({ value }) => {
            const [column, direction] = value.split(':');
            sortBy(Number(column), direction === 'asc');
          }}
        >
          {LIST_COLUMNS.flatMap((label, index) => [
            <SelectList.Option key={`${index}-asc`} label={`${label} (ascending)`} value={`${index}:asc`} />,
            <SelectList.Option key={`${index}-desc`} label={`${label} (descending)`} value={`${index}:desc`} />,
          ])}
        </SelectList>
      </Box>
      {/* No display:none at any breakpoint here: hiding the table on mobile
          is the bug this round fixes (contract point 9's mobile rows). The
          wrapper only adds horizontal scroll so the table still fits. */}
      <Box overflow="auto">
        <Table accessibilityLabel="Jobs list">
          <Table.Header>
            <Table.Row>
              {LIST_COLUMNS.map((label, index) => (
                <SortableHeaderCell
                  key={label}
                  label={label}
                  status={sortColumn === index ? 'active' : 'inactive'}
                  sortOrder={sortColumn === index && !ascending ? 'desc' : 'asc'}
                  onSortChange={() => sortBy(index, sortColumn === index ? !ascending : true)}
                />
              ))}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {sorted.map((job) => (
              <Table.Row key={job.id}>
                <Table.Cell>
                  <Link href={jobHref(job.id)} display="inlineBlock">
                    <Text color="link">{job.title}</Text>
                  </Link>
                </Table.Cell>
                <Table.Cell>
                  <CompanyDisplay job={job} />
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.source}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Flex direction="column" gap={1}>
                    <Text>{titleCase(job.status)}</Text>
                    <IngestIndicator job={job} onRetry={onRetry} />
                  </Flex>
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.location || ''}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.posted_date || ''}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.added}</Text>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
      </Box>
    </Box>
  );
}

function DuplicateDialog({ duplicate, onCancel, onOpenExisting, onPromote, onAddAnyway }) {
  const basisText = duplicate.basis === 'same_ats_posting_id' ? 'the same posting ID' : 'the same URL';
  return (
    <Modal
      accessibilityModalLabel="Possible duplicate job"
      heading="Possible duplicate"
      onDismiss={onCancel}
      footer={
        <Flex gap={2} justifyContent="end" wrap>
          {duplicate.actions.includes('open_existing') ? (
            <Button text="Open existing" onClick={onOpenExisting} />
          ) : null}
          {duplicate.actions.includes('promote') ? <Button text="Promote to pipeline" onClick={onPromote} /> : null}
          {duplicate.actions.includes('add_anyway') ? (
            <Button color="red" text="Add anyway" onClick={onAddAnyway} />
          ) : null}
          <Button text="Cancel" onClick={onCancel} />
        </Flex>
      }
    >
      <Text>
        &quot;{duplicate.existing.title}&quot; looks like a job you already have (matched by {basisText}). Nothing
        is created until you choose.
      </Text>
    </Modal>
  );
}

export default function JobsBoard() {
  const [board, setBoard] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [view, setView] = useState(readStoredView);
  const [needsAttention, setNeedsAttention] = useState(readStoredNeedsAttention);
  const [functionFilter, setFunctionFilter] = useState('all');
  const [toast, setToast] = useState(null);
  const [intakeUrl, setIntakeUrl] = useState('');
  const [intakeBusy, setIntakeBusy] = useState(false);
  const [intakeError, setIntakeError] = useState(null);
  const [duplicate, setDuplicate] = useState(null);
  const moveGenerationRef = useRef({});

  function showToast(message, type = 'success') {
    setToast({ message, type });
  }

  async function load() {
    try {
      const data = await fetchBoard();
      setBoard(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), TOAST_LIFETIME_MS);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    let hiddenAt = document.hidden ? Date.now() : null;
    function onVisibilityChange() {
      if (document.hidden) {
        hiddenAt = Date.now();
        return;
      }
      const elapsed = hiddenAt === null ? 0 : Date.now() - hiddenAt;
      hiddenAt = null;
      if (elapsed > AUTO_REFRESH_AFTER_MS) load();
    }
    function onPageShow(event) {
      if (event.persisted) load();
    }
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, []);

  function persistView(nextView) {
    setView(nextView);
    try {
      window.localStorage.setItem(VIEW_KEY, nextView);
    } catch {
      // localStorage unavailable; view choice just will not persist.
    }
  }

  function toggleNeedsAttention() {
    const next = !needsAttention;
    setNeedsAttention(next);
    try {
      window.localStorage.setItem(NEEDS_ATTENTION_KEY, String(next));
    } catch {
      // localStorage unavailable; toggle choice just will not persist.
    }
  }

  // Two moves on the same job can overlap in flight (e.g. New->Interested
  // sent, then New->Applied sent before the first replies). Whichever
  // reply lands last used to win regardless of which one is stale; a
  // per-job generation counter fixes that: a failure only rolls the board
  // back if no newer move for that job has started since it was sent.
  async function handleMove(id, status) {
    const previous = board.entries.find((job) => job.id === id)?.status;
    if (!previous || previous === status) return;
    const generation = (moveGenerationRef.current[id] || 0) + 1;
    moveGenerationRef.current[id] = generation;
    setBoard((current) => ({
      ...current,
      entries: current.entries.map((job) => (job.id === id ? { ...job, status } : job)),
    }));
    try {
      await moveJobStatus(id, status);
      showToast('Status updated', 'success');
    } catch (err) {
      if (moveGenerationRef.current[id] === generation) {
        setBoard((current) => ({
          ...current,
          entries: current.entries.map((job) => (job.id === id ? { ...job, status: previous } : job)),
        }));
      }
      showToast(err.message, 'error');
    }
  }

  async function handleRetry(id) {
    try {
      await retryIngest(id);
      await load();
      showToast('Retry started', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function handleIntakeSubmit(url, { force = false } = {}) {
    const trimmed = url.trim();
    if (!trimmed) return;
    setIntakeBusy(true);
    try {
      const result = await intakeJob(trimmed, { force });
      if (result?.duplicate) {
        setDuplicate({ ...result, url: trimmed });
        setIntakeError(null);
        return;
      }
      setDuplicate(null);
      setIntakeError(null);
      setIntakeUrl('');
      await load();
      showToast('Job added', 'success');
    } catch (err) {
      setIntakeError({ message: err.message, url: trimmed, force });
      showToast(err.message, 'error');
    } finally {
      setIntakeBusy(false);
    }
  }

  function handleIntakeRetry() {
    if (intakeError) handleIntakeSubmit(intakeError.url, { force: intakeError.force });
  }

  function handleDuplicateCancel() {
    setDuplicate(null);
  }

  function handleDuplicateOpenExisting() {
    window.location.href = jobHref(duplicate.existing.id);
  }

  async function handleDuplicatePromote() {
    const id = duplicate.existing.id;
    try {
      await promoteJob(id);
      setDuplicate(null);
      setIntakeUrl('');
      await load();
      showToast('Promoted to pipeline', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function handleDuplicateAddAnyway() {
    const url = duplicate.url;
    setDuplicate(null);
    handleIntakeSubmit(url, { force: true });
  }

  const functionLabels = useMemo(() => {
    if (!board) return {};
    return Object.fromEntries(board.function_options.map(([id, label]) => [id, label]));
  }, [board]);

  const filteredEntries = useMemo(() => {
    if (!board) return [];
    return board.entries.filter((job) => {
      const functionOk = functionFilter === 'all' || job.function.includes(functionFilter);
      const needsOk = !needsAttention || job.needs_attention;
      return functionOk && needsOk;
    });
  }, [board, functionFilter, needsAttention]);

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

  if (!board) {
    return (
      <Box padding={6}>
        <Text>Loading jobs…</Text>
      </Box>
    );
  }

  const isEmpty = board.entries.length === 0;
  const needsAttentionEmpty = !isEmpty && needsAttention && filteredEntries.length === 0;

  return (
    <Box padding={6}>
      <PageHeader title="Jobs" />
      {/* PageHeader's own items slot is `display: none` below the md
          breakpoint (gestalt/src/PageHeader/components.tsx
          PageHeaderItemsBlock), so Board/List lived there would be
          unreachable on mobile and the mobile list-rows fix would be moot.
          This row has no such hiding and stays visible at every width. */}
      <Box marginTop={3} marginBottom={3}>
        <Flex gap={2}>
          <ButtonToggle text="Board" selected={view === 'board'} onClick={() => persistView('board')} />
          <ButtonToggle text="List" selected={view === 'list'} onClick={() => persistView('list')} />
        </Flex>
      </Box>
      <Box marginTop={4} marginBottom={4}>
        <Flex gap={2} alignItems="end" wrap>
          <Box flex="grow" minWidth={240}>
            <TextField
              id="posting-url"
              type="url"
              label="Posting URL"
              placeholder="https://company.example/careers/role"
              value={intakeUrl}
              disabled={intakeBusy}
              onChange={({ value }) => setIntakeUrl(value)}
            />
          </Box>
          <Button
            text="Add"
            color="red"
            disabled={intakeBusy || !intakeUrl.trim()}
            onClick={() => handleIntakeSubmit(intakeUrl)}
          />
        </Flex>
        {intakeError ? (
          <Box marginTop={2}>
            <Flex gap={2} alignItems="center" wrap>
              <Text dataTestId="intake-error" color="error">
                {intakeError.message}
              </Text>
              <Button dataTestId="intake-retry" size="sm" text="Retry" onClick={handleIntakeRetry} />
            </Flex>
          </Box>
        ) : null}
      </Box>
      <Box marginBottom={4}>
        <Flex gap={3} alignItems="center" wrap>
          <Box maxWidth={240}>
            <SelectList
              id="function-filter"
              label="Function"
              value={functionFilter}
              onChange={({ value }) => setFunctionFilter(value)}
            >
              <SelectList.Option label="All functions" value="all" />
              {board.function_options.map(([id, label]) => (
                <SelectList.Option key={id} label={label} value={id} />
              ))}
            </SelectList>
          </Box>
          <ButtonToggle text="Needs attention" selected={needsAttention} onClick={toggleNeedsAttention} />
        </Flex>
      </Box>
      {isEmpty ? (
        <Text color="subtle">{board.empty}</Text>
      ) : needsAttentionEmpty ? (
        <Text color="subtle">Nothing needs attention.</Text>
      ) : view === 'board' ? (
        <Flex wrap>
          {board.statuses.map((status) => (
            <BoardColumn
              key={status}
              status={status}
              entries={filteredEntries.filter((job) => job.status === status)}
              statuses={board.statuses}
              functionLabels={functionLabels}
              onMove={handleMove}
              onRetry={handleRetry}
            />
          ))}
        </Flex>
      ) : (
        <ListView entries={filteredEntries} onRetry={handleRetry} />
      )}
      {duplicate ? (
        <DuplicateDialog
          duplicate={duplicate}
          onCancel={handleDuplicateCancel}
          onOpenExisting={handleDuplicateOpenExisting}
          onPromote={handleDuplicatePromote}
          onAddAnyway={handleDuplicateAddAnyway}
        />
      ) : null}
      {toast ? (
        <Layer>
          <Box position="fixed" bottom left right display="flex" justifyContent="center" padding={4}>
            <Toast type={toast.type === 'error' ? 'error' : 'success'} text={toast.message} />
          </Box>
        </Layer>
      ) : null}
    </Box>
  );
}
