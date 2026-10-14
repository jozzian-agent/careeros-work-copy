import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Accordion, BannerSlim, Badge, Box, Button, Flex, Link, Text } from 'gestalt';
import {
  checkPosting,
  deleteJob,
  fetchJobPage,
  fetchJobTaxonomy,
  pasteDescription,
  retryIngest,
  updateJob,
} from '../api/jobs.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, { DETAIL_MAX_WIDTH, DividerList, KeyValueGrid } from '../components/SectionCard.jsx';
import FitChip from '../components/FitChip.jsx';
import StatusSelect from '../components/StatusSelect.jsx';
import EditJobPopup from '../components/EditJobPopup.jsx';
import EditCriteriaPopup from '../components/EditCriteriaPopup.jsx';
import PasteDescriptionPopup from '../components/PasteDescriptionPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';

const INGEST_MESSAGE = {
  fetch_failed: 'Fetching the posting failed.',
  extract_failed: 'Extraction failed.',
  stub: 'Details filling in…',
  fetched: 'Details filling in…',
};

// JOZ-267 fix round 1 finding 4: a terminal ingest_state means nothing is
// ever going to advance a still-pending field again on its own (the owner
// must act, via Retry or Paste); a pending field_status left over from a
// past bug, or from a terminal failure that landed between page loads,
// must not poll forever once nothing can change it.
const TERMINAL_INGEST_STATES = ['complete', 'fetch_failed', 'extract_failed'];

// JOZ-267 Section 3: field_status values the job detail page must show,
// one row per covered field. Order matches careeros/ingest.py STATUS_FIELDS.
const FIELD_LABELS = {
  title: 'Title',
  company: 'Company',
  location: 'Location',
  function: 'Function',
  seniority: 'Seniority',
  employment_type: 'Employment type',
  skills: 'Skills',
  description_structured: 'Description',
};
const STATUS_ORDER = Object.keys(FIELD_LABELS);
const STATUS_BADGE = {
  pending: { type: 'info', text: 'Pending' },
  done: { type: 'success', text: 'Done' },
  failed: { type: 'error', text: 'Failed' },
  not_evidenced: { type: 'warning', text: 'Not evidenced' },
};
const POSTING_QUALITY_NOTICE = {
  thin: 'This posting has very little text; extraction will be limited.',
};

// Fallback for the words the page shows where a fit rating would go. The
// backend sends them as fit_placeholder; this is only the floor for an
// older payload that does not carry the key yet.
const FIT_PLACEHOLDER = 'Not calculated yet';

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [criteriaOpen, setCriteriaOpen] = useState(false);
  const [criteria, setCriteria] = useState(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [checkBusy, setCheckBusy] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [pasteOpen, setPasteOpen] = useState(false);

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
    load();
  }

  async function openCriteria() {
    try {
      const data = await fetchJobTaxonomy(id);
      setCriteria(data);
      setCriteriaOpen(true);
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handleSaveCriteria(fields) {
    await updateJob(id, fields);
    setCriteriaOpen(false);
    load();
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
        error: 'Error: posting unreachable; will retry on the next scan.',
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

  const dates = job.added ? `Added ${job.added}` : null;
  const ingestMessage = INGEST_MESSAGE[job.ingest_state];

  return (
    <Box padding={6}>
      <Flex direction="column" gap={5} maxWidth={DETAIL_MAX_WIDTH}>
        <DetailHeader
          type="JOB"
          backHref="/jobs"
          backLabel="Jobs"
          title={job.title}
          subtitle={company ? <Link href={`/companies/${encodeURIComponent(company.id)}`}>{company.name}</Link> : null}
          location={job.location}
          dates={dates}
          editLabel="Edit job"
          onEdit={() => setEditOpen(true)}
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
        {ingestMessage ? (
          <SectionCard title="Posting status">
            <Flex gap={3} alignItems="center" wrap>
              <Text color="subtle">{ingestMessage}</Text>
              {(job.ingest_state === 'fetch_failed' || job.ingest_state === 'extract_failed') && (
                <Button text="Retry" size="sm" onClick={handleRetry} />
              )}
              {job.ingest_state === 'fetch_failed' && (
                <Button text="Paste posting text manually" size="sm" color="gray" onClick={() => setPasteOpen(true)} />
              )}
            </Flex>
          </SectionCard>
        ) : null}
        {job.posting_quality && POSTING_QUALITY_NOTICE[job.posting_quality] ? (
          <BannerSlim type="warning" message={POSTING_QUALITY_NOTICE[job.posting_quality]} />
        ) : null}
        {job.field_status && Object.keys(job.field_status).length ? (
          <SectionCard title="Extraction">
            <Flex direction="column" gap={3}>
              <Flex gap={2} wrap>
                {STATUS_ORDER.filter((field) => job.field_status[field]).map((field) => {
                  const badge = STATUS_BADGE[job.field_status[field]];
                  return (
                    <Flex key={field} gap={1} alignItems="center">
                      <Text size="200">{FIELD_LABELS[field]}</Text>
                      {badge ? <Badge type={badge.type} text={badge.text} /> : null}
                    </Flex>
                  );
                })}
              </Flex>
              {job.description_structured?.requirements?.length || job.description_structured?.nice_to_have?.length ? (
                <>
                  {job.description_structured.method === 'llm'
                  && job.field_provenance?.description_structured !== 'user' ? (
                    <Flex gap={2} alignItems="center">
                      <Badge type="info" text="AI-generated" />
                      <Button text="Edit" size="sm" color="gray" onClick={() => setEditOpen(true)} />
                    </Flex>
                  ) : null}
                  {job.description_structured.requirements?.length ? (
                    <Box>
                      <Text weight="bold" size="200">
                        Requirements
                      </Text>
                      <DividerList items={job.description_structured.requirements} />
                    </Box>
                  ) : null}
                  {job.description_structured.nice_to_have?.length ? (
                    <Box>
                      <Text weight="bold" size="200">
                        Nice to have
                      </Text>
                      <DividerList items={job.description_structured.nice_to_have} />
                    </Box>
                  ) : null}
                </>
              ) : null}
            </Flex>
          </SectionCard>
        ) : null}
        {job.company_link_state === 'needs_review' ? (
          <SectionCard title="Company needs your input">
            <Text color="subtle">Confirm which company this job belongs to.</Text>
          </SectionCard>
        ) : null}
        {job.summary ? (
          <SectionCard title="Summary" aiLabel={job.summary_source === 'ai' ? 'generated' : null}>
            <Text>{job.summary}</Text>
          </SectionCard>
        ) : null}
        {hasDescription ? (
          <SectionCard title="Content">
            <Accordion id="original-posting-text" title="Original posting text (from source)">
              <Text>{job.description}</Text>
            </Accordion>
          </SectionCard>
        ) : null}
        {job.skills?.length ? (
          <SectionCard title="Skills">
            <Flex gap={2} wrap>
              {job.skills.map((skill) => (
                <Badge key={skill} text={skill} />
              ))}
            </Flex>
          </SectionCard>
        ) : null}
        {job.responsibilities?.length ? (
          <SectionCard title="Responsibilities">
            <DividerList items={job.responsibilities} />
          </SectionCard>
        ) : null}
        {job.background ? (
          <SectionCard title="Background required">
            <Text>{job.background}</Text>
          </SectionCard>
        ) : null}
        {job.certifications?.length ? (
          <SectionCard title="Certifications">
            <DividerList items={job.certifications} />
          </SectionCard>
        ) : null}
        <SectionCard title="Classification">
          {job.function?.length || job.tags?.length ? (
            <Text>Function, sector and tags are set.</Text>
          ) : (
            <Text color="subtle">Function, sector and tags are not set yet.</Text>
          )}
          <Box>
            <Button text="Edit classification" color="gray" size="sm" onClick={openCriteria} />
          </Box>
        </SectionCard>
        <SectionCard title="Details">
          <KeyValueGrid
            entries={[
              ['Location', job.location || 'Unknown'],
              ['Source', job.source || 'Unknown'],
              ['Posted date', job.posted_date || 'Unknown'],
              ['Added date', job.added || 'Unknown'],
            ]}
          />
          {job.url ? (
            <Box>
              <Link href={job.url} target="blank" display="inlineBlock">
                <Text color="link">Open posting</Text>
              </Link>
            </Box>
          ) : null}
          <Flex gap={3} alignItems="center" wrap>
            <Button
              text="Check posting"
              size="sm"
              color="gray"
              disabled={!watchEligible || checkBusy}
              accessibilityLabel={!watchEligible ? watchReason : 'Check posting'}
              onClick={handleCheckPosting}
            />
            <div role="status" aria-live="polite">
              {checkBusy ? <Text color="subtle">Checking…</Text> : checkResult ? <Text color="subtle">{checkResult}</Text> : null}
            </div>
          </Flex>
        </SectionCard>
        <SectionCard title="Notes">
          {job.notes ? (
            <Box dangerouslySetInlineStyle={{ __style: { fontSize: 16, lineHeight: '24px' } }}>
              <span dangerouslySetInnerHTML={{ __html: markdown }} />
            </Box>
          ) : (
            <Text color="subtle">No notes yet.</Text>
          )}
        </SectionCard>
        {job.history?.length ? (
          <SectionCard title="History">
            <DividerList
              items={job.history.slice().reverse()}
              renderItem={(entry) => (
                <Flex justifyContent="between" gap={3}>
                  <Text>{entry.detail || entry.event}</Text>
                  <Text color="subtle">{entry.ts}</Text>
                </Flex>
              )}
            />
          </SectionCard>
        ) : null}
      </Flex>
      {editOpen ? <EditJobPopup job={job} onSave={handleSaveJob} onDismiss={() => setEditOpen(false)} /> : null}
      {criteriaOpen && criteria ? (
        <EditCriteriaPopup taxonomy={criteria} onSave={handleSaveCriteria} onDismiss={() => setCriteriaOpen(false)} />
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
