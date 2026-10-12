import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Button,
  ButtonToggle,
  Flex,
  IconButton,
  Layer,
  Link,
  Modal,
  PageHeader,
  SelectList,
  Table,
  Text,
  TextField,
} from 'gestalt';
import { fetchBoard, intakeJob, moveJobStatus, promoteJob, retryIngest } from '../api/jobs.js';
import KanbanBoard from '../components/KanbanBoard.jsx';
import JobCard, { CompanyDisplay, IngestIndicator } from '../components/JobCard.jsx';
import FloatingMessage from '../components/Message.jsx';
import AddJobPopupShell from '../components/AddJobPopupShell.jsx';

const VIEW_KEY = 'careerJobsView';
const NEEDS_ATTENTION_KEY = 'careerNeedsAttention';
const LIST_COLUMNS = ['Title', 'Company', 'Source', 'Status', 'Location', 'Posted', 'Added'];
const AUTO_REFRESH_AFTER_MS = 30000;
// Success toasts auto-hide; error messages stay until the user dismisses
// them (owner decision, Message README).
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

// List view is untouched by this rebuild (JOZ-278 is board-only).
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
  const [toasts, setToasts] = useState([]);
  const [intakeUrl, setIntakeUrl] = useState('');
  const [intakeBusy, setIntakeBusy] = useState(false);
  const [intakeError, setIntakeError] = useState(null);
  const [duplicate, setDuplicate] = useState(null);
  const [addPopupOpen, setAddPopupOpen] = useState(false);
  const [dragId, setDragId] = useState(null);
  const [overColumn, setOverColumn] = useState(null);
  const moveGenerationRef = useRef({});
  const toastIdRef = useRef(0);

  // One success toast auto-hides on its own timer; an error toast has none
  // and sits until dismissed. Toasts are a list, not a single slot, so a
  // success elsewhere can never replace (and silently clear) an outstanding
  // error - they just stack in the same fixed bottom-centre container.
  function showToast(kind, text, action) {
    const id = ++toastIdRef.current;
    const entry = { id, kind, text, ...action };
    if (entry.onAction) {
      const fire = entry.onAction;
      entry.onAction = () => {
        dismissToast(id);
        fire();
      };
    }
    setToasts((prev) => [...prev, entry]);
    if (kind !== 'error') {
      window.setTimeout(() => dismissToast(id), TOAST_LIFETIME_MS);
    }
  }

  function dismissToast(id) {
    setToasts((prev) => prev.filter((entry) => entry.id !== id));
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

  // Re-slots one card into `toStatus`, inserting it ahead of `beforeId` (or
  // at the end of that column when `beforeId` is null/absent/gone). Used
  // both for the live move and for rolling a single card back later -
  // always against whatever `entries` is current at that moment, never a
  // frozen whole-board snapshot, so an unrelated card's move in between is
  // never clobbered.
  function reorderEntries(entries, id, toStatus, beforeId) {
    const movingJob = entries.find((job) => job.id === id);
    if (!movingJob) return entries;
    const withoutMoving = entries.filter((job) => job.id !== id);
    const insertAt = beforeId ? withoutMoving.findIndex((job) => job.id === beforeId) : -1;
    const updatedJob = movingJob.status === toStatus ? movingJob : { ...movingJob, status: toStatus };
    return insertAt === -1
      ? [...withoutMoving, updatedJob]
      : [...withoutMoving.slice(0, insertAt), updatedJob, ...withoutMoving.slice(insertAt)];
  }

  // The id of the card immediately after `id` within its own column (or
  // null if it is last/not found), captured so a later rollback can put it
  // back in the same slot rather than just the same column.
  function nextInColumn(entries, id, status) {
    const columnEntries = entries.filter((job) => job.status === status);
    const ownIndex = columnEntries.findIndex((job) => job.id === id);
    if (ownIndex === -1 || ownIndex === columnEntries.length - 1) return null;
    return columnEntries[ownIndex + 1].id;
  }

  // Shared by the status dropdown and drag-and-drop (StatusSelect README:
  // "Changing it moves the card to that column", same handler as drag).
  // beforeId reorders within/into a column by inserting ahead of that card;
  // null appends to the end. A same-column move is a pure client-side
  // reorder (no backend concept of card position); a cross-column move is
  // the real status mutation, with a per-job generation counter so an
  // older failed request cannot roll back a newer successful one. Rollback
  // (on failure, or via Undo) only ever touches this one card's slot, via
  // reorderEntries against the latest board state, so a different card's
  // move that lands in between is never reverted by this one.
  function performMove(id, toStatus, beforeId) {
    if (!board) return;
    const current = board.entries;
    const movingJob = current.find((job) => job.id === id);
    if (!movingJob || id === beforeId) return;
    const fromStatus = movingJob.status;
    const originalBeforeId = nextInColumn(current, id, fromStatus);
    const nextEntries = reorderEntries(current, id, toStatus, beforeId);

    if (fromStatus === toStatus) {
      setBoard((prev) => ({ ...prev, entries: nextEntries }));
      return;
    }

    const generation = (moveGenerationRef.current[id] || 0) + 1;
    moveGenerationRef.current[id] = generation;
    setBoard((prev) => ({ ...prev, entries: nextEntries }));

    moveJobStatus(id, toStatus)
      .then(() => {
        if (moveGenerationRef.current[id] !== generation) return;
        showToast('success', `Moved to ${titleCase(toStatus)}`, {
          actionLabel: 'Undo',
          onAction: () => undoMove(id, generation, fromStatus, toStatus, originalBeforeId),
        });
      })
      .catch((err) => {
        if (moveGenerationRef.current[id] === generation) {
          setBoard((prev) => ({ ...prev, entries: reorderEntries(prev.entries, id, fromStatus, originalBeforeId) }));
        }
        showToast('error', err.message);
      });
  }

  function undoMove(id, generation, previousStatus, movedStatus, originalBeforeId) {
    if (moveGenerationRef.current[id] !== generation) return;
    const undoGeneration = generation + 1;
    moveGenerationRef.current[id] = undoGeneration;

    // Captured from inside the same functional update that performs the
    // rollback, so it reflects the card's actual slot at undo-time (not a
    // stale closure), for the failure branch below to restore it to.
    const movedBeforeId = { current: null };
    setBoard((prev) => {
      movedBeforeId.current = nextInColumn(prev.entries, id, movedStatus);
      return { ...prev, entries: reorderEntries(prev.entries, id, previousStatus, originalBeforeId) };
    });

    moveJobStatus(id, previousStatus).catch((err) => {
      // The Undo PUT failed: the server kept the moved-to status even
      // though we already rolled the card back visually above. Only
      // reconcile to that moved state if no newer move has touched this
      // card since the Undo started - otherwise the card's generation has
      // already moved on (e.g. a second drag while the Undo was in
      // flight) and restoring movedStatus here would clobber that newer,
      // already-confirmed move with stale data.
      if (moveGenerationRef.current[id] === undoGeneration) {
        setBoard((prev) => ({ ...prev, entries: reorderEntries(prev.entries, id, movedStatus, movedBeforeId.current) }));
      }
      showToast('error', err.message);
    });
  }

  function handleMove(id, status) {
    performMove(id, status, null);
  }

  function cardDragHandlers(job) {
    return {
      onDragStart: (event) => {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', job.id);
        setDragId(job.id);
      },
      onDragEnd: () => {
        setDragId(null);
        setOverColumn(null);
      },
      onDragOver: (event) => event.preventDefault(),
      onDrop: (event) => {
        event.preventDefault();
        event.stopPropagation();
        const id = event.dataTransfer.getData('text/plain') || dragId;
        if (id) performMove(id, job.status, job.id);
        setDragId(null);
        setOverColumn(null);
      },
    };
  }

  function columnDragHandlers(status) {
    return {
      onDragOver: (event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        if (overColumn !== status) setOverColumn(status);
      },
      onDrop: (event) => {
        event.preventDefault();
        const id = event.dataTransfer.getData('text/plain') || dragId;
        if (id) performMove(id, status, null);
        setDragId(null);
        setOverColumn(null);
      },
    };
  }

  async function handleRetry(id) {
    try {
      await retryIngest(id);
      await load();
      showToast('success', 'Retry started');
    } catch (err) {
      showToast('error', err.message);
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
      showToast('success', 'Job added');
    } catch (err) {
      setIntakeError({ message: err.message, url: trimmed, force });
      showToast('error', err.message);
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
      showToast('success', 'Promoted to pipeline');
    } catch (err) {
      showToast('error', err.message);
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

  const columns = board.statuses.map((status) => {
    const entries = filteredEntries.filter((job) => job.status === status);
    return {
      status,
      title: titleCase(status),
      count: entries.length,
      isEmpty: entries.length === 0,
      isOver: overColumn === status,
      ...columnDragHandlers(status),
      children: entries.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          statuses={board.statuses}
          functionLabels={functionLabels}
          onMove={handleMove}
          onRetry={handleRetry}
          dragHandlers={cardDragHandlers(job)}
          isDragging={dragId === job.id}
        />
      )),
    };
  });

  return (
    <Box padding={6}>
      <PageHeader title="Jobs" />
      {/* PageHeader's own items slot is `display: none` below the md
          breakpoint (gestalt/src/PageHeader/components.tsx
          PageHeaderItemsBlock), so Board/List lived there would be
          unreachable on mobile and the mobile list-rows fix would be moot.
          This row has no such hiding and stays visible at every width. */}
      <Box marginTop={3} marginBottom={3}>
        <Flex gap={2} alignItems="center">
          <IconButton
            accessibilityLabel="Add a job"
            accessibilityPopupRole="dialog"
            icon="add"
            bgColor="red"
            size="lg"
            onClick={() => setAddPopupOpen(true)}
          />
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
        <KanbanBoard columns={columns} />
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
      {addPopupOpen ? <AddJobPopupShell onDismiss={() => setAddPopupOpen(false)} /> : null}
      {toasts.length ? (
        <Layer>
          <Box position="fixed" bottom left right display="flex" justifyContent="center" padding={4}>
            <Box width={560} maxWidth="100%">
              <Flex direction="column" gap={2}>
                {toasts.map((entry) => (
                  <FloatingMessage
                    key={entry.id}
                    kind={entry.kind}
                    text={entry.text}
                    actionLabel={entry.actionLabel}
                    onAction={entry.onAction}
                    onDismiss={() => dismissToast(entry.id)}
                  />
                ))}
              </Flex>
            </Box>
          </Box>
        </Layer>
      ) : null}
    </Box>
  );
}
