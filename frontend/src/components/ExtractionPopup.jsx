import { Button, Flex, Modal, Text } from 'gestalt';
import { DividerList } from './SectionCard.jsx';
import { localDate } from '../dates.js';

// "How this was extracted": one row per field the reader covers, with
// what came of it and where that came from. This replaces the Extraction
// card and its row of status badges, which put eight machine states on
// the page permanently to answer a question that is only asked once.
//
// Field order matches careeros/ingest.py STATUS_FIELDS.
const FIELDS = [
  { key: 'title', label: 'Title', setter: 'job' },
  { key: 'company', label: 'Company', setter: null },
  { key: 'location', label: 'Location', setter: 'job' },
  { key: 'function', label: 'Function', setter: 'classification' },
  { key: 'seniority', label: 'Seniority', setter: null },
  { key: 'employment_type', label: 'Employment type', setter: null },
  { key: 'skills', label: 'Skills', setter: 'job' },
  { key: 'description_structured', label: 'Description', setter: 'job' },
  // The five requirement groups are reported as the one field they are
  // stored in: the reader says whether the posting yielded grouped
  // requirements and who grouped them, and it has nothing to say per
  // group, so a row per group would be five invented states.
  { key: 'requirement_groups', label: 'Requirements', setter: 'job' },
];

// The one label the extraction row reads out of the resolved history, so
// it can say when the posting was last read. Owned by
// careeros/history.py READ_LABEL; tests/test_history_registry.py pins the
// value this surface depends on.
const READ_LABEL = 'Details read from the posting';

// When the posting was last read, out of the resolved history, or null.
export function readTimestamp(history) {
  const entry = (history || []).filter((item) => item.label === READ_LABEL).pop();
  return entry ? entry.ts : null;
}

// The one sentence about the last read. The extraction row and this
// popup's header both read it from here, so they cannot disagree about
// when the posting was read -- the owner asked for the same fact in both
// places, which makes it one fact with one home.
export function readSentence(ts) {
  return ts ? `Read from the posting on ${localDate(ts)}.` : 'This posting has not been read yet.';
}

// field_status values, in the words the page uses for them.
const RESULTS = {
  done: 'Found',
  not_evidenced: 'Not found in posting',
  failed: 'Failed',
  pending: 'Pending',
};

// field_provenance values. 'scrape' is the offline rules reading the page
// itself; 'llm' is the model; 'user' is the owner having corrected it.
const SOURCES = { scrape: 'Page data', llm: 'AI', user: 'You' };

// The result for one field, or null when the reader never reported on it.
export function extractionRows(job) {
  const status = job.field_status || {};
  const provenance = job.field_provenance || {};
  return FIELDS.filter((field) => status[field.key]).map((field) => ({
    ...field,
    status: status[field.key],
    result: RESULTS[status[field.key]] || status[field.key],
    // Where a value came from is only a fact once there is a value. A
    // field nothing was found for has no source, and saying "AI" there
    // would credit the model with a value it did not produce.
    source: status[field.key] === 'done'
      ? SOURCES[provenance[field.key]] || 'Not recorded'
      : null,
  }));
}

export function notFoundLabels(rows) {
  return rows.filter((row) => row.status === 'not_evidenced').map((row) => row.label);
}

// Where a field that was not found can be set, when anywhere can. The
// setter labels are the page's own buttons, so the row sends the owner to
// a surface that exists rather than naming a field they cannot reach.
const SETTERS = { job: 'Set it in Edit job', classification: 'Set it in Edit classification' };

export default function ExtractionPopup({ job, readAt, onDismiss, onOpenSetter }) {
  const rows = extractionRows(job);
  return (
    <Modal
      accessibilityModalLabel="How this was extracted"
      heading="How this was extracted"
      size={480}
      onDismiss={onDismiss}
      footer={
        <Flex justifyContent="end">
          <Button text="Close" color="gray" onClick={onDismiss} />
        </Flex>
      }
    >
      <Flex direction="column" gap={3}>
        {/* When the posting was read, above the per-field rows: the owner
            asked the same question the extraction row answers, so the
            popup answers it too instead of only listing fields. */}
        <Text color="subtle">{readSentence(readAt)}</Text>
        {rows.length ? (
          <DividerList
            items={rows.map((row) => ({ ...row, key: row.key }))}
            renderItem={(row) => (
              <Flex direction="column" gap={1}>
                <Flex gap={3} justifyContent="between" alignItems="center" wrap>
                  <Text weight="bold" size="200">
                    {row.label}
                  </Text>
                  <Text size="200" color="subtle">
                    {row.source ? `${row.result} · ${row.source}` : row.result}
                  </Text>
                </Flex>
                {row.status === 'not_evidenced' && row.setter ? (
                  <Button
                    text={SETTERS[row.setter]}
                    size="sm"
                    color="transparent"
                    onClick={() => onOpenSetter(row.setter)}
                  />
                ) : null}
              </Flex>
            )}
          />
        ) : (
          <Text color="subtle">Nothing was reported field by field.</Text>
        )}
      </Flex>
    </Modal>
  );
}
