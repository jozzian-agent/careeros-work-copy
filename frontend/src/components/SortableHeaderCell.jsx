import { useEffect, useRef } from 'react';
import { Table, Text } from 'gestalt';

// Table.SortableHeaderCell never sets aria-sort on its <th> (still true in
// gestalt@177.0.12: the string "aria-sort" appears nowhere in the bundle);
// it only swaps the visible sort icon. This adapter sets the attribute
// directly on the ancestor <th> after render, which is the minimal fix
// since Table.HeaderCell does not accept extra DOM attributes either.
//
// Its own component since B4 (CAREER-91), because the Companies list view
// sorts by Name and Open jobs and would otherwise need a second copy of
// the same workaround.
export default function SortableHeaderCell({ label, status, sortOrder, onSortChange }) {
  const markerRef = useRef(null);

  useEffect(() => {
    const th = markerRef.current?.closest('th');
    if (!th) return;
    th.setAttribute('aria-sort', status === 'active' ? (sortOrder === 'desc' ? 'descending' : 'ascending') : 'none');
  }, [status, sortOrder]);

  return (
    <Table.SortableHeaderCell status={status} sortOrder={sortOrder} onSortChange={onSortChange}>
      <span ref={markerRef} style={{ display: 'contents' }}>
        <Text weight="bold">{label}</Text>
      </span>
    </Table.SortableHeaderCell>
  );
}
