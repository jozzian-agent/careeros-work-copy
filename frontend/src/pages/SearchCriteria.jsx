import { useCallback, useEffect, useState } from 'react';
import { BannerSlim, Box, Button, Flex, Text, TextArea, TextField } from 'gestalt';
import PageLayout from '../components/PageLayout.jsx';
import { fetchSearchPage, saveSearch } from '../api/search.js';
import SectionCard, { DividerList } from '../components/SectionCard.jsx';

const REMOVE_BUTTON_STYLE = {
  marginLeft: 12,
  color: 'var(--color-text-error)',
  border: 'none',
  background: 'none',
  cursor: 'pointer',
  fontSize: 16,
  lineHeight: '22px',
  padding: 0,
};

export default function SearchCriteria() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [criteria, setCriteria] = useState(null);
  const [backup, setBackup] = useState(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [drafts, setDrafts] = useState({});

  const load = useCallback(() => {
    fetchSearchPage()
      .then((data) => {
        setPage(data);
        setCriteria(data.data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate() {
    setError(null);
    try {
      await saveSearch({});
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function startEdit() {
    if (busy || editing) return;
    setBackup(structuredClone(criteria));
    setEditing(true);
  }

  function cancelEdit() {
    if (busy || !editing) return;
    setCriteria(backup);
    setBackup(null);
    setEditing(false);
    setDrafts({});
    setError(null);
  }

  async function finishEdit() {
    if (busy || !editing) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await saveSearch(criteria);
      setCriteria(saved);
      setBackup(null);
      setEditing(false);
      setDrafts({});
    } catch (err) {
      // Keep edits, stay in edit mode so the owner can retry.
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function removeItem(key, index) {
    if (busy || !editing) return;
    setCriteria((prev) => ({ ...prev, [key]: prev[key].filter((_, i) => i !== index) }));
  }

  function addItem(key) {
    const value = (drafts[key] || '').trim();
    if (!value || busy || !editing) return;
    setCriteria((prev) => ({ ...prev, [key]: [...prev[key], value] }));
    setDrafts((prev) => ({ ...prev, [key]: '' }));
  }

  function setNotes(value) {
    setCriteria((prev) => ({ ...prev, notes: value }));
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
        <Text>Loading your criteria…</Text>
      </Box>
    );
  }

  if (criteria === null) {
    return (
      <PageLayout title="Search">
        <Box rounding={4} borderStyle="sm" padding={6} color="default">
          <Flex direction="column" gap={3} alignItems="center">
            <Text align="center" color="subtle">
              {page.empty}
            </Text>
            <Button text="Create criteria" color="red" onClick={handleCreate} />
            {error ? <BannerSlim type="error" message={error} onDismiss={() => setError(null)} /> : null}
          </Flex>
        </Box>
      </PageLayout>
    );
  }

  return (
    <PageLayout title="Search">
      <Flex direction="column" gap={5} maxWidth={880}>
        <Flex justifyContent="end" gap={2}>
          {editing ? (
            <>
              <Button text="Done" color="red" disabled={busy} onClick={finishEdit} />
              <Button text="Cancel" disabled={busy} onClick={cancelEdit} />
            </>
          ) : (
            <Button text="Edit criteria" color="red" disabled={busy} onClick={startEdit} />
          )}
        </Flex>
        {error ? <BannerSlim type="error" message={error} onDismiss={() => setError(null)} /> : null}
        {page.sections.map(([key, label]) => {
          const items = criteria[key] || [];
          return (
            <SectionCard key={key} title={label}>
              {items.length ? (
                <DividerList
                  items={items}
                  renderItem={(item, index) => (
                    <Flex justifyContent="between" alignItems="center">
                      <Text>{item}</Text>
                      {editing ? (
                        <button
                          type="button"
                          aria-label={`Remove ${item}`}
                          disabled={busy}
                          onClick={() => removeItem(key, index)}
                          style={REMOVE_BUTTON_STYLE}
                        >
                          ×
                        </button>
                      ) : null}
                    </Flex>
                  )}
                />
              ) : (
                <Text color="subtle">No items yet.</Text>
              )}
              {editing ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    addItem(key);
                  }}
                >
                  <Flex gap={2}>
                    <Box dangerouslySetInlineStyle={{ __style: { flex: '1 1 auto', minWidth: 0 } }}>
                      <TextField
                        id={`add-${key}`}
                        label={`New ${label.toLowerCase()} item`}
                        labelDisplay="hidden"
                        placeholder="Add an item"
                        value={drafts[key] || ''}
                        disabled={busy}
                        onChange={({ value }) => setDrafts((prev) => ({ ...prev, [key]: value }))}
                      />
                    </Box>
                    <Button text="Add" type="submit" disabled={busy} />
                  </Flex>
                </form>
              ) : null}
            </SectionCard>
          );
        })}
        <SectionCard title="Notes">
          {editing ? (
            <TextArea
              id="search-notes"
              label="Notes"
              labelDisplay="hidden"
              value={criteria.notes || ''}
              disabled={busy}
              onChange={({ value }) => setNotes(value)}
            />
          ) : (
            <Box dangerouslySetInlineStyle={{ __style: { whiteSpace: 'pre-wrap' } }}>
              <Text color={criteria.notes ? undefined : 'subtle'}>{criteria.notes || 'No notes yet.'}</Text>
            </Box>
          )}
        </SectionCard>
      </Flex>
    </PageLayout>
  );
}
