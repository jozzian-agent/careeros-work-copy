import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Button,
  DeviceTypeProvider,
  Flex,
  Layer,
  Link,
  Modal,
  SelectList,
  Table,
  Text,
} from 'gestalt';
import { FormattedMessage, useIntl } from 'react-intl';
import { fetchBoard, intakeJob, moveJobStatus, promoteJob, retryIngest, updateJob } from '../api/jobs.js';
import { createNote } from '../api/notes.js';
import KanbanBoard from '../components/KanbanBoard.jsx';
import JobCard, { CompanyDisplay, IngestIndicator } from '../components/JobCard.jsx';
import FloatingMessage from '../components/Message.jsx';
import AddJobPopup from '../components/AddJobPopup.jsx';
import FilterBar from '../components/FilterBar.jsx';
import FilterChip from '../components/FilterChip.jsx';
import SegmentedControl from '../components/SegmentedControl.jsx';
import PageLayout from '../components/PageLayout.jsx';
import { EndingChooser, ReasonPopup, WonConfirm } from '../components/EndJobFlow.jsx';
import { ClosedPostingsBanner, ClosedPostingsReview } from '../components/ClosedPostings.jsx';
import SortableHeaderCell from '../components/SortableHeaderCell.jsx';
import { usePhoneLayout } from '../layout.js';
import { sessionEnded } from '../api/client.js';
import { anyReading } from '../aiStatus.js';
import {
  EMPTY_JOB_FILTERS,
  JOB_FILTER_GROUPS,
  filterJobs,
  jobFilterOptions,
  titleCase,
} from '../jobFilters.js';

const VIEW_KEY = 'careerJobsView';
const NEEDS_ATTENTION_KEY = 'careerNeedsAttention';
// Which closed-posting rows the owner has said "Not now" to. The ids, not a
// single hidden flag, because the banner comes back when ANOTHER job
// crosses the week (D7), and only the ids can tell those two apart.
const CLOSED_DISMISSED_KEY = 'careerClosedReviewDismissed';
const AUTO_REFRESH_AFTER_MS = 30000;
// CAREER-37: while any job on the board still has a reading owed, the
// board asks again at this interval. It stops on its own the moment none
// is left, so a settled board polls nothing.
const AI_POLL_MS = 5000;
// Success toasts auto-hide; error messages stay until the user dismisses
// them (owner decision, Message README).
const TOAST_LIFETIME_MS = 4000;

function looksLikeUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

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

function readDismissedClosed() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(CLOSED_DISMISSED_KEY) || '[]');
    return Array.isArray(stored) ? stored.filter((id) => typeof id === 'string') : [];
  } catch {
    return [];
  }
}

// The day the owner kept a closed posting, in the YYYY-MM-DD the vault
// stores. Local date parts, not toISOString(), which would shift the day
// backwards for anyone east of UTC late in the evening.
function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

// The statuses the closed-postings banner asks about: everything before
// Applied, matching the backend's BEFORE_APPLIED, derived from the payload
// order rather than repeated here so the two cannot drift apart.
function beforeAppliedStatuses(board) {
  const at = board.statuses.indexOf('applied');
  return at < 0 ? board.statuses : board.statuses.slice(0, at);
}

// True while a job in this status is still one the banner asks about.
function isBeforeApplied(board, status) {
  return beforeAppliedStatuses(board).includes(status);
}

// Take a job out of the review list, the way a move to Applied-or-later or
// an ending takes it out of what the banner asks about, so the warning chip
// turns neutral straight away instead of after a reload.
function pruneClosedReview(board, id) {
  return (board.closed_review || []).filter((row) => row.id !== id);
}

// Put a review row back after a failed write or an Undo, in payload order
// (the backend emits rows in entry order, so re-sorting by the entries list
// keeps the two agreeing). Missing row means nothing to restore.
function restoreClosedReview(board, row) {
  if (!row) return board.closed_review;
  const rows = pruneClosedReview(board, row.id);
  const position = board.entries.findIndex((entry) => entry.id === row.id);
  const after = rows.findIndex((candidate) => {
    const at = board.entries.findIndex((entry) => entry.id === candidate.id);
    return at > position;
  });
  rows.splice(after < 0 ? rows.length : after, 0, row);
  return rows;
}

function jobHref(id) {
  return `/jobs/${encodeURIComponent(id)}`;
}

// `column` indexes the list view's own columns, in the order ListView
// below builds them (title, company, source, status, location, posted,
// added). The two lists are read together and must stay in step.
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

// List view is untouched by the board rebuilds (JOZ-278 and D7 are both
// board-only), apart from reading the status words from the payload the
// way every other surface now does.
function ListView({ entries, statusLabels, onRetry }) {
  const { formatMessage } = useIntl();
  const [sortColumn, setSortColumn] = useState(null);
  const [ascending, setAscending] = useState(true);
  const sorted = useMemo(() => sortEntries(entries, sortColumn, ascending), [entries, sortColumn, ascending]);
  // The columns in order, which is also the order sortEntries() reads its
  // fields in. Every id is a literal, so scripts/check_i18n.py can see
  // which catalog keys this file uses.
  const columns = useMemo(
    () => [
      formatMessage({ id: 'board.list.column.title' }),
      formatMessage({ id: 'board.list.column.company' }),
      formatMessage({ id: 'board.list.column.source' }),
      formatMessage({ id: 'board.list.column.status' }),
      formatMessage({ id: 'board.list.column.location' }),
      formatMessage({ id: 'board.list.column.posted' }),
      formatMessage({ id: 'board.list.column.added' }),
    ],
    [formatMessage],
  );

  function sortBy(column, direction) {
    setSortColumn(column);
    setAscending(direction);
  }

  return (
    <Box>
      <Box display="block" mdDisplay="none" marginBottom={3} maxWidth={280}>
        <SelectList
          id="job-sort"
          label={formatMessage({ id: 'board.list.sortBy' })}
          placeholder={formatMessage({ id: 'board.list.sortPlaceholder' })}
          value={sortColumn === null ? null : `${sortColumn}:${ascending ? 'asc' : 'desc'}`}
          onChange={({ value }) => {
            const [column, direction] = value.split(':');
            sortBy(Number(column), direction === 'asc');
          }}
        >
          {columns.flatMap((label, index) => [
            <SelectList.Option
              key={`${index}-asc`}
              label={formatMessage({ id: 'board.list.sortAscending' }, { column: label })}
              value={`${index}:asc`}
            />,
            <SelectList.Option
              key={`${index}-desc`}
              label={formatMessage({ id: 'board.list.sortDescending' }, { column: label })}
              value={`${index}:desc`}
            />,
          ])}
        </SelectList>
      </Box>
      <Box overflow="auto">
        <Table accessibilityLabel={formatMessage({ id: 'board.list.tableLabel' })}>
          <Table.Header>
            <Table.Row>
              {columns.map((label, index) => (
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
                    <Text>{statusLabels[job.status] || titleCase(job.status)}</Text>
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
  const { formatMessage } = useIntl();
  const basisText =
    duplicate.basis === 'same_ats_posting_id'
      ? formatMessage({ id: 'board.duplicate.basisPostingId' })
      : formatMessage({ id: 'board.duplicate.basisUrl' });
  return (
    <Modal
      accessibilityModalLabel={formatMessage({ id: 'board.duplicate.modalLabel' })}
      heading={formatMessage({ id: 'board.duplicate.heading' })}
      onDismiss={onCancel}
      footer={
        <Flex gap={2} justifyContent="end" wrap>
          {duplicate.actions.includes('open_existing') ? (
            <Button text={formatMessage({ id: 'board.duplicate.openExisting' })} onClick={onOpenExisting} />
          ) : null}
          {duplicate.actions.includes('promote') ? (
            <Button text={formatMessage({ id: 'board.duplicate.promote' })} onClick={onPromote} />
          ) : null}
          {duplicate.actions.includes('add_anyway') ? (
            <Button color="red" text={formatMessage({ id: 'board.duplicate.addAnyway' })} onClick={onAddAnyway} />
          ) : null}
          <Button text={formatMessage({ id: 'board.duplicate.cancel' })} onClick={onCancel} />
        </Flex>
      }
    >
      <Text>
        <FormattedMessage
          id="board.duplicate.body"
          values={{ title: duplicate.existing.title, basis: basisText }}
        />
      </Text>
    </Modal>
  );
}

export default function JobsBoard() {
  const { formatMessage } = useIntl();
  const [board, setBoard] = useState(null);
  const [loadError, setLoadError] = useState(null);
  // Counts polls attempted, not boards received: see the polling effect.
  const [pollTick, setPollTick] = useState(0);
  const [view, setView] = useState(readStoredView);
  const [needsAttention, setNeedsAttention] = useState(readStoredNeedsAttention);
  // Deliberately not remembered: the brief has "Hide closed postings" off
  // by default and the Ended lane collapsed on every load, so neither is
  // stored and a reload always starts from the same board. Remembering the
  // lane is on the brief's own deferred list.
  const [hideClosed, setHideClosed] = useState(false);
  const [laneExpanded, setLaneExpanded] = useState(false);
  const [filters, setFilters] = useState(EMPTY_JOB_FILTERS);
  const [toasts, setToasts] = useState([]);
  const [intakeUrl, setIntakeUrl] = useState('');
  const [intakeBusy, setIntakeBusy] = useState(false);
  const [intakeError, setIntakeError] = useState(null);
  const [duplicate, setDuplicate] = useState(null);
  const [addPopupOpen, setAddPopupOpen] = useState(false);
  const [dragId, setDragId] = useState(null);
  const [overColumn, setOverColumn] = useState(null);
  const [chooserFor, setChooserFor] = useState(null);
  const [wonFor, setWonFor] = useState(null);
  // The job id, not the record: the popup must read the status the job
  // has NOW (the ending move already landed), not the one it had when
  // the message that offers the reason was created.
  const [reasonForId, setReasonForId] = useState(null);
  const [reasonBusy, setReasonBusy] = useState(false);
  const [reasonError, setReasonError] = useState(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(null);
  const [dismissedClosed, setDismissedClosed] = useState(readDismissedClosed);
  const [phoneStatus, setPhoneStatus] = useState(null);
  const moveGenerationRef = useRef({});
  // Closed-postings review rows removed by an optimistic move, keyed by job
  // id, so a failed write or an Undo restores the exact row the payload
  // carried (days_closed included) without a reload.
  const closedRowRef = useRef({});
  const toastIdRef = useRef(0);
  const isPhone = usePhoneLayout();

  // One success toast auto-hides on its own timer; an error toast has none
  // and sits until dismissed. Toasts are a list, not a single slot, so a
  // success elsewhere can never replace (and silently clear) an outstanding
  // error - they just stack in the same fixed bottom-centre container.
  // Either action dismisses its own message first, so pressing Undo or
  // "Add a reason" never leaves a stale message behind the popup it opens.
  function showToast(kind, text, action) {
    const id = ++toastIdRef.current;
    const entry = { id, kind, text, ...action };
    ['onAction', 'onSecondaryAction'].forEach((key) => {
      if (!entry[key]) return;
      const fire = entry[key];
      entry[key] = () => {
        dismissToast(id);
        fire();
      };
    });
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

  // CAREER-37: the AI work runs off the request path, so the only way the
  // board learns a reading finished is to ask. It asks every five seconds
  // while at least one job is queued or running, and the effect simply
  // does not re-arm once none is, which is how the polling ends itself.
  //
  // The tick is what re-arms it, and the board on its own could not: a
  // poll whose fetch failed leaves the board exactly as it was, so the
  // effect never re-ran and the polling stopped for good on one bad
  // response, with the chip left saying running forever (fix round C4).
  // Counting the attempt rather than the result means a transient
  // failure costs one interval and nothing more, and no failure can
  // schedule a second timer: the effect holds one at a time.
  //
  // M1: counting the attempt is also what made a lost session expensive.
  // A 401 is not a transient failure -- every later ask gets the same
  // answer -- so the loop re-arming on it would be a request storm aimed
  // at a server that has already said no. The session check ends the loop
  // instead, while the api client takes the browser to the login page.
  useEffect(() => {
    if (!board || sessionEnded() || !anyReading(board.entries)) return undefined;
    const timer = window.setTimeout(() => {
      load().finally(() => setPollTick((previous) => previous + 1));
    }, AI_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [board, pollTick]);

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

  function toggleFilterValue(group, value) {
    setFilters((current) => {
      const values = current[group];
      const next = values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
      return { ...current, [group]: next };
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

  // Re-slots one card into `toStatus`, inserting it ahead of `beforeId` (or
  // at the end of that column when `beforeId` is null/absent/gone). Used
  // both for the live move and for rolling a single card back later -
  // always against whatever `entries` is current at that moment, never a
  // frozen whole-board snapshot, so an unrelated card's move in between is
  // never clobbered.
  function reorderEntries(entries, id, toStatus, beforeId, fields) {
    const movingJob = entries.find((job) => job.id === id);
    if (!movingJob) return entries;
    const withoutMoving = entries.filter((job) => job.id !== id);
    const insertAt = beforeId ? withoutMoving.findIndex((job) => job.id === beforeId) : -1;
    const changed = movingJob.status !== toStatus || fields;
    const updatedJob = changed ? { ...movingJob, status: toStatus, ...(fields || {}) } : movingJob;
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

  // The word a status is shown as, from the payload (vault.STATUS_LABELS).
  // Nothing on this page title-cases a status id of its own accord any
  // more; titleCase is only the fallback for a payload that predates the
  // key.
  function statusLabel(status) {
    return (board?.status_labels || {})[status] || titleCase(status);
  }

  // The reasons a status offers, from the payload. An empty list means the
  // outcome has no vocabulary (Won has none), and nothing then offers to
  // add a reason for it: the popup exists to pick one of these words.
  function reasonSuggestions(status) {
    return (board?.end_reasons || {})[status] || [];
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
  //
  // D7: `fields` rides along in the same PUT (the review popup's Stop sends
  // the reason with the move), and a move into a status that has reason
  // suggestions offers "Add a reason" beside Undo, because that is the
  // moment the owner knows why.
  function performMove(id, toStatus, beforeId, fields) {
    if (!board) return;
    const current = board.entries;
    const movingJob = current.find((job) => job.id === id);
    if (!movingJob || id === beforeId) return;
    const fromStatus = movingJob.status;
    const originalBeforeId = nextInColumn(current, id, fromStatus);
    // What those extra fields were before, so a rollback restores the
    // record the owner actually had rather than leaving half of a move
    // behind on the card.
    const revertFields = fields
      ? Object.fromEntries(Object.keys(fields).map((key) => [key, movingJob[key] ?? null]))
      : undefined;
    const nextEntries = reorderEntries(current, id, toStatus, beforeId, fields);

    if (fromStatus === toStatus) {
      setBoard((prev) => ({ ...prev, entries: nextEntries }));
      return;
    }

    const generation = (moveGenerationRef.current[id] || 0) + 1;
    moveGenerationRef.current[id] = generation;
    // A move out of a before-Applied status (to Applied or later, or to an
    // ending) takes the job out of what the closed-postings banner asks
    // about, so its review row goes with the move, straight away, and the
    // card's warning chip turns neutral. The row is kept in a ref so a
    // failed write or an Undo can put it back exactly as it was.
    const closedRow = (board.closed_review || []).find((row) => row.id === id);
    const keepsRow = isBeforeApplied(board, toStatus);
    if (closedRow && !keepsRow) {
      closedRowRef.current[id] = closedRow;
    }
    setBoard((prev) => ({
      ...prev,
      entries: nextEntries,
      closed_review: keepsRow ? prev.closed_review : pruneClosedReview(prev, id),
    }));

    moveJobStatus(id, toStatus, fields)
      .then(() => {
        if (moveGenerationRef.current[id] !== generation) return;
        const canExplain = reasonSuggestions(toStatus).length > 0;
        showToast('success', formatMessage({ id: 'board.toast.movedTo' }, { status: statusLabel(toStatus) }), {
          actionLabel: formatMessage({ id: 'board.toast.undo' }),
          onAction: () => undoMove(id, generation, fromStatus, toStatus, originalBeforeId, fields),
          secondaryLabel: canExplain ? formatMessage({ id: 'board.toast.addReason' }) : undefined,
          onSecondaryAction: canExplain ? () => openReason(id) : undefined,
        });
      })
      .catch((err) => {
        if (moveGenerationRef.current[id] === generation) {
          setBoard((prev) => ({
            ...prev,
            entries: reorderEntries(prev.entries, id, fromStatus, originalBeforeId, revertFields),
            closed_review: restoreClosedReview(prev, closedRowRef.current[id]),
          }));
          delete closedRowRef.current[id];
        }
        showToast('error', err.message);
      });
  }

  function undoMove(id, generation, previousStatus, movedStatus, originalBeforeId, movedFields) {
    if (moveGenerationRef.current[id] !== generation) return;
    const undoGeneration = generation + 1;
    moveGenerationRef.current[id] = undoGeneration;

    // Captured from inside the same functional update that performs the
    // rollback, so it reflects the card's actual slot at undo-time (not a
    // stale closure), for the failure branch below to restore it to.
    const movedBeforeId = { current: null };
    // An undone ending keeps the reason it was given: the record keeps what
    // the owner said rather than being rewritten behind them (D7, and
    // docs/surfaces/jobs.md), and the Undo PUT sends the status alone, so
    // the card must not clear end_reason locally either or the two would
    // disagree until a reload. The review row comes back with it: the job
    // is before Applied, closed and unkept again, exactly what the banner
    // asks about.
    const restoredRow = closedRowRef.current[id];
    delete closedRowRef.current[id];
    setBoard((prev) => {
      movedBeforeId.current = nextInColumn(prev.entries, id, movedStatus);
      return {
        ...prev,
        entries: reorderEntries(prev.entries, id, previousStatus, originalBeforeId),
        closed_review: restoreClosedReview(prev, restoredRow),
      };
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
        setBoard((prev) => ({
          ...prev,
          entries: reorderEntries(prev.entries, id, movedStatus, movedBeforeId.current, movedFields),
          // The server kept the ended status, so the job really is out of
          // what the banner asks about: the review row this Undo restored
          // goes again with the card.
          closed_review: pruneClosedReview(prev, id),
        }));
      }
      showToast('error', err.message);
    });
  }

  // Every route into an ended status runs through here: the status select,
  // a drop on one of the lane's groups, and the chooser the collapsed lane
  // opens. Won asks first and the other two move at once, because Won is
  // the one outcome the owner cannot take back in their own head (D7).
  function requestEnd(id, status) {
    const job = board.entries.find((entry) => entry.id === id);
    if (!job) return;
    if (status === 'won') {
      setWonFor(job);
      return;
    }
    performMove(id, status, null);
  }

  function handleMove(id, status) {
    if ((board.ended_statuses || []).includes(status)) {
      requestEnd(id, status);
      return;
    }
    performMove(id, status, null);
  }

  function openReason(id) {
    setReasonError(null);
    setReasonForId(id);
  }

  // Save writes at most two things, and only what the owner actually gave:
  // the picked suggestion through the ordinary job PUT, and the free text
  // as a dated note under the title the payload names. Skip writes nothing
  // at all, so a job never waits for a reason (D7).
  async function saveReason({ reason, note }) {
    const job = board.entries.find((entry) => entry.id === reasonForId);
    if (!job) return;
    setReasonBusy(true);
    setReasonError(null);
    try {
      if (reason && reason !== job.end_reason) {
        await updateJob(job.id, { end_reason: reason });
      }
      if (note) {
        await createNote('jobs', job.id, { title: board.end_note_title, body: note });
      }
      // The reason lands on the one card that shows it, rather than through
      // a whole-board reload: a reload here would throw away any other
      // card's in-flight optimistic move, which is the bug class the board
      // was already fixed for once (PROJECT.md 2026-10-12).
      setBoard((prev) => ({
        ...prev,
        entries: prev.entries.map((entry) =>
          entry.id === job.id ? { ...entry, end_reason: reason || entry.end_reason } : entry,
        ),
      }));
      setReasonForId(null);
      showToast('success', formatMessage({ id: 'board.toast.reasonSaved' }));
    } catch (err) {
      setReasonError(err.message);
    } finally {
      setReasonBusy(false);
    }
  }

  // Keep marks the job reviewed, which is what takes it out of
  // closed_review and turns its warning chip back into the neutral one.
  // The flag itself is left alone, because the posting really is gone. The
  // row goes straight away rather than after a reload, the same way a move
  // lands straight away, and comes back if the write fails.
  async function keepClosed(job) {
    const row = (board.closed_review || []).find((entry) => entry.id === job.id);
    const reviewed = today();
    setReviewBusy(job.id);
    setBoard((prev) => ({
      ...prev,
      closed_review: (prev.closed_review || []).filter((entry) => entry.id !== job.id),
      entries: prev.entries.map((entry) => (entry.id === job.id ? { ...entry, closed_reviewed_at: reviewed } : entry)),
    }));
    try {
      await updateJob(job.id, { closed_reviewed_at: reviewed });
      showToast('success', formatMessage({ id: 'board.toast.keeping' }, { title: job.title }));
    } catch (err) {
      setBoard((prev) => ({
        ...prev,
        closed_review: row ? [...(prev.closed_review || []), row] : prev.closed_review,
        entries: prev.entries.map((entry) =>
          entry.id === job.id ? { ...entry, closed_reviewed_at: job.closed_reviewed_at } : entry,
        ),
      }));
      showToast('error', err.message);
    } finally {
      setReviewBusy(null);
    }
  }

  // Stop is the ordinary ending move with the reason already known, sent in
  // the same PUT, and it can be changed later like any other. The review
  // row leaves with the move (performMove prunes it, because an ended job
  // is no longer one the owner has not applied to) and comes back if the
  // write fails or the owner undoes.
  function stopClosed(job) {
    performMove(job.id, 'stopped', null, { end_reason: 'Posting closed' });
  }

  // "Not now" hides the banner for the jobs it is asking about today, and
  // for those only: a job that crosses the week later is not in this list,
  // so the banner comes back for it (D7).
  function dismissClosedReview() {
    const ids = (board.closed_review || []).map((row) => row.id);
    setDismissedClosed(ids);
    try {
      window.localStorage.setItem(CLOSED_DISMISSED_KEY, JSON.stringify(ids));
    } catch {
      // localStorage unavailable; the banner will just come back next load.
    }
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

  // A drop on the collapsed strip does not say which outcome it was, so it
  // opens the chooser at the strip; a drop on one of the expanded lane's
  // groups does, so it ends the job there and then (D7).
  const laneDragHandlers = {
    onDragOver: (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      if (overColumn !== 'ended') setOverColumn('ended');
    },
    onDrop: (event) => {
      event.preventDefault();
      // The strip itself is the chooser's anchor, read here rather than
      // from a ref during render: this IS the element the card was dropped
      // on, which is as close to the drop point as a Popover can be
      // anchored.
      const anchor = event.currentTarget;
      const id = event.dataTransfer.getData('text/plain') || dragId;
      setDragId(null);
      setOverColumn(null);
      const job = id ? board.entries.find((entry) => entry.id === id) : null;
      setChooserFor(job ? { job, anchor } : null);
    },
  };

  function endedGroupDragHandlers(status) {
    return {
      onDragOver: (event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        if (overColumn !== `ended-${status}`) setOverColumn(`ended-${status}`);
      },
      onDrop: (event) => {
        event.preventDefault();
        event.stopPropagation();
        const id = event.dataTransfer.getData('text/plain') || dragId;
        setDragId(null);
        setOverColumn(null);
        if (id) requestEnd(id, status);
      },
    };
  }

  async function handleRetry(id) {
    try {
      await retryIngest(id);
      await load();
      showToast('success', formatMessage({ id: 'board.toast.retryStarted' }));
    } catch (err) {
      showToast('error', err.message);
    }
  }

  // Shared by every path that calls the intake endpoint: the add-job
  // popup's own submit/retry, and the duplicate dialog's Promote/Add
  // anyway actions. A duplicate whose existing job is already on the
  // board (in_pipeline !== false) is handled inside the popup itself (its
  // "already on your board" state); one that is only in the shared
  // universe (in_pipeline: false, eligible for promotion) closes the
  // popup and hands off to the separate duplicate dialog, since that
  // flow needs more actions than the popup's single primary button.
  async function submitIntake(url, { force = false } = {}) {
    if (!force && !looksLikeUrl(url)) {
      setDuplicate(null);
      setIntakeError({ kind: 'not_link' });
      return;
    }
    setIntakeError(null);
    setIntakeBusy(true);
    try {
      const result = await intakeJob(url, { force });
      if (result?.duplicate) {
        setDuplicate({ ...result, url });
        if (result.existing.in_pipeline === false) setAddPopupOpen(false);
        return;
      }
      // careeros/server.py job_intake() still returns 201 when the stub
      // saved fine but the fetch/extract itself failed (ingest_state
      // fetch_failed/extract_failed): that is a real read failure, not a
      // success, even though the HTTP request succeeded. The job id is
      // already durable, so the retry path is the extraction endpoint for
      // that record, never a second intake (which would just dedup).
      const ingestState = result?.job?.ingest_state;
      if (ingestState === 'fetch_failed' || ingestState === 'extract_failed') {
        setDuplicate(null);
        setIntakeError({
          kind: 'ingest_failed',
          message: formatMessage({ id: 'board.couldNotRead' }),
          jobId: result.job.id,
        });
        await load();
        return;
      }
      setDuplicate(null);
      setIntakeUrl('');
      setAddPopupOpen(false);
      await load();
      showToast('success', formatMessage({ id: 'board.toast.addedToNew' }));
    } catch (err) {
      // A 503 from job_intake() (extraction could not start) still saved the
      // stub, carried here as err.jobId (frontend/src/api/jobs.js). That
      // record is already durable, so this is the same saved-job retry path
      // as the 201-failed-ingest branch above, never a second intake call.
      if (err.jobId) {
        setDuplicate(null);
        setIntakeError({
          kind: 'ingest_failed',
          message: formatMessage({ id: 'board.couldNotRead' }),
          jobId: err.jobId,
        });
        await load();
        return;
      }
      setIntakeError({ kind: 'failed', message: err.message, url, force });
    } finally {
      setIntakeBusy(false);
    }
  }

  // Retries a job that intake already saved but could not read, via the
  // extraction endpoint for that specific record (not a second intake
  // call). Fire-and-forget, same as the board's own per-card ingest
  // retry (handleRetry): the worker runs in the background, so the popup
  // closes and the board's own ingest badge/retry affordance picks up
  // from there.
  async function retrySavedIngest(jobId) {
    setIntakeError(null);
    setIntakeBusy(true);
    try {
      await retryIngest(jobId);
      setDuplicate(null);
      setIntakeUrl('');
      setAddPopupOpen(false);
      await load();
      showToast('success', formatMessage({ id: 'board.toast.retryStarted' }));
    } catch (err) {
      setIntakeError({ kind: 'ingest_failed', message: err.message, jobId });
    } finally {
      setIntakeBusy(false);
    }
  }

  function handleAddJobPrimary() {
    if (intakeError?.kind === 'ingest_failed') {
      retrySavedIngest(intakeError.jobId);
      return;
    }
    const trimmed = intakeUrl.trim();
    if (!trimmed) return;
    const force = intakeError?.kind === 'failed' ? Boolean(intakeError.force) : false;
    submitIntake(trimmed, { force });
  }

  // Edited text always wins (never lost on dismiss), but any stale
  // duplicate/error/force state from a previous URL must not survive the
  // edit: otherwise "Show job"/"Add anyway" would still act on the old
  // duplicate, and a retry would keep resubmitting with the old force
  // flag against a URL the owner has since changed.
  function handleIntakeUrlChange(value) {
    setIntakeUrl(value);
    if (duplicate || intakeError) {
      setDuplicate(null);
      setIntakeError(null);
    }
  }

  function handleAddJobDismiss() {
    // Deliberately does not reset intakeUrl/intakeError/duplicate: closing
    // never loses typed text or an in-progress state silently (README).
    setAddPopupOpen(false);
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
      showToast('success', formatMessage({ id: 'board.toast.promoted' }));
    } catch (err) {
      showToast('error', err.message);
    }
  }

  // Shared by the popup's own "Add anyway" (popup already open) and the
  // separate DuplicateDialog's (off-board duplicate, popup already
  // closed per submitIntake above). Always runs the forced add through
  // the popup's reading/error flow, so a failure here is visible the
  // same way any other intake failure is, rather than closing every
  // dialog and leaving only a silent intakeError behind.
  function handleDuplicateAddAnyway() {
    const url = duplicate.url;
    setDuplicate(null);
    setIntakeUrl(url);
    setAddPopupOpen(true);
    submitIntake(url, { force: true });
  }

  const optionsByGroup = useMemo(() => jobFilterOptions(board), [board]);

  const filteredEntries = useMemo(
    () => (board ? filterJobs(board.entries, filters, { needsAttention, hideClosed }) : []),
    [board, filters, needsAttention, hideClosed],
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

  if (!board) {
    return (
      <Box padding={6}>
        <Text>
          <FormattedMessage id="common.jobs.loading" />
        </Text>
      </Box>
    );
  }

  const endedStatuses = board.ended_statuses || [];
  const reasonJob = reasonForId ? board.entries.find((entry) => entry.id === reasonForId) : null;
  // Defaulted, not assumed, like `size_classes` above: `counts` is a new
  // payload key, and a bundle loaded against a server that predates it
  // must fall back to the plain total, not lose the whole board.
  const countSummary = board.counts
    ? formatMessage({ id: 'common.jobs.countSummary' }, { open: board.counts.open, ended: board.counts.ended })
    : undefined;
  const openStatuses = board.statuses.filter((status) => !endedStatuses.includes(status));
  // The payload counts the days a posting has been gone for exactly the
  // jobs whose card must warn rather than inform, so the chip, the banner
  // and the review popup cannot disagree and the browser counts nothing.
  const closedDaysById = Object.fromEntries((board.closed_review || []).map((row) => [row.id, row.days_closed]));
  const isEmpty = board.entries.length === 0;
  const anyGroupFilterActive = Object.values(filters).some((values) => values.length > 0);
  const noMatches = !isEmpty && filteredEntries.length === 0;
  const noMatchesMessage =
    needsAttention && !anyGroupFilterActive
      ? formatMessage({ id: 'board.nothingNeedsAttention' })
      : formatMessage({ id: 'common.jobs.noMatches' });
  const needsAttentionCount = board.entries.filter((job) => job.needs_attention).length;
  const closedCount = board.entries.filter((job) => job.closed).length;
  const pendingClosedReview = (board.closed_review || []).filter((row) => !dismissedClosed.includes(row.id));
  const reviewRows = (board.closed_review || [])
    .map((row) => ({ job: board.entries.find((entry) => entry.id === row.id), days: row.days_closed }))
    .filter((row) => row.job);

  const popupDuplicate = duplicate && duplicate.existing.in_pipeline !== false ? duplicate : null;
  const dialogDuplicate = duplicate && duplicate.existing.in_pipeline === false ? duplicate : null;
  const addJobStatus = intakeBusy
    ? 'reading'
    : popupDuplicate
      ? 'duplicate'
      : intakeError?.kind === 'not_link'
        ? 'not_link'
        : intakeError?.kind === 'failed' || intakeError?.kind === 'ingest_failed'
          ? 'error'
          : 'ready';

  function renderCard(job, compact = false) {
    return (
      <JobCard
        key={job.id}
        job={job}
        statuses={board.statuses}
        statusLabels={board.status_labels || {}}
        endedStatuses={endedStatuses}
        closedDays={closedDaysById[job.id]}
        compact={compact}
        canExplain={reasonSuggestions(job.status).length > 0}
        onMove={handleMove}
        onRetry={handleRetry}
        onAddReason={(target) => openReason(target.id)}
        dragHandlers={isPhone ? undefined : cardDragHandlers(job)}
        isDragging={dragId === job.id}
      />
    );
  }

  const allColumns = openStatuses.map((status) => {
    const entries = filteredEntries.filter((job) => job.status === status);
    return {
      status,
      title: statusLabel(status),
      count: entries.length,
      isEmpty: entries.length === 0,
      isOver: overColumn === status,
      ...(isPhone ? {} : columnDragHandlers(status)),
      children: entries.map((job) => renderCard(job)),
    };
  });

  // Latest first inside a lane group, by the day the status last changed:
  // "its latest 3 jobs" is about when a job ended, not when it was added.
  const endedGroups = endedStatuses.map((status) => ({
    status,
    label: statusLabel(status),
    jobs: filteredEntries
      .filter((job) => job.status === status)
      .sort((a, b) => String(b.status_changed || '').localeCompare(String(a.status_changed || ''))),
    isOver: overColumn === `ended-${status}`,
    ...(isPhone ? {} : endedGroupDragHandlers(status)),
  }));

  const lane = {
    expanded: laneExpanded,
    collapsible: !isPhone,
    total: endedGroups.reduce((sum, group) => sum + group.jobs.length, 0),
    groups: endedGroups,
    searchSoFar: board.search_so_far || {},
    isOver: overColumn === 'ended',
    laneDragHandlers,
    onToggle: () => setLaneExpanded((value) => !value),
    renderCard: (job) => renderCard(job, true),
  };

  // The phone layout shows one column at a time, picked from a chip row
  // with Ended as the last chip (D7). Nothing is dragged there, so every
  // move goes through the status select, which runs the same flows.
  const phoneSelection = phoneStatus || openStatuses[0];
  const columns = isPhone ? allColumns.filter((column) => column.status === phoneSelection) : allColumns;
  const laneProps = isPhone ? (phoneSelection === 'ended' ? lane : null) : lane;

  // The page header stack, in the order the artboard draws it: the title
  // (PageLayout's own H1), then "Add a job" with the Board/List pair,
  // then the filter bar, then the closed-postings banner.
  //
  // Board and List are one SegmentedControl in a labelled group rather
  // than two ButtonToggles (brief 2026-10-18, section 1): a selected view
  // is a state, and ButtonToggle's selected state is a primary brand
  // fill, which made the view look like the page's main action. "Add a
  // job" stays the only brand fill above the board. Nothing here reads
  // --color-background-button-selected-default (2026-10-29 brief, A3).
  // The pair was two FilterChips until CAREER-118 PR 1; it is the view
  // switch, not a filter, so it no longer carries the filter's wash.
  // The 16px between the button and the pair is the row's own 8px gap
  // plus 8px on the button.
  const headerRows = (
    <>
      <Flex gap={2} alignItems="center" wrap>
        <Box marginEnd={2}>
          <Button
            text={formatMessage({ id: 'board.addJob' })}
            color="red"
            accessibilityHaspopup
            onClick={() => setAddPopupOpen(true)}
          />
        </Box>
        <SegmentedControl
          ariaLabel={formatMessage({ id: 'common.view.groupLabel' })}
          value={view}
          onChange={persistView}
          items={[
            {
              value: 'board',
              label: formatMessage({ id: 'board.view.board' }),
              dataTestId: 'view-chip-board',
            },
            {
              value: 'list',
              label: formatMessage({ id: 'common.view.list' }),
              dataTestId: 'view-chip-list',
            },
          ]}
        />
      </Flex>
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
            key: 'needs-attention',
            label: formatMessage({ id: 'board.needsAttention' }),
            count: needsAttentionCount,
            countColor: 'var(--color-brand-violet)',
            pressed: needsAttention,
            onToggle: toggleNeedsAttention,
          },
          {
            key: 'hide-closed',
            label: formatMessage({ id: 'common.jobs.hideClosed' }),
            count: closedCount,
            pressed: hideClosed,
            onToggle: () => setHideClosed((value) => !value),
          },
        ]}
        summaryText={countSummary}
        resultCount={filteredEntries.length}
        totalCount={board.entries.length}
      />
      {pendingClosedReview.length > 0 ? (
        <ClosedPostingsBanner
          count={pendingClosedReview.length}
          short={isPhone}
          onReview={() => setReviewOpen(true)}
          onNotNow={dismissClosedReview}
        />
      ) : null}
    </>
  );

  const boardUi = (
    <PageLayout title={<FormattedMessage id="board.title" />} header={headerRows}>
      {isPhone && view === 'board' && !isEmpty ? (
        <Box marginBottom={4} overflow="scrollX">
          <Flex gap={2} alignItems="center" wrap={false}>
            {allColumns.map((column) => (
              <FilterChip
                key={column.status}
                label={column.title}
                count={column.count}
                dataTestId={`status-chip-${column.status}`}
                selected={phoneSelection === column.status}
                pressed={phoneSelection === column.status}
                onClick={() => setPhoneStatus(column.status)}
              />
            ))}
            <FilterChip
              label={formatMessage({ id: 'board.endedChip' })}
              count={lane.total}
              dataTestId="status-chip-ended"
              selected={phoneSelection === 'ended'}
              pressed={phoneSelection === 'ended'}
              onClick={() => setPhoneStatus('ended')}
            />
          </Flex>
        </Box>
      ) : null}
      {isEmpty ? (
        <Text color="subtle">{board.empty}</Text>
      ) : noMatches ? (
        <Text color="subtle">{noMatchesMessage}</Text>
      ) : view === 'board' ? (
        <KanbanBoard columns={columns} lane={laneProps} canDrag={!isPhone} />
      ) : (
        <ListView entries={filteredEntries} statusLabels={board.status_labels || {}} onRetry={handleRetry} />
      )}
      {chooserFor ? (
        <EndingChooser
          anchor={chooserFor.anchor}
          jobTitle={chooserFor.job.title}
          endedStatuses={endedStatuses}
          statusLabels={board.status_labels || {}}
          onPick={(status) => {
            const { job } = chooserFor;
            setChooserFor(null);
            requestEnd(job.id, status);
          }}
          onDismiss={() => setChooserFor(null)}
        />
      ) : null}
      {wonFor ? (
        <WonConfirm
          job={wonFor}
          statusLabels={board.status_labels || {}}
          onCancel={() => setWonFor(null)}
          onConfirm={() => {
            const job = wonFor;
            setWonFor(null);
            performMove(job.id, 'won', null);
          }}
        />
      ) : null}
      {reasonJob ? (
        <ReasonPopup
          job={reasonJob}
          reasons={reasonSuggestions(reasonJob.status)}
          noteTitle={board.end_note_title}
          statusLabels={board.status_labels || {}}
          busy={reasonBusy}
          error={reasonError}
          onSave={saveReason}
          onSkip={() => setReasonForId(null)}
        />
      ) : null}
      {reviewOpen ? (
        <ClosedPostingsReview
          rows={reviewRows}
          busyId={reviewBusy}
          onKeep={keepClosed}
          onStop={stopClosed}
          onDone={() => setReviewOpen(false)}
        />
      ) : null}
      {dialogDuplicate ? (
        <DuplicateDialog
          duplicate={dialogDuplicate}
          onCancel={handleDuplicateCancel}
          onOpenExisting={handleDuplicateOpenExisting}
          onPromote={handleDuplicatePromote}
          onAddAnyway={handleDuplicateAddAnyway}
        />
      ) : null}
      {addPopupOpen ? (
        <AddJobPopup
          url={intakeUrl}
          onUrlChange={handleIntakeUrlChange}
          status={addJobStatus}
          errorMessage={
            intakeError?.kind === 'failed' || intakeError?.kind === 'ingest_failed' ? intakeError.message : null
          }
          duplicateTitle={popupDuplicate?.existing?.title}
          onSubmit={handleAddJobPrimary}
          onShowExisting={handleDuplicateOpenExisting}
          onAddAnyway={handleDuplicateAddAnyway}
          onDismiss={handleAddJobDismiss}
        />
      ) : null}
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
                    secondaryLabel={entry.secondaryLabel}
                    onSecondaryAction={entry.onSecondaryAction}
                    onDismiss={() => dismissToast(entry.id)}
                  />
                ))}
              </Flex>
            </Box>
          </Box>
        </Layer>
      ) : null}
    </PageLayout>
  );

  // Below the phone width every popup is a full-width sheet (D7). Gestalt
  // renders Modal, Popover and Dropdown that way already once it is told
  // the device is a phone, so the phone layout is one provider rather than
  // a second set of mobile-only components.
  return isPhone ? <DeviceTypeProvider deviceType="mobile">{boardUi}</DeviceTypeProvider> : boardUi;
}
