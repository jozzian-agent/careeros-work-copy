import { useCallback, useEffect, useState } from 'react';
import { Badge, Box, Button, Flex, Heading, Link, PageHeader, SelectList, Text } from 'gestalt';
import { fetchCompaniesPage } from '../api/companies.js';

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

export default function CompaniesList() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [sectorFilter, setSectorFilter] = useState('all');
  const [sizeFilter, setSizeFilter] = useState('all');

  const load = useCallback(() => {
    fetchCompaniesPage()
      .then((data) => {
        setPage(data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
        <Text>Loading companies…</Text>
      </Box>
    );
  }

  const { entries, counts, empty, isic_sections: isicSections, sector_labels: sectorLabels, size_classes: sizeClasses } = page;

  // Same client-side filter semantics as companies.html's inline script:
  // the sector filter matches ANY of the company's sectors, the size
  // filter matches size_class exactly.
  const filtered = entries.filter((company) => {
    const sectorOk = sectorFilter === 'all' || (company.sectors || []).includes(sectorFilter);
    const sizeOk = sizeFilter === 'all' || company.size_class === sizeFilter;
    return sectorOk && sizeOk;
  });

  return (
    <Box padding={6}>
      <PageHeader title="Companies" />
      {entries.length === 0 ? (
        <Text color="subtle">{empty}</Text>
      ) : (
        <>
          <Box marginTop={4} marginBottom={4}>
            <Flex gap={4} wrap>
              <Box minWidth={200}>
                <SelectList id="sector-filter" label="Sector" value={sectorFilter} onChange={({ value }) => setSectorFilter(value)}>
                  <SelectList.Option value="all" label="All sectors" />
                  {isicSections.map((section) => (
                    <SelectList.Option key={section.code} value={section.code} label={section.label} />
                  ))}
                </SelectList>
              </Box>
              <Box minWidth={200}>
                <SelectList id="size-filter" label="Size" value={sizeFilter} onChange={({ value }) => setSizeFilter(value)}>
                  <SelectList.Option value="all" label="All sizes" />
                  {sizeClasses.map((sizeClass) => (
                    <SelectList.Option key={sizeClass} value={sizeClass} label={titleCase(sizeClass)} />
                  ))}
                </SelectList>
              </Box>
            </Flex>
          </Box>
          <Flex gap={3} wrap>
            {filtered.map((company) => {
              const sectorText = (sectorLabels[company.id] || []).join(', ') || 'Sector unknown';
              const sizeLabel = company.size_range || (company.size_class ? titleCase(company.size_class) : 'Size unknown');
              return (
                <Box key={company.id} width={280}>
                  <Link href={`/companies/${encodeURIComponent(company.id)}`} display="block">
                    <Box rounding={4} borderStyle="sm" padding={4} color="default">
                      <Flex direction="column" gap={2}>
                        <Heading size="300">{company.name}</Heading>
                        <Text color="subtle">
                          {sectorText} · {sizeLabel}
                        </Text>
                        <Box>
                          <Badge text={`${counts[company.id] || 0} open jobs`} />
                        </Box>
                      </Flex>
                    </Box>
                  </Link>
                </Box>
              );
            })}
          </Flex>
        </>
      )}
    </Box>
  );
}
