"""Flask entry point for the CareerOS shell."""

import argparse
from contextlib import nullcontext
from html import escape
import os
from threading import RLock, Thread
from pathlib import Path
from urllib.parse import urlsplit, unquote

from flask import Flask, request, jsonify, redirect, send_from_directory, url_for
from careeros import vault as storage
from careeros import intake
from careeros import ingest
from careeros import users
from org_intake import classify as sectors
from org_intake import enrich as org_enrich
from careeros import enrich as company_enrichment
from careeros.org_store import CompanyCreationDenied, VaultOrganisationStore
from org_intake import identity, ats
from org_intake.url import normalize_url
from careeros.intake import posting_ats
from careeros import dedupe
from careeros.extraction_worker import ai_queue
import difflib

from careeros.web import ui
from careeros.web.pages import companies, experiences, jobs, notes, search, taxonomy
from careeros.web.theme import page_shell

_ATS_FEED_URL = {
    'greenhouse': 'https://boards.greenhouse.io/{tenant}',
    'lever': 'https://jobs.lever.co/{tenant}',
    'ashby': 'https://jobs.ashbyhq.com/{tenant}',
    'smartrecruiters': 'https://jobs.smartrecruiters.com/{tenant}',
    'recruitee': 'https://{tenant}.recruitee.com',
    'teamtailor': 'https://{tenant}.teamtailor.com/jobs',
    'personio': 'https://{tenant}.jobs.personio.de',
    'workday': 'https://{tenant}.myworkdayjobs.com',
    'refline': 'https://m.refline.ch/{tenant}',
    'join': 'https://{tenant}.join.com/jobs',
}


class AiFailed(Exception):
    """A failed unit of AI work whose own message is the owner-facing
    reason (CAREER-36).

    Raised by the queued work itself for the failures it can describe in
    plain words, so the reason stored on the record is a sentence rather
    than an exception type. Anything else that goes wrong is reported by
    type instead, see ai_reason.
    """


def ai_reason(error):
    """The sentence a failed reading stores in ai_error.

    An exception the queued work did not raise on purpose is reported by
    its type and never by its text: a transport failure's own message can
    name the host it was talking to, and a record is a file that gets
    copied around.
    """
    if isinstance(error, AiFailed):
        return str(error)
    return f'Enrichment failed ({type(error).__name__}).'


def _ats_feed_url(ats_match, fallback_url):
    template = _ATS_FEED_URL.get(ats_match['provider'])
    return template.format(tenant=ats_match['tenant']) if template else fallback_url


def add_source(root, company, kind, url, ats_provider=None):
    """Append one source, deduped by normalized url; last_polled stays null
    (Journey 2 polls, Journey 1 only records, per spec §5)."""
    if not url:
        return company
    normalized = normalize_url(url)
    sources = company.get('sources') or []
    if any(normalize_url(source.get('url') or '') == normalized for source in sources):
        return company
    new_source = {'id': f'SRC-{len(sources) + 1}', 'kind': kind, 'url': url,
                  'ats_provider': ats_provider, 'active': True, 'last_polled': None}
    return storage.save_company(root, {'sources': sources + [new_source]}, company['id'])



def tenant_employer_names(root, url, owner=None):
    """Every employer name the caller's own jobs record against one ATS
    tenant.

    Scoped since the M2 privacy review (owner decision 2026-10-18), and
    an earlier round of this work argued the opposite: that resolution
    should read the whole vault so one tenant resolved to one company
    for everybody. It cannot. `employer_named_in_posting` is text
    extracted from a private posting, and the ladder acts on it -- one
    foreign job on the same tenant is enough to turn a clean `linked`
    into `needs_review` with reason `shared_tenant`, and enough for an
    admin resolution to publish a tester's ATS association as an
    identifier on a shared company. Both are another user's private
    record changing what this user sees and what the shared half
    records.

    So the read is the caller's own: for a tester their own jobs, for
    the admin theirs plus the legacy ownerless records, which is what
    `vault.Owner` already means. Cross-user resolution consistency is
    traded away on purpose; see enrich.record_owner_scope and the
    PROJECT.md open question. The same scoping applies to
    `find_company`'s own tenant sweep below.
    """
    match = ats.detect_ats(url)
    return [job.get('employer_named_in_posting') for job in storage.list_jobs(root, owner)
            if match and job.get('ats_provider') == match['provider']
            and job.get('ats_tenant') == match['tenant']]


def record_company_source(root, company, url):
    match = ats.detect_ats(url)
    if match:
        return add_source(root, company, 'ats_feed', _ats_feed_url(match, url), match['provider'])
    if intake.domain(url):
        return add_source(root, company, 'careers_page', url)
    return company


def company_job_fields(result):
    review = result['review']
    if review is not None:
        review = {**review, 'at': storage.timestamp(), 'candidates': [
            {('company_id' if k == 'record_id' else k): v for k, v in c.items()}
            for c in review['candidates']]}
    reason = result['link_reason']
    return dict(company_id=result['record_id'], company_link_state=result['link_state'],
                company_link_reason='ambiguous_exact' if reason == 'ambiguous_exact_name_match' else reason,
                company_review=review)


def resolve_company(root, *, url, shared=True, owner=None, **kwargs):
    """Pass product evidence in and map capability output to stored job fields.

    `owner` is the ownership scope the jobs this resolution reads are
    read under (M2, owner decision 2026-10-18): the caller's own, never
    the whole vault. See tenant_employer_names.

    `shared` is whether the job being resolved may write the shared half
    (M2, decision D3; see enrich.contributes_to_shared). False means the
    posting resolves to a company that already exists and never brings
    one into existence, teaches it nothing, and has no careers page or
    ATS feed recorded onto it as a source.

    A posting whose company does not exist yet therefore answers
    `pending` with no company_id, which is the state the product already
    has for a posting whose employer it could not place. The job keeps
    the employer name as its own free text (the `company` field it was
    extracted into), so the owner still reads who the posting is from;
    what they do not get is a shared record nobody reviewed. Giving a
    tester's evidence a way into the shared half is the M3 merge queue
    (PROJECT.md open questions).
    """
    store = VaultOrganisationStore(root, shared=shared)
    try:
        result = identity.resolve_identity(store, url=url,
            tenant_employer_names=tenant_employer_names(root, url, owner), **kwargs)
    except CompanyCreationDenied:
        # The ladder reached its create rung. Nothing was written: every
        # other write it makes carries an id, and those are no-ops on a
        # store that may not write (see careeros.org_store).
        return company_job_fields(dict(record_id=None, link_state='pending',
                                       link_reason=None, review=None))
    if shared and result['record_id'] and result['link_state'] == 'linked':
        record_company_source(root, storage.load_company(root, result['record_id']), url)
    return company_job_fields(result)


DEFAULT_VAULT = Path('/root/career-os')

# M7 (JOZ-266 fix round): the new-company enrichment cascade (see
# schedule_company_cascade) is on by default -- a fresh company created by
# rung 4 gets the same sector/size enrichment an owner-triggered backfill
# would give it. A module-level switch (rather than a parameter threaded
# through create_app, which every test call site would need to learn
# about) lets the test suite's own offline network guard
# (tests/conftest.py) turn this off process-wide, since the cascade's
# default fetcher is intake.fetch_url -- the exact function most tests
# monkeypatch for their own posting-fetch mocking, with no relation to
# this feature at all.
AUTO_CASCADE_ENABLED = True


SHARED_ATS_HOSTS = (
    'lever.co', 'greenhouse.io', 'smartrecruiters.com', 'workday.com',
    'myworkdayjobs.com', 'icims.com', 'taleo.net', 'ashbyhq.com',
    'teamtailor.com', 'personio.de', 'recruitee.com',
)

# O1 (fix round 2): the generic job PUT marks every field it sets as
# owner-provenance, so later automation (Phase B, the LLM callback) never
# overwrites it -- except these, which are either not content fields worth
# protecting, already have their own dedicated handling, or would make the
# marking meaningless (field_provenance itself).
# M1 (JOZ-266 fix round): company_link_state and company_link_reason are
# NOT excluded -- they are owner-editable, and must get the same
# user-provenance protection as company_id itself, as a coherent group,
# whether the owner sets them directly or (via the company_id branch
# below) implicitly. company_review stays excluded: it is not itself a
# decision field, only automation-managed review metadata.
_PROVENANCE_EXCLUDED_FIELDS = frozenset({
    'field_provenance', 'history', 'id', 'added', 'status_changed',
    'summary_source', 'ingest_state', 'ingest_error', 'proposed_tags',
    'normalized_url', 'ats_provider', 'ats_tenant', 'ats_posting_id',
    'company_review',
})

# The company link is these three fields together: every writer sets them
# in one breath, every owner lock covers all three, and their provenance
# moves as a group (B3).
COMPANY_LINK_GROUP = ('company_id', 'company_link_state', 'company_link_reason')

# Every outcome the extract route's description refresh can reach, with the
# history event it writes. A table rather than an event type assembled from
# the outcome string: the event types stay literal and enumerable, so
# tests/test_history_registry.py can check them against the registry the
# same way it checks the ingest-state backstop.
REFRESH_EVENTS = {
    'ok': ('description_refreshed', 'Live posting refreshed.'),
    'failed': ('description_refresh_failed', 'Live page unavailable; enriching stored text.'),
    'skipped': ('description_refresh_skipped', 'No posting URL; enriching stored text.'),
}

# What a re-read that produced nothing tells the owner, and the two of
# those are not the same fact: a reading that ran and had nothing new to
# say, and a reading that never started at all. One sentence for both
# said the model had read the text in the case where no reader ever ran.
REREAD_FAILED_HISTORY = ('re_extract_failed', 'Reading the stored text again found nothing new.')
REREAD_NOT_STARTED_HISTORY = ('re_extract_not_started', 'Could not start the re-read.')

# Who the lines a re-read regroups belong to, by the `method` of the
# stored block they come from. The rules did the grouping either way, but
# the lines are whoever read or wrote them: a model's requirements called
# page data would lose the AI label off a section the model wrote, and
# the owner's own lines credited to the page would claim a reader for
# text the owner typed. Anything else (the offline section split, a raw
# block) is page data.
REREAD_PROVENANCE = {'llm': 'llm', 'user': 'user'}

# CAREER-36: what each outcome careeros.ingest reports for a reading that
# produced nothing says to the owner. A table rather than the raw reason
# string, because ai_error is shown on a card and 'unusable_output' is an
# internal word: AGENTS.md's approval checks say every visible word is one
# the user would use.
AI_FAILURE_FALLBACK = 'The reading found nothing to fill in.'
AI_FAILURE_REASONS = {
    'transport_error': 'Could not reach the reader. Try again.',
    'unusable_output': 'The reader answered with nothing usable.',
    'no_usable_fields': AI_FAILURE_FALLBACK,
}


def ai_failure_reason(reason):
    """The sentence a reading that produced nothing stores in ai_error."""
    return AI_FAILURE_REASONS.get(reason, AI_FAILURE_FALLBACK)


def apply_field_status(job, filled_fields, unfilled='not_evidenced'):
    """Per-field extraction status (JOZ-267 Section 3). A covered field
    this attempt actually filled becomes done. A covered field this
    attempt found nothing for becomes unfilled -- 'pending' while a
    further attempt (the LLM, after an instant heuristic pass) is still
    to come, 'not_evidenced' once no further attempt is coming and the
    text genuinely did not support it -- unless an earlier attempt
    already marked it done, which this never downgrades. A field whose
    provenance is already 'user' is never touched (global rule 1).

    A field this write carries a `field_status_reason` for is
    not_evidenced whatever value goes with it: the reason says the reader
    covered the field and the record still holds nothing the owner can
    use, and the value beside it is a placeholder (the provisional title
    an intake stores when the posting's heading turned out to be its
    careers page, careeros/intake._extract). Saying done there would
    make the vault drop the reason, and with it the ask."""
    provenance = job.get('field_provenance', {})
    status = dict(job.get('field_status', {}))
    unevidenced = set(filled_fields.get('field_status_reason') or ())
    for field in ingest.STATUS_FIELDS:
        if provenance.get(field) == 'user':
            continue
        if field in unevidenced:
            status[field] = 'not_evidenced'
        elif filled_fields.get(field):
            status[field] = 'done'
        elif status.get(field) != 'done':
            status[field] = unfilled
    return status


def reread_field_status(job, filled_fields):
    """Per-field status for a re-read of text that was already read once
    (package 2's Re-extract).

    A field an earlier reading settled keeps what it settled on. A field
    marked not_evidenced was read and genuinely was not in the posting,
    and a re-read that fails does not turn that into a failure: it is the
    same text, and the answer about that field has not changed. Only a
    field this attempt just filled, and a field nothing has settled yet,
    move. `apply_field_status` is the first reading's rule, where every
    covered field is still open. A field this write carries a reason for
    is not_evidenced here too, for the same reason."""
    provenance = job.get('field_provenance', {})
    status = dict(job.get('field_status', {}))
    unevidenced = set(filled_fields.get('field_status_reason') or ())
    for field in ingest.STATUS_FIELDS:
        if provenance.get(field) == 'user':
            continue
        if field in unevidenced:
            status[field] = 'not_evidenced'
        elif filled_fields.get(field):
            status[field] = 'done'
        elif status.get(field) not in ('done', 'not_evidenced'):
            status[field] = 'pending'
    return status


def function_drop_reason(dropped):
    """The owner-facing sentence for function ids a reading produced that
    the vault's function registry does not carry (decision 23: every
    returned id is validated against tags.yaml and an unknown id is
    dropped). It names the count and the ids, because the usual cause is a
    registry that has not been seeded yet rather than a posting that said
    nothing about the role."""
    return (f'The reading suggested {len(dropped)} function id(s) the vault function list '
            f'does not contain: {", ".join(dropped)}.')


def redaction_drop_reason():
    """The owner-facing sentence for a field redaction emptied. It names
    neither the value nor the pattern that caught it: the content is the
    private-network detail redaction exists to keep out of the vault, so
    the reason says what happened and where, and the posting itself is
    where the owner reads the rest."""
    return ('The reading answered for this field, and the answer was removed because it held '
            'private network details, so nothing could be stored.')


def drop_status(job, reasons, status=None, kept=None):
    """The record changes that make a dropped field value visible, or {}.

    Dropping a value a reading produced used to leave no trace at all:
    the field read as not_evidenced, which says the posting did not
    support it, while what actually happened is that the reader answered
    and the answer could not be stored. So the status stays the same word
    (nothing was evidenced that this vault can hold) and it gains the
    reason that tells the two apart, per the product rule that failures
    and unknowns are visible states with a reason.

    `reasons` maps a field to that sentence. A field is skipped when this
    write kept a value for it (`kept`), when the record already has one,
    when the field is already settled as done, or when the owner wrote it
    themselves (global rule 1). Only fields `ingest.STATUS_FIELDS`
    reports are recorded: the vault drops a reason as soon as its field
    moves off not_evidenced, and a field no status rule ever moves would
    keep its reason for good. `status` is this write's field_status when
    the caller computed one, the stored one otherwise."""
    status = dict(job.get('field_status', {}) if status is None else status)
    provenance = job.get('field_provenance', {})
    recorded = {}
    for field, reason in reasons.items():
        if (field not in ingest.STATUS_FIELDS or (kept or {}).get(field) or job.get(field)
                or status.get(field) == 'done' or provenance.get(field) == 'user'):
            continue
        status[field] = 'not_evidenced'
        recorded[field] = reason
    if not recorded:
        return {}
    return {'field_status': status,
            'field_status_reason': {**job.get('field_status_reason', {}), **recorded}}


def function_drop_status(job, kept, dropped, status=None):
    """`drop_status` for the one drop site that has its own vocabulary:
    function ids a reading produced that the vault registry does not
    carry (decision 23)."""
    if not dropped:
        return {}
    return drop_status(job, {'function': function_drop_reason(dropped)}, status,
                       kept={'function': kept})


def fail_pending_field_status(job):
    """A total extraction failure (no fields at all came back) turns any
    field still pending into failed: visibly distinct from not_evidenced
    (the text was read and found wanting) and from done (an earlier
    heuristic or scrape pass already filled it)."""
    provenance = job.get('field_provenance', {})
    status = dict(job.get('field_status', {}))
    for field in ingest.STATUS_FIELDS:
        if provenance.get(field) != 'user' and status.get(field) == 'pending':
            status[field] = 'failed'
    return status


def _netloc(value):
    if not value:
        return ''
    parsed = urlsplit(value)
    host = (parsed.hostname or '').rstrip('.').casefold().removeprefix('www.')
    port = parsed.port
    return host + (f':{port}' if port and port not in (80, 443) else '')


def _shared_ats(value):
    host = (urlsplit(value or '').hostname or '').rstrip('.').casefold()
    return any(host == suffix or host.endswith('.' + suffix) for suffix in SHARED_ATS_HOSTS)


def _domain_of(value):
    try:
        return intake.domain(value)
    except Exception:
        return ''


def _company_website(value):
    return (ingest.redact(value) or None) if value and not _shared_ats(value) else None



# M1: where a signed-in person lands. One home for the fact, read by the
# form redirect and sent to the React login page as `next`, so the two
# cannot disagree about where logging in takes you.
AFTER_LOGIN = '/jobs'

# M1: the endpoints the gate lets through without a session. Everything
# else needs one, including an unknown path, so a stranger cannot learn
# which routes exist by reading status codes. 'static' and 'react_assets'
# are the asset routes; a login page that could not load its own assets
# would be a door with no handle.
PUBLIC_ENDPOINTS = frozenset({'login', 'health', 'static', 'react_assets'})


def login_page(error: str | None = None) -> str:
    """The sign-in page served when the React build is not available.

    /jobs already falls back to a Jinja rendering when there is no build
    (see create_app), and the one page a person must be able to reach
    before they have a session cannot be the one page that needs a build.
    Built from the shell and the shared control styles with no CSS of its
    own: plain fields and one primary button, per the design system
    record. Nothing on it reads a record, so there is nothing here to
    leak.

    No navigation and no logout, like the React rendering of the same page
    (docs/surfaces/accounts.md): every link a nav could show leads back
    here until there is a session.
    """
    message = f"<p class='danger' role='alert'>{escape(error)}</p>" if error else ''
    return page_shell(
        'Log in', '',
        "<section class='card'><h1>Log in</h1>"
        "<p class='muted'>CareerOS is invitation only. Ask the owner for an account.</p>"
        f"{message}"
        "<form class='stack spaced' method='post' action='/login'>"
        "<label>Email<input type='email' name='email' autocomplete='username' required></label>"
        "<label>Password<input type='password' name='password' "
        "autocomplete='current-password' required></label>"
        "<button type='submit' class='primary'>Log in</button>"
        "</form></section>",
        ui.CSS,
        nav=False,
    )


def create_app(vault: str | Path | None = None) -> Flask:
    """Build the app with an explicit, environment, or default vault path."""
    app = Flask(__name__)
    app.config['VAULT_PATH'] = users.vault_root(vault)
    # M0 migration (JOZ-273): with CAREEROS_REACT_UI=1 the Jobs page is
    # served by the built React/Gestalt front end instead of the Jinja
    # template. The SPA fetches the same JSON API either way, so flipping
    # the flag changes only which renderer answers GET /jobs. The Jinja
    # page stays reachable whenever the flag is off or the build output
    # is missing (a fresh clone has no dist/ until `npm run build`).
    react_dist = Path(os.environ.get('CAREEROS_REACT_DIST') or Path(__file__).resolve().parent.parent / 'frontend' / 'dist')
    react_ui = os.environ.get('CAREEROS_REACT_UI') == '1' and (react_dist / 'index.html').is_file()
    if not react_ui:
        app.add_url_rule('/jobs', 'jobs', jobs.build_page)
    # JOZ-280/JOZ-283: the detail-page skeleton (Job, Experience, Company,
    # Company Classification) and, as of JOZ-283, Search (home),
    # Experiences list and Companies list are a React/Gestalt rebuild with
    # no Jinja coexistence (owner decision). Unlike /jobs above, these
    # routes exist only when react_ui is on; their Jinja routes, views and
    # templates are removed rather than kept as a flag-off fallback. The
    # Search page's own URL is "/", not "/search"; the redundant second
    # URL the Jinja template answered to is retired, not carried over.
    if react_ui:
        react_index = lambda **_kwargs: send_from_directory(react_dist, 'index.html')
        app.add_url_rule('/', 'react_index', react_index)
        app.add_url_rule('/jobs', 'react_jobs', react_index)
        app.add_url_rule('/jobs/<identifier>', 'react_job_detail', react_index)
        app.add_url_rule('/experiences', 'react_experiences', react_index)
        app.add_url_rule('/experiences/<identifier>', 'react_experience_detail', react_index)
        app.add_url_rule('/companies', 'react_companies', react_index)
        app.add_url_rule('/companies/<identifier>', 'react_company_detail', react_index)
        app.add_url_rule('/taxonomy', 'react_taxonomy', react_index)
        # The owner's round added Notes: every note in the vault with the
        # job or company it belongs to. React-only, like /taxonomy, so it
        # has no Jinja route and no entry in theme.py's NAV_PAGES.
        app.add_url_rule('/notes', 'react_notes', react_index)
        app.add_url_rule('/assets/<path:filename>', 'react_assets', lambda filename: send_from_directory(react_dist / 'assets', filename))

    app.add_url_rule('/experiences/new', 'experience_new', experiences.form)
    app.add_url_rule('/experiences/<identifier>/edit', 'experience_edit', experiences.form)
    app.add_url_rule('/jobs/<identifier>/taxonomy', 'job_taxonomy', jobs.taxonomy)

    # M1 sessions. A signed cookie holding one user id: HttpOnly so no
    # script can read it, SameSite=Lax so another site cannot post with
    # it, and a 30-day life so closing the browser does not sign anybody
    # out. Secure is deliberately not forced, because the instance is not
    # always reached over HTTPS.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=users.SESSION_MAX_AGE,
    )
    # The signing key is persisted in the vault, so sessions survive a
    # restart (see users.secret_key). Set unconditionally: every request
    # reads the session, including the login page's own, so a process with
    # no key answers 500 to everything rather than being merely unable to
    # sign anybody in. A vault directory that does not exist yet is
    # created for it -- the one write a read-only start makes, because a
    # fresh vault has to be able to serve a working login.
    app.secret_key = users.secret_key(app.config['VAULT_PATH'])

    # The gate (M1 scope 4). One before_request, registered before every
    # other hook so nothing runs on behalf of a request that has no
    # business being served. An API call without a session is told to log
    # in and nothing else; a page request is sent to the login page.
    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if users.session_user(app.config['VAULT_PATH']) is not None:
            return None
        if request.path.startswith('/api/'):
            return jsonify(error=users.LOGIN_REQUIRED), 401
        return redirect(url_for('login'))

    # The M2 split (CAREER-39, decisions D3/D4). Three readings of the
    # signed-in user, so no route decides for itself what privacy means:
    #
    #   session_owner()    whose private records this request may touch.
    #                      Every job and experience read is filtered
    #                      through it, and a record it does not own
    #                      answers like one that does not exist.
    #   may_edit_shared()  whether this request may change a company or
    #                      the tag vocabulary, which is the admin alone.
    #   shared_denied()    the one answer a tester's shared write gets.
    #
    # Each reads the session user again rather than caching it on `g`:
    # the record is one small YAML file, the gate above has already read
    # it on this request, and one cache is one more place an answer can
    # go stale inside a request.
    #
    # Every route scopes its FIRST read of a record, which is the one
    # that decides whether the request is answered at all. The reloads
    # inside the AI queue and the background extraction threads
    # (apply_enrichment, refresh_and_enrich, mark_ingest_state,
    # set_ai_status, start_llm_enrichment and the rest) are deliberately
    # unscoped: they re-read a job id their own request already proved
    # the caller owns, they run off the request thread where there is no
    # session to read, and ownership never moves once stamped.
    def session_owner():
        return users.owner(users.session_user(app.config['VAULT_PATH']))

    def may_edit_shared():
        return users.is_admin(users.session_user(app.config['VAULT_PATH']))

    def shared_denied():
        return jsonify(error=users.SHARED_READ_ONLY), 403

    def vocabulary_additions(root, payload):
        """The tag values this payload would add to the shared registry.

        A write registers a new value only through the explicit proposal
        flow (`proposed_tags`, see vault.validate_tags) or through the
        legacy skills-only experience payload, which proposes its own
        translation inside vault.save_experience. Both are checked here,
        so a tester cannot extend shared vocabulary by either route.
        """
        if not isinstance(payload, dict):
            return []
        proposed = payload.get('proposed_tags')
        tokens = [t for t in proposed if isinstance(t, str)] if isinstance(proposed, list) else []
        if 'skills' in payload and 'tags' not in payload and isinstance(payload.get('skills'), list):
            tokens += [storage.legacy_skill_to_tag_id(skill) for skill in payload['skills']
                       if isinstance(skill, str) and skill.strip()]
        return storage.unregistered_tags(root, tokens)

    @app.get('/api/health')
    def health():
        """The one unauthenticated check: is the process up.

        It answers that and nothing else, so it cannot grow into a way to
        read a record without logging in.
        """
        return jsonify(ok=True)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """The sign-in page and the sign-in itself.

        A JSON request is answered with JSON and a form post with a
        redirect, so the React page and the no-build fallback form share
        one endpoint rather than needing one each. A failed attempt gets
        one message whichever half was wrong, so the page cannot be used
        to find out who has an account.
        """
        root = app.config['VAULT_PATH']
        if request.method == 'GET':
            if users.session_user(root) is not None:
                return redirect(AFTER_LOGIN)
            return send_from_directory(react_dist, 'index.html') if react_ui else login_page()
        payload = request.get_json(silent=True)
        wants_json = isinstance(payload, dict)
        submitted = payload if wants_json else request.form
        user = users.authenticate(root, submitted.get('email'), submitted.get('password'))
        if user is None:
            if wants_json:
                return jsonify(error=users.SIGN_IN_FAILED), 401
            return login_page(users.SIGN_IN_FAILED), 401
        users.sign_in(user)
        return jsonify(ok=True, next=AFTER_LOGIN) if wants_json else redirect(AFTER_LOGIN)

    @app.post('/logout')
    def logout():
        """Drop the session. Behind the gate, like every other route: a
        request with no session has nothing to log out of."""
        users.sign_out()
        return jsonify(ok=True) if isinstance(request.get_json(silent=True), dict) \
            else redirect(url_for('login'))

    write_lock = storage.WriteLock(app.config['VAULT_PATH'], RLock())

    # JOZ-265: idempotent, additive-only; safe to run on every startup.
    # A vault that does not exist yet (fresh install) has nothing to
    # migrate, so a missing directory is not an error here.
    try:
        with write_lock:
            storage.migrate_job_fields(app.config['VAULT_PATH'])
            storage.migrate_company_fields(app.config['VAULT_PATH'])
            # CAREER-36: the AI queue lives in this process, so a process
            # that stopped took its queue with it. Any record still
            # reading queued or running is a record nothing can finish,
            # and it is settled here with a reason rather than left as a
            # state that never resolves.
            storage.recover_interrupted_ai(app.config['VAULT_PATH'])
    except OSError:
        pass

    # Exposed so the verification and the tests can wait for queued AI
    # work to finish. Nothing in a request path reads it: a request that
    # waits for the queue is the synchronous call the queue retires.
    app.config['AI_QUEUE'] = ai_queue

    # Worker-local pending assumes a single-process deployment.
    llm_pending = {}
    # Exposed so pages can render the pending state without reaching into the closure.
    app.config['LLM_PENDING'] = llm_pending
    # Exposed so tests can join a background extraction deterministically.
    app.config['LLM_THREADS'] = {}
    app.config['REFRESH_THREADS'] = {}
    # Exposed so tests can join a background cascade (M7) deterministically.
    app.config['CASCADE_THREADS'] = {}
    # Guards llm_pending reservation so intake and /extract can never both
    # win a worker slot for the same job, and so a stale callback can never
    # clear a slot a newer run holds.
    # Lock order (JOZ-267 fix round 3, R3-C2): whenever both are needed,
    # acquire write_lock first and nest pending_lock inside it, never the
    # reverse -- every site below that holds both follows this order, so
    # two threads can never deadlock waiting on each other's lock.
    pending_lock = RLock()

    def prune_cascade_threads():
        with pending_lock:
            threads = app.config['CASCADE_THREADS']
            for identifier, thread in list(threads.items()):
                if thread.ident is not None and not thread.is_alive():
                    threads.pop(identifier, None)

    @app.teardown_appcontext
    def teardown_cascades(error=None):
        prune_cascade_threads()

    def run_company_cascade(root, company_id):
        """Shared cascade body for the automatic new-company path
        (schedule_company_cascade) and the owner-triggered company Retry
        (POST /api/companies/<id>/retry, M1 audit: replaces the Backfill
        sector/size button, scoped to one company instead of sweeping all
        of them). Same sectors_cascade/size_cascade entry points
        backfill_sector_size uses; org_enrich.py itself stays
        unmodified. Runs the network phase outside the write lock -- a
        caller holding it across network I/O would starve every other
        writer -- and applies any eligible result under the lock
        afterward, with the same Decision-20 review-flag accounting
        plan_backfill runs. Returns (company, applied) where company is
        the saved record (or the unmodified record, possibly None, when
        there is nothing eligible to run) and applied lists the cascade
        field names ('sectors'/'size') this invocation actually wrote.
        applied is call-fresh by construction: stored field_states can
        carry an older run's applied_fields when a concurrent edit or an
        owner-set value makes this invocation skip a field, so UI code
        must use this list, never the stored states, to decide whether
        the retry changed anything."""
        company = storage.load_company(root, company_id)
        if company is None or company.get('kind', 'employer') != 'employer':
            return company, []
        collector = org_enrich.BackfillAccounting()
        options = company_enrichment.classification_options()
        new_sectors, sector_flag = org_enrich.classify_sector(company, collector=collector, signals=company_enrichment.SECTOR_SIGNALS, **options)
        size_changes, size_flag = org_enrich.classify_size(company, collector=collector, signals=company_enrichment.SIZE_SIGNALS, **options)
        identifiers = []
        if isinstance(new_sectors, dict):
            identifiers.extend(new_sectors.get('identifiers', []))
            new_sectors = new_sectors.get('sectors')
        if size_changes and 'identifiers' in size_changes:
            identifiers.extend(size_changes['identifiers'])
            size_changes = {k: v for k, v in size_changes.items() if k != 'identifiers'}
        # The cascade proposes the class alone: the numeric range is the
        # scale the class retired (owner decision 2026-10-15), and since
        # 2026-10-16 the capability no longer derives it for writing, so
        # there is nothing to strip off here. The accounting below reports
        # what it filled, and a value no write persists would have
        # reported a fill that did not happen.
        with write_lock:
            current = storage.load_company(root, company_id)
            if current is None or current.get('kind', 'employer') != 'employer':
                return current, []
            # A completed cascade invalidates older results, including state and accounting.
            if current.get('enrichment', {}).get('attempted_at') != company.get('enrichment', {}).get('attempted_at'):
                return current, []
            for identifier in identifiers:
                # Writable on purpose: both callers of run_company_cascade
                # are admin-gated (the company Retry endpoint and
                # schedule_company_cascade, which only fires when the
                # driving job may write the shared half).
                current = identity.add_identifier(VaultOrganisationStore(root), current,
                    identifier['type'], identifier['value'], identifier['provenance'])
            provenance = current.get('field_provenance', {})
            changes = {}
            applied = []
            flags = current.get('review_flags', [])
            states = dict(current.get('enrichment', {}).get('field_states', {}))
            # `keys` is every field this signal's evidence was read
            # against, so a stale or owner-touched one stops the write.
            # `stored_keys` is the subset the product persists, which is
            # what "this field is filled" can honestly mean: a company
            # with a size_class and no size_range has a known size, since
            # the range is the scale the class retired.
            for field, keys, stored_keys, proposed, flag, resolved in (
                ('sectors', ('sectors',), ('sectors',), {'sectors': new_sectors} if new_sectors else {},
                 sector_flag, (org_enrich.FLAG_SECTOR_AMBIGUOUS, org_enrich.FLAG_SECTOR_CONFLICT)),
                ('size', ('size_range', 'size_class'), ('size_class',), size_changes or {}, size_flag,
                 (org_enrich.FLAG_SIZE_INCONSISTENT,)),
            ):
                # Size is a consistency-checked pair: discard stale evidence if either changed.
                if any(current.get(k) != company.get(k) or provenance.get(k) == 'user' for k in keys):
                    continue
                eligible = {k: v for k, v in proposed.items() if not current.get(k)}
                changes.update(eligible)
                if eligible:
                    applied.append(field)
                    flags = company_enrichment._clear_flags(flags, resolved)
                elif flag:
                    flags = company_enrichment._merge_flags(flags, flag)
                states[field] = {
                    'state': 'filled' if eligible or all(current.get(k) for k in stored_keys)
                             else 'flagged' if flag else 'exhausted',
                    'attempted_at': storage.timestamp(),
                    # Preserve BackfillAccounting's event/summary shape, including empty outcomes.
                    'events': [e for e in company_enrichment.company_events(collector) if e['field'] == field],
                    'applied_fields': list(eligible),
                }
            changes['review_flags'] = flags
            changes['enrichment'] = {**current.get('enrichment', {}), 'field_states': states,
                                    'attempted_at': storage.timestamp(),
                                    'events': company_enrichment.company_events(collector), 'summary': collector.summary()}
            return storage.save_company(root, changes, company_id), applied

    def schedule_company_cascade(root, company_id):
        """M7: a rung-4 new company gets the same cascade run_company_cascade
        runs for an owner-triggered company Retry. Runs in a background
        thread since this path fires unannounced right after intake
        creates the company. Tests disable AUTO_CASCADE_ENABLED to avoid
        network calls. Explicit Retry bypasses this switch and always
        runs the cascade; see the /retry route below."""
        if not AUTO_CASCADE_ENABLED:
            return None
        prune_cascade_threads()
        thread = Thread(target=lambda: run_company_cascade(root, company_id)[0], daemon=True)
        with pending_lock:
            app.config['CASCADE_THREADS'][company_id] = thread
            thread.start()
        return thread

    def fill_company_metadata(root, company, extracted):
        """Section 1's field-group matrix applies at every enrichment entry
        point: institutions receive only locations (name/website lookups
        happen at their own call sites), and only employers receive sector
        and size derivation. (The former third kind, 'aggregate', was
        removed by owner decision on 2026-10-07: it never applied to a
        real record.)

        Fill eligibility consults the NEW-shape fields (sectors,
        size_class), never the legacy sector/size strings alone, so an
        owner-set sectors list or size value is not clobbered by a posting
        signal just because the legacy field happens to be empty.
        employee_count is deliberately not in the generic passthrough: the
        company schema has no raw employee_count field, only the derived
        size_class, so it gets its own branch through the
        consistency-checked derivation function instead.

        A posting's headcount fills the class and nothing else (CAREER-33).
        It used to fill the legacy `size` string as well, from a bucket
        `intake._extract` derived from the very same count -- so one signal
        wrote two scales, which is what the 2026-10-15 decision retired.
        A legacy `size` an older record carries is still read (see
        `careeros/web/pages/companies.py`); nothing writes one."""
        kind = company.get('kind', 'employer')
        changes = {}
        if extracted.get('locations') and not company.get('locations'):
            changes['locations'] = extracted['locations']
        if kind == 'employer':
            if extracted.get('sector') and not company.get('sector') and not company.get('sectors'):
                changes['sector'] = extracted['sector']
            changes.update(sectors.fill_size_updates(
                extracted.get('employee_count'), company.get('size_range'), company.get('size_class')))
        return storage.save_company(root, changes, company['id']) if changes else company

    # M4 (JOZ-266 fix round): hosts where the tenant lives in the URL PATH
    # (first segment), used only to parse a company's bare board-root
    # *website* (no posting id, so detect_ats itself can't recognize it)
    # leniently enough to compare against a POSTING's own, fully
    # detect_ats-verified tenant -- never to derive a tenant identity on
    # its own. A provider missing here (personio/workday/teamtailor/
    # recruitee/join) encodes its tenant in the HOST/subdomain instead, so
    # an exact netloc match against the posting's own host already proves
    # the same tenant, with no separate path parse needed.
    _PATH_TENANT_HOSTS = {
        'lever': ('jobs.lever.co',),
        'greenhouse': ('boards.greenhouse.io', 'job-boards.greenhouse.io'),
        'ashby': ('jobs.ashbyhq.com',),
        'smartrecruiters': ('jobs.smartrecruiters.com',),
        'refline': ('refline.ch',),
    }

    def _lenient_website_tenant_match(website, ats_match):
        hosts = _PATH_TENANT_HOSTS.get(ats_match.provider)
        if not website or hosts is None:
            return False
        host = (urlsplit(website).hostname or '').rstrip('.').casefold()
        if not any(host == h or host.endswith('.' + h) for h in hosts):
            return False
        segments = [s for s in urlsplit(website).path.split('/') if s]
        return bool(segments) and segments[0].casefold() == ats_match.tenant.casefold()

    def find_company(root, name, posting_url, owner=None):
        """Pre-JOZ-266 matching, kept as org_intake.identity's legacy_hint: a
        company predates the identifiers table whenever it was created
        before this ladder existed (its ATS tenant/domain lives only in its
        free-text name or website field, or in another job's url on the
        same tenant), so this stays the fallback the ladder consults once
        its own identifier-based rungs find nothing. Any match made here is
        taught into a real identifier by the ladder (see
        org_intake/identity.py apply_review/_record_link_evidence), so later
        lookups for the same tenant/domain no longer need this fallback at
        all.

        M4 (JOZ-266 fix round): matching for an ATS-hosted posting URL is
        decided ONLY by the posting's own detect_ats provider+tenant
        identity, confirmed exactly (never a bare "known shared-ATS host"
        classifier matching on host alone, and never a different tenant
        under the same provider). A provider-host match WITHOUT an
        identical tenant slug (two different Refline tenants, say) is
        never promoted to ats_tenant ownership; it is simply not a match.

        M2 (owner decision 2026-10-18): the tenant sweep below reads the
        caller's own jobs, through `owner`, and never the whole vault.
        Deriving a company link from somebody else's private posting is
        that posting changing what this user sees, and the link it
        produces gets its tenant taught onto a shared company as an
        identifier. See tenant_employer_names for the full reasoning."""
        # M2 soft retire: this is the ladder's own legacy fallback, so it
        # answers over the same candidates the ladder's store offers (see
        # careeros.org_store). Without the filter a retired company would
        # come back as a legacy hint and the ladder would honour it,
        # resurrecting the record the admin retired -- and for a tester it
        # would produce a new link `vault.linkable_company` then refuses,
        # failing their intake. One answer for everybody, like the store.
        companies_ = [c for c in storage.list_companies(root)
                      if not storage.is_retired(c)]
        if name:
            matches = [c for c in companies_
                      if str(c.get('name', '')).strip().casefold() == name.strip().casefold()]
            if len(matches) == 1:
                return matches[0]
            # Zero or multiple name matches: fall through to the
            # identifier-based checks below. An ambiguous name match is
            # never resolved here -- that is Decision-20's
            # org_intake.identity resolve ladder territory, not this
            # legacy, pre-identifiers fallback.
        ats_match = posting_ats(posting_url)
        if ats_match is not None:
            posting_host = (urlsplit(posting_url).hostname or '').rstrip('.').casefold()
            for company in companies_:
                website = company.get('website') or ''
                website_host = (urlsplit(website).hostname or '').rstrip('.').casefold()
                if website and (
                    (ats_match.provider not in _PATH_TENANT_HOSTS and website_host == posting_host)
                    or _lenient_website_tenant_match(website, ats_match)
                ):
                    return company
            for job in storage.list_jobs(root, owner):
                if not job.get('company_id'):
                    continue
                job_match = posting_ats(job.get('url') or '')
                if (job_match is not None and job_match.provider == ats_match.provider
                        and job_match.tenant == ats_match.tenant):
                    return next((c for c in companies_ if c['id'] == job['company_id']), None)
            return None
        domain = _domain_of(posting_url)
        if not domain:
            return None
        return next((c for c in companies_ if c.get('website') and _domain_of(c['website']) == domain), None)

    def legacy_hint(root, name, posting_url, owner=None):
        company = find_company(root, name, posting_url, owner)
        if company is None:
            return None
        return (company, 'ats_tenant' if posting_ats(posting_url) is not None else 'domain')

    def accept_function_ids(root, values):
        """Split the function ids a reading returned into the ones the vault
        registry knows and the ones it does not, logging the drop count.

        `vault.save_job` rejects an unknown id outright, so a reading's
        ids have to be filtered before they reach it (decision 23). The
        drop is logged here, at the one place that does the filtering, so
        a run can be read back for how often the registry came up short
        -- an empty or narrow function facet is the expected cause, and
        before this it left no record anywhere."""
        known = storage.known_function_ids(root)
        kept = [value for value in values if value in known]
        dropped = [value for value in values if value not in known]
        if dropped:
            app.logger.warning('Dropped %d function id(s) missing from the vault function list: %s',
                               len(dropped), ', '.join(dropped))
        return kept, dropped

    def apply_llm_update(root, baseline, fields, token):
        """Apply under the caller-held write lock. The baseline contains only
        values automation wrote; fresh owner provenance always takes priority."""
        fillable = ('title', 'company', 'location', 'employment_type', 'seniority',
                    'remote_ok', 'keywords', 'contact_email',
                    'background', 'skills', 'certifications', 'responsibilities', 'function',
                    'description_structured', 'requirement_groups')
        if llm_pending.get(baseline['id']) is not token:
            return
        job = storage.load_job(root, baseline['id'])
        if job is None or any(job.get(key) != baseline.get(key) for key in ('url', 'original_url')):
            return
        # M2 (D3): whether this job's reading may write the shared company
        # it resolves to. Read off the record's own owner, not a session:
        # this runs on the AI queue, where there is no request.
        shared = company_enrichment.contributes_to_shared(root, job)
        # And whose jobs this resolution may read, reconstructed from the
        # record for the same reason: no session on the queue.
        scope = company_enrichment.record_owner_scope(root, job)
        provenance = job.get('field_provenance', {})
        explicit_empty_summary = 'summary' in fields and not (fields['summary'] or '').strip()
        redacted = []
        fields = ingest.redact(fields, redacted)
        if 'contact_email' in fields and not ingest.is_valid_contact_email(fields.get('contact_email')):
            # The reader answered with something that is not a usable
            # address (a placeholder domain, a tracking subdomain, an
            # image filename shaped like an email). Dropping it is right;
            # dropping it in silence is what this logs instead. The
            # address itself stays out of the log, since the field is
            # personal data either way.
            fields.pop('contact_email', None)
            app.logger.warning('Dropped the extracted contact_email for job %s: not a usable address.',
                               baseline['id'])
        dropped_functions = []
        if 'function' in fields:
            fields['function'], dropped_functions = accept_function_ids(root, fields['function'])
        if fields.get('requirements') or fields.get('nice_to_have') or fields.get('summary'):
            fields['description_structured'] = {
                'summary': fields.get('summary') or '', 'requirements': fields.get('requirements') or [],
                'nice_to_have': fields.get('nice_to_have') or [], 'method': 'llm'}
        # Package 2: the grouped requirements this extraction supports. A
        # model that answered the groups wins; a model that only filled
        # the flat lists still yields groups, through the same one home
        # the offline rules use.
        if fields.get('requirement_groups') or fields.get('requirements') or fields.get('nice_to_have'):
            fields['requirement_groups'] = ingest.requirement_groups(
                fields.get('requirement_groups'), fields.get('requirements'),
                fields.get('nice_to_have'))
        updates = {key: fields[key] for key in fillable
                   if fields.get(key) not in (None, '', [])
                   and job.get(key) == baseline.get(key)
                   and provenance.get(key) != 'user'}
        # A key present with an empty value means the model deliberately
        # found no real summary (e.g. a chrome-only page); that must be
        # able to clear a previously polluted summary and its AI badge,
        # which the blanket not-in-(None,'',[]) filter above would block.
        # An absent key (no 'summary' in fields) must leave it untouched.
        if ('summary' in fields and (fields['summary'] or explicit_empty_summary)
                and job.get('summary') == baseline.get('summary')
                and provenance.get('summary') != 'user'):
            summary = (fields['summary'] or '').strip()
            updates['summary'] = summary
            updates['summary_source'] = 'ai' if summary else ''
        new_provenance = {**provenance, **{key: 'llm' for key in updates if key != 'summary_source'}}
        if job.get('ingest_source') == 'heuristic':
            updates['ingest_source'] = 'llm'
        correction = updates.get('company')
        changed_company = correction and correction != job.get('company')
        new_company_id = None
        # M2: the extraction callback's 'company' field IS the spec's
        # post-fetch employer-name signal (employer_named_in_posting),
        # not just free display text -- persist it with provenance and
        # re-run the shared ladder under this same lock, with the same
        # owner-link-group protection every other ladder entry point
        # honors (M1), instead of the old ad-hoc exact-name-only match
        # that bypassed the fuzzy check and any staffing/shared-tenant
        # flag entirely.
        if (correction and correction != job.get('employer_named_in_posting')
                and provenance.get('employer_named_in_posting') != 'user'):
            updates['employer_named_in_posting'] = correction
            new_provenance['employer_named_in_posting'] = 'llm'
            owner_locked = any(provenance.get(key) == 'user' for key in COMPANY_LINK_GROUP)
            if not owner_locked:
                resolution = resolve_company(
                    root, url=job.get('url') or '', shared=shared, owner=scope,
                    employer_name=correction,
                    fallback_name=updates.get('company', job.get('company')),
                    existing=(job.get('company_id'), job.get('company_link_reason')))
                updates.update(resolution)
                if resolution.get('company_id'):
                    new_provenance['company_id'] = 'llm'
                    # B3: the link group (company_id, company_link_state,
                    # company_link_reason) is written in one breath, so its
                    # provenance has to move in one breath too. Marking only
                    # company_id left the other two reading as whatever set
                    # them last -- a link state automation had just
                    # replaced, still attributed to an earlier writer.
                    new_provenance['company_link_state'] = 'llm'
                    if resolution.get('company_link_reason'):
                        new_provenance['company_link_reason'] = 'llm'
                if resolution.get('company_link_reason') == 'new_company':
                    new_company_id = resolution['company_id']
        updates['field_status'] = apply_field_status(job, updates)
        updates.update(function_drop_status(job, fields.get('function'), dropped_functions,
                                            updates['field_status']))
        # Redaction is the other way a reading's answer reaches the write
        # and is stored as nothing. `redact` logs every field it empties;
        # this is the half that shows up on the record itself. A field it
        # emptied carries no value, so the reason explains the same
        # not_evidenced the status rule above already settled on. The
        # dotted path of a nested value names its top-level field, which
        # is the one field_status reports.
        if redacted:
            # Two drop sites can fire on one write. `drop_status` rebases its
            # reason map on the stored record, so handing it `job` again here
            # would clobber the function reason the call above just recorded.
            # Carry the merged map forward instead.
            base = {**job, 'field_status_reason':
                    updates.get('field_status_reason',
                                job.get('field_status_reason', {}))}
            updates.update(drop_status(
                base, {path.split('.')[0]: redaction_drop_reason() for path in redacted},
                updates['field_status'], kept=updates))
        updates['enriched'] = True
        detail = None
        if changed_company:
            detail = ('Extraction corrected company text; ' +
                      ('linked company matched.' if updates.get('company_id')
                       else 'existing company link retained for review.'))
        storage.save_job(root, updates | {'field_provenance': new_provenance},
                         baseline['id'], correction_detail=detail)
        return new_company_id

    # Prune on the next request, retaining joinable handles for active work.
    def prune_threads():
        threads = app.config['LLM_THREADS']
        for identifier, thread in list(threads.items()):
            if not thread.is_alive():
                threads.pop(identifier, None)

    @app.before_request
    def prune_completed_enrichment():
        prune_threads()
        prune_cascade_threads()

    def mark_ingest_state(root, job_id, state, *, stage=None, reason=None, history=None, locked=False,
                          settle_fields=False):
        """Re-read current state under the write lock and apply the ingest
        state transition; never called while holding the lock across a
        network or LLM call. Returns None if the job no longer exists.

        settle_fields flips any still-pending covered field to failed in
        the same write. Pass it at every terminal-failure call site (a
        worker that never even started, or any other failure after which
        no further attempt can ever reach that field) so a field never
        stays pending forever with nothing left to advance it (JOZ-267 fix
        round 1 finding 4)."""
        error = {'stage': stage, 'reason': reason, 'at': storage.timestamp()} if stage else None
        with nullcontext() if locked else write_lock:
            current = storage.load_job(root, job_id)
            if current is None:
                return None
            updates = {'ingest_state': state, 'ingest_error': error}
            if settle_fields:
                updates['field_status'] = fail_pending_field_status(current)
            return storage.save_job(root, updates, job_id, history_event=history)

    def set_ai_status(identifier, update, *, locked=False):
        """Write one AI lifecycle transition onto a job.

        Returns the saved job, or None when it is gone (a job deleted
        while its reading ran has nothing left to report into, and that
        is not a failure worth logging). `locked` says the caller already
        holds the write lock, following mark_ingest_state's own
        convention, so a transition can ride inside a lock scope the
        caller opened for other reasons.
        """
        root = app.config['VAULT_PATH']
        try:
            with nullcontext() if locked else write_lock:
                if storage.load_job(root, identifier) is None:
                    return None
                return storage.save_job(root, update, identifier)
        except Exception as error:
            # Storage itself refused the write. The run's own outcome is
            # already lost at this point; swallowing it here keeps that
            # from also killing the worker thread every later unit of
            # work depends on.
            ingest.warn(error)
            return None

    def settle_ai_status(identifier, reason, *, locked=False):
        """Fail a reading that stopped without saying so, and leave a
        settled one alone.

        The backstop for every path that abandons a run after the job was
        already marked queued or running: it writes a failure only while
        the stored status still says work is owed, so it can never
        overwrite the done or failed a run already recorded for itself.
        """
        root = app.config['VAULT_PATH']
        with nullcontext() if locked else write_lock:
            record = storage.load_job(root, identifier)
            if record is None or storage.ai_status(record) not in storage.AI_UNSETTLED:
                return None
            return set_ai_status(identifier, storage.ai_failed(reason), locked=True)

    def queue_ai_work(work):
        """Hand one unit of AI work to the queue and return at once
        (CAREER-36).

        Nothing waits for it and nothing reads its result, so a unit that
        fails has only this log line to leave behind. The job endpoints
        use enqueue_ai below instead, which records the outcome on the
        job; the company endpoint has no status field to record into and
        is queued for the shape alone.
        """
        def unit():
            try:
                work()
            except Exception as error:
                ingest.warn(error)

        ai_queue.submit(unit)

    def enqueue_ai(identifier, work, *, release=None):
        """Queue one unit of AI work for a job and return at once, with
        the job's own status carrying what happened to it (CAREER-36).

        This is the whole of what /enrich does on the request thread: the
        job is marked queued before this returns, so the 202 the caller
        gets is already true of the record it will poll, and `work` runs
        later on the queue's single worker thread, one unit at a time.
        `work` takes no arguments and returns nothing; it raises AiFailed
        to name an owner-facing reason, and any other exception is
        reported as its type.

        `release`, when supplied, is called once the unit has written its
        own end state, never before: it is how /enrich gives back the
        reservation it holds (see reserve_enrichment), and a reservation
        given back while the status still said running would let the next
        request queue a second reading over the first one's result.

        The entry points that already write the queued transition inside
        a lock scope of their own (/extract, /re-extract) do not come
        through here at all: they hand the reading to the extraction
        worker instead.
        """
        set_ai_status(identifier, storage.ai_queued())

        def unit():
            set_ai_status(identifier, storage.ai_running())
            try:
                try:
                    work()
                except Exception as error:
                    if not isinstance(error, AiFailed):
                        ingest.warn(error)
                    set_ai_status(identifier, storage.ai_failed(ai_reason(error)))
                else:
                    set_ai_status(identifier, storage.ai_done())
            finally:
                if release is not None:
                    release()

        queue_ai_work(unit)

    def reserve_enrichment(job_id):
        """Atomically claim the right to start a worker for this job.

        Returns a unique token on success, or None if a run is already
        pending. Checking both entry points against the same lock means
        intake and /extract can never both start a worker for the same job.
        """
        with pending_lock:
            if job_id in llm_pending:
                return None
            token = object()
            llm_pending[job_id] = token
            return token

    def settle_failed_reread(root, job_id, *, history_event, locked=False):
        """Record a failed re-read of text that was already read, and
        return the saved job, or None when this job has no earlier reading
        to keep.

        The owner pressed Re-extract on a job whose details were read
        once. That reading still stands: downgrading the record to
        extract_failed would raise the card that asks for a posting text
        the job already stores, and would call a complete job unread. So
        the attempt gets its own event instead of the state change, and
        the fields this attempt moved back to pending settle, since
        nothing further will reach them. A job that never had a reading
        keeps the ordinary failure path, card and all.

        `history_event` is what this particular failure says happened: the
        caller is the one that knows whether a reading ran, so the
        sentence comes from there rather than being one sentence for every
        way an attempt can end with nothing."""
        with nullcontext() if locked else write_lock:
            current = storage.load_job(root, job_id)
            if current is None or current.get('ingest_state') != 'complete':
                return None
            return storage.save_job(
                root, {'field_status': fail_pending_field_status(current)}, job_id,
                history_event=history_event)

    def release_enrichment(job_id, token):
        """Give back a reservation whose run never started, if it is still
        this caller's. The token identity check is what keeps a caller
        from releasing a newer run's slot."""
        with pending_lock:
            if llm_pending.get(job_id) is token:
                llm_pending.pop(job_id, None)

    def settle_and_release(root, job_id, token, current):
        """Settle any still-pending covered field and release the caller's
        extraction ownership token as one step (JOZ-267 fix round 3,
        R3-C1/R3-C2): every early return that abandons a job without ever
        reaching a terminal ingest_state write must leave neither a
        settled-but-still-owned nor an owned-but-abandoned gap for a
        concurrent reader to observe.

        Callers must already hold write_lock; this nests pending_lock
        inside it, per the module's documented lock order, and must
        itself be the last thing done before returning from that
        write_lock scope -- not deferred to an outer finally -- so no
        reader can acquire write_lock in between the settle and the
        release.

        CAREER-36: the AI status settles here too, for the same reason the
        fields do. This run is the one that marked the record queued, so
        abandoning it without a word would leave the record saying a
        reading is still owed when nothing is left to deliver one."""
        storage.save_job(root, {'field_status': fail_pending_field_status(current)}, job_id)
        settle_ai_status(job_id, 'The posting link changed while it was being read.', locked=True)
        with pending_lock:
            if llm_pending.get(job_id) is token:
                llm_pending.pop(job_id, None)

    def start_llm_enrichment(root, baseline, description, token, on_started=None, reread=False):
        """Start the background worker for a reserved token.

        Returns True if a worker thread actually started. The callback only
        clears llm_pending if it still owns the slot (token identity check),
        so a slow/stale run can never clobber a newer run's pending state.

        reread says this run is reading text the job was already read
        from, which changes only what a failure means: see
        settle_failed_reread.
        """
        job_id = baseline['id']

        def on_result(fields, reason=None):
            new_company_id = None
            try:
                with write_lock:
                    with pending_lock:
                        if llm_pending.get(job_id) is not token:
                            return
                    current = storage.load_job(root, job_id)
                    if current is None:
                        return
                    if any(current.get(k) != baseline.get(k) for k in ('url', 'original_url')):
                        # JOZ-267 fix round 2 finding 4 gap (R2-C): the url
                        # changed while this ran, so the result itself is
                        # for a posting that no longer matches the record
                        # and must be discarded -- but whatever fields this
                        # attempt was the last chance to settle must not be
                        # left pending forever with nothing left to advance
                        # them. The PUT path that changed the url already
                        # set the terminal ingest_state; this only settles
                        # the fields that terminal state leaves stranded.
                        # R3-C2: settle and release together, still under
                        # write_lock, so no reader can observe the fields
                        # settled while this run still shows as the owner.
                        settle_and_release(root, job_id, token, current)
                        return

                    # CAREER-36: this callback is the one place every
                    # reading lands, whichever entry point queued it, so
                    # it is where the AI status reaches its end state.
                    if fields:
                        new_company_id = apply_llm_update(root, baseline, fields, token)
                        mark_ingest_state(root, job_id, 'complete', history=('extracted', 'Extraction completed.'), locked=True)
                        set_ai_status(job_id, storage.ai_done(), locked=True)
                    elif reread and settle_failed_reread(
                            root, job_id, history_event=REREAD_FAILED_HISTORY, locked=True) is not None:
                        # A re-read of a job that already has its reading
                        # keeps that reading, and says what happened in its
                        # own words (package 2 fix round, F6). The reading
                        # the record keeps is the earlier one, so this
                        # attempt still failed and says so.
                        set_ai_status(job_id, storage.ai_failed(
                            ai_failure_reason(reason)), locked=True)
                    else:
                        # JOZ-267 fix round 1 finding 4: settle any still-
                        # pending field every time, even when a more
                        # specific fetch/empty-content failure already
                        # explains why there is nothing to show -- that
                        # more specific reason is still worth preserving
                        # (below), but it must never come at the cost of
                        # leaving a field pending forever with no further
                        # attempt able to reach it.
                        storage.save_job(root, {'field_status': fail_pending_field_status(current)}, job_id)
                        if (current.get('ingest_state') != 'fetch_failed'
                                and (current.get('ingest_error') or {}).get('reason') != 'empty_content'):
                            mark_ingest_state(root, job_id, 'extract_failed', stage='extract',
                                              reason=reason or 'no_usable_fields',
                                              history=('extract_failed', 'Extraction failed.'), locked=True)
                        set_ai_status(job_id, storage.ai_failed(
                            ai_failure_reason(reason)), locked=True)
                if new_company_id is not None and shared:
                    schedule_company_cascade(root, new_company_id)
            except Exception as error:
                # M3: applying a successful result (or recording its own
                # failure above) must never just get logged and leave the
                # job stuck mid-state with no visible reason.
                ingest.warn(error)
                try:
                    mark_ingest_state(root, job_id, 'extract_failed', stage='extract',
                                      reason=type(error).__name__,
                                      history=('extract_failed', 'Extraction failed.'), settle_fields=True)
                    set_ai_status(job_id, storage.ai_failed(ai_reason(error)))
                except Exception:
                    # Storage itself is unavailable; the root cause is
                    # already logged above, so this is not a second,
                    # independent failure worth logging again.
                    pass
            finally:
                # JOZ-267 fix round 2 finding 3 (R2-B): a Paste that landed
                # after this run already chose its own extraction input
                # (fetched text, or whatever description this run started
                # with) could never reserve a slot of its own while this
                # one was still running, and would otherwise be silently
                # ignored -- the owner's text sits saved with 'user'
                # provenance, but nothing ever extracts it. Once this run's
                # own reservation is released, detect that drift and give
                # the fresh text its own extraction with explicit, fresh
                # ownership.
                #
                # R3-B2/R3-B3: release of the old token and reservation of
                # the replacement token must be one atomic step under
                # pending_lock -- not release-then-separately-reserve --
                # or a GET in between sees complete/llm_pending False/no
                # pending fields (stops polling before the replacement
                # starts), and an intervening Retry can win its own
                # reservation in that same gap and duplicate the
                # extraction. Swapping the dict entry directly from token
                # to replacement_token, with no pop in between, means
                # llm_pending never has a moment without an entry for
                # job_id when a replacement is actually warranted.
                latest, replacement_token = None, None
                try:
                    latest = storage.load_job(root, job_id)
                except Exception as error:
                    ingest.warn(error)
                needs_replacement = (latest is not None
                                     and latest.get('field_provenance', {}).get('description') == 'user'
                                     and latest.get('description') != description)
                with pending_lock:
                    owns_slot = llm_pending.get(job_id) is token
                    if owns_slot and needs_replacement:
                        replacement_token = object()
                        llm_pending[job_id] = replacement_token
                    elif owns_slot:
                        llm_pending.pop(job_id, None)
                if replacement_token is not None:
                    try:
                        # R3-B1: a replacement that fails to start must not
                        # be silently ignored -- the pasted text would
                        # otherwise never be extracted while the job still
                        # reads back as complete with no error and no owner.
                        started = start_llm_enrichment(
                            root, latest, latest.get('description') or '', replacement_token)
                        if not started:
                            mark_ingest_state(root, job_id, 'extract_failed', stage='extract',
                                              reason='worker_start_failed', settle_fields=True,
                                              history=('extract_failed', 'Could not start extraction.'))
                    except Exception as error:
                        ingest.warn(error)

        callback_lock = RLock()
        ready = False
        queued = []

        def receive(fields, reason=None):
            with callback_lock:
                if not ready:
                    queued.append((fields, reason))
                    return
            on_result(fields, reason)

        try:
            thread = ingest.extract_async(description, receive,
                                          function_options=storage.function_facet_options(root))
        except Exception as error:
            release_enrichment(job_id, token)
            ingest.warn(error)
            # CAREER-36: the reservation is gone and no worker exists, so
            # this is the end of the line for whatever marked the record
            # queued; say so rather than leaving the status owed.
            settle_ai_status(job_id, 'Could not start the reading.')
            return False
        app.config['LLM_THREADS'][job_id] = thread
        with callback_lock:
            # CAREER-36: the worker exists, so the reading has left the
            # queue. Written before `ready` is flipped, so a reading that
            # finished before this line still reports its own done or
            # failed afterwards and never back to running.
            set_ai_status(job_id, storage.ai_running())
            if on_started:
                on_started()
            ready = True
            for fields, reason in queued:
                on_result(fields, reason)
        return True

    def stub_title(url):
        """URL-only fallback title for the Phase A stub: no network, no HTML
        parse. Overwritten by the real extracted title once Phase B's fetch
        succeeds."""
        segment = unquote(urlsplit(url).path.rstrip('/').split('/')[-1]).replace('-', ' ').replace('_', ' ').strip()
        return segment or 'New job'

    @app.route('/api/jobs/intake', methods=['POST'])
    def job_intake():
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError('Provide a URL object.')
        # M1: structural validation only (scheme + host) before the stub is
        # saved; no DNS lookup here. DNS/SSRF resolution (intake.check_url)
        # happens inside intake.fetch_url, in Phase B, after the stub exists,
        # so an unresolvable or SSRF-blocked posting still gets a durable,
        # retryable record instead of vanishing with a bare 400.
        url = intake.check_url_format(payload.get('url'))
        force = bool(payload.get('force'))
        origin = payload.get('origin') or 'manual'
        if origin not in ('manual', 'discovered'):
            raise ValueError('Invalid origin.')
        root = app.config['VAULT_PATH']
        normalized = normalize_url(url)
        ats_match = posting_ats(url)
        # M2 (D4): the posting belongs to whoever adds it. The same owner
        # scopes the duplicate check below, so the same link added by two
        # users is two private records rather than one of them being told
        # about the other's.
        owner = session_owner()
        # M2 (D3): and whether anything this intake learns may be written
        # onto the shared company it resolves to. A tester's posting may
        # bring a company into existence to point at, and may add not one
        # fact to it: no website, no size, no sector, no source, and no
        # enrichment cascade. Read once here rather than per write site,
        # and from the session rather than from the record, because the
        # record this will create does not exist yet.
        shared = may_edit_shared()

        # Step 2 (hard duplicate check) and Step 3 (stub creation) share one
        # lock scope: no network/LLM call happens in here, so this never
        # holds the write-lock across a slow call, and two concurrent
        # intake calls for the same URL can never both slip past the check.
        with write_lock:
            existing, basis = dedupe.find_duplicate(root, normalized, ats_match, owner)
            if existing and not force:
                return jsonify(dedupe.duplicate_payload(existing, basis))
            # Resolution ladder rungs 1-2 (JOZ-266): pure local identifier
            # lookups, no network I/O, safe to run synchronously here
            # before the fetch below. Rungs 3-5 need the posting text and
            # run after fetch, in Phase B.
            pre_link = resolve_company(root, url=url, shared=shared, owner=owner,
                                       legacy_hint=legacy_hint(root, '', url, owner))
            stub_fields = {
                'url': url, 'normalized_url': normalized, 'title': stub_title(url),
                'status': 'new', 'ingest_state': 'stub', 'in_pipeline': True,
                'origin': origin, 'source_id': None,
                'ats_provider': ats_match.provider if ats_match else None,
                'ats_tenant': ats_match.tenant if ats_match else None,
                'ats_posting_id': ats_match.posting_id if ats_match else None,
                storage.OWNER_FIELD: owner.identifier,
                **pre_link,
            }
            history = (('duplicate_override', f'Added despite matching {existing["id"]} ({basis}).')
                       if existing else None)
            job = storage.save_job(root, stub_fields, history_event=history)

        # Phase B: fetch -> parse -> queue LLM extract, as today. The stub
        # above is already durably saved and independently readable (by
        # another request, or a direct vault read) before this network call
        # starts; this is the "instant, non-blocking stub" guarantee JOZ-265
        # delivers now, ahead of JOZ-267's real async worker. Global rule 4
        # (never reject user input) means a fetch failure still produces a
        # usable record: the URL-derived heuristic fallback (company from
        # domain, title from the path) does not depend on the page having
        # loaded, it only loses the real posting content.
        #
        # M3: everything from here on runs after the stub is already
        # durable, so any failure (fetch, parse, company linking, or the
        # LLM worker failing to even start) must degrade the stub to a
        # visible, retryable failure state instead of either losing the
        # record (an uncaught exception reaching Flask's error handler) or
        # silently leaving it stuck at 'stub'/'fetched' with no reason.
        company = None
        try:
            try:
                html = intake.fetch_url(url)
                if not isinstance(html, str) or not html.strip():
                    raise ValueError('Posting returned no content.')
                fetch_error = None
            except Exception as error:
                html = ''
                fetch_error = error

            data = intake.heuristic_posting(url, html)
            name = data['company']
            website = _company_website(data.pop('website'))
            metadata = {key: data.pop(key) for key in ('sector', 'locations', 'employee_count')}
            posting_origin = _company_website(f'{urlsplit(url).scheme}://{_netloc(url)}')
            # O2 (fix round 2): a fetch that succeeds structurally but yields
            # no extractable body text (a metadata-only page) must not settle
            # at 'fetched'/error None -- that looks healthy forever, since
            # extract_async's own empty-description no-op (below) never then
            # flips it to anything else. Treated the same as a failed
            # extraction attempt (stage 'extract': the HTTP fetch itself did
            # succeed; there was simply nothing for extraction to work with).
            no_content = fetch_error is None and not (data.get('description') or '').strip()
            if fetch_error is not None:
                ingest_fields = {'ingest_state': 'fetch_failed', 'ingest_error': {
                    'stage': 'fetch', 'reason': type(fetch_error).__name__, 'at': storage.timestamp()}}
                history = ('fetch_failed', 'Unable to fetch the posting page.')
            elif no_content:
                ingest_fields = {'ingest_state': 'extract_failed', 'ingest_error': {
                    'stage': 'extract', 'reason': 'empty_content', 'at': storage.timestamp()}}
                history = ('extract_failed', 'Posting fetched but contained no extractable content.')
            else:
                ingest_fields = {'ingest_state': 'fetched', 'ingest_error': None}
                history = ('fetched', 'Posting fetched.')
            discarded = False
            new_company_id = None
            with write_lock:
                current = storage.load_job(root, job['id'], owner)
                if current is None:
                    return jsonify(job=job, company=None), 201
                if current.get('url') != job.get('url'):
                    # N2: the owner changed the url while this fetch ran
                    # against the OLD url. Every field below (company link,
                    # title, description, ATS identity) was derived from a
                    # posting that no longer matches the record's url;
                    # applying any of it -- even the fields that happen to
                    # still equal the Phase A baseline -- would silently
                    # resurrect the stale posting under the new url. Discard
                    # the whole result wholesale and leave the record exactly
                    # as the owner's edit left it (job_api already recomputed
                    # normalized_url/ats_* atomically with that edit); a fresh
                    # /extract retry against the new url is a separate,
                    # not-yet-attempted pipeline run.
                    discarded = True
                    job = storage.save_job(root, {
                        'ingest_state': 'extract_failed',
                        'ingest_error': {'stage': 'extract', 'reason': 'source_url_changed', 'at': storage.timestamp()},
                    }, current['id'], history_event=('extract_failed', 'Posting URL changed; stale result discarded.'))
                else:
                    provenance = current.get('field_provenance', {})
                    # Resolution ladder rungs 1-5 (JOZ-266): employer_name is
                    # the strict, never-guessed signal (spec global rule 2),
                    # used for name matching and the staffing/shared-tenant
                    # flags; name (data['company'], possibly slug/domain-
                    # guessed) is the pre-existing permissive fallback,
                    # consulted only once the strict signal has nothing to
                    # offer, so a company is still always created when any
                    # name signal at all is available (unchanged from
                    # JOZ-265), without ever basing a review question or a
                    # flag on a guess.
                    resolution = resolve_company(
                        root, url=url, shared=shared, owner=owner,
                        employer_name=data.get('employer_named_in_posting'), fallback_name=name,
                        legacy_hint=legacy_hint(root, name, url, owner),
                        existing=(current.get('company_id'), current.get('company_link_reason')))
                    if resolution.get('company_link_reason') == 'new_company' and resolution.get('company_id'):
                        new_company_id = resolution['company_id']
                    company = storage.load_company(root, resolution['company_id']) if resolution['company_id'] else None
                    # M2 (D3): every fill below writes the shared company
                    # record, so a tester's intake reads the company and
                    # changes nothing on it. The capability is gated, not
                    # removed: the same posting added by the admin fills
                    # all of it, and the M3 merge queue is where a
                    # tester's evidence earns its way in.
                    if company is not None and shared:
                        # employee_count has no company-schema home of its own: the
                        # company only ever stores the derived size_class, which is
                        # the one scale the capability derives (and the one write
                        # vault._drop_retired_size_range still guards, for a legacy
                        # payload that names the retired range itself).
                        # A freshly created company (no website/metadata yet) gets the
                        # same size derivation JOZ-265 always applied at creation time;
                        # an already-existing company only gets its metadata filled in
                        # (fill_company_metadata already fills-empty-only).
                        if resolution['company_link_reason'] == 'new_company' and not company.get('size_class'):
                            derived = sectors.derive_size(metadata.get('employee_count'))
                            if derived:
                                company = storage.save_company(root, derived, company['id'])
                        company = fill_company_metadata(root, company, metadata)
                        if not company.get('website'):
                            company = storage.save_company(root, {'website': website or posting_origin}, company['id'])
                    candidate = data | {'url': url, 'sector': metadata['sector'],
                                        'employee_count': metadata['employee_count'], **resolution}
                    structured_fallback = ingest.heuristic_structured_description(data.get('description') or '')
                    if (structured_fallback['summary'] or structured_fallback['requirements']
                            or structured_fallback['nice_to_have']):
                        candidate['description_structured'] = structured_fallback
                        # The rule-based groups, so a job has grouped
                        # requirements from this first offline pass on;
                        # the queued model pass replaces them with real
                        # groups when it lands. Only when the pass found
                        # lines to group: an empty list written here would
                        # stamp provenance on a field nobody wrote, and a
                        # stamp is what the page reads as "written".
                        groups = ingest.requirement_groups(
                            None, structured_fallback['requirements'],
                            structured_fallback['nice_to_have'])
                        if groups:
                            candidate['requirement_groups'] = groups
                    # M2: a concurrent owner edit made to the stub while the
                    # fetch was in flight must survive. Re-read the current
                    # record and only let an automated field land if it still
                    # matches the Phase A snapshot (`job`) for that field;
                    # this covers an owner clearing a field to empty, and
                    # extends the same protection to company_id and url. O1
                    # (fix round 2): snapshot equality is not enough on its
                    # own -- a field explicitly marked owner-set in
                    # field_provenance is never written by automation here,
                    # regardless of whether it happens to still equal the
                    # baseline.
                    updates = {key: value for key, value in candidate.items()
                              if current.get(key) == job.get(key) and provenance.get(key) != 'user'}
                    new_provenance = {**provenance, **{key: 'scrape' for key in updates}}
                    # JOZ-267 Section 3: posting_quality is informational
                    # (never provenance-tracked); field_status reflects this
                    # heuristic pass, with 'pending' (not not_evidenced) for
                    # a covered field it did not fill, since the queued LLM
                    # extraction below still gets a chance at it.
                    updates['posting_quality'] = ingest.classify_posting_quality(data.get('description') or '')
                    updates['field_status'] = apply_field_status(current, updates, unfilled='pending')
                    automation_baseline = job | updates
                    job = storage.save_job(root, updates | ingest_fields | {'field_provenance': new_provenance},
                                           job['id'], history_event=history)
        except Exception as error:
            ingest.warn(error)
            job = mark_ingest_state(root, job['id'], 'fetch_failed', stage='fetch',
                                    reason=type(error).__name__,
                                    history=('fetch_failed', 'Unable to process the posting.')) or job
            return jsonify(job=job, company=company), 201

        if discarded:
            return jsonify(job=job, company=None), 201

        if new_company_id is not None and shared:
            schedule_company_cascade(root, new_company_id)

        token = reserve_enrichment(job['id'])
        if token is not None:
            started = start_llm_enrichment(root, automation_baseline, data['description'], token)
            if not started:
                job = mark_ingest_state(root, job['id'], 'extract_failed', stage='extract',
                                        reason='worker_start_failed', settle_fields=True,
                                        history=('extract_failed', 'Could not start extraction.')) or job
                # O2 (fix round 2): a worker that never started is a truthful
                # failure, not the same outcome as the normal 201 this route
                # returns when extraction actually gets underway; a bare 201
                # here would be indistinguishable from success to a caller
                # that only checks response.ok.
                return jsonify(job=job, company=company, error='Could not start extraction.'), 503
        return jsonify(job=job, company=company), 201

    @app.post('/api/jobs/<identifier>/resolve-review')
    def resolve_review(identifier):
        """Owner resolves a needs_review company link (JOZ-266 §6): pick an
        existing candidate (company_id) or create a new company
        (create={'name': ...}). Writes the posting's employer name as a
        user name_variant identifier on the chosen company (owner decision
        3.A), so the same fuzzy case never asks twice, then links the job
        and clears the review state -- the same invariant the generic PUT
        bypass fix enforces."""
        root = app.config['VAULT_PATH']
        with write_lock:
            job = storage.load_job(root, identifier, session_owner())
            if job is None:
                return jsonify(error='Job not found.'), 404
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Record must be an object.')
            # Every choice consumes one active review revision, including empty candidate lists.
            review = job.get('company_review')
            submitted_token = payload.get('review_token')
            if not submitted_token or review is None or review.get('token') != submitted_token:
                return jsonify(error='This review is out of date. Reload and try again.'), 409
            # M2 (D3): picking one of the candidates this review offers is
            # a write to the owner's own job. Creating a company instead
            # is a write to the shared half, so it is the admin's, the
            # same rule the intake ladder's create rung now follows (see
            # careeros.org_store). A review a tester can actually reach
            # is an ambiguity between companies that already exist, so
            # there is always a candidate to pick: their own intake
            # answers `pending` rather than proposing a new company.
            creating = bool(payload.get('create')) and not payload.get('company_id')
            if creating and not may_edit_shared():
                return shared_denied()
            # Validate the selection BEFORE apply_review, because
            # apply_review writes on its way through: it teaches the
            # chosen company a name_variant, and the link validation
            # inside save_job runs only after that. Submitting a retired
            # company id therefore used to leave the variant behind and
            # then answer 400, which is both a mutation on a refused
            # request and the tombstone made readable. The answer is the
            # one apply_review itself gives for an id that is not there,
            # so a retired id and a nonexistent one stay the same
            # request with the same outcome and no side effect either way.
            selected = payload.get('company_id')
            if selected and not storage.linkable_company(root, selected, job.get('company_id')):
                raise ValueError('Company not found.')
            # M2 (D3): selecting a candidate is a write to the owner's own
            # job and stays open to everybody. What is not open is the
            # thing apply_review also does on the way through: it teaches
            # the chosen company a `name_variant` identifier carrying
            # `employer_named_in_posting`, which is text extracted from
            # this user's own private posting, onto a record every user
            # reads. So a tester gets the read-only store, which links
            # the job and no-ops the variant, exactly as the intake
            # ladder's own identifier writes are no-opped for them.
            shared = company_enrichment.contributes_to_shared(root, job)
            try:
                result = identity.apply_review(VaultOrganisationStore(root, shared=shared),
                    url=job.get('url'), link_reason=job.get('company_link_reason'),
                    employer_name=job.get('employer_named_in_posting'),
                    record_id=payload.get('company_id'), create=payload.get('create'),
                    token=submitted_token, current_token=review['token'])
            except ValueError as error:
                raise ValueError(str(error).replace('Record', 'Company').replace('record', 'company')) from error
            company = result['record']
            if creating:
                company = record_company_source(root, company, job.get('url') or '')
            provenance = {**job.get('field_provenance', {}), 'company_id': 'user',
                         'company_link_state': 'user', 'company_link_reason': 'user'}
            return jsonify(storage.save_job(root, {
                'company_id': company['id'], 'company_link_state': 'linked',
                'company_link_reason': 'manual', 'company_review': None,
                'field_provenance': provenance,
            }, identifier))

    @app.post('/api/jobs/<identifier>/resolve')
    def rerun_resolution(identifier):
        """Re-run the resolution ladder for an existing job (JOZ-266 §6),
        using its stored url and employer_named_in_posting; no network
        fetch. A no-op when company_id already carries owner provenance
        (global rule 1: human edits always win)."""
        root = app.config['VAULT_PATH']
        with write_lock:
            job = storage.load_job(root, identifier, session_owner())
            if job is None:
                return jsonify(error='Job not found.'), 404
            owner_set = any((job.get('field_provenance') or {}).get(key) == 'user'
                            for key in ('company_id', 'company_link_state', 'company_link_reason'))
            # M2 (D3): re-running the ladder can reach its create rung, so
            # it runs against the same gated store the intake path uses,
            # keyed on this job's own owner.
            shared = company_enrichment.contributes_to_shared(root, job)
            scope = session_owner()
            try:
                result = identity.rerun(
                    VaultOrganisationStore(root, shared=shared), url=job.get('url') or '',
                    employer_name=job.get('employer_named_in_posting'), fallback_name=job.get('company'),
                    record_id=job.get('company_id'), link_reason=job.get('company_link_reason'),
                    link_state=job.get('company_link_state'), review=job.get('company_review'),
                    owner_set=owner_set,
                    tenant_employer_names=tenant_employer_names(root, job.get('url') or '', scope))
            except CompanyCreationDenied:
                result = dict(record_id=None, link_state='pending', link_reason=None, review=None)
            resolution = company_job_fields(result) if not owner_set else {
                key: job.get(key) for key in ('company_id', 'company_link_state', 'company_link_reason', 'company_review')}
            if (not owner_set and result['record_id'] and result['link_state'] == 'linked'
                    and shared):
                # M2 (D3): same rule as the intake ladder. Re-running the
                # resolution relinks the owner's own job either way; what
                # the gate withholds is the source written onto the
                # shared company.
                record_company_source(root, storage.load_company(root, result['record_id']), job.get('url') or '')
            return jsonify(storage.save_job(root, resolution, identifier))

    @app.post('/api/jobs/<identifier>/promote')
    def promote_job(identifier):
        """Journey 2 constraint, wired now: flips in_pipeline true on a
        universe record. Nothing creates in_pipeline false records yet."""
        root = app.config['VAULT_PATH']
        with write_lock:
            job = storage.load_job(root, identifier, session_owner())
            if job is None:
                return jsonify(error='Job not found.'), 404
            if job.get('in_pipeline'):
                return jsonify(job)
            return jsonify(storage.save_job(root, {'in_pipeline': True}, identifier,
                                            history_event=('promoted', 'Promoted to pipeline.')))

    @app.post('/api/jobs/<identifier>/enrich')
    def enrich_job(identifier):
        """Read the live posting again and fill whatever is still empty.

        CAREER-36: the reading itself runs off the request path. What the
        request thread still does is validate -- the job has to exist, and
        its posting link has to be one this product will fetch, which is
        the structural check plus the private-address guard and no read of
        the posting at all. Everything after that (the fetch, the model
        pass, the company resolution and the write) is one unit of work on
        the AI queue, because the model host is CPU-only and takes minutes
        per call while a proxy in front of this app gives up in seconds.

        So a caller never reads the enriched job out of this response. It
        gets 202 and the queued status, and reads the outcome off the
        record, which is where the queue writes it.

        One reading per job, like every other entry point: this takes the
        same reservation /extract, /re-extract and the pasted-text path
        take, and gives it back only once the queued unit has written its
        own end state. Without it, N clicks queued N readings of the same
        posting, each writing done over the next one's queued, so the
        board stopped polling while a reading was still owed.
        """
        root = app.config['VAULT_PATH']
        job = storage.load_job(root, identifier, session_owner())
        if job is None:
            return jsonify(error='Job not found.'), 404
        try:
            url = intake.check_url(job.get('url'))
        except Exception:
            return jsonify(error='Unable to fetch and parse posting.'), 422

        def read_posting():
            try:
                html = intake.fetch_url(url)
                if not isinstance(html, str) or not html.strip():
                    raise ValueError('Posting returned no content.')
                extracted = intake.ingest_posting(url, html, function_options=storage.function_facet_options(root))
            except Exception as error:
                raise AiFailed('Unable to fetch and parse posting.') from error
            apply_enrichment(extracted)
            # The offline rules answer for a posting the model could not
            # be read for, so the fields above fill either way and that
            # write stands. What must not happen is this reading reporting
            # itself done when the model call behind it failed: the fields
            # alone cannot tell the two apart, so the reason the
            # extraction itself recorded is what settles it (fix round
            # B1). 'not_configured' is not among them on purpose, since
            # an environment with no reader configured attempted no call
            # and the offline reading is the whole of what was ever
            # coming.
            reason = extracted.get('extract_reason')
            if reason in ('transport_error', 'unusable_output'):
                raise AiFailed(ai_failure_reason(reason))

        def apply_enrichment(extracted):
            with write_lock:
                job = storage.load_job(root, identifier)
                if job is None:
                    raise AiFailed('This job was removed while the posting was being read.')
                if job.get('url') != url:
                    raise AiFailed('Posting URL changed during enrichment. Try again.')
                dropped_functions = []
                if 'function' in extracted:
                    extracted['function'], dropped_functions = accept_function_ids(root, extracted['function'])
                fill_fields = ('title', 'location', 'source', 'posted_date',
                               'employment_type', 'valid_through', 'description', 'company',
                               'seniority', 'summary', 'keywords', 'ingest_source', 'remote_ok', 'sector',
                               'background', 'skills', 'certifications', 'responsibilities',
                               'employee_count', 'function', 'description_structured',
                               'requirement_groups')
                if not job.get('enriched'):
                    fill_fields += ('salary_info', 'salary_note')
                # This fills empty fields only, so a value that is itself empty
                # fills nothing: an empty list used to pass the guard and land
                # in updates, where it stamps provenance on a field nothing was
                # found for, and a field_provenance entry is what the page
                # reads as "this was written, and here is by whom".
                updates = {key: extracted[key] for key in fill_fields
                           if (job.get(key) in (None, '', []) or
                               (key == 'salary_info' and job.get(key) is False))
                           and extracted.get(key) not in (None, '', [], {})
                           and job.get('field_provenance', {}).get(key) != 'user'}
                updates['posting_quality'] = ingest.classify_posting_quality(extracted.get('description') or '')
                if 'summary' in updates:
                    # extracted['summary'] can be the heuristic fallback even when
                    # other fields came from the model; trust the field-specific
                    # marker ingest.extract() computed, not the overall ingest_source.
                    updates['summary_source'] = extracted.get('summary_source', '')
                # A nonempty title is always treated as owner-set; no heuristic replacement.
                name, website = extracted['company'], _company_website(extracted['website'])
                provenance = job.get('field_provenance', {})
                employer_evidence = extracted.get('employer_named_in_posting')
                # The source THIS call's extraction credits its employer evidence
                # to: 'llm' after a model pass, 'scrape' after the offline rules.
                # Stamped on employer_named_in_posting when that text moves, and
                # on the link group below whenever this resolution moves it --
                # which is not the same condition: an employer name identical to
                # the stored one still resolves against a vault that has changed
                # underneath it, and can land on a different company.
                evidence_source = extracted.get('field_provenance', {}).get(
                    'employer_named_in_posting', 'scrape')
                if employer_evidence and employer_evidence != job.get('employer_named_in_posting') \
                        and provenance.get('employer_named_in_posting') != 'user':
                    updates['employer_named_in_posting'] = employer_evidence
                    updates['field_provenance'] = {**provenance,
                                                   'employer_named_in_posting': evidence_source}
                # Package 2: the grouped requirements this call just filled have
                # to say who read the lines they hold, because the Requirements
                # section's AI label has nothing else to read for them (the flat
                # block carries its own `method`, the groups do not). Same rule
                # the Re-extract write applies: the lines are the model's when a
                # model answered this posting, the page's otherwise.
                if 'requirement_groups' in updates:
                    updates['field_provenance'] = {
                        **updates.get('field_provenance', provenance),
                        'requirement_groups': 'llm' if extracted.get('ingest_source') == 'llm' else 'scrape'}
                # M3: route through the SAME shared ladder every other
                # resolution entry point uses -- same owner-link-group
                # protection (M1), same fuzzy/ambiguity/shared-tenant
                # treatment, never a duplicate company without identifiers.
                # existing= anchors on the job's current link (however it was
                # established) so a confirmed link is never silently abandoned
                # just because this URL's own identifiers don't happen to
                # match it; this is the entry point for a never-yet-linked job
                # too (existing[0] falsy there), which still gets full rungs
                # 1-5 treatment via resolve_and_link.
                new_company_id = None
                # M2 (D3): off the record's own owner, since this runs on
                # the AI queue with no session to read.
                shared = company_enrichment.contributes_to_shared(root, job)
                scope = company_enrichment.record_owner_scope(root, job)
                owner_locked = any(provenance.get(key) == 'user' for key in COMPANY_LINK_GROUP)
                if not owner_locked:
                    resolution = resolve_company(
                        root, url=url, shared=shared, owner=scope,
                        employer_name=employer_evidence, fallback_name=name,
                        legacy_hint=legacy_hint(root, name, url, scope),
                        existing=(job.get('company_id'), job.get('company_link_reason')))
                    updates.update(resolution)
                    # B3, second path: the link group is written in one breath
                    # here too, so its provenance has to move in one breath --
                    # otherwise a link this resolution just replaced keeps reading
                    # as whatever set it last. The trigger is the link moving, not
                    # the employer text moving. Only the keys this call actually
                    # changed are restamped: a resolution that re-confirms the
                    # stored link leaves the provenance of whoever established
                    # it alone.
                    relinked = {key: evidence_source for key in COMPANY_LINK_GROUP
                                if resolution.get(key) != job.get(key)}
                    if relinked:
                        updates['field_provenance'] = {
                            **updates.get('field_provenance', provenance), **relinked}
                    if resolution.get('company_link_reason') == 'new_company':
                        new_company_id = resolution['company_id']
                target_id = updates.get('company_id', job.get('company_id'))
                target = storage.load_company(root, target_id) if target_id else None
                # M2 (D3): the same two shared-company fills the intake
                # path does, behind the same gate.
                if target and shared:
                    fill_company_metadata(root, target, extracted)
                    if website and not target.get('website'):
                        storage.save_company(root, {'website': website}, target['id'])
                if provenance.get('company_id') == 'user':
                    updates.pop('company_id', None)
                # This path writes no per-field status of its own (it fills
                # empty fields and says so through provenance), so the drop is
                # the one thing it does have to say about a field: the reader
                # answered for function and nothing storable came of it.
                updates.update(function_drop_status(job, extracted.get('function'), dropped_functions))
                updates['enriched'] = True
                storage.save_job(root, updates, identifier)
                if new_company_id is not None and shared:
                    schedule_company_cascade(root, new_company_id)

        token = reserve_enrichment(identifier)
        if token is None:
            # A reading of this job is already under way, and it is the
            # one that owns the status, exactly as on /extract. Saying
            # queued is still true of the record the caller will poll,
            # and no second reading of the same posting is started.
            return jsonify(status='queued'), 202
        try:
            enqueue_ai(identifier, read_posting,
                       release=lambda: release_enrichment(identifier, token))
        except Exception:
            # Nothing was queued, so the reservation is this request's to
            # give back; a token left behind would block every later
            # reading of this job for the life of the process.
            release_enrichment(identifier, token)
            settle_ai_status(identifier, 'Could not start the reading.')
            raise
        return jsonify(status='queued'), 202

    @app.post('/api/jobs/<identifier>/extract')
    def extract_job(identifier):
        """Reserve before starting background refresh and enrichment.

        This route already answered 202 and did its work on a background
        thread before CAREER-36. What that ticket adds is the stored
        status: the queued transition rides inside the same lock scope
        that wins the reservation, so a caller that gets 202 can read
        queued off the record straight away, and start_llm_enrichment and
        its callback carry it on to running, then done or failed. The body
        is the same small answer the other three AI endpoints give, since
        the job in it was always a snapshot from before the work ran.
        """
        root = app.config['VAULT_PATH']
        with write_lock:
            job = storage.load_job(root, identifier, session_owner())
            if job is None:
                return jsonify(error='Job not found.'), 404
            token = reserve_enrichment(identifier)
            if token is not None:
                job = storage.save_job(root, storage.ai_queued(), identifier)
        if token is None:
            # A reading of this job is already under way, and it is the
            # one that owns the status. Saying queued is still true of the
            # record the caller will poll.
            return jsonify(status='queued'), 202
        target = job.get('original_url') or job.get('url')

        def refresh_and_enrich():
            handed_off = False
            try:
                outcome, description, fetch_error = 'skipped', job.get('description') or '', None
                if target:
                    try:
                        html = intake.fetch_url(target)
                        if not isinstance(html, str) or not html.strip():
                            raise ValueError('Empty posting response.')
                        description = intake.extract(target, html).get('description') or ''
                        outcome = 'ok'
                    except Exception as error:
                        ingest.warn(error)
                        outcome = 'failed'
                        fetch_error = error
                with write_lock:
                    current = storage.load_job(root, identifier)
                    if current is None:
                        return
                    if any(current.get(key) != job.get(key) for key in ('url', 'original_url')):
                        # R3-C1: this retry is abandoning the job (the url
                        # changed under it), so settle whatever covered
                        # fields it was the last chance to advance and
                        # release ownership in the same step, or a reader
                        # could see them still pending with no owner left.
                        settle_and_release(root, identifier, token, current)
                        return
                    # JOZ-267 fix round 1 finding 3: a paste that lands while
                    # this retry's own fetch is still in flight cannot
                    # reserve a second worker slot (this retry already holds
                    # the only one), so it saves the pasted text with owner
                    # provenance and waits -- it never starts an extraction
                    # of its own. Recognize that here by its signature (the
                    # description changed and is now owner-provenance) and
                    # hand the pasted text to THIS already-reserved
                    # operation instead of discarding it as an unrelated
                    # concurrent edit, which would otherwise leave nothing
                    # ever processing it.
                    pasted_while_running = (current.get('description') != job.get('description')
                                            and current.get('field_provenance', {}).get('description') == 'user')
                    if current.get('description') != job.get('description') and not pasted_while_running:
                        # R3-C1: an unrelated concurrent change invalidated
                        # this retry's fetched text; settle and release
                        # together rather than abandoning the job with its
                        # covered fields left pending and no owner.
                        settle_and_release(root, identifier, token, current)
                        return
                    with pending_lock:
                        if llm_pending.get(identifier) is not token:
                            return
                    if pasted_while_running:
                        description = current['description']
                    updates = {'refresh': outcome}
                    if outcome == 'ok':
                        if current.get('field_provenance', {}).get('description') != 'user':
                            updates['description'] = description
                        else:
                            # Fetched text is discarded in favor of the
                            # owner's own text; quality below must reflect
                            # what extraction will actually run against.
                            description = current.get('description') or ''
                    # JOZ-267 fix round 1 finding 5: recompute posting_quality
                    # from the description extraction is actually about to
                    # run against, on every retry outcome -- otherwise a
                    # thin-classified failed fetch stays thin forever after
                    # a rich paste or a later successful refetch.
                    updates['posting_quality'] = ingest.classify_posting_quality(description)
                    # JOZ-267: a retry re-queues extraction, so every covered
                    # field not already done (user-set or filled earlier)
                    # goes back to pending, visibly in flight again rather
                    # than showing a stale failed/not_evidenced from the
                    # previous attempt.
                    updates['field_status'] = apply_field_status(current, {}, unfilled='pending')
                    # A job that never got past the stub (first fetch still
                    # pending/failed) drives ingest_state through this same
                    # retry path; a job already fetched once keeps its state
                    # here (a later refresh failure just enriches stored text).
                    # extract_failed is included too (m11): a retry must
                    # transition it through fetched/fetch_failed, clearing
                    # the stale extract error rather than leaving it
                    # alongside a fresh fetch success.
                    if current.get('ingest_state') in ('stub', 'fetch_failed', 'extract_failed'):
                        if outcome == 'failed':
                            updates['ingest_state'] = 'fetch_failed'
                            updates['ingest_error'] = {'stage': 'fetch', 'reason': type(fetch_error).__name__,
                                                       'at': storage.timestamp()}
                    storage.save_job(root, ingest.redact(updates), identifier,
                                     history_event=REFRESH_EVENTS[outcome])
                # Keep the owner error until startup succeeds. Early callbacks
                # are queued until this handoff transition is persisted.
                def accepted():
                    with write_lock:
                        latest = storage.load_job(root, identifier)
                        if latest and all(latest.get(k) == job.get(k) for k in ('url', 'original_url')) and outcome == 'ok':
                            mark_ingest_state(root, identifier, 'fetched', history=('fetched', 'Extraction worker started.'), locked=True)

                handed_off = start_llm_enrichment(root, job, description, token, on_started=accepted)
                if not handed_off:
                    mark_ingest_state(root, identifier, 'extract_failed', stage='extract',
                                      reason='worker_start_failed', settle_fields=True,
                                      history=('extract_failed', 'Could not start extraction.'))
            except Exception as error:
                ingest.warn(error)
                mark_ingest_state(root, identifier, 'extract_failed', stage='extract',
                                  reason=type(error).__name__, settle_fields=True,
                                  history=('extract_failed', 'Refresh worker failed.'))
            finally:
                if not handed_off:
                    with pending_lock:
                        owns_slot = llm_pending.get(identifier) is token
                        if owns_slot:
                            llm_pending.pop(identifier, None)
                    # CAREER-36: this run ended without ever handing the
                    # reading to a worker, so nothing downstream will
                    # report an outcome for it. Settle the status rather
                    # than leaving the record saying work is still owed,
                    # and only while this run is still the owner, so a
                    # replacement reading's own queued state survives.
                    if owns_slot:
                        settle_ai_status(identifier, 'The reading did not start.')

        thread = Thread(target=refresh_and_enrich, daemon=True)
        app.config['REFRESH_THREADS'][identifier] = thread
        try:
            thread.start()
        except Exception as error:
            ingest.warn(error)
            with pending_lock:
                if llm_pending.get(identifier) is token:
                    llm_pending.pop(identifier, None)
            job = mark_ingest_state(root, identifier, 'extract_failed', stage='extract',
                                    reason='refresh_worker_start_failed', settle_fields=True,
                                    history=('extract_failed', 'Could not start refresh.')) or job
            settle_ai_status(identifier, 'Could not start refresh.')
            return jsonify(job | {'llm_pending': False, 'error': 'Could not start refresh.'}), 503
        return jsonify(status='queued'), 202

    @app.post('/api/jobs/<identifier>/re-extract')
    def re_extract_job(identifier):
        """Read the stored posting text again (package 2).

        This is the owner's per-job migration to grouped requirements, and
        the only thing the interface offers for a job written before them:
        every write path fills requirement_groups for a job added since,
        but no read migrates a record and nothing re-runs in bulk (owner
        decision). It is not /extract, which fetches the live
        posting first: the posting a legacy job was read from may be gone,
        and the text to group is the one already stored.

        The rule-based groups (the flat must/nice lists under Skills) are
        written here, synchronously, so the action lands a result even
        when no model is reachable; the queued extraction replaces them
        with real groups when it finishes.

        A list the owner emptied on purpose is filled again, because the
        owner lock keeps automation out of a field the owner has set and
        pressing Re-extract is the owner themselves asking for it to be
        read again. That takes two things, since the stored block may have
        no lines left to regroup: the lines, when there are any, and the
        lock itself, which comes off the field so the reading this request
        queues can answer into it. A list the owner has written lines into
        is left exactly as it is, lock and all: a re-read fills an empty
        field and never replaces text the owner can see.

        Everything else is the same machinery /extract uses: one
        reservation per job, the covered fields that are still open back
        to pending while the attempt runs, and the attempt's own history
        event. A job whose reading is already running is a 409: there is
        one reservation per job, and this request did not get it.

        What a failure means here is its own thing, because the text was
        already read once: see settle_failed_reread.
        """
        root = app.config['VAULT_PATH']
        with write_lock:
            job = storage.load_job(root, identifier, session_owner())
            if job is None:
                return jsonify(error='Job not found.'), 404
            if not (job.get('description') or '').strip():
                return jsonify(error='This job has no posting text to read.'), 409
            token = reserve_enrichment(identifier)
            if token is None:
                # A reading of this job is already running. Answering 202
                # would claim this request started one, so the owner would
                # read whatever that other run writes as this click's
                # result, and a click that did nothing would look like a
                # click that worked.
                return jsonify(job | {'llm_pending': True,
                                      'error': 'This posting is already being read.'}), 409
            try:
                provenance = job.get('field_provenance', {})
                structured = job.get('description_structured') or {}
                updates = {}
                # The owner emptied the list and then asked for the stored
                # text to be read again, which is the owner asking for it
                # to be filled: the lock their clear put on the field has
                # to come off, or the reading this request queues answers
                # into a field the owner-provenance rule then drops it
                # from, and the action is a dead end for exactly the job
                # it exists for.
                emptied_by_owner = (not job.get('requirement_groups')
                                    and provenance.get('requirement_groups') == 'user')
                if not job.get('requirement_groups'):
                    groups = ingest.requirement_groups(None, structured.get('requirements'),
                                                       structured.get('nice_to_have'))
                    stamp = REREAD_PROVENANCE.get(structured.get('method'), 'scrape')
                    new_provenance = {key: value for key, value in provenance.items()
                                      if not (emptied_by_owner and key == 'requirement_groups')}
                    if groups:
                        updates['requirement_groups'] = groups
                        # The owner's own lines, regrouped on an emptied
                        # list, are stamped for nobody: stamping them
                        # 'user' again would re-lock the field this very
                        # request is unlocking, and crediting a reader
                        # with text the owner typed is the lie this stamp
                        # exists to avoid.
                        if not (emptied_by_owner and stamp == 'user'):
                            new_provenance['requirement_groups'] = stamp
                    if new_provenance != provenance:
                        updates['field_provenance'] = new_provenance
                updates['field_status'] = reread_field_status(job, updates)
                if emptied_by_owner:
                    # The field is open again, so its status follows this
                    # reading rather than the clear that set it: filled by
                    # the regrouped lines, or still being read.
                    updates['field_status']['requirement_groups'] = (
                        'done' if updates.get('requirement_groups') else 'pending')
                # CAREER-36: the queued transition rides in this same
                # write, so the record says queued the instant the 202
                # goes out and no second save exists just to say it.
                updates.update(storage.ai_queued())
                job = storage.save_job(root, updates, identifier,
                                       history_event=('re_extracted', 'Stored posting text read again.'))
            except Exception:
                # The reservation is this request's to give back: a write
                # that failed started no reading, and a token left behind
                # would block every later attempt on this job for the life
                # of the process. The failure itself still reaches the
                # owner, through the app's own error handler.
                release_enrichment(identifier, token)
                raise
        if not start_llm_enrichment(root, job, job.get('description') or '', token, reread=True):
            job = (settle_failed_reread(root, identifier,
                                        history_event=REREAD_NOT_STARTED_HISTORY)
                   or mark_ingest_state(root, identifier, 'extract_failed', stage='extract',
                                        reason='worker_start_failed', settle_fields=True,
                                        history=('extract_failed', 'Could not start extraction.'))
                   or job)
            # start_llm_enrichment already settled the AI status for a
            # worker that never started, so nothing is written here.
            return jsonify(job | {'llm_pending': False, 'error': 'Could not start extraction.'}), 503
        return jsonify(status='queued'), 202

    @app.post('/api/jobs/<identifier>/paste-description')
    def paste_description(identifier):
        """Spec Section 3 step 5: fetch failure keeps the stub and offers
        Retry fetch plus Paste posting text manually; pasted text resumes
        at extraction through the same worker /extract uses (scope item 6).
        Only valid while the posting itself was never fetched (stub or
        fetch_failed); once fetched, the owner edits description through
        the generic job PUT instead."""
        root = app.config['VAULT_PATH']
        payload = request.get_json()
        if not isinstance(payload, dict) or not str(payload.get('description') or '').strip():
            raise ValueError('Provide posting text.')
        text = payload['description'].strip()
        with write_lock:
            job = storage.load_job(root, identifier, session_owner())
            if job is None:
                return jsonify(error='Job not found.'), 404
            if job.get('ingest_state') not in ('stub', 'fetch_failed'):
                return jsonify(error='This job already has a fetched posting.'), 409
            provenance = {**job.get('field_provenance', {}), 'description': 'user'}
            updates = {'description': text, 'ingest_state': 'fetched', 'ingest_error': None,
                      'field_provenance': provenance,
                      # JOZ-267 fix round 1 finding 5: a rich paste over a
                      # thin-classified failed fetch must reclassify, not
                      # keep showing the old fetch's limited-extraction notice.
                      'posting_quality': ingest.classify_posting_quality(text),
                      'field_status': apply_field_status(job, {}, unfilled='pending')}
            job = storage.save_job(root, updates, identifier,
                                   history_event=('pasted', 'Posting text pasted manually.'))
            token = reserve_enrichment(identifier)
        if token is None:
            return jsonify(job | {'llm_pending': True}), 202
        started = start_llm_enrichment(root, job, text, token)
        if not started:
            job = mark_ingest_state(root, identifier, 'extract_failed', stage='extract',
                                    reason='worker_start_failed', settle_fields=True,
                                    history=('extract_failed', 'Could not start extraction.')) or job
            return jsonify(job=job, error='Could not start extraction.'), 503
        return jsonify(job | {'llm_pending': True, 'accepted': True}), 202

    @app.post('/api/companies/<identifier>/enrich')
    def enrich_company(identifier):
        """Re-derive a company's aggregated facts from its own jobs.

        CAREER-36 moves this onto the AI queue with the three job
        endpoints, so every enrichment entry point answers the same way
        and a caller has one thing to read rather than one rule per
        endpoint. The aggregation itself reads only the vault and is fast;
        it is queued for the shape, and because it shares the write lock
        with the readings that are not fast, where it would otherwise sit
        waiting for one of them to let go of the lock inside the request.

        No status is recorded for it. The four ai_ fields are the job
        record's, which is what the chip and its polling read; a company
        had them too for one round and nothing ever read them, so they
        are gone rather than kept as four fields per company that no
        surface can show.
        """
        from careeros.enrich import regenerate_company
        root = app.config['VAULT_PATH']
        # M2 (D3): the aggregation writes the shared company record, so
        # it is an admin act like every other company write.
        if not may_edit_shared():
            return shared_denied()
        if storage.may_see_company(root, identifier, session_owner()) is None:
            return jsonify(error='Company not found.'), 404

        def aggregate():
            with write_lock:
                if regenerate_company(root, identifier) is None:
                    raise AiFailed('This company was removed while it was being enriched.')

        queue_ai_work(aggregate)
        return jsonify(status='queued'), 202

    @app.post('/api/watch/scan')
    def watch_scan():
        from careeros import watcher
        root = app.config['VAULT_PATH']
        identifier = request.args.get('job')
        # M2: the sweep is this user's own jobs, named or not. A scan with
        # no job argument used to recheck every posting in the vault and
        # report an event per change, which would have named another
        # user's job id and title.
        owner = session_owner()
        if identifier is not None and storage.load_job(root, identifier, owner) is None:
            return jsonify(error='Job not found.'), 404
        events = watcher.scan(root, job_id=identifier, lock=write_lock, owner=owner)
        result = dict(events=events)
        if identifier:
            job = storage.load_job(root, identifier, owner)
            if not watcher.eligible(job):
                result.update(watch_status='not_watched', reason=watcher.NOT_WATCHED_REASON)
            else:
                result['watch_status'] = job.get('watch', {}).get('watch_status', 'unchanged')
        return jsonify(result)

    @app.get('/api/jobs')
    def job_collection():
        if request.args.get('view') == 'board':
            context = jobs.page_context(app.config['VAULT_PATH'], session_owner())
            summaries = jobs.company_summaries(context['companies'], sectors.load_isic_sections())
            return jsonify(context | {
                'companies': summaries,
                'entries': [job | {'company_name': summaries.get(job.get('company_id'), {}).get('name'),
                                   'company_industry': summaries.get(job.get('company_id'), {}).get('industry'),
                                   'company_size_class': summaries.get(job.get('company_id'), {}).get('size_class'),
                                   'pending': not bool(job.get('enriched'))}
                            for job in context['entries']],
            })
        return jsonify(storage.list_jobs(app.config['VAULT_PATH'], session_owner()))

    @app.get('/api/companies')
    def company_collection():
        # The company records themselves are shared universe and are sent
        # to everybody; what the directory view scopes is the open-jobs
        # count on each card, which is this user's own (M2, D3).
        if request.args.get('view') == 'page':
            return jsonify(companies.page_context(app.config['VAULT_PATH'], session_owner()))
        return jsonify(storage.visible_companies(app.config['VAULT_PATH'], session_owner()))

    @app.get('/api/jobs/<identifier>/taxonomy')
    def job_taxonomy_api(identifier):
        return jsonify(jobs.taxonomy_context(app.config['VAULT_PATH'], identifier,
                                             session_owner(), may_edit_shared()))

    @app.get('/api/taxonomy')
    def taxonomy_api():
        return jsonify(taxonomy.taxonomy_context(app.config['VAULT_PATH'], session_owner()))

    @app.get('/api/experiences/new')
    @app.get('/api/experiences/<identifier>/edit')
    def experience_form_api(identifier=None):
        return jsonify(experiences.form_context(app.config['VAULT_PATH'], identifier,
                                                session_owner(), may_edit_shared()))

    @app.route('/api/jobs/<identifier>', methods=['GET', 'PUT', 'DELETE'])
    def job_api(identifier):
        root = app.config['VAULT_PATH']
        owner = session_owner()
        with write_lock:
            # Somebody else's job reads as None here, so every method
            # below answers 'Job not found.' for it, which is the same
            # answer a job that was never added gets (M2, D3).
            data = storage.load_job(root, identifier, owner)
            if data is None:
                return jsonify(error='Job not found.'), 404
            if request.method == 'GET':
                if request.args.get('view') == 'page':
                    return jsonify(jobs.detail_context(root, identifier, identifier in llm_pending, owner))
                return jsonify(data | {'llm_pending': identifier in llm_pending})
            if request.method == 'DELETE':
                storage.delete_job(root, identifier)
                return jsonify(deleted=identifier)
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Record must be an object.')
            # M2 (D3/D4): a tag value this edit would add to the shared
            # registry is an admin act, so a tester is told so rather
            # than having the vocabulary extended on their behalf. Their
            # own tags, picked from values already registered, save fine.
            if not may_edit_shared() and vocabulary_additions(root, payload):
                return shared_denied()
            # Only trusted extraction paths (apply_llm_update, /enrich,
            # /extract) may set summary_source: strip any client-supplied
            # value, then clear it whenever this PUT actually changes the
            # summary text (replacement or clearing to empty), since an
            # owner edit must never keep an AI badge on text it didn't write.
            #
            # owner_id is stripped on the same principle and for a harder
            # reason: it is who the record belongs to, it is stamped once
            # by the path that creates the record, and a client that
            # could set it could hand its own job to somebody else or
            # take one of theirs (D4: a posting belongs to whoever added
            # it, and that never changes).
            payload = {k: v for k, v in payload.items()
                       if k not in ('summary_source', storage.OWNER_FIELD)}
            if 'summary' in payload and payload['summary'] != data.get('summary'):
                payload['summary_source'] = ''
            # N2 (fix round 2): normalized_url and ATS identity must be
            # recomputed in the SAME write whenever url changes through this
            # generic edit path, atomically -- a url change that lands
            # without this would leave the record's dedupe identity
            # describing the OLD posting while url already points at a new
            # one (a stale normalized_url falsely matches a later re-add of
            # the old url, and a stale ats_* falsely matches/misses future
            # hard-duplicate checks).
            if 'url' in payload and payload['url'] != data.get('url'):
                ats_match = posting_ats(payload['url'] or '')
                payload['normalized_url'] = normalize_url(payload['url'])
                payload['ats_provider'] = ats_match.provider if ats_match else None
                payload['ats_tenant'] = ats_match.tenant if ats_match else None
                payload['ats_posting_id'] = ats_match.posting_id if ats_match else None
                payload['original_url'] = None
                payload['ingest_state'] = 'extract_failed'
                payload['ingest_error'] = {'stage': 'extract', 'reason': 'source_url_changed', 'at': storage.timestamp()}
            # Bug class 9 (JOZ-266): no bypass -- a PUT that sets company_id
            # outside the dedicated resolve-review flow is itself the owner's
            # link decision, and must carry the same invariant that flow
            # keeps: linked state, a manual reason, and no leftover review
            # candidates. Clearing company_id (null) is the converse owner
            # decision -- unlink -- and reverts to pending with no reason.
            if 'company_id' in payload:
                if payload['company_id']:
                    payload['company_link_state'] = 'linked'
                    payload['company_link_reason'] = 'manual'
                else:
                    payload['company_link_state'] = 'pending'
                    payload['company_link_reason'] = None
                payload['company_review'] = None
            # O1 (fix round 2): mark every field this owner edit actually
            # sets as owner-provenance, so Phase B and the LLM callback
            # never overwrite it later, regardless of whether it happens to
            # still equal whatever baseline they were snapshotting against.
            # B2: only keys the vault actually persists. A payload key the
            # whitelist drops (a stray `fit: null` from a client, a typo)
            # changes nothing on the record, so claiming the owner set it
            # would freeze a field against automation that never got a value.
            marked = {key: 'user' for key in payload
                      if key not in _PROVENANCE_EXCLUDED_FIELDS and key in storage.job_field_names()}
            if marked:
                payload['field_provenance'] = {**data.get('field_provenance', {}), **payload.get('field_provenance', {}), **marked}
                # An owner edit to a covered field is itself a confident,
                # final value: field_status must say done, never a stale
                # pending/not_evidenced/failed left over from automation.
                touched = set(marked) & set(ingest.STATUS_FIELDS)
                if touched:
                    payload['field_status'] = {**data.get('field_status', {}),
                                               **{field: 'done' for field in touched}}
            return jsonify(storage.save_job(root, payload, identifier))

    @app.route('/api/companies/<identifier>', methods=['GET', 'PUT', 'DELETE'])
    def company_api(identifier):
        root = app.config['VAULT_PATH']
        owner = session_owner()
        with write_lock:
            # A company the admin retired reads as absent for them, which
            # is the same answer an id nothing ever used gives: their own
            # delete and a company that never existed must not be
            # tellable apart (M2 soft retire). A user whose own record
            # still links it keeps reading it here.
            data = storage.may_see_company(root, identifier, owner)
            if data is None:
                return jsonify(error='Company not found.'), 404
            if request.method == 'GET':
                if request.args.get('view') == 'page':
                    return jsonify(companies.detail_context(root, identifier, session_owner(),
                                                            may_edit_shared()))
                return jsonify(data)
            # M2 (D3): the record is shared universe, so everybody reads
            # it and the admin alone changes it. Checked after the 404 so
            # a tester cannot learn which company ids exist by comparing
            # 403 against 404.
            if not may_edit_shared():
                return shared_denied()
            if request.method == 'DELETE':
                # M2 (D3): the counts in this answer are the deleter's
                # OWN links and nobody else's. They used to be vault-wide,
                # which told the admin how many private records other
                # users hold against a company -- a count is a leak like
                # any other. Their own links are a conflict they can act
                # on, so they still get the 409 and the numbers.
                job_count = sum(job.get('company_id') == identifier
                                for job in storage.list_jobs(root, owner))
                exp_count = sum(exp.get('company_id') == identifier
                                for exp in storage.list_experiences(root, owner))
                if job_count or exp_count:
                    pieces = [f'{job_count} jobs'] * bool(job_count) + [f'{exp_count} experiences'] * bool(exp_count)
                    return jsonify(error='Still linked to ' + ' and '.join(pieces), count=job_count + exp_count), 409
                # Nothing of theirs links. SOFT RETIRE (owner decision,
                # 2026-10-18): the delete succeeds from here, whether or
                # not somebody else's record still points at the company,
                # and the answer is the same either way. Refusing when a
                # foreign record linked was the last one-bit leak -- an
                # admin with no links of their own could tell "somebody
                # has records here" from "nobody does".
                #
                # Which of the two actually happens is invisible from the
                # API and matters on disk. A company nothing links to is
                # deleted outright, as before: no tombstone earns its
                # place when no record needs the id to keep resolving. A
                # company another user's record links is tombstoned
                # instead, because deleting it would leave that job
                # pointing at nothing and `save_job` would then refuse
                # every later edit to it, breaking a record for an owner
                # who can see no cause. Retired, it is gone from every
                # admin-facing surface and from the resolution ladder, so
                # the admin's own next posting never resurrects it, while
                # the user who links it reads it exactly as before.
                if any(record.get('company_id') == identifier
                       for record in storage.list_jobs(root) + storage.list_experiences(root)):
                    storage.retire_company(root, identifier)
                else:
                    storage.delete_company(root, identifier)
                return jsonify(deleted=identifier)
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Record must be an object.')
            # B2: same rule as the job PUT -- provenance only for keys the
            # vault persists, never for keys it drops.
            accepted = storage.company_field_names()
            payload['field_provenance'] = {**data.get('field_provenance', {}),
                **{key: 'user' for key in payload if key != 'field_provenance' and key in accepted}}
            return jsonify(storage.save_company(root, payload | {'name_source': 'owner'}, identifier))

    # A note is the same object on a job and on a company: a title, a
    # body, and the record it lives in. One pair of handlers serves both,
    # picked by the `kind` default on each rule, rather than two copies of
    # the same list arithmetic. Writes go through save_job/save_company,
    # so a note write is an ordinary record write: same lock, same
    # validation, same history backstop.
    #
    # M2 (D3) splits the two halves apart, which is why the loader is
    # wrapped rather than named directly: a note on a job is a write to
    # one user's own private record, so it is scoped to them and
    # somebody else's job answers 'Job not found.'; a note on a company
    # is a write to a shared record, so it is the admin's alone. Giving a
    # note privacy of its own is CAREER-41 and not this change.
    NOTE_KINDS = {
        'jobs': (lambda root, identifier: storage.load_job(root, identifier, session_owner()),
                 storage.save_job, 'Job not found.', False),
        'companies': (lambda root, identifier: storage.may_see_company(root, identifier,
                                                                        session_owner()),
                      storage.save_company, 'Company not found.', True),
    }

    @app.get('/api/notes')
    def notes_api():
        """Every note on this user's own jobs plus every company note,
        newest first, with its record. Read only: a note is edited on the
        page of the record that holds it."""
        return jsonify(notes.page_context(app.config['VAULT_PATH'], session_owner()))

    @app.post('/api/jobs/<identifier>/notes', defaults={'kind': 'jobs'})
    @app.post('/api/companies/<identifier>/notes', defaults={'kind': 'companies'})
    def create_note(kind, identifier):
        root = app.config['VAULT_PATH']
        load, save, missing, shared = NOTE_KINDS[kind]
        with write_lock:
            record = load(root, identifier)
            if record is None:
                return jsonify(error=missing), 404
            if shared and not may_edit_shared():
                return shared_denied()
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Note must be an object.')
            note = storage.new_note(payload.get('title'), payload.get('body') or '')
            # notes_view, not the raw field: a record still holding its
            # notes as legacy free text gets that text persisted as its
            # first note by this very write, never dropped by it.
            save(root, storage.notes_payload([*storage.notes_view(record), note]), identifier)
            return jsonify(note), 201

    @app.route('/api/jobs/<identifier>/notes/<note_id>', methods=['PATCH', 'DELETE'],
               defaults={'kind': 'jobs'})
    @app.route('/api/companies/<identifier>/notes/<note_id>', methods=['PATCH', 'DELETE'],
               defaults={'kind': 'companies'})
    def note_api(kind, identifier, note_id):
        root = app.config['VAULT_PATH']
        load, save, missing, shared = NOTE_KINDS[kind]
        with write_lock:
            record = load(root, identifier)
            if record is None:
                return jsonify(error=missing), 404
            if shared and not may_edit_shared():
                return shared_denied()
            stored = storage.notes_view(record)
            target = next((note for note in stored if note['id'] == note_id), None)
            if target is None:
                return jsonify(error='Note not found.'), 404
            if request.method == 'DELETE':
                save(root, storage.notes_payload([n for n in stored if n['id'] != note_id]), identifier)
                return jsonify(deleted=note_id)
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Note must be an object.')
            edited = storage.edit_note(target, payload)
            save(root, storage.notes_payload([edited if n['id'] == note_id else n for n in stored]),
                 identifier)
            return jsonify(edited)

    @app.route('/api/search', methods=['GET', 'POST'])
    def search_api():
        root = app.config['VAULT_PATH']
        if request.method == 'GET':
            if request.args.get('view') == 'page':
                return jsonify(search.page_context(root))
            return jsonify(storage.load_search(root))
        with write_lock:
            return jsonify(storage.save_search(root, request.get_json()))

    @app.route('/api/experiences', methods=['GET', 'POST'])
    def experience_collection():
        root = app.config['VAULT_PATH']
        owner = session_owner()
        if request.method == 'GET':
            if request.args.get('view') == 'page':
                return jsonify(experiences.page_context(root, owner))
            return jsonify(storage.list_experiences(root, owner))
        payload = request.get_json()
        if not may_edit_shared() and vocabulary_additions(root, payload):
            return shared_denied()
        with write_lock:
            # M2 (D3): a new position is this user's, stamped here, which
            # is the one and only path that creates one. The stamp goes
            # last so a payload carrying its own owner_id cannot name
            # somebody else as the owner.
            return jsonify(storage.save_experience(
                root, _experience_payload(payload) | {storage.OWNER_FIELD: owner.identifier})), 201

    def _experience_payload(payload):
        """One experience write payload with `owner_id` taken out.

        Who a record belongs to is stamped by the path that creates it
        and never again (D4), so a client cannot hand its own position to
        another user or take one of theirs. A non-object payload passes
        through untouched, so save_experience raises its own error for it
        rather than this helper raising a different one.
        """
        return ({k: v for k, v in payload.items() if k != storage.OWNER_FIELD}
                if isinstance(payload, dict) else payload)

    @app.route('/api/experiences/<identifier>', methods=['GET', 'PUT', 'POST', 'DELETE'])
    def experience_api(identifier):
        root = app.config['VAULT_PATH']
        owner = session_owner()
        with write_lock:
            # Somebody else's position reads as None, so every method
            # answers 'Position not found.' for it (M2, D3).
            data = storage.load_experience(root, identifier, owner)
            if data is None:
                return jsonify(error='Position not found.'), 404
            if request.method == 'GET':
                if request.args.get('view') == 'page':
                    return jsonify(experiences.detail_context(root, identifier, owner))
                return jsonify(data)
            if request.method == 'DELETE':
                storage.delete_experience(root, identifier)
                return jsonify(deleted=identifier)
            payload = request.get_json()
            if not may_edit_shared() and vocabulary_additions(root, payload):
                return shared_denied()
            return jsonify(storage.save_experience(root, _experience_payload(payload), identifier))

    @app.post('/api/experiences/<identifier>/link-company')
    def link_experience_company(identifier):
        root = app.config['VAULT_PATH']
        with write_lock:
            exp = storage.load_experience(root, identifier, session_owner())
            if exp is None:
                return jsonify(error='Position not found.'), 404
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Record must be an object.')
            if payload.get('unlink'):
                # Freeze the currently resolved label into the free-text
                # company field, so the experience keeps a readable label
                # afterward instead of reverting to stale pre-link text.
                company = storage.load_company(root, exp.get('company_id')) if exp.get('company_id') else None
                label = company['name'] if company else exp.get('company')
                return jsonify(storage.save_experience(root, {'company_id': None, 'company': label}, identifier))
            if payload.get('company_id'):
                # A company this user cannot see is one they cannot link
                # to, and answers like an id that was never used.
                if not storage.may_see_company(root, payload['company_id'], session_owner()):
                    return jsonify(error='Company not found.'), 404
                return jsonify(storage.save_experience(root, {'company_id': payload['company_id']}, identifier))
            create = payload.get('create')
            if not isinstance(create, dict) or not str(create.get('name') or '').strip():
                raise ValueError('Provide company_id, create, or unlink.')
            # M2 (D3): creating a company is a write to the shared half,
            # so it is the admin's. Checked before the suggestion lookup
            # below, because the request's whole intent is to create one
            # and offering a near-match to pick instead would be a flow
            # that cannot end. Linking this position to a company that
            # already exists (the company_id branch above) and unlinking
            # it stay open to everybody: both write the position only.
            if not may_edit_shared():
                return shared_denied()
            name = create['name'].strip()
            # The reader's own view, not the whole vault: a retired
            # company coming back as a near-match suggestion while a
            # deleted one does not is the tombstone being readable
            # through a response shape (M2 soft retire). Only the admin
            # reaches this line, and a company they retired is one they
            # may not see, so the suggestion never names it and typing
            # that name creates a fresh company instead.
            candidates = storage.visible_companies(root, session_owner())
            if not payload.get('confirm_create'):
                casefolded = {c.get('name', '').strip().casefold(): c for c in candidates}
                close = difflib.get_close_matches(name.casefold(), list(casefolded), n=1, cutoff=0.6)
                if close:
                    return jsonify(suggestion=casefolded[close[0]])
            company = storage.save_company(root, {'name': name, 'kind': create.get('kind', 'employer'),
                                                   'name_source': 'owner'})
            return jsonify(storage.save_experience(root, {'company_id': company['id']}, identifier)), 201

    @app.post('/api/companies/backfill-sector-size')
    def backfill_sector_size():
        """Decision 27: explicit, owner-triggered action only. Never wired to
        run automatically; the external-fetch tier makes real network calls
        that should not happen unannounced.

        The network sweep runs WITHOUT the write lock: a cold pass over many
        employers can take minutes, and holding the vault lock that long
        starves every other writer (the Enrich button, intake, etc.) behind
        it, which reads as 'both buttons do nothing'. Planning is read-only;
        only the fast local-filesystem apply phase takes the lock."""
        root = app.config['VAULT_PATH']
        # M2 (D3): a sweep that rewrites every company is the broadest
        # shared write there is, so it is the admin's alone.
        if not may_edit_shared():
            return shared_denied()
        collector = org_enrich.BackfillAccounting()
        plan, scanned = company_enrichment.plan_backfill(root, collector=collector)
        with write_lock:
            updated = company_enrichment.apply_backfill(root, plan)
        return jsonify(updated=updated, scanned=scanned, signal_summary=collector.summary())

    @app.post('/api/companies/<identifier>/retry')
    def retry_company(identifier):
        """M1 audit: the per-company Retry that replaces the Backfill
        sector/size button -- same explicit, owner-triggered rule as
        backfill_sector_size (decision 27), reusing run_company_cascade
        (the same sectors_cascade/size_cascade entry points) scoped to one
        company instead of sweeping all of them. Never gated on
        AUTO_CASCADE_ENABLED: a deliberate Retry click must never appear
        to do nothing.

        M2 (D3): Retry writes the shared company record, so it stays with
        the admin, and the company page offers the control to nobody
        else."""
        root = app.config['VAULT_PATH']
        if not may_edit_shared():
            return shared_denied()
        company = storage.may_see_company(root, identifier, session_owner())
        if company is None:
            return jsonify(error='Company not found.'), 404
        if company.get('kind', 'employer') != 'employer':
            return jsonify(error='Only employers have sector and size enrichment.'), 400
        result, applied = run_company_cascade(root, identifier)
        if result is None:
            return jsonify(error='Company not found.'), 404
        if result.get('kind', 'employer') != 'employer':
            return jsonify(error='Only employers have sector and size enrichment.'), 400
        # retry_applied is response-only metadata: which cascade fields THIS
        # invocation actually wrote. The frontend must use it (never stored
        # field_states, which can carry an older run's outcome when this
        # invocation skipped a field) to say whether the retry changed
        # anything. Deliberately not saved into the vault record.
        return jsonify({**result, 'retry_applied': applied})

    @app.errorhandler(ValueError)
    def invalid_data(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(400)
    @app.errorhandler(415)
    def bad_request(error):
        return jsonify(error='Provide a valid JSON object.'), error.code

    @app.errorhandler(OSError)
    def storage_error(error):
        app.logger.exception('Vault operation failed')
        return jsonify(error='Unable to access the vault. Please try again.'), 500

    @app.errorhandler(404)
    def not_found(error):
        if request.endpoint in ('job_taxonomy_api', 'experience_form_api'):
            return jsonify(error='Record not found.'), 404
        # Behind the gate like every other page, so it carries the logout
        # affordance too: the login page is the one exception, because it
        # is the one page reachable without a session to end.
        return page_shell(
            'Page not found', '',
            "<section class='card empty-state'><h1>Page not found</h1>"
            "<p class='muted'>This page does not exist. <a href='/search'>Return to Search</a>.</p></section>",
            logout=True,
        ), 404

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--vault', type=Path, default=None)
    args = parser.parse_args()
    create_app(args.vault).run(host=args.host, port=args.port, debug=False)


if __name__ == '__main__':
    main()
