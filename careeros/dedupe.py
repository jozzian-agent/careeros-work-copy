"""Hard duplicate check for Journey 1, Step 2: instant, no network calls.

Compares a candidate normalized_url and detected ATS posting id against
every job the adding user already has (pipeline and universe records
alike). Never merges, never silently drops; the caller decides what to do
with the match.

M2 (CAREER-39, decision D4): the comparison is against that user's own
jobs and no further. A posting belongs to whoever added it, so the same
link added by two users is two records and not a duplicate, and the
warning payload names a job id and title -- telling one user that another
user holds the posting would be the existence leak D3 forbids.
"""
from careeros import vault


def find_duplicate(root, normalized_url, ats_match, owner=None):
    """Return (existing_job, basis) or (None, None)."""
    # list_owned_jobs, not list_jobs: a universe-only record is exactly
    # what this check has to be able to find. The payload below offers
    # `promote` for one, and a pasted link that matched a pool posting
    # and was told "no duplicate" would add the posting a second time.
    jobs = vault.list_owned_jobs(root, owner)
    if normalized_url:
        match = next((job for job in jobs if job.get('normalized_url') == normalized_url), None)
        if match:
            return match, 'same_url'
    if ats_match is not None:
        # Every supported ATS scopes its posting id to a tenant (one
        # employer's board); the same slug/id under a different tenant is
        # an unrelated posting, not a duplicate (JOZ-265 fix round, M4).
        match = next((job for job in jobs if job.get('ats_provider') == ats_match.provider
                      and job.get('ats_tenant') == ats_match.tenant
                      and job.get('ats_posting_id') == ats_match.posting_id), None)
        if match:
            return match, 'same_ats_posting_id'
    return None, None


def duplicate_payload(existing, basis):
    """JSON-ready warning payload: existing record, match basis, actions.

    Primary action is 'open_existing', unless the match is a universe
    record not yet in the pipeline, in which case the normal Journey 2
    case is promoting it instead. 'add_anyway' is always offered alongside
    the primary action(s) (R4): never merge/auto-drop, and never force the
    caller through promote/open_existing when a genuinely separate record
    is what they want. A real dismissal (create nothing) is the caller's
    own UI affordance, not a listed action here.
    """
    actions = (['promote', 'open_existing'] if existing.get('in_pipeline') is False
               else ['open_existing']) + ['add_anyway']
    return {
        'duplicate': True,
        'basis': basis,
        'existing': {
            'id': existing['id'],
            'title': existing.get('title', ''),
            'in_pipeline': existing.get('in_pipeline', True),
        },
        'actions': actions,
    }
