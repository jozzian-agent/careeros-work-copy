import { useMemo, useState } from 'react';
import { Box, Flex, Link, SelectList, Table, Text } from 'gestalt';
import { useIntl } from 'react-intl';
import { CompanyDisplay, IngestIndicator } from './JobCard.jsx';
import SortableHeaderCell from './SortableHeaderCell.jsx';
import { titleCase } from '../jobFilters.js';

function jobHref(id) {
  return `/jobs/${encodeURIComponent(id)}`;
}

// `column` indexes the list view's own columns, in the order JobsListView
// below builds them (title, company, source, status, location, posted,
// added). The two lists are read together and must stay in step.
export function sortEntries(entries, column, ascending) {
  if (column === null) return entries;
  const getField = [
    (job) => job.title,
    (job) => job.company_name || '',
    (job) => job.source || '',
    (job) => job.status,
    (job) => job.location || '',
    (job) => job.posted_date || '',
    (job) => job.added || '',
  ][column];
  const copy = [...entries];
  copy.sort((a, b) => getField(a).localeCompare(getField(b), undefined, { numeric: true }) * (ascending ? 1 : -1));
  return copy;
}

// The sortable job table, extracted from JobsBoard (CAREER-121 follow-up,
// owner request 2026-11-01) so the All jobs tab can offer the same List
// view without a second table that could drift from this one. List view
// is untouched by the board rebuilds (JOZ-278 and D7 are both
// board-only), apart from reading the status words from the payload the
// way every other surface now does. `onRetry` stays optional: All jobs
// has no retry action, and the chip simply renders without its button.
export default function JobsListView({ entries, statusLabels, onRetry }) {
  const { formatMessage } = useIntl();
  const [sortColumn, setSortColumn] = useState(null);
  const [ascending, setAscending] = useState(true);
  const sorted = useMemo(() => sortEntries(entries, sortColumn, ascending), [entries, sortColumn, ascending]);
  // The columns in order, which is also the order sortEntries() reads its
  // fields in. Every id is a literal, so scripts/check_i18n.py can see
  // which catalog keys this file uses.
  const columns = useMemo(
    () => [
      formatMessage({ id: 'board.list.column.title' }),
      formatMessage({ id: 'board.list.column.company' }),
      formatMessage({ id: 'board.list.column.source' }),
      formatMessage({ id: 'board.list.column.status' }),
      formatMessage({ id: 'board.list.column.location' }),
      formatMessage({ id: 'board.list.column.posted' }),
      formatMessage({ id: 'board.list.column.added' }),
    ],
    [formatMessage],
  );

  function sortBy(column, direction) {
    setSortColumn(column);
    setAscending(direction);
  }

  return (
    <Box>
      <Box display="block" mdDisplay="none" marginBottom={3} maxWidth={280}>
        <SelectList
          id="job-sort"
          label={formatMessage({ id: 'board.list.sortBy' })}
          placeholder={formatMessage({ id: 'board.list.sortPlaceholder' })}
          value={sortColumn === null ? null : `${sortColumn}:${ascending ? 'asc' : 'desc'}`}
          onChange={({ value }) => {
            const [column, direction] = value.split(':');
            sortBy(Number(column), direction === 'asc');
          }}
        >
          {columns.flatMap((label, index) => [
            <SelectList.Option
              key={`${index}-asc`}
              label={formatMessage({ id: 'board.list.sortAscending' }, { column: label })}
              value={`${index}:asc`}
            />,
            <SelectList.Option
              key={`${index}-desc`}
              label={formatMessage({ id: 'board.list.sortDescending' }, { column: label })}
              value={`${index}:desc`}
            />,
          ])}
        </SelectList>
      </Box>
      <Box overflow="auto">
        <Table accessibilityLabel={formatMessage({ id: 'board.list.tableLabel' })}>
          <Table.Header>
            <Table.Row>
              {columns.map((label, index) => (
                <SortableHeaderCell
                  key={label}
                  label={label}
                  status={sortColumn === index ? 'active' : 'inactive'}
                  sortOrder={sortColumn === index && !ascending ? 'desc' : 'asc'}
                  onSortChange={() => sortBy(index, sortColumn === index ? !ascending : true)}
                />
              ))}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {sorted.map((job) => (
              <Table.Row key={job.id}>
                <Table.Cell>
                  <Link href={jobHref(job.id)} display="inlineBlock">
                    <Text color="link">{job.title}</Text>
                  </Link>
                </Table.Cell>
                <Table.Cell>
                  <CompanyDisplay job={job} />
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.source}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Flex direction="column" gap={1}>
                    <Text>{statusLabels[job.status] || titleCase(job.status)}</Text>
                    <IngestIndicator job={job} onRetry={onRetry} />
                  </Flex>
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.location || ''}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.posted_date || ''}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Text>{job.added}</Text>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
      </Box>
    </Box>
  );
}
