// The job facets, shared by the two surfaces that filter jobs: My Jobs
// and the All jobs tab (B2, CAREER-89). Both read the same payload
// (`GET /api/jobs?view=board|universe`), so the groups, the option lists
// and the predicate live here once rather than being copied into the
// second page -- a copy would let the two drift into filtering the same
// records by different rules.
import { countBy, labelPairs, presentOptions, sortedOptions } from './filters.js';

// No Fit facet: fit is not calculated, so neither surface offers a filter
// for it (D7 removed the chip the JOZ-279 bar still had).
export const JOB_FILTER_GROUPS = [
  { key: 'function', label: 'Function' },
  { key: 'location', label: 'Location' },
  { key: 'industry', label: 'Industry', legend: 'Industry (estimated)', inMore: true },
  { key: 'companySize', label: 'Company size', legend: 'Company size (estimated)', inMore: true },
];

export const EMPTY_JOB_FILTERS = { function: [], location: [], industry: [], companySize: [] };

export function titleCase(value) {
  return value.length ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

// One option list per group, counted over the payload's own entries.
// Function keeps the vault's own label list and order; Location and
// Industry come from the data; Company size is the one size scale the
// backend sends (`size_classes`), read off the linked company's class
// rather than bucketed from a posting's headcount in the browser. Both
// fixed vocabularies arrive as [code, label] pairs and are shown by the
// label the backend sent, never by a code this file dressed up.
export function jobFilterOptions(payload) {
  const entries = payload?.entries || [];
  const counts = countBy(entries, (job) => job.function || []);
  return {
    function: (payload?.function_options || []).map(([value, label]) => ({
      value,
      label,
      count: counts.get(value) || 0,
    })),
    location: sortedOptions(countBy(entries, (job) => [job.location])),
    industry: sortedOptions(countBy(entries, (job) => job.industries || [])),
    // Defaulted, not assumed: a bundle loaded against a server that
    // predates `size_classes` loses the facet's options, not the page.
    companySize: presentOptions(
      labelPairs(payload?.size_classes),
      countBy(entries, (job) => [job.company_size_class]),
    ),
  };
}

// A job matches a group when it carries ANY of that group's checked
// values; an unchecked group filters nothing. The two toggles are
// optional, because a surface decides which of them it offers: "Hide
// closed postings" is about the posting, so it hides a flagged job
// wherever it sits.
export function filterJobs(entries, filters, { needsAttention = false, hideClosed = false } = {}) {
  return entries.filter((job) => {
    const functionOk = filters.function.length === 0 || (job.function || []).some((f) => filters.function.includes(f));
    const locationOk = filters.location.length === 0 || filters.location.includes(job.location);
    const industryOk = filters.industry.length === 0 || (job.industries || []).some((v) => filters.industry.includes(v));
    const sizeOk = filters.companySize.length === 0 || filters.companySize.includes(job.company_size_class);
    const needsOk = !needsAttention || job.needs_attention;
    const closedOk = !hideClosed || !job.closed;
    return functionOk && locationOk && industryOk && sizeOk && needsOk && closedOk;
  });
}
