import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Accordion, Badge, BannerSlim, Box, Button, Flex, Link, Text } from 'gestalt';
import {
  checkPosting,
  deleteJob,
  fetchJobPage,
  fetchJobTaxonomy,
  pasteDescription,
  resolveReview,
  retryIngest,
  updateJob,
} from '../api/jobs.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, {
  DETAIL_MAX_WIDTH, DividerList, EmptyState, KeyValueGrid,
} from '../components/SectionCard.jsx';
import FitChip from '../components/FitChip.jsx';
import StatusSelect from '../components/StatusSelect.jsx';
import NeedsInputCard, { NeedsInputChip } from '../components/NeedsInputCard.jsx';
import Requirements, { requirementEntries } from '../components/Requirements.jsx';
import ExtractionPopup, {
  extractionRows, notFoundLabels, readSentence, readTimestamp,
} from '../components/ExtractionPopup.jsx';
import EditJobPopup from '../components/EditJobPopup.jsx';
import EditClassificationPopup from '../components/EditClassificationPopup.jsx';
import PasteDescriptionPopup from '../components/PasteDescriptionPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';
import { prettifyTag } from '../tags.js';
import { localDate } from '../dates.js';

// JOZ-267 fix round 1 finding 4: a terminal ingest_state means nothing is
// ever going to advance a still-pending field again on its own (the owner
// must act, via Retry or Paste); a pending field_status left over from a
// past bug, or from a terminal failure that landed between page loads,
// must not poll forever once nothing can change it.
const TERMINAL_INGEST_STATES = ['complete', 'fetch_failed', 'extract_failed'];

const POSTING_QUALITY_NOTICE = {
  thin: 'This posting has very little text; extraction will be limited.',
};

// Fallback for the words the page shows where a fit rating would go. The
// backend sends them as fit_placeholder; this is only the floor for an
// older payload that does not carry the key yet.
const FIT_PLACEHOLDER = 'Not calculated yet';

// What a section says while the posting is still being read.
const PENDING_TEXT = 'Being read from the posting.';

// A field with no value says so in the posting's terms, not with a blank.
const NOT_FOUND = 'Not found in posting';

// Paragraph breaks in the stored posting text are content: they are how
// the posting was written. One Text per paragraph keeps them.
function paragraphs(text) {
  return String(text || '').split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
}

// A machine wrote this section unless the owner has since corrected it.
// `machine` is what the extractor recorded about how the text was
// produced (summary_source, description_structured.method,
// ingest_source); field_provenance records who last touched it, and the
// owner always wins, so a corrected field loses its label.
function aiLabel(job, keys, machine, kind) {
  const provenance = job.field_provenance || {};
  const corrected = keys.some((key) => provenance[key] === 'user');
  return machine && !corrected ? kind : null;
}

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editFocus, setEditFocus] = useState(null);
  const [classificationOpen, setClassificationOpen] = useState(false);
  const [taxonomy, setTaxonomy] = useState(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [checkBusy, setCheckBusy] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [extractionOpen, setExtractionOpen] = useState(false);
  const [resolveBusy, setResolveBusy] = useState(false);

  const load = useCallback(() => {
    fetchJobPage(id)
      .then((data) => {
        setPage(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // JOZ-267 Section 7: extraction progress must be visible without a
  // manual reload. Polling is the cheap mechanism the spec allows; it
  // stops on its own once nothing is pending, so a settled job never
  // keeps polling.
  useEffect(() => {
    if (!page) return undefined;
    const hasPendingField = Object.values(page.job.field_status || {}).includes('pending');
    const pending = page.llm_pending
      || (hasPendingField && !TERMINAL_INGEST_STATES.includes(page.job.ingest_state));
    if (!pending) return undefined;
    const timer = setTimeout(load, 3000);
    return () => clearTimeout(timer);
  }, [page, load]);

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
        <Text>Loading job…</Text>
      </Box>
    );
  }

  const {
    job, company, statuses, markdown, has_description: hasDescription,
    watch_eligible: watchEligible, watch_reason: watchReason,
    history, classification, needs_input: needsInput, reading,
    summary_effective: summaryEffective, function_labels: functionLabels,
  } = page;

  async function handleStatusChange(status) {
    try {
      await updateJob(id, { status });
      await load();
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handleSaveJob(fields) {
    await updateJob(id, fields);
    setEditOpen(false);
    setEditFocus(null);
    load();
  }

  function openEdit(focus = null) {
    setEditFocus(focus);
    setEditOpen(true);
  }

  async function openClassification() {
    try {
      const data = await fetchJobTaxonomy(id);
      setTaxonomy(data);
      setClassificationOpen(true);
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handleSaveClassification(fields) {
    await updateJob(id, fields);
    setClassificationOpen(false);
    load();
  }

  // The extraction popup sends the owner to whichever surface can set the
  // field it could not find.
  function openSetter(setter) {
    setExtractionOpen(false);
    if (setter === 'classification') {
      openClassification();
      return;
    }
    openEdit();
  }

  async function handleRetry() {
    try {
      await retryIngest(id);
      await load();
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handlePasteDescription(description) {
    await pasteDescription(id, description);
    setPasteOpen(false);
    await load();
  }

  // Both company answers go through the same endpoint with the review
  // revision the owner actually saw, so a review that moved on in the
  // meantime fails loudly instead of linking the wrong company.
  async function handleResolveReview(payload) {
    setResolveBusy(true);
    setActionError(null);
    try {
      await resolveReview(id, { ...payload, review_token: needsInput?.review?.token });
      await load();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setResolveBusy(false);
    }
  }

  async function handleCheckPosting() {
    setCheckBusy(true);
    setCheckResult(null);
    try {
      const data = await checkPosting(id);
      if (data.events?.length) {
        await load();
        return;
      }
      const messages = {
        not_watched: data.reason,
        error: 'Error: posting unreachable.',
        gone: 'Gone: posting previously unavailable.',
      };
      setCheckResult(messages[data.watch_status] || 'Unchanged');
    } catch (err) {
      setCheckResult(`Error: ${err.message}`);
    } finally {
      setCheckBusy(false);
    }
  }

  async function handleDelete() {
    setDeleteBusy(true);
    try {
      await deleteJob(id);
      navigate('/jobs');
    } catch (err) {
      setDeleteError(err.message);
      setDeleteBusy(false);
    }
  }

  const structured = job.description_structured || {};
  const requirements = requirementEntries(job);
  const rows = extractionRows(job);
  const notFound = notFoundLabels(rows);
  const readAt = readTimestamp(history);
  const sector = classification?.sector || {};
  const functions = (classification?.function || []).map(
    (key) => functionLabels?.[key]?.label || prettifyTag(key),
  );
  const tags = (classification?.tags || []).map(prettifyTag);

  return (
    <Box padding={6}>
      <Flex direction="column" gap={5} maxWidth={DETAIL_MAX_WIDTH}>
        <DetailHeader
          type="JOB"
          backHref="/jobs"
          backLabel="Jobs"
          chip={needsInput ? <NeedsInputChip /> : null}
          title={job.title}
          subtitle={company ? <Link href={`/companies/${encodeURIComponent(company.id)}`}>{company.name}</Link> : null}
          location={job.location}
          dates={job.added ? `Added ${job.added}` : null}
          meta={job.url ? (
            <Link href={job.url} target="blank" display="inlineBlock" externalLinkIcon="default">
              <Text color="link">Open posting</Text>
            </Link>
          ) : null}
          editLabel="Edit job"
          onEdit={() => openEdit()}
          onDelete={() => setDeleteOpen(true)}
        />
        {actionError ? <BannerSlim type="error" message={actionError} onDismiss={() => setActionError(null)} /> : null}
        <Flex gap={4} wrap>
          <Box>
            <Text weight="bold" size="200">
              Status
            </Text>
            <Box marginTop={1}>
              <StatusSelect
                id={job.id}
                jobTitle={job.title}
                status={job.status}
                statuses={statuses}
                onChange={handleStatusChange}
              />
            </Box>
          </Box>
          <Box>
            <Text weight="bold" size="200">
              Fit
            </Text>
            <Box marginTop={1}>
              <FitChip fit={page.fit} placeholder={page.fit_placeholder || FIT_PLACEHOLDER} />
            </Box>
          </Box>
        </Flex>
        {/* The reading strip: present only while the posting is being read,
            gone the moment it is done, so it is never a permanent fixture. */}
        {reading ? (
          <Box
            padding={3}
            rounding={4}
            dangerouslySetInlineStyle={{ __style: { background: 'var(--color-brand-wash-blue)' } }}
          >
            <Text>Reading the posting now. The sections below fill in as the details arrive.</Text>
          </Box>
        ) : null}
        {needsInput ? (
          <NeedsInputCard
            needsInput={needsInput}
            employerName={job.employer_named_in_posting}
            errorStage={job.ingest_error?.stage}
            hasText={hasDescription}
            busy={resolveBusy}
            onLink={(companyId) => handleResolveReview({ company_id: companyId })}
            onCreate={(name) => handleResolveReview({ create: { name } })}
            onPaste={() => setPasteOpen(true)}
            onRetry={handleRetry}
          />
        ) : null}
        {job.posting_quality && POSTING_QUALITY_NOTICE[job.posting_quality] ? (
          <BannerSlim type="warning" message={POSTING_QUALITY_NOTICE[job.posting_quality]} />
        ) : null}
        {summaryEffective || reading ? (
          <SectionCard
            title="Summary"
            aiLabel={aiLabel(job, ['summary'], job.summary_source === 'ai', 'generated')}
          >
            {summaryEffective ? <Text>{summaryEffective}</Text> : <Text color="subtle">{PENDING_TEXT}</Text>}
          </SectionCard>
        ) : null}
        {requirements.length || reading ? (
          <SectionCard
            title="Requirements"
            aiLabel={aiLabel(job, ['description_structured', 'skills'], structured.method === 'llm', 'extracted')}
          >
            {requirements.length ? <Requirements entries={requirements} /> : <Text color="subtle">{PENDING_TEXT}</Text>}
          </SectionCard>
        ) : null}
        {job.responsibilities?.length || reading ? (
          <SectionCard
            title="Responsibilities"
            aiLabel={aiLabel(job, ['responsibilities'], job.ingest_source === 'llm', 'extracted')}
          >
            {job.responsibilities?.length ? (
              <DividerList items={job.responsibilities} />
            ) : (
              <Text color="subtle">{PENDING_TEXT}</Text>
            )}
          </SectionCard>
        ) : null}
        {/* The extraction row: one line about the last read, and the way
            into the detail. The eight per-field status badges this
            replaces lived on the page permanently. */}
        <Flex gap={3} alignItems="center" wrap>
          <Text color="subtle">
            {readSentence(readAt)}
            {notFound.length ? ` Not found: ${notFound.join(', ')}.` : ''}
          </Text>
          <Button
            text="How this was extracted"
            size="sm"
            color="transparent"
            onClick={() => setExtractionOpen(true)}
          />
        </Flex>
        {/* Collapsed by default, and each in its own Accordion.Expandable:
            one instance only ever keeps one item open, and opening the
            posting must not close Details. No wrapper card around either,
            since the accordion is itself the card. */}
        {hasDescription ? (
          <Accordion.Expandable
            id="original-posting"
            // Gestalt names the toggle "Expand section" by default, which
            // is the same name on both accordions here.
            accessibilityExpandLabel="Show the original posting"
            accessibilityCollapseLabel="Hide the original posting"
            items={[{
              title: 'Original posting',
              children: (
                <Flex direction="column" gap={3}>
                  {paragraphs(job.description).map((paragraph, index) => (
                    <Text key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</Text>
                  ))}
                </Flex>
              ),
            }]}
          />
        ) : null}
        <Accordion.Expandable
          id="job-details"
          accessibilityExpandLabel="Show details"
          accessibilityCollapseLabel="Hide details"
          items={[{
            title: 'Details',
            children: (
              <Flex direction="column" gap={3}>
                <KeyValueGrid
                  entries={[
                    ['Source', job.source || 'Unknown'],
                    ['Posted', job.posted_date || 'Unknown'],
                  ]}
                />
                <Flex gap={3} alignItems="center" wrap>
                  <Button
                    text="Check if still online"
                    size="sm"
                    color="gray"
                    disabled={!watchEligible || checkBusy}
                    accessibilityLabel={!watchEligible ? watchReason : 'Check if still online'}
                    onClick={handleCheckPosting}
                  />
                  <div role="status" aria-live="polite">
                    {checkBusy ? <Text color="subtle">Checking…</Text>
                      : checkResult ? <Text color="subtle">{checkResult}</Text> : null}
                  </div>
                </Flex>
              </Flex>
            ),
          }]}
        />
        <SectionCard
          title="Classification"
          actions={<Button text="Edit classification" color="gray" size="sm" onClick={openClassification} />}
        >
          <Flex direction="column" gap={3}>
            <Flex direction="column" gap={1}>
              <Text size="200" color="subtle">
                Sector
              </Text>
              <Text>{sector.value || NOT_FOUND}</Text>
              {/* Sector belongs to the company, not the posting: a job
                  with none of its own inherits it, and says so. */}
              {sector.source === 'company' ? <Text size="200" color="subtle">From the company</Text> : null}
            </Flex>
            <Flex direction="column" gap={1}>
              <Text size="200" color="subtle">
                Function
              </Text>
              {functions.length ? (
                <Flex gap={2} wrap>
                  {functions.map((label) => <Badge key={label} text={label} />)}
                </Flex>
              ) : (
                <Text>{NOT_FOUND}</Text>
              )}
            </Flex>
            <Flex direction="column" gap={1}>
              <Text size="200" color="subtle">
                Tags
              </Text>
              {tags.length ? (
                <Flex gap={2} wrap>
                  {tags.map((label) => <Badge key={label} text={label} />)}
                </Flex>
              ) : (
                <Text>{NOT_FOUND}</Text>
              )}
            </Flex>
          </Flex>
        </SectionCard>
        <SectionCard title="Notes">
          {job.notes ? (
            <Box dangerouslySetInlineStyle={{ __style: { fontSize: 16, lineHeight: '24px' } }}>
              <span dangerouslySetInnerHTML={{ __html: markdown }} />
            </Box>
          ) : (
            <EmptyState
              text="No notes yet."
              action={<Button text="Add a note" size="sm" color="gray" onClick={() => openEdit('notes')} />}
            />
          )}
        </SectionCard>
        {history?.length ? (
          <SectionCard title="History">
            <DividerList
              items={history.slice().reverse()}
              renderItem={(entry) => (
                <Flex justifyContent="between" gap={3} wrap>
                  <Text>{entry.label}</Text>
                  <Text color="subtle">{localDate(entry.ts)}</Text>
                </Flex>
              )}
            />
          </SectionCard>
        ) : null}
      </Flex>
      {editOpen ? (
        <EditJobPopup
          job={job}
          focus={editFocus}
          onSave={handleSaveJob}
          onDismiss={() => {
            setEditOpen(false);
            setEditFocus(null);
          }}
        />
      ) : null}
      {classificationOpen && taxonomy ? (
        <EditClassificationPopup
          mode="job"
          taxonomy={taxonomy}
          onSave={handleSaveClassification}
          onDismiss={() => setClassificationOpen(false)}
        />
      ) : null}
      {extractionOpen ? (
        <ExtractionPopup
          job={job}
          readAt={readAt}
          onDismiss={() => setExtractionOpen(false)}
          onOpenSetter={openSetter}
        />
      ) : null}
      {pasteOpen ? (
        <PasteDescriptionPopup onSave={handlePasteDescription} onDismiss={() => setPasteOpen(false)} />
      ) : null}
      {deleteOpen ? (
        <DeleteConfirmModal
          kind="job"
          name={job.title}
          busy={deleteBusy}
          error={deleteError}
          onConfirm={handleDelete}
          onDismiss={() => {
            setDeleteOpen(false);
            setDeleteError(null);
          }}
        />
      ) : null}
    </Box>
  );
}
