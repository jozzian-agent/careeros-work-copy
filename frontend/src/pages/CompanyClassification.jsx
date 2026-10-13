import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Box, Button, Checkbox, Flex, SelectList, Text, TextField } from 'gestalt';
import { fetchCompanyTaxonomy, updateCompany } from '../api/companies.js';
import DetailHeader from '../components/DetailHeader.jsx';
import SectionCard from '../components/SectionCard.jsx';

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// The one full-page classification editor the routing list keeps as a
// standalone React page (the job-side equivalent is the Edit criteria
// popup instead, per the approved JOZ-280 Phase A wireframe). Saves via
// the existing PUT /api/companies/<id> with kind/sectors/size_class, the
// same payload shape company_taxonomy.html already sends.
export default function CompanyClassification() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [kind, setKind] = useState('employer');
  const [sectors, setSectors] = useState([]);
  const [sizeClass, setSizeClass] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    fetchCompanyTaxonomy(id)
      .then((payload) => {
        setData(payload);
        setKind(payload.company.kind || 'employer');
        setSectors(payload.company.sectors || []);
        setSizeClass(payload.company.size_class || '');
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  function toggleSector(code, checked) {
    setSectors((prev) => (checked ? [...prev, code] : prev.filter((c) => c !== code)));
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await updateCompany(id, { kind, sectors, size_class: sizeClass || null });
      navigate(`/companies/${encodeURIComponent(id)}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
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
  if (!data) {
    return (
      <Box padding={6}>
        <Text>Loading classification…</Text>
      </Box>
    );
  }

  const { company, isic_sections: isicSections, size_classes: sizeClasses, kinds } = data;

  return (
    <Box padding={6}>
      <Flex direction="column" gap={5} maxWidth={880}>
        <DetailHeader
          type="COMPANY CLASSIFICATION"
          backHref={`/companies/${encodeURIComponent(id)}`}
          backLabel={company.name}
          title="Classification"
          showActions={false}
        />
        {error ? <Text color="error">{error}</Text> : null}
        <SectionCard title="Kind">
          <Box maxWidth={220}>
            <SelectList id="classification-kind" label="Company kind" value={kind} onChange={({ value }) => setKind(value)}>
              {kinds.map((k) => (
                <SelectList.Option key={k} value={k} label={titleCase(k)} />
              ))}
            </SelectList>
          </Box>
        </SectionCard>
        <SectionCard title="Sectors (ISIC Rev.4)">
          <Text color="subtle">What industry the company operates in. Multi-select.</Text>
          <Flex gap={0} wrap>
            {isicSections.map((section) => (
              <Box key={section.code} minWidth={320}>
                <Checkbox
                  id={`sector-${section.code}`}
                  label={`${section.code} — ${section.label}`}
                  checked={sectors.includes(section.code)}
                  onChange={({ checked }) => toggleSector(section.code, checked)}
                />
              </Box>
            ))}
          </Flex>
        </SectionCard>
        <SectionCard title="Size">
          <Flex direction="column" gap={3}>
            <Box maxWidth={260}>
              <SelectList
                id="classification-size-class"
                label="Size class (EU definition)"
                value={sizeClass}
                onChange={({ value }) => setSizeClass(value)}
              >
                <SelectList.Option value="" label="Unknown" />
                {sizeClasses.map((sc) => (
                  <SelectList.Option key={sc} value={sc} label={titleCase(sc)} />
                ))}
              </SelectList>
            </Box>
            <TextField
              id="classification-size-range"
              label="Size range (read-only; derived from employee count)"
              value={company.size_range || 'Unknown'}
              disabled
              onChange={() => {}}
            />
          </Flex>
        </SectionCard>
        {company.review_flags?.length ? (
          <SectionCard title="Review flags">
            <Text>{company.review_flags.length} open — {company.review_flags.join(', ')}</Text>
          </SectionCard>
        ) : null}
        <Flex gap={2}>
          <Button text="Save changes" color="red" disabled={busy} onClick={handleSave} />
          <Button text="Cancel" onClick={() => navigate(`/companies/${encodeURIComponent(id)}`)} />
        </Flex>
      </Flex>
    </Box>
  );
}
