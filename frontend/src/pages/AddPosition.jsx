import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BannerSlim, Box, Button, Flex, Text } from 'gestalt';
import { FormattedMessage, useIntl } from 'react-intl';
import PageLayout from '../components/PageLayout.jsx';
import PositionFields from '../components/PositionFields.jsx';
import {
  COMPANY_NOT_LINKED, matchCompanyByName, positionPayload, registryTokens, slugify,
} from '../positions.js';
import {
  createExperience, fetchExperienceFormContext, linkExperienceCompany,
} from '../api/experiences.js';

// Add position: the Jinja `experience_form.html` page rebuilt in React
// (owner-approved artboard, 2026-11-01). A short add form is a dialog and a
// long multi-section one is a page -- the owner decision recorded in
// docs/decisions/design-system.md -- so this is the one position write that
// is not a popup. The field set itself is shared with the edit form the
// follow-up moves here (components/PositionFields.jsx).
//
// Everything is written through endpoints that already existed:
// POST /api/experiences creates and stamps the owner, and a company the
// record has to bring into existence goes through
// POST /api/experiences/<id>/link-company afterwards -- the same two-step
// the old form did, because link-company needs an experience id to link to.

// The artboard's content column. Narrower than the detail pages' 960px
// (SectionCard's DETAIL_MAX_WIDTH) on purpose: a form reads better in a
// shorter line, and the two widths are a design decision each.
const FORM_MAX_WIDTH = 920;

const EMPTY = {
  title: '', company: '', company_id: null, start: '', end: '', location: '',
  people_led: '', summary: '', highlights: '', detail: '', tags: [], custom: [],
};

export default function AddPosition() {
  const { formatMessage } = useIntl();
  const navigate = useNavigate();
  const [context, setContext] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [tagDrafts, setTagDrafts] = useState({});
  const [registryPicks, setRegistryPicks] = useState({});
  // A company the record has to create cannot be created before the record
  // exists, so the intent is held here and spent right after the POST --
  // which is exactly what the old form's `pendingCreate` flag did.
  const [pendingCompany, setPendingCompany] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState(null);
  // Set once the POST has answered. From then on the position exists, so
  // the page must never offer Save again -- a second press would create a
  // second record. It is only ever non-null when the company link that
  // followed the create failed, which is the one case this page does not
  // navigate away from: the failure is a visible state with a reason
  // (product rule), and the way on is the record itself.
  const [savedId, setSavedId] = useState(null);

  const load = useCallback(() => {
    fetchExperienceFormContext()
      .then((data) => {
        setContext(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const companies = context?.companies || [];
  const matched = matchCompanyByName(companies, values.company);
  // The matched record wins over a stale company_id: typing a different
  // name is how a person changes which company this position is for.
  const companyId = matched ? matched.id : null;
  const companyName = (values.company || '').trim();
  const linkStatus = companyId
    ? formatMessage({ id: 'addPosition.linkedTo' }, { name: matched.name })
    : pendingCompany
      ? formatMessage({ id: 'addPosition.willCreate' }, { name: pendingCompany })
      : COMPANY_NOT_LINKED;

  function handleChange(field, value) {
    setValues((prev) => ({ ...prev, [field]: value }));
    if (field === 'company') setPendingCompany(null);
    // An error clears as soon as the field it is about has something in
    // it, so a corrected field does not keep complaining until Save.
    if (errors[field] && String(value).trim()) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  }

  function handleRegistryPick(facet, token) {
    setRegistryPicks((prev) => ({ ...prev, [facet]: '' }));
    if (!token || (values.tags || []).includes(token)) return;
    setValues((prev) => ({ ...prev, tags: [...(prev.tags || []), token] }));
  }

  function handleProposeTag(facet) {
    const raw = slugify((tagDrafts[facet] || '').trim());
    if (!raw) return;
    const token = `${facet}:${raw}`;
    setTagDrafts((prev) => ({ ...prev, [facet]: '' }));
    if ((values.tags || []).includes(token)) return;
    setValues((prev) => ({ ...prev, tags: [...(prev.tags || []), token] }));
  }

  // The three required fields and the owner's own three messages. No other
  // field is refused here: the backend validates the rest (a start date
  // that is not YYYY-MM, a negative people-led) and its message is what
  // the banner shows.
  function validate() {
    const found = {};
    if (!(values.title || '').trim()) found.title = formatMessage({ id: 'addPosition.error.title' });
    if (!(values.start || '').trim()) found.start = formatMessage({ id: 'addPosition.error.start' });
    if (!(values.location || '').trim()) found.location = formatMessage({ id: 'addPosition.error.location' });
    return found;
  }

  async function handleSave() {
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setSaveError(null);
    let payload;
    try {
      payload = positionPayload({ ...values, company_id: companyId },
                                { knownTags: registryTokens(context.tags) });
    } catch (err) {
      setSaveError(err.message);
      setBusy(false);
      return;
    }
    let saved;
    try {
      saved = await createExperience(payload);
    } catch (err) {
      setSaveError(err.message);
      setBusy(false);
      return;
    }
    // The position exists from here on. A failing company link must not
    // read as a failed save, and must not be swallowed either: the page
    // stays, says what failed, and offers the record it did create.
    if (pendingCompany && !companyId) {
      try {
        await linkPendingCompany(saved.id, pendingCompany);
      } catch (err) {
        setSavedId(saved.id);
        setSaveError(formatMessage({ id: 'addPosition.companyLinkFailed' }, { reason: err.message }));
        setBusy(false);
        return;
      }
    }
    navigate(saved.id ? `/experiences/${encodeURIComponent(saved.id)}` : '/experiences');
  }

  // The same confirm-on-suggestion path the Edit position popup takes: the
  // endpoint answers a near-match rather than creating a second company
  // under a name that is nearly one it already has, and the person decides.
  async function linkPendingCompany(id, name) {
    let response = await linkExperienceCompany(id, { create: { name } });
    if (response.suggestion) {
      const useSuggestion = window.confirm(
        formatMessage({ id: 'addPosition.companySuggestion' },
                      { suggestion: response.suggestion.name, name }),
      );
      response = useSuggestion
        ? await linkExperienceCompany(id, { company_id: response.suggestion.id })
        : await linkExperienceCompany(id, { create: { name }, confirm_create: true });
    }
    return response;
  }

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
  if (!context) {
    return (
      <Box padding={6}>
        <Text>
          <FormattedMessage id="addPosition.loading" />
        </Text>
      </Box>
    );
  }

  return (
    <PageLayout
      title={<FormattedMessage id="addPosition.title" />}
      backLink={{ href: '/experiences', label: formatMessage({ id: 'addPosition.back' }) }}
    >
      <Box maxWidth={FORM_MAX_WIDTH}>
        <Flex direction="column" gap={5}>
          {saveError ? <BannerSlim type="error" message={saveError} /> : null}
          <PositionFields
            values={values}
            errors={errors}
            onChange={handleChange}
            companyLinkStatus={linkStatus}
            companyAction={!companyId && companyName && !pendingCompany ? (
              <Button
                text={formatMessage({ id: 'addPosition.createCompany' })}
                size="sm"
                onClick={() => setPendingCompany(companyName)}
              />
            ) : null}
            tagRegistry={context.tags}
            canProposeTags={Boolean(context.can_edit_shared)}
            tagDrafts={tagDrafts}
            onTagDraftChange={(facet, value) => setTagDrafts((prev) => ({ ...prev, [facet]: value }))}
            onProposeTag={handleProposeTag}
            registryPicks={registryPicks}
            onRegistryPick={handleRegistryPick}
          />
        </Flex>
      </Box>
      {/* The artboard's sticky bar: the two actions stay reachable however
          far down the three cards the person is. Sticky rather than fixed,
          so it sits inside the content column and never covers it. */}
      <Box
        marginTop={6}
        maxWidth={FORM_MAX_WIDTH}
        paddingY={4}
        color="default"
        dangerouslySetInlineStyle={{
          __style: {
            position: 'sticky',
            bottom: 0,
            borderTop: '1px solid var(--color-border-container)',
          },
        }}
      >
        <Flex gap={2}>
          {savedId ? (
            <Button
              text={formatMessage({ id: 'addPosition.openPosition' })}
              color="red"
              onClick={() => navigate(`/experiences/${encodeURIComponent(savedId)}`)}
            />
          ) : (
            <Button
              text={formatMessage({ id: 'addPosition.save' })}
              color="red"
              disabled={busy}
              onClick={handleSave}
            />
          )}
          <Button
            text={formatMessage({ id: 'addPosition.cancel' })}
            color="gray"
            disabled={busy}
            onClick={() => navigate('/experiences')}
          />
        </Flex>
      </Box>
    </PageLayout>
  );
}
