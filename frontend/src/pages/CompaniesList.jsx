import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Box, Button, Flex, Heading, Link, PageHeader, Text } from 'gestalt';
import { fetchCompaniesPage } from '../api/companies.js';
import FilterBar from '../components/FilterBar.jsx';
import { countBy, presentOptions, sortedOptions } from '../filters.js';

const FILTERS_KEY = 'careerCompaniesFilters';
const FILTER_GROUPS = [
  { key: 'sector', label: 'Sector' },
  { key: 'size', label: 'Size' },
  { key: 'openJobs', label: 'Open jobs' },
];
const EMPTY_FILTERS = { sector: [], size: [], openJobs: [] };
// "Any" is this facet's cleared state: with neither box checked every
// company matches, so the two boxes say the only two things worth asking
// for, and Clear (or Clear all) is what "Any" means.
const OPEN_JOBS_OPTIONS = [
  { value: 'with', label: 'With open jobs' },
  { value: 'without', label: 'Without open jobs' },
];
// Owner decision 2026-10-15: at most 30 characters of a name are shown,
// cut at 30 with one ellipsis character appended, and the full name is the
// element's tooltip. Display only -- the stored name is never touched.
const NAME_LIMIT = 30;
// Every card is the same width (the grid) and the same height (this), so
// the directory reads as a straight grid however ragged its content is:
// a long sector label or a third line can never stretch one card past its
// neighbours. Fits the card's four rows at the smallest column width:
// two lines of name, the sector line, the size line, and the chip row.
const CARD_HEIGHT = 200;
const GRID_STYLE = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
  gap: '16px',
};

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// Counted and cut by character, not by UTF-16 code unit: an astral
// character (an emoji, some CJK extensions) straddling the limit would
// otherwise be cut into a lone surrogate and render as a replacement
// glyph.
function displayName(name) {
  const characters = Array.from(name || '');
  return characters.length > NAME_LIMIT ? `${characters.slice(0, NAME_LIMIT).join('')}…` : name || '';
}

function openJobsChip(count) {
  if (count === 0) return { text: 'No open jobs', type: 'neutral' };
  return { text: `${count} open ${count === 1 ? 'job' : 'jobs'}`, type: 'info' };
}

// Filters live in localStorage, like the board's own view and toggle
// (owner decision: no URL sync). A stored value is merged onto the empty
// shape and sanitized to lists of strings, so a key left behind by an
// older shape cannot break the page.
function readStoredFilters() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(FILTERS_KEY) || '{}');
    const groups = Object.fromEntries(
      FILTER_GROUPS.map(({ key }) => [
        key,
        (Array.isArray(stored[key]) ? stored[key] : []).filter((value) => typeof value === 'string'),
      ]),
    );
    return { filters: groups, needsAttention: stored.needsAttention === true };
  } catch {
    return { filters: EMPTY_FILTERS, needsAttention: false };
  }
}

export default function CompaniesList() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [stored] = useState(readStoredFilters);
  const [filters, setFilters] = useState(stored.filters);
  const [needsAttention, setNeedsAttention] = useState(stored.needsAttention);

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

  useEffect(() => {
    try {
      window.localStorage.setItem(FILTERS_KEY, JSON.stringify({ ...filters, needsAttention }));
    } catch {
      // localStorage unavailable; the filter choice just will not persist.
    }
  }, [filters, needsAttention]);

  function toggleFilterValue(group, value) {
    setFilters((current) => {
      const values = current[group];
      return {
        ...current,
        [group]: values.includes(value) ? values.filter((v) => v !== value) : [...values, value],
      };
    });
  }

  function clearFilterGroup(group) {
    setFilters((current) => ({ ...current, [group]: [] }));
  }

  function clearFilterGroups(groups) {
    setFilters((current) => {
      const next = { ...current };
      groups.forEach((group) => {
        next[group] = [];
      });
      return next;
    });
  }

  // Memoized off the one loaded payload so every option list and the
  // filtered grid below recompute when the page loads, not on every
  // render.
  const entries = useMemo(() => page?.entries || [], [page]);
  const counts = useMemo(() => page?.counts || {}, [page]);
  const openJobs = useCallback((company) => counts[company.id] || 0, [counts]);

  const sectorOptions = useMemo(() => {
    const labels = Object.fromEntries((page?.isic_sections || []).map((section) => [section.code, section.label]));
    return sortedOptions(
      countBy(entries, (company) => company.sectors || []),
      (code) => labels[code] || code,
    );
  }, [entries, page]);

  const sizeOptions = useMemo(
    () =>
      presentOptions(
        page?.size_classes || [],
        countBy(entries, (company) => [company.size_class]),
        titleCase,
      ),
    [entries, page],
  );

  const openJobsOptions = useMemo(
    () =>
      OPEN_JOBS_OPTIONS.map((option) => ({
        ...option,
        count: entries.filter((company) => (openJobs(company) > 0) === (option.value === 'with')).length,
      })),
    [entries, openJobs],
  );

  const optionsByGroup = useMemo(
    () => ({ sector: sectorOptions, size: sizeOptions, openJobs: openJobsOptions }),
    [sectorOptions, sizeOptions, openJobsOptions],
  );

  // A company matches a group when it carries ANY of that group's checked
  // values (sector, size class, has/has not open jobs); an unchecked group
  // filters nothing. Needs-your-input narrows to records a review flag
  // stands against, which the backend has already marked.
  const filtered = useMemo(
    () =>
      entries.filter((company) => {
        const sectorOk =
          filters.sector.length === 0 || (company.sectors || []).some((code) => filters.sector.includes(code));
        const sizeOk = filters.size.length === 0 || filters.size.includes(company.size_class);
        const openOk =
          filters.openJobs.length === 0 || filters.openJobs.includes(openJobs(company) > 0 ? 'with' : 'without');
        const needsOk = !needsAttention || company.needs_attention;
        return sectorOk && sizeOk && openOk && needsOk;
      }),
    [entries, filters, needsAttention, openJobs],
  );

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

  const isEmpty = entries.length === 0;
  const anyGroupFilterActive = Object.values(filters).some((values) => values.length > 0);
  const noMatches = !isEmpty && filtered.length === 0;
  const noMatchesMessage =
    needsAttention && !anyGroupFilterActive ? 'Nothing needs your input.' : 'No companies match these filters.';
  const needsAttentionCount = entries.filter((company) => company.needs_attention).length;

  return (
    <Box padding={6}>
      <PageHeader title="Companies" />
      {isEmpty ? (
        <Text color="subtle">{page.empty}</Text>
      ) : (
        <>
          <Box marginTop={4}>
            <FilterBar
              groups={FILTER_GROUPS}
              countNoun="companies"
              needsLabel="Needs your input"
              optionsByGroup={optionsByGroup}
              selected={filters}
              onToggleValue={toggleFilterValue}
              onClearGroup={clearFilterGroup}
              onClearGroups={clearFilterGroups}
              needsAttention={needsAttention}
              needsAttentionCount={needsAttentionCount}
              onToggleNeedsAttention={() => setNeedsAttention((current) => !current)}
              resultCount={filtered.length}
              totalCount={entries.length}
            />
          </Box>
          {noMatches ? (
            <Text color="subtle">{noMatchesMessage}</Text>
          ) : (
            <Box dangerouslySetInlineStyle={{ __style: GRID_STYLE }}>
              {filtered.map((company) => {
                // Defaulted like counts/isic_sections/size_classes above, so a
                // bundle served by a server that predates the key still renders.
                const sectorText = ((page.sector_labels || {})[company.id] || []).join(', ') || 'Sector unknown';
                const sizeText = company.size_class ? titleCase(company.size_class) : 'Size unknown';
                const chip = openJobsChip(openJobs(company));
                return (
                  <Link key={company.id} href={`/companies/${encodeURIComponent(company.id)}`} display="block">
                    <Box
                      rounding={4}
                      borderStyle="sm"
                      padding={4}
                      color="default"
                      height={CARD_HEIGHT}
                      display="flex"
                      direction="column"
                      overflow="hidden"
                      data-testid={`company-card-${company.id}`}
                    >
                      <Flex direction="column" gap={2}>
                        <Heading size="300" lineClamp={2}>
                          {/* The tooltip is the full stored name; the heading itself
                              shows at most NAME_LIMIT characters of it. */}
                          <span title={company.name}>{displayName(company.name)}</span>
                        </Heading>
                        <Text color="subtle" size="200" lineClamp={2} title={sectorText}>
                          {sectorText}
                        </Text>
                        <Text color="subtle" size="200">
                          {sizeText}
                        </Text>
                      </Flex>
                      <Box marginTop="auto">
                        <Badge type={chip.type} text={chip.text} />
                      </Box>
                    </Box>
                  </Link>
                );
              })}
            </Box>
          )}
        </>
      )}
    </Box>
  );
}
