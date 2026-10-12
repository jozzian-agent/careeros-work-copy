import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Accordion, Badge, Box, Button, Flex, Link, Text } from 'gestalt';
import { deleteJob, fetchJobPage, fetchJobTaxonomy, retryIngest, updateJob } from '../api/jobs.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, { DividerList, KeyValueGrid } from '../components/SectionCard.jsx';
import FitChip from '../components/FitChip.jsx';
import StatusSelect from '../components/StatusSelect.jsx';
import FitSelect from '../components/FitSelect.jsx';
import EditJobPopup from '../components/EditJobPopup.jsx';
import EditCriteriaPopup from '../components/EditCriteriaPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';

const INGEST_MESSAGE = {
  fetch_failed: 'Fetching the posting failed.',
  extract_failed: 'Extraction failed.',
  stub: 'Details filling in…',
  fetched: 'Details filling in…',
};

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

  if (loadError) {
    return (
      <Box padding={6}>
        <Text color="error">{loadError}</Text>
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

  const { job, company, statuses, markdown, has_description: hasDescription } = page;

  async function handleStatusChange(status) {
    await updateJob(id, { status });
    load();
  }

  async function handleFitChange(fit) {
    await updateJob(id, { fit });
    load();
  }

  async function handleSaveJob(fields) {
    await updateJob(id, fields);
    setEditOpen(false);
    load();
  }

  async function openCriteria() {
    const data = await fetchJobTaxonomy(id);
    setCriteria(data);
    setCriteriaOpen(true);
  }

  async function handleSaveCriteria(fields) {
    await updateJob(id, fields);
    setCriteriaOpen(false);
    load();
  }

  async function handleRetry() {
    await retryIngest(id);
    load();
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
      <Flex direction="column" gap={5} maxWidth={880}>
        <DetailHeader
          type="JOB"
          backHref="/jobs"
          backLabel="Jobs"
          chip={<FitChip fit={job.fit} />}
          title={job.title}
          subtitle={company ? <Link href={`/companies/${encodeURIComponent(company.id)}`}>{company.name}</Link> : null}
          location={job.location}
          dates={dates}
          editLabel="Edit job"
          onEdit={() => setEditOpen(true)}
          onDelete={() => setDeleteOpen(true)}
        />
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
              <FitSelect jobTitle={job.title} fit={job.fit} onChange={handleFitChange} />
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
            </Flex>
          </SectionCard>
        ) : null}
        {job.company_link_state === 'needs_review' ? (
          <SectionCard title="Company needs your input">
            <Text color="subtle">Confirm which company this job belongs to.</Text>
          </SectionCard>
        ) : null}
        {job.summary ? (
          <SectionCard title="Summary" label={job.summary_source === 'ai' ? 'AI-generated' : null}>
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
