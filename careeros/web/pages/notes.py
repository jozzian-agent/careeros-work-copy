"""Every note in the vault, with the record each one belongs to."""
from careeros import vault

EMPTY_STATE = 'No notes yet. A note is added from a job or a company page.'

# One row's worth of body text. The page shows a note's first line; the
# whole body sits on the record's own page, which the row links to.
PREVIEW_LIMIT = 120


def body_preview(body):
    """A note's first non-empty line, shortened to one row."""
    first = next((line.strip() for line in str(body or '').splitlines() if line.strip()), '')
    return first if len(first) <= PREVIEW_LIMIT else first[:PREVIEW_LIMIT].rstrip() + '…'


def page_context(root, owner=None):
    # M2 (CAREER-39): the job half is this user's own jobs, so a note on
    # somebody else's job is not listed and not countable. CAREER-41:
    # the company half is now private the same way -- `visible_companies`
    # answers each company with only the notes this reader owns (plus
    # the legacy authorless ones for the admin), so one user's company
    # note is listed for nobody else.
    #
    # `list_jobs` is the board read, so a universe-only pool posting is
    # not walked here (CAREER-72/74). Nothing is lost by it: a note is
    # written from a record's own page by a person, and nobody has
    # written one on a posting the feed imported this morning.
    return notes_context(vault.list_jobs(root, owner), vault.visible_companies(root, owner))


def notes_context(jobs, companies):
    """Every note across jobs and companies, newest first.

    Read-only aggregation. The page it feeds links through to the record a
    note lives in rather than editing the note there, so a note keeps one
    editing surface and not two. Each row names its record because living
    in that record's file is the only thing that associates them, and a
    note the owner cannot trace back to a job or a company is a note they
    cannot act on.

    Every row carries all four association keys, two of them null: one
    shape is easier to render and to pin than an optional one.
    """
    rows = []
    for job in jobs:
        for note in vault.notes_view(job):
            rows.append(_row(note) | {'job_id': job.get('id'), 'job_title': job.get('title'),
                                      'company_id': None, 'company_name': None})
    for company in companies:
        for note in vault.notes_view(company):
            rows.append(_row(note) | {'job_id': None, 'job_title': None,
                                      'company_id': company.get('id'), 'company_name': company.get('name')})
    # A note migrated out of the legacy free-text field has no created
    # date, and it is the oldest note its record holds, so an empty sort
    # key putting it last is the right answer rather than a fallback.
    rows.sort(key=lambda row: str(row['created'] or ''), reverse=True)
    return dict(notes=rows, empty=EMPTY_STATE)


def _row(note):
    return {'id': note['id'], 'title': note['title'],
            'body_preview': body_preview(note['body']),
            'created': note['created'], 'updated': note['updated']}
