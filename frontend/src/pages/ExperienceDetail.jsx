import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { BannerSlim, Badge, Box, Button, Flex, Link, Text } from 'gestalt';
import { deleteExperience, fetchExperiencePage, fetchExperienceTagsRegistry, updateExperience } from '../api/experiences.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, { DividerList, KeyValueGrid } from '../components/SectionCard.jsx';
import EditPositionPopup from '../components/EditPositionPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';

// The schema permits any YAML value for salary (vault.py never validates
// it, by design -- compensation is vault-file-only). A plain string/number
// renders as-is; a structured value (e.g. {amount, currency}) is flattened
// to a readable "key: value" line instead of being handed to <Text> raw,
// which throws on a non-string child.
function formatSalary(value) {
  if (typeof value === 'object') {
    return Object.entries(value).map(([key, val]) => `${key}: ${val}`).join(', ');
  }
  return String(value);
}

export default function ExperienceDetail() {
  const { id } = useParams();
  const [page, setPage] = useState(null);
  const [tagRegistry, setTagRegistry] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

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
    try {
      const registry = tagRegistry || (await fetchExperienceTagsRegistry());
      if (!tagRegistry) setTagRegistry(registry);
      setEditOpen(true);
    } catch (err) {
      setActionError(err.message);
    }
  }

  // Closing the popup always refetches the page, on both Save and Cancel:
  // the popup's own company-create/link action (EditPositionPopup's
  // "Create & link new company") persists immediately against the record,
  // so a Cancel that skipped this would leave `exp` showing the stale
  // company, and reopening the popup would then resubmit that stale
  // company_id on an unrelated save, undoing the link.
  function handleEditDismiss() {
    setEditOpen(false);
    load();
  }

  async function handleSave(fields) {
    await updateExperience(id, fields);
    handleEditDismiss();
  }

  async function handleDelete() {
    setDeleteBusy(true);
    try {
      await deleteExperience(id);
      // /experiences is the Jinja list page, not an App.jsx route, so a
      // client-side navigate() would find no matching Route and render
      // blank -- a full-document navigation is required to actually reach
      // the server.
      window.location.assign('/experiences');
    } catch (err) {
      setDeleteError(err.message);
      setDeleteBusy(false);
    }
  }

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
        {actionError ? <BannerSlim type="error" message={actionError} onDismiss={() => setActionError(null)} /> : null}
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
        {exp.salary !== null && exp.salary !== undefined ? (
          <SectionCard title="Salary">
            <Text>{formatSalary(exp.salary)}</Text>
          </SectionCard>
        ) : null}
      </Flex>
      {editOpen && tagRegistry ? (
        <EditPositionPopup
          exp={exp}
          companies={page.companies}
          tagRegistry={tagRegistry}
          onSave={handleSave}
          onDismiss={handleEditDismiss}
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
