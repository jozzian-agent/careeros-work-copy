import { useCallback, useEffect, useState } from 'react';
import { Badge, Box, Button, ButtonLink, Flex, Heading, Link, PageHeader, Text } from 'gestalt';
import { fetchExperiencesPage } from '../api/experiences.js';
import { tagLabel } from '../tags.js';

export default function ExperiencesList() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const load = useCallback(() => {
    fetchExperiencesPage()
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
        <Text>Loading experiences…</Text>
      </Box>
    );
  }

  const { entries, empty, companies, labels, tag_labels: tagLabels } = page;

  return (
    <Box padding={6}>
      <PageHeader
        title="Experiences"
        primaryAction={{
          component: <ButtonLink href="/experiences/new" text="Add position" color="red" target="self" />,
          dropdownItems: [],
        }}
      />
      <Box marginTop={4}>
        {entries.length === 0 ? (
          <Box rounding={4} borderStyle="sm" padding={6} color="default">
            <Flex direction="column" gap={3} alignItems="center">
              <Text align="center" color="subtle">
                {empty}
              </Text>
              <ButtonLink href="/experiences/new" text="Add position" color="red" target="self" />
            </Flex>
          </Box>
        ) : (
          <Flex direction="column" gap={3}>
            {entries.map((exp) => {
              const companyHref = exp.company_id && companies[exp.company_id] ? `/companies/${encodeURIComponent(exp.company_id)}` : null;
              const label = labels[exp.id];
              return (
                <Box key={exp.id} rounding={4} borderStyle="sm" padding={4} color="default">
                  <Flex direction="column" gap={2}>
                    <Link href={`/experiences/${encodeURIComponent(exp.id)}`} display="inlineBlock">
                      <Heading size="300">{exp.title}</Heading>
                    </Link>
                    {companyHref ? (
                      <Link href={companyHref} display="inlineBlock">
                        <Text color="link">{label}</Text>
                      </Link>
                    ) : (
                      <Text>{label}</Text>
                    )}
                    <Text color="subtle">
                      {exp.start} – {exp.end} · {exp.location}
                    </Text>
                    <Flex gap={2} wrap>
                      {(exp.skills || []).map((skill) => (
                        <Badge key={skill} text={skill} />
                      ))}
                      {(exp.tags || []).map((tag) => {
                        const entry = tagLabels[tag];
                        return (
                          <Flex key={tag} gap={1} alignItems="center">
                            <Badge text={tagLabel(tag, tagLabels)} />
                            {entry?.local ? (
                              <span title="Local extension, not mapped to an ISCO group">
                                <Badge text="local" />
                              </span>
                            ) : null}
                          </Flex>
                        );
                      })}
                      {exp.people_led !== null && exp.people_led !== undefined ? (
                        <Badge text={`Led ${exp.people_led} people`} />
                      ) : null}
                    </Flex>
                  </Flex>
                </Box>
              );
            })}
          </Flex>
        )}
      </Box>
    </Box>
  );
}
