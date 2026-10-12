import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, Box, Flex, Link, Text } from 'gestalt';
import { deleteExperience, fetchExperiencePage, fetchExperienceTagsRegistry, updateExperience } from '../api/experiences.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, { DividerList, KeyValueGrid } from '../components/SectionCard.jsx';
import EditPositionPopup from '../components/EditPositionPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';

export default function ExperienceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState(null);
  const [tagRegistry, setTagRegistry] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = useCallback(() => {
    fetchExperiencePage(id)
      .then((data) => {
        setPage(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function openEdit() {
    if (!tagRegistry) setTagRegistry(await fetchExperienceTagsRegistry());
    setEditOpen(true);
  }

  async function handleSave(fields) {
    await updateExperience(id, fields);
    setEditOpen(false);
    load();
  }

  async function handleDelete() {
    setDeleteBusy(true);
    try {
      await deleteExperience(id);
      navigate('/experiences');
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
        <Text>Loading position…</Text>
      </Box>
    );
  }

  const { exp, label, markdown } = page;
  const companyHref = exp.company_id ? `/companies/${encodeURIComponent(exp.company_id)}` : null;
  const skillTags = (exp.tags || []).filter((tag) => !tag.startsWith('function:'));

  return (
    <Box padding={6}>
      <Flex direction="column" gap={5} maxWidth={880}>
        <DetailHeader
          type="EXPERIENCE"
          backHref="/experiences"
          backLabel="Experiences"
          title={exp.title}
          subtitle={companyHref ? <Link href={companyHref}>{label}</Link> : label}
          location={exp.location}
          dates={`${exp.start} – ${exp.end}`}
          editLabel="Edit position"
          onEdit={openEdit}
          onDelete={() => setDeleteOpen(true)}
        />
        {exp.summary || skillTags.length ? (
          <SectionCard title="Summary">
            {exp.summary ? <Text>{exp.summary}</Text> : null}
            {skillTags.length ? (
              <Flex gap={2} wrap>
                {skillTags.map((tag) => (
                  <Badge key={tag} text={tag.split(':').pop()} />
                ))}
              </Flex>
            ) : null}
          </SectionCard>
        ) : null}
        {exp.highlights?.length ? (
          <SectionCard title="Highlights">
            <DividerList items={exp.highlights} />
          </SectionCard>
        ) : null}
        {exp.detail ? (
          <SectionCard title="Content">
            <Box dangerouslySetInlineStyle={{ __style: { fontSize: 16, lineHeight: '24px' } }}>
              <span dangerouslySetInnerHTML={{ __html: markdown }} />
            </Box>
          </SectionCard>
        ) : null}
        <SectionCard title="Details">
          <KeyValueGrid
            entries={[
              ['Organization', companyHref ? <Link href={companyHref}>{label}</Link> : label || 'Unknown'],
              ['People led', exp.people_led ?? 'Not set'],
            ]}
          />
        </SectionCard>
        {exp.custom && Object.keys(exp.custom).length ? (
          <SectionCard title="Additional details">
            <KeyValueGrid
              entries={Object.entries(exp.custom).map(([key, value]) => [
                key,
                typeof value === 'string' ? value : JSON.stringify(value),
              ])}
            />
          </SectionCard>
        ) : null}
        {exp.salary ? (
          <SectionCard title="Salary">
            <Text>{exp.salary}</Text>
          </SectionCard>
        ) : null}
      </Flex>
      {editOpen && tagRegistry ? (
        <EditPositionPopup
          exp={exp}
          companies={page.companies}
          tagRegistry={tagRegistry}
          onSave={handleSave}
          onDismiss={() => setEditOpen(false)}
        />
      ) : null}
      {deleteOpen ? (
        <DeleteConfirmModal
          kind="experience"
          name={exp.title}
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
