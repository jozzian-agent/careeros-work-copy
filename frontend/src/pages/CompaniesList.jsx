import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Box, Flex, Heading, Link, Table, Text, Button } from 'gestalt';
import { FormattedMessage, useIntl } from 'react-intl';
import { fetchCompaniesPage } from '../api/companies.js';
import FilterBar from '../components/FilterBar.jsx';
import SegmentedControl from '../components/SegmentedControl.jsx';
import PageLayout from '../components/PageLayout.jsx';
import SortableHeaderCell from '../components/SortableHeaderCell.jsx';
import { countBy, labelPairs, presentOptions, sortedOptions } from '../filters.js';

const FILTERS_KEY = 'careerCompaniesFilters';
// B4 (CAREER-91): which of the two views this browser last chose,
// remembered the way the Jobs board remembers Board/List.
const VIEW_KEY = 'careerCompaniesView';
// The one shape of this page's filters, and so the one list of its facet
// keys: the labels moved into the component with CAREER-116 (they are
// catalog keys now, which only a hook can resolve), and this object is
// what tells the stored-filter reader below which keys exist.
const EMPTY_FILTERS = { sector: [], size: [], openJobs: [] };
const FILTER_KEYS = Object.keys(EMPTY_FILTERS);
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

// Counted and cut by character, not by UTF-16 code unit: an astral
// character (an emoji, some CJK extensions) straddling the limit would
// otherwise be cut into a lone surrogate and render as a replacement
// glyph.
function displayName(name) {
  const characters = Array.from(name || '');
  return characters.length > NAME_LIMIT ? `${characters.slice(0, NAME_LIMIT).join('')}…` : name || '';
}

// The chip reads "No open jobs", "1 open job" or "N open jobs". The count
// variation is real, so the catalog carries it as an ICU plural rather
// than this function choosing the noun.
function openJobsChip(formatMessage, count) {
  if (count === 0) return { text: formatMessage({ id: 'companies.noOpenJobs' }), type: 'neutral' };
  return { text: formatMessage({ id: 'companies.openJobsChip' }, { count }), type: 'info' };
}

function companyHref(id) {
  return `/companies/${encodeURIComponent(id)}`;
}

// Filters live in localStorage, like the board's own view and toggle
// (owner decision: no URL sync). A stored value is merged onto the empty
// shape and sanitized to lists of strings, so a key left behind by an
// older shape cannot break the page -- which is what happens to the
// `needsAttention` flag the removed "Needs your input" toggle wrote (B5):
// it is simply not read any more.
function readStoredFilters() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(FILTERS_KEY) || '{}');
    return Object.fromEntries(
      FILTER_KEYS.map((key) => [
        key,
        (Array.isArray(stored[key]) ? stored[key] : []).filter((value) => typeof value === 'string'),
      ]),
    );
  } catch {
    return EMPTY_FILTERS;
  }
}

function readStoredView() {
  try {
    return window.localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'tiles';
  } catch {
    return 'tiles';
  }
}

export default function CompaniesList() {
  const { formatMessage } = useIntl();
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [filters, setFilters] = useState(readStoredFilters);
  const [view, setView] = useState(readStoredView);
  const [sortColumn, setSortColumn] = useState(null);
  const [ascending, setAscending] = useState(true);

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
      window.localStorage.setItem(FILTERS_KEY, JSON.stringify(filters));
    } catch {
      // localStorage unavailable; the filter choice just will not persist.
    }
  }, [filters]);

  function persistView(nextView) {
    setView(nextView);
    try {
      window.localStorage.setItem(VIEW_KEY, nextView);
    } catch {
      // localStorage unavailable; view choice just will not persist.
    }
  }

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
  const sectorLabels = useCallback(
    // Defaulted like counts/isic_sections/size_classes, so a bundle
    // served by a server that predates the key still renders.
    (company) =>
      ((page?.sector_labels || {})[company.id] || []).join(', ') ||
      formatMessage({ id: 'companies.sectorUnknown' }),
    [page, formatMessage],
  );

  const sectorOptions = useMemo(() => {
    const labels = Object.fromEntries((page?.isic_sections || []).map((section) => [section.code, section.label]));
    return sortedOptions(
      countBy(entries, (company) => company.sectors || []),
      (code) => labels[code] || code,
    );
  }, [entries, page]);

  // The one size vocabulary, as the backend sent it: [code, label] pairs,
  // so the facet, the tile and the row all say "Very large" where the
  // record carries `xl` (CAREER-71). Shown by the label and filtered by
  // the code, which is what makes the two lines below one list.
  const sizeClasses = useMemo(() => labelPairs(page?.size_classes), [page]);
  const sizeLabels = useMemo(() => new Map(sizeClasses), [sizeClasses]);
  // A class the vocabulary does not carry falls back to the stored code
  // rather than to a word nothing said.
  const sizeText = useCallback(
    (company) =>
      company.size_class
        ? sizeLabels.get(company.size_class) || company.size_class
        : formatMessage({ id: 'companies.sizeUnknown' }),
    [sizeLabels, formatMessage],
  );

  const sizeOptions = useMemo(
    () => presentOptions(sizeClasses, countBy(entries, (company) => [company.size_class])),
    [entries, sizeClasses],
  );

  // The bar's three facet chips, in the order it draws them. Every id is
  // a literal, so scripts/check_i18n.py can see which keys this file uses.
  // "Sector", "Size" and "Open jobs" are also the list view's own column
  // headings, so the two read the same catalog keys rather than two
  // spellings of one word.
  const filterGroups = useMemo(
    () => [
      { key: 'sector', label: formatMessage({ id: 'companies.field.sector' }) },
      { key: 'size', label: formatMessage({ id: 'companies.field.size' }) },
      { key: 'openJobs', label: formatMessage({ id: 'companies.field.openJobs' }) },
    ],
    [formatMessage],
  );

  // The list view's columns, owner-approved (B4). Name and Open jobs sort;
  // the other three are what the tile already shows, in columns. There is
  // no column saying where a company came from: the owner asked for none,
  // and the list is the same universe whatever the source.
  const listColumns = useMemo(
    () => [
      { key: 'name', label: formatMessage({ id: 'companies.field.name' }), sortable: true },
      { key: 'sector', label: formatMessage({ id: 'companies.field.sector' }) },
      { key: 'size', label: formatMessage({ id: 'companies.field.size' }) },
      { key: 'location', label: formatMessage({ id: 'companies.field.location' }) },
      { key: 'openJobs', label: formatMessage({ id: 'companies.field.openJobs' }), sortable: true },
    ],
    [formatMessage],
  );

  // "Any" is this facet's cleared state: with neither box checked every
  // company matches, so the two boxes say the only two things worth asking
  // for, and Clear (or Clear all) is what "Any" means.
  const openJobsOptions = useMemo(
    () =>
      [
        { value: 'with', label: formatMessage({ id: 'companies.openJobs.with' }) },
        { value: 'without', label: formatMessage({ id: 'companies.openJobs.without' }) },
      ].map((option) => ({
        ...option,
        count: entries.filter((company) => (openJobs(company) > 0) === (option.value === 'with')).length,
      })),
    [entries, openJobs, formatMessage],
  );

  const optionsByGroup = useMemo(
    () => ({ sector: sectorOptions, size: sizeOptions, openJobs: openJobsOptions }),
    [sectorOptions, sizeOptions, openJobsOptions],
  );

  // A company matches a group when it carries ANY of that group's checked
  // values (sector, size class, has/has not open jobs); an unchecked group
  // filters nothing. One predicate for both views, so the filters mean the
  // same records whichever one is showing (B4).
  const filtered = useMemo(
    () =>
      entries.filter((company) => {
        const sectorOk =
          filters.sector.length === 0 || (company.sectors || []).some((code) => filters.sector.includes(code));
        const sizeOk = filters.size.length === 0 || filters.size.includes(company.size_class);
        const openOk =
          filters.openJobs.length === 0 || filters.openJobs.includes(openJobs(company) > 0 ? 'with' : 'without');
        return sectorOk && sizeOk && openOk;
      }),
    [entries, filters, openJobs],
  );

  // Sorting is the list view's own, over the filtered set: by name, or by
  // the open-jobs number the chip shows. A name sorts case- and
  // accent-insensitively through localeCompare; the count sorts
  // numerically, because "10" before "2" is not an order anybody asked
  // for.
  const sorted = useMemo(() => {
    if (sortColumn === null) return filtered;
    const copy = [...filtered];
    copy.sort((a, b) => {
      const direction = ascending ? 1 : -1;
      if (sortColumn === 'openJobs') return (openJobs(a) - openJobs(b)) * direction;
      return String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true }) * direction;
    });
    return copy;
  }, [filtered, sortColumn, ascending, openJobs]);

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
  if (!page) {
    return (
      <Box padding={6}>
        <Text>
          <FormattedMessage id="companies.loading" />
        </Text>
      </Box>
    );
  }

  const isEmpty = entries.length === 0;
  const noMatches = !isEmpty && filtered.length === 0;

  // Companies has no main action, so its header stack is the view pair
  // and the filter bar (brief 2026-10-18, section 3). The pair sits where
  // Board and List sit on Jobs, and is the same control as there: one
  // SegmentedControl since CAREER-118 PR 1.
  const header = isEmpty ? null : (
    <>
      <Flex gap={2} alignItems="center" wrap>
        <SegmentedControl
          ariaLabel={formatMessage({ id: 'common.view.groupLabel' })}
          value={view}
          onChange={persistView}
          items={[
            {
              value: 'tiles',
              label: formatMessage({ id: 'companies.view.tiles' }),
              dataTestId: 'view-chip-tiles',
            },
            {
              value: 'list',
              label: formatMessage({ id: 'common.view.list' }),
              dataTestId: 'view-chip-list',
            },
          ]}
        />
      </Flex>
      <FilterBar
        groups={filterGroups}
        countNoun="companies"
        optionsByGroup={optionsByGroup}
        selected={filters}
        onToggleValue={toggleFilterValue}
        onClearGroup={clearFilterGroup}
        onClearGroups={clearFilterGroups}
        resultCount={filtered.length}
        totalCount={entries.length}
      />
    </>
  );

  const tiles = (
    <Box dangerouslySetInlineStyle={{ __style: GRID_STYLE }}>
      {filtered.map((company) => {
        const chip = openJobsChip(formatMessage, openJobs(company));
        return (
          <Link key={company.id} href={companyHref(company.id)} display="block">
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
                <Text color="subtle" size="200" lineClamp={2} title={sectorLabels(company)}>
                  {sectorLabels(company)}
                </Text>
                <Text color="subtle" size="200">
                  {sizeText(company)}
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
  );

  const list = (
    <Box overflow="auto">
      <Table accessibilityLabel={formatMessage({ id: 'companies.tableLabel' })}>
        <Table.Header>
          <Table.Row>
            {listColumns.map(({ key, label, sortable }) =>
              sortable ? (
                <SortableHeaderCell
                  key={key}
                  label={label}
                  status={sortColumn === key ? 'active' : 'inactive'}
                  sortOrder={sortColumn === key && !ascending ? 'desc' : 'asc'}
                  onSortChange={() => {
                    setAscending(sortColumn === key ? !ascending : true);
                    setSortColumn(key);
                  }}
                />
              ) : (
                <Table.HeaderCell key={key}>
                  <Text weight="bold">{label}</Text>
                </Table.HeaderCell>
              ),
            )}
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {sorted.map((company) => {
            const chip = openJobsChip(formatMessage, openJobs(company));
            return (
              <Table.Row key={company.id}>
                <Table.Cell>
                  {/* Gestalt's Table.Row renders a plain <tr> and
                      forwards no extra props, so the row's own handle
                      lives here, the way a card carries one. */}
                  <span data-testid={`company-row-${company.id}`}>
                    <Link href={companyHref(company.id)} display="inlineBlock">
                      <Text color="link">{company.name}</Text>
                    </Link>
                  </span>
                </Table.Cell>
                <Table.Cell>
                  <Text>{sectorLabels(company)}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Text>{sizeText(company)}</Text>
                </Table.Cell>
                <Table.Cell>
                  {/* The company's own stored locations, the way the
                      profile header joins them. "Location unknown"
                      rather than a blank cell: a column that is
                      sometimes empty says nothing about why. */}
                  <Text>
                    {(company.locations || []).join(', ') ||
                      formatMessage({ id: 'companies.locationUnknown' })}
                  </Text>
                </Table.Cell>
                <Table.Cell>
                  <Badge type={chip.type} text={chip.text} />
                </Table.Cell>
              </Table.Row>
            );
          })}
        </Table.Body>
      </Table>
    </Box>
  );

  return (
    <PageLayout title={<FormattedMessage id="companies.title" />} header={header}>
      {isEmpty ? (
        <Text color="subtle">{page.empty}</Text>
      ) : noMatches ? (
        <Text color="subtle">
          <FormattedMessage id="companies.noMatches" />
        </Text>
      ) : view === 'list' ? (
        list
      ) : (
        tiles
      )}
    </PageLayout>
  );
}
