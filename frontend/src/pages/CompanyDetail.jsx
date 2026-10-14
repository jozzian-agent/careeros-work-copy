import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { BannerSlim, Box, Button, Flex, Link, Text } from 'gestalt';
import { deleteCompany, fetchCompanyPage, retryCompany, updateCompany } from '../api/companies.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard, { DETAIL_MAX_WIDTH, EmptyState } from '../components/SectionCard.jsx';
import EditCompanyPopup from '../components/EditCompanyPopup.jsx';
import EditClassificationPopup from '../components/EditClassificationPopup.jsx';
import DeleteConfirmModal from '../components/DeleteConfirmModal.jsx';
import { NEEDS_INPUT_ANCHOR, NEEDS_INPUT_TITLE, NeedsInputChip } from '../components/NeedsInputCard.jsx';

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

const RETRY_OUTCOME_LABELS = { filled: 'filled', exhausted: 'nothing found', flagged: 'needs review' };
const RETRY_FLAG_REASONS = {
  'sector-ambiguous': 'several sectors matched',
  'sector-source-conflict': 'sector sources disagree',
  'size-inconsistent': 'size sources disagree',
};

// Where a stored classification value came from, in owner words. The
// backend sends either 'user' or the name of the enrichment signal that
// produced the value (careeros/web/pages/companies.py field_source).
const SOURCE_LABELS = {
  user: 'Set by you',
  llm: 'Found by AI',
  jsonld: "Found on the company's website",
  wikidata: 'Found on Wikidata',
  osm: 'Found on OpenStreetMap',
};
const FALLBACK_SOURCE_LABEL = 'Found by the rules';

// The same sources, named as things that were tried rather than things
// that found something, for the needs-input card.
const TRIED_LABELS = {
  llm: 'AI',
  jsonld: "the company's website",
  wikidata: 'Wikidata',
  osm: 'OpenStreetMap',
};

function sourceLabel(source) {
  if (!source) return null;
  return SOURCE_LABELS[source] || FALLBACK_SOURCE_LABEL;
}

function triedLabel(source) {
  return TRIED_LABELS[source] || source;
}

// Mirrors the Jinja company_detail.html retry script's result messaging:
// one line per enrichment field (outcome, flag reason, "kept: you set it"
// when owner-provenanced), plus a no-website hint when nothing changed and
// the company has no website/identifiers/sources to search. `changed`
// comes only from retry_applied (what THIS call actually wrote), never the
// stored field_states, which can carry an older run's outcome.
function buildRetryFeedback(result) {
  const states = result.enrichment?.field_states || {};
  const provenance = result.field_provenance || {};
  const applied = result.retry_applied || [];
  const changed = applied.length > 0;
  const messages = [];
  for (const [field, value] of Object.entries(states)) {
    const isSectors = field === 'sectors';
    const label = isSectors ? 'Sector' : 'Size';
    let message = `${label}: ${RETRY_OUTCOME_LABELS[value.state] || 'not tried'}`;
    if (value.state === 'flagged') {
      const flag = (result.review_flags || []).find(
        (f) => RETRY_FLAG_REASONS[f] && f.startsWith(isSectors ? 'sector' : 'size'),
      );
      if (flag) message += ` (${RETRY_FLAG_REASONS[flag]})`;
    }
    const ownerSet = isSectors
      ? provenance.sectors === 'user'
      : provenance.size_range === 'user' || provenance.size_class === 'user';
    if (ownerSet) message += ' (kept: you set it)';
    messages.push(message);
  }
  if (!changed && !result.website && !(result.identifiers || []).length && !(result.sources || []).length) {
    messages.push('This company has no website; add one so Retry has something to search');
  }
  const prefix = changed ? 'Retry updated the company.' : 'Retry ran; nothing changed.';
  return `${prefix} ${messages.join('. ') || 'No eligible fields to retry.'}`;
}

// One linked record: its title as a link, and what state it is in. Jobs
// and positions render through the same row, which is why the backend
// sends both as {id, title, status}.
function LinkedRows({ rows, hrefPrefix }) {
  return (
    <Flex direction="column" gap={2}>
      {rows.map((row) => (
        <Flex key={row.id} gap={2} alignItems="center" justifyContent="between" wrap>
          <Link href={`${hrefPrefix}/${encodeURIComponent(row.id)}`} display="inlineBlock">
            <Text color="link">{row.title}</Text>
          </Link>
          {row.status ? (
            <Text size="200" color="subtle">
              {titleCase(row.status)}
            </Text>
          ) : null}
        </Flex>
      ))}
    </Flex>
  );
}

function ClassificationRow({ label, field }) {
  const source = sourceLabel(field?.source);
  return (
    <Flex direction="column" gap={1}>
      <Text size="200" color="subtle">
        {label}
      </Text>
      <Text>{field?.value || 'Not known yet'}</Text>
      {source ? (
        <Text size="200" color="subtle">
          {source}
        </Text>
      ) : null}
    </Flex>
  );
}

export default function CompanyDetail() {
  const { id } = useParams();
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editFocus, setEditFocus] = useState(null);
  const [classificationOpen, setClassificationOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryFeedback, setRetryFeedback] = useState(null);

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
    setEditFocus(null);
    load();
  }

  function openEdit(focus = null) {
    setEditFocus(focus);
    setEditOpen(true);
  }

  async function handleSaveClassification(fields) {
    await updateCompany(id, fields);
    setClassificationOpen(false);
    load();
  }

  async function handleRetry() {
    setRetryBusy(true);
    setRetryFeedback(null);
    try {
      const result = await retryCompany(id);
      setRetryFeedback({ type: 'success', message: buildRetryFeedback(result) });
      await load();
    } catch (err) {
      setRetryFeedback({ type: 'error', message: err.message });
    } finally {
      setRetryBusy(false);
    }
  }

  async function handleDelete() {
    setDeleteBusy(true);
    try {
      await deleteCompany(id);
      // CompanyDetail is a React SPA route (App.jsx), but /companies is
      // still the Jinja list page -- react-router's navigate() would just
      // find no matching Route and render blank, since Flask never sees
      // the navigation. A full-document navigation is required so the
      // browser actually requests /companies from the server.
      window.location.assign('/companies');
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
        <Text>Loading company…</Text>
      </Box>
    );
  }

  const {
    company, jobs = [], experiences = [], classification = {}, needs_input: needsInput,
    isic_sections: sectorOptions = [], size_classes: sizeOptions = [],
  } = page;
  const locations = (company.locations || []).join(', ');
  const sectorText = classification.sector?.value || 'Sector unknown';
  const sizeText = classification.size?.value || 'Size unknown';
  const tried = needsInput?.tried || [];

  return (
    <Box padding={6}>
      <Flex direction="column" gap={5} maxWidth={DETAIL_MAX_WIDTH}>
        <DetailHeader
          type="COMPANY"
          backHref="/companies"
          backLabel="Companies"
          chip={needsInput ? <NeedsInputChip /> : null}
          title={company.name}
          subtitle={`${sectorText} · ${sizeText}`}
          location={locations || null}
          meta={company.website ? (
            <Link href={company.website} target="blank" display="inlineBlock" externalLinkIcon="default">
              <Text color="link">{company.website}</Text>
            </Link>
          ) : null}
          editLabel="Edit company"
          onEdit={() => openEdit()}
          onDelete={() => setDeleteOpen(true)}
        />
        {/* The one ask, and only when automation has genuinely run out of
            ideas: the backend decides that (companies.py
            company_needs_input), so a stale review flag on a field that
            does have a value can no longer keep the card up. */}
        {needsInput ? (
          <SectionCard
            title={NEEDS_INPUT_TITLE}
            variant="needs-input"
            anchorId={NEEDS_INPUT_ANCHOR}
            actions={[
              <Button
                key="set"
                text="Set it yourself"
                color="red"
                onClick={() => setClassificationOpen(true)}
              />,
              <Button key="retry" text="Try again" color="gray" disabled={retryBusy} onClick={handleRetry} />,
            ]}
          >
            <Flex direction="column" gap={2}>
              <Text>
                {needsInput.field === 'sector'
                  ? 'This company has no sector yet.'
                  : 'This company has no size yet.'}
              </Text>
              <Text color="subtle">
                {tried.length
                  ? `Tried: ${tried.map(triedLabel).join(', ')}.`
                  : 'No source has been tried yet.'}
              </Text>
            </Flex>
          </SectionCard>
        ) : null}
        {retryFeedback ? (
          <BannerSlim
            type={retryFeedback.type}
            message={retryFeedback.message}
            onDismiss={() => setRetryFeedback(null)}
          />
        ) : null}
        <SectionCard title="Jobs">
          {jobs.length ? <LinkedRows rows={jobs} hrefPrefix="/jobs" /> : <EmptyState text="No jobs linked yet" />}
        </SectionCard>
        <SectionCard title="Experiences">
          {experiences.length ? (
            <LinkedRows rows={experiences} hrefPrefix="/experiences" />
          ) : (
            <EmptyState text="No linked experience yet" />
          )}
        </SectionCard>
        {/* Collapsed by default, in the same accordion the Job page's own
            Classification uses: the sector and the size are settled facts
            the owner checks occasionally, not something the page has to
            hold open. */}
        <SectionCard
          title="Classification"
          collapsible
          actions={(
            <Button
              text="Edit classification"
              color="gray"
              size="sm"
              onClick={() => setClassificationOpen(true)}
            />
          )}
        >
          <Flex direction="column" gap={3}>
            <ClassificationRow label="Sector" field={classification.sector} />
            <ClassificationRow label="Size" field={classification.size} />
          </Flex>
        </SectionCard>
        <SectionCard title="Notes">
          {company.notes ? (
            <Text>{company.notes}</Text>
          ) : (
            <EmptyState
              text="No notes yet."
              action={<Button text="Add a note" size="sm" color="gray" onClick={() => openEdit('notes')} />}
            />
          )}
        </SectionCard>
      </Flex>
      {editOpen ? (
        <EditCompanyPopup
          company={company}
          focus={editFocus}
          onSave={handleSave}
          onDismiss={() => {
            setEditOpen(false);
            setEditFocus(null);
          }}
        />
      ) : null}
      {classificationOpen ? (
        <EditClassificationPopup
          mode="company"
          company={company}
          sectorOptions={sectorOptions}
          sizeOptions={sizeOptions}
          onSave={handleSaveClassification}
          onDismiss={() => setClassificationOpen(false)}
        />
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
