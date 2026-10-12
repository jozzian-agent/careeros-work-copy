import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Box, Button, Flex, Link, Text } from 'gestalt';
import { deleteCompany, fetchCompanyPage, retryCompany, updateCompany } from '../api/companies.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, { EmptyState, KeyValueGrid } from '../components/SectionCard.jsx';
import EditCompanyPopup from '../components/EditCompanyPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// Mirrors the Jinja company_detail.html's "show Retry" decision (BUILD_NOTES
// JOZ-280): any enrichment field exhausted/flagged, a review flag present,
// or the company never enriched at all. Scoped to employers, same as the
// backend retry_company endpoint.
function retryState(company) {
  if ((company.kind || 'employer') !== 'employer') return null;
  const fieldStates = company.enrichment?.field_states || {};
  const needsLook = (company.review_flags || []).length > 0 ||
    Object.values(fieldStates).some((state) => ['exhausted', 'flagged'].includes(state.state));
  if (needsLook) return 'Sector or size enrichment needs another look.';
  const neverEnriched = !company.sectors?.length && !company.size_range && !company.size_class;
  if (neverEnriched) return 'Please add a url to enrich.';
  return null;
}

export default function CompanyDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [retryBusy, setRetryBusy] = useState(false);

  const load = useCallback(() => {
    fetchCompanyPage(id)
      .then((data) => {
        setPage(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(fields) {
    await updateCompany(id, fields);
    setEditOpen(false);
    load();
  }

  async function handleRetry() {
    setRetryBusy(true);
    try {
      await retryCompany(id);
      await load();
    } finally {
      setRetryBusy(false);
    }
  }

  async function handleDelete() {
    setDeleteBusy(true);
    try {
      await deleteCompany(id);
      navigate('/companies');
    } catch (err) {
      setDeleteError(err.message);
      setDeleteBusy(false);
    }
  }

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
        <Text>Loading company…</Text>
      </Box>
    );
  }

  const { company, sector_labels: sectorLabels, entries: jobs, experiences } = page;
  // Mirrors the Jinja company_detail.html convention exactly: the raw
  // size_range string wins when present, title-cased size_class otherwise.
  const sizeLabel = company.size_range || (company.size_class ? titleCase(company.size_class) : 'Size unknown');
  const sectorText = sectorLabels.length ? sectorLabels.join(', ') : 'Sector unknown';
  const retryMessage = retryState(company);

  return (
    <Box padding={6}>
      <Flex direction="column" gap={5} maxWidth={880}>
        <DetailHeader
          type="COMPANY"
          backHref="/companies"
          backLabel="Companies"
          title={company.name}
          subtitle={`${sectorText} · ${sizeLabel}`}
          editLabel="Edit company"
          onEdit={() => setEditOpen(true)}
          onDelete={() => setDeleteOpen(true)}
        />
        {retryMessage ? (
          <SectionCard title="Enrichment">
            <Flex gap={3} alignItems="center" wrap>
              <Text color="subtle">{retryMessage}</Text>
              <Button text="Retry" size="sm" disabled={retryBusy} onClick={handleRetry} />
            </Flex>
          </SectionCard>
        ) : null}
        <SectionCard title="Classification">
          <Text>
            {sectorText} · {sizeLabel}
          </Text>
          <Box>
            <Link href={`/companies/${encodeURIComponent(company.id)}/taxonomy`} display="inlineBlock">
              <Text color="link">Edit classification</Text>
            </Link>
          </Box>
        </SectionCard>
        <SectionCard title="Details">
          <KeyValueGrid
            entries={[
              ['Name', company.name],
              ['Website', company.website ? <Link href={company.website}>{company.website}</Link> : 'Unknown'],
              ['Locations', (company.locations || []).join(', ') || 'Unknown'],
            ]}
          />
        </SectionCard>
        <SectionCard title="Notes">
          <Text color={company.notes ? undefined : 'subtle'}>{company.notes || 'No notes yet.'}</Text>
        </SectionCard>
        <SectionCard title="Jobs">
          {jobs.length ? (
            <Flex direction="column" gap={2}>
              {jobs.map((job) => (
                <Link key={job.id} href={`/jobs/${encodeURIComponent(job.id)}`} display="inlineBlock">
                  <Text color="link">{job.title}</Text>
                </Link>
              ))}
            </Flex>
          ) : (
            <EmptyState text="No jobs linked yet" />
          )}
        </SectionCard>
        <SectionCard title="Experiences">
          {experiences.length ? (
            <Flex direction="column" gap={2}>
              {experiences.map((exp) => (
                <Link key={exp.id} href={`/experiences/${encodeURIComponent(exp.id)}`} display="inlineBlock">
                  <Text color="link">{exp.title}</Text>
                </Link>
              ))}
            </Flex>
          ) : (
            <EmptyState text="No linked experience yet" />
          )}
        </SectionCard>
      </Flex>
      {editOpen ? (
        <EditCompanyPopup company={company} onSave={handleSave} onDismiss={() => setEditOpen(false)} />
      ) : null}
      {deleteOpen ? (
        <DeleteConfirmModal
          kind="company"
          name={company.name}
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
