import { useCallback, useEffect, useState } from 'react';
import { Box, Button, Flex, Heading, PageHeader, Table, Text } from 'gestalt';
import { fetchTaxonomy } from '../api/taxonomy.js';

function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function CountTable({ accessibilityLabel, labelHeading, rows, getKey, getLabel }) {
  return (
    <Box overflow="auto">
      <Table accessibilityLabel={accessibilityLabel}>
        <Table.Header>
          <Table.Row>
            <Table.HeaderCell>
              <Text weight="bold">{labelHeading}</Text>
            </Table.HeaderCell>
            <Table.HeaderCell>
              <Text weight="bold">Count</Text>
            </Table.HeaderCell>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {rows.map((row) => (
            <Table.Row key={getKey(row)}>
              <Table.Cell>
                <Text>{getLabel(row)}</Text>
              </Table.Cell>
              <Table.Cell>
                <Text>{row.count}</Text>
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </Box>
  );
}

// Read-only methodology page (owner gate findings, 2026-10-13): how skills,
// industries and company sizes are derived and counted across the vault.
// No editing lives here -- every count is a vault-wide aggregate, not a
// single record a popup could edit.
export default function Taxonomy() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const load = useCallback(() => {
    fetchTaxonomy()
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
        <Text>Loading taxonomy…</Text>
      </Box>
    );
  }

  const { skills, industries, sizes } = page;

  return (
    <Box padding={6}>
      <PageHeader title="Taxonomy" />
      <Flex direction="column" gap={6} maxWidth={720}>
        <Box>
          <Heading size="400">Skills</Heading>
          <Box marginTop={1} marginBottom={3}>
            <Text color="subtle">Skills used across your experiences.</Text>
          </Box>
          <CountTable
            accessibilityLabel="Skills"
            labelHeading="Skill"
            rows={skills}
            getKey={(row) => row.skill}
            getLabel={(row) => row.skill}
          />
        </Box>
        <Box>
          <Heading size="400">Industries</Heading>
          <Box marginTop={1} marginBottom={3}>
            <Text color="subtle">Companies by ISIC industry section.</Text>
          </Box>
          <CountTable
            accessibilityLabel="Industries"
            labelHeading="Industry"
            rows={industries}
            getKey={(row) => row.code}
            getLabel={(row) => row.label}
          />
        </Box>
        <Box>
          <Heading size="400">Company size</Heading>
          <Box marginTop={1} marginBottom={3}>
            <Text color="subtle">Companies by size class.</Text>
          </Box>
          <CountTable
            accessibilityLabel="Company size"
            labelHeading="Size"
            rows={sizes}
            getKey={(row) => row.size_class}
            getLabel={(row) => titleCase(row.size_class)}
          />
        </Box>
      </Flex>
    </Box>
  );
}
