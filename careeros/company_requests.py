"""Resolving a company request: matching it, linking it, or handing it
to the admin.

PR #44 shipped the filing half. A user who may not write a shared
company asks for the one their posting names, and the ask becomes a
private `company_requests` record with status `filed`
(`careeros/vault.py`, "company requests"). This module is the other
half: what turns a filed request into a company and a link.

Two surfaces read it and neither owns it:

* `scripts/resolve_company_requests.py`, the nightly pass on the VPS.
  It runs with no Flask app and no request context, which is why the
  matching and the writes live here rather than in a server closure.
* the admin review list in `careeros/server.py`
  (`GET /api/company-requests` and its approve/reject endpoints), which
  settles whatever the nightly pass could not.

Both go through the same three functions, so an approval by hand and a
nightly match write the same fields in the same shape and a surface
cannot grow its own idea of what resolving means.

## What may be matched automatically, and what may not

Three rungs, in order, and every one of them is an equality:

1. the exact normalized name, which is `identity.find_all_by_exact_name`
   and therefore also matches a company's `name_variant` identifiers;
2. a `name_variant` identifier equal to the requested name as typed,
   which is `identity.find_by_identifier`;
3. suffix-stripped equality, which is `company_suffixes` applied to both
   sides, so "Northwind AG" and "Northwind" are the same employer.

A fuzzy candidate is NEVER linked. `identity.fuzzy_candidates` is read
in exactly one place here, `suggestions`, which feeds the admin list a
scored hint to click; nothing acts on its output. That is rule 4 of the
identity ladder and the reason this module cannot silently merge two
employers whose names merely look alike.

More than one company matching a rung is an ambiguity, not a
first-wins pick (rule 5): the group goes to the admin with a
`needs_admin` status, whatever the auto-create switch says.

## Why a group and not a request

The same company gets asked for by several people, and by one person on
several postings. Requests are therefore resolved by NAME: one match or
one creation settles every open request whose name normalizes the same
way, and links every one of their jobs. Otherwise the first run would
create the company and the second would find it by exact name, which
works but writes the company's history as two unrelated events and
leaves the other requests open for a day.
"""
from careeros import company_suffixes, vault
from careeros.org_store import VaultOrganisationStore
from org_intake import identity

#: The statuses a resolution writes, out of `vault.COMPANY_REQUEST_STATUSES`.
#: Named here so a caller reads a word rather than a string literal, and
#: so the one list stays the vault's.
LINKED = 'linked'
CREATED = 'created'
NEEDS_ADMIN = 'needs_admin'
REJECTED = 'rejected'

#: Why a request can end up rejected without anybody deciding anything.
#: A request outlives the job it came from on purpose (the name is what a
#: later resolution matches against, and a job is deleted by its owner at
#: any time), so the resolver meets requests whose job is gone and says
#: so in the record rather than leaving them open for ever.
JOB_GONE_NOTE = ('The job this request came from was deleted before the '
                 'request was resolved.')

#: The link reason every resolution writes onto a job, out of
#: `vault.COMPANY_LINK_REASONS`.
#:
#: `manual` and not `name_exact`, for the same reason
#: `server.resolve_review` writes it: the basis of this link is a person
#: naming the company, not an extraction matching one. It is also what
#: keeps a later `POST /api/jobs/<id>/resolve` from undoing the answer,
#: since the provenance written beside it marks the three link fields as
#: owner-set and the ladder's rule 1 leaves an owner-set link alone.
LINK_REASON = 'manual'


#: Every status that still owes somebody an answer: the one a filing
#: writes, and the one the resolver hands to the admin. A request in
#: either of them may be approved or rejected; one in `linked`,
#: `created` or `rejected` has been answered and is not touched again.
UNRESOLVED = (vault.COMPANY_REQUEST_OPEN, NEEDS_ADMIN)


def requests_with_status(root, statuses, owner=None):
    """Every request this reader may see in one of those statuses, oldest
    id first.

    `owner` is a `vault.Owner` and is passed straight to
    `vault.list_company_requests`, whose rule this does not restate: the
    admin reads every request, because they are the one person who can
    resolve one, and nobody else reads anybody else's. An admin endpoint
    therefore passes its own session scope and gets the whole queue.

    `owner=None` is the unscoped read that same function documents as
    the resolver's: the nightly pass runs off a request thread with no
    session to scope to.

    Oldest first so a pass is deterministic and the person who asked
    first is answered first. `list_company_requests` answers newest
    first, which is the order a list surface wants and the opposite of
    the one a queue does.
    """
    return sorted((request for request in vault.list_company_requests(root, owner)
                   if request.get('status') in statuses),
                  key=lambda request: str(request.get('id')))


def open_requests(root, owner=None):
    """The nightly pass's queue: the requests a filing wrote."""
    return requests_with_status(root, (vault.COMPANY_REQUEST_OPEN,), owner)


def admin_queue(root, owner=None):
    """The admin review list's queue: the ones the pass could not settle."""
    return requests_with_status(root, (NEEDS_ADMIN,), owner)


def shared_companies(root):
    """Every company a request may be matched to.

    Retired companies are left out, the same way
    `org_store.VaultOrganisationStore.list_organisations` leaves them
    out of the resolution ladder: a retired company takes no new link
    from anybody (M2 soft retire), so matching one would produce a link
    `vault.linkable_company` then refuses.
    """
    return [company for company in vault.list_companies(root)
            if not vault.is_retired(company)]


def company_name_forms(company):
    """The suffix-stripped forms of every name one company answers to.

    Its own name and every `name_variant` identifier on file, which is
    the same set `identity` matches an exact name against -- read here
    through `company_suffixes` so rung 3 compares like with like.
    """
    names = [company.get('name')]
    names += [identifier.get('value') for identifier in company.get('identifiers') or []
              if identifier.get('type') == 'name_variant']
    forms = {company_suffixes.strip_legal_suffix(name) for name in names if name}
    return {form for form in forms if form}


def match_company(companies, name):
    """The one company this name is, as `(company, ambiguous)`.

    `(None, False)` is "nothing on file is this name", which is what the
    auto-create switch answers. `(None, True)` is "more than one company
    is", which is the admin's question and never the switch's.

    The three rungs are the module docstring's. Rung 2 can only ever
    confirm what rung 1 already found, because a raw-equal name variant
    is also a normalized-equal one; it is written out anyway because it
    is the rung the design names, and saying so here is cheaper than a
    reader wondering which lookup is missing.
    """
    exact = identity.find_all_by_exact_name(companies, name)
    if len(exact) > 1:
        return None, True
    if exact:
        return exact[0], False
    variant = identity.find_by_identifier(companies, 'name_variant', name)
    if variant is not None:
        return variant, False
    target = company_suffixes.strip_legal_suffix(name)
    if not target:
        return None, False
    stripped = [company for company in companies if target in company_name_forms(company)]
    if len(stripped) > 1:
        return None, True
    return (stripped[0], False) if stripped else (None, False)


def suggestions(companies, name):
    """Scored company suggestions for the admin list, in the API's shape.

    The ONE reader of `identity.fuzzy_candidates` in this product's
    request path. Nothing acts on it: it is a hint the admin clicks, and
    a resolution that linked on it would be the silent merge rule 4 of
    the ladder forbids.
    """
    return [{'company_id': candidate['record_id'], 'name': candidate['name'],
             'score': candidate['score']}
            for candidate in identity.fuzzy_candidates(companies, name)]


def requests_for_name(requests, name):
    """Every request in `requests` asking for the same company as `name`.

    Same name means the same normalized name, which is the notion of
    sameness rung 1 matches companies by, so a group cannot hold two
    names the exact-name rung would treat as different employers.
    """
    target = company_suffixes.normalized_name(name)
    return [request for request in requests
            if company_suffixes.normalized_name(request.get('name')) == target]


def group_waiting(waiting):
    """`partition`'s waiting pairs as the groups that resolve together.

    One list of `(request, job)` pairs per normalized name, in the order
    the names were first seen, so a caller that read the queue
    oldest-first gets groups in the order they were asked for.
    """
    groups = {}
    for request, job in waiting:
        key = company_suffixes.normalized_name(request.get('name'))
        groups.setdefault(key, []).append((request, job))
    return list(groups.values())


def create_company(root, name):
    """Bring the requested company into existence, through the server's
    own create path.

    `identity.apply_review` with `create=` is exactly what
    `server.resolve_review` calls when the admin answers a company ask
    by naming a new company, so a company this creates is
    indistinguishable from one created there: the capability builds the
    record, this module never hands a company dict to the vault.

    `url=''` is what says there is no posting URL to learn an identifier
    from. A group can hold several jobs on several ATS tenants, so there
    is no one URL whose tenant or domain this company owns, and teaching
    it one of them would be a guess. The name is the evidence, and the
    name is all that is written.

    No requester is stamped on the record. A company is shared universe
    and carries no owner by design (decision D3); who asked for it stays
    on the private request record.
    """
    result = identity.apply_review(VaultOrganisationStore(root), url='',
                                   create={'name': name})
    return result['record']


def link_job(root, job, company_id):
    """Link one job to the resolved company.

    The write `server.resolve_review` makes, field for field: the
    company, the linked state, the reason, the cleared review block and
    the provenance that marks the three link fields as owner-set.
    """
    provenance = {**job.get('field_provenance', {}), 'company_id': 'user',
                  'company_link_state': 'user', 'company_link_reason': 'user'}
    return vault.save_job(root, {
        'company_id': company_id, 'company_link_state': 'linked',
        'company_link_reason': LINK_REASON, 'company_review': None,
        'field_provenance': provenance,
    }, job['id'])


def settle(root, request, status, *, company_id=None, note=None):
    """Write one request's outcome, and nothing it was not sent."""
    updates = {'status': status}
    if company_id is not None:
        updates['resolved_company_id'] = company_id
    if note is not None:
        updates['resolution_note'] = note
    return vault.save_company_request(root, updates, request['id'])


def admin_rows(root, owner=None):
    """The admin review list, one row per `needs_admin` request.

    Read-only. What each row carries, and why nothing more:

    * `name`, `created_at` and `id` come straight off the request.
    * `requester` is the id the filing stamped plus that account's
      display name, which the admin manages anyway (`python -m
      careeros.users`). The address is not here: the review list needs
      to know who asked, not how to mail them.
    * `job` carries the id the request names, which is already on the
      admin-readable request record, and the title ONLY when the job
      loads under this reader's own ownership scope. A request comes
      from somebody else's private posting, and decision D3 is that the
      admin reaches no part of a tester's job -- `GET /api/jobs/<id>`
      answers them 404 for one. So a title the admin may not read is
      absent rather than lifted out of the record here, and the id is
      what the row identifies the posting by.
    * `suggestions` is `suggestions()` above: scored, never acted on.

    `owner` is this reader's `vault.Owner`. Passing None reads titles
    unscoped and is for a caller with no session; no endpoint does that.
    """
    # Imported here rather than at the top of the module, the way
    # `careeros/enrich.py` imports its own: this is the one function in
    # here the nightly pass never calls, and `careeros.users` pulls in
    # Flask for the session it reads. The pass has to run headless.
    from careeros import users

    companies = shared_companies(root)
    rows = []
    for request in admin_queue(root, owner):
        requester = users.load_user(root, request.get(vault.OWNER_FIELD)) or {}
        job = vault.load_job(root, request.get('job_id'), owner)
        rows.append({
            'id': request.get('id'),
            'name': request.get('name'),
            'created_at': request.get('created_at'),
            'requester': {'id': request.get(vault.OWNER_FIELD),
                          'name': requester.get('name')},
            'job': {'id': request.get('job_id'),
                    'title': (job or {}).get('title')},
            'suggestions': suggestions(companies, request.get('name')),
        })
    return rows


def partition(root, requests):
    """Sort `requests` by what is still true about the job each came from.

    `(waiting, gone, answered)`, each a list of `(request, job)` pairs
    except `gone`, which is requests alone.

    A request outlives its job, so two of its three futures are decided
    before any company is matched:

    * `gone` -- the job was deleted. There is nothing left to link, so
      the request is rejected rather than resolved.
    * `answered` -- the job already carries a company. Somebody settled
      the ask another way between the filing and now: the owner answered
      the pending link themselves, or an earlier run did. The link is
      left exactly as it stands and the request is settled against the
      company the job really points at. Nothing here overwrites a link
      it did not make, because `company_id` on a settled job carries
      owner provenance and rule 1 is that human edits win.
    * `waiting` -- the job is still asking. These are the only requests
      a name match or a creation is for.

    The job read is unscoped: the resolver has no session, and the admin
    endpoints have proved the caller is the admin before they get here.
    A request's `job_id` was written by the filing endpoint off a job
    that loaded under its own owner's scope, so this is a re-read of an
    already proved id -- the same rule the AI queue's own reloads follow.
    """
    waiting, gone, answered = [], [], []
    for request in requests:
        job = vault.load_job(root, request.get('job_id'))
        if job is None:
            gone.append(request)
        elif job.get('company_id'):
            answered.append((request, job))
        else:
            waiting.append((request, job))
    return waiting, gone, answered


def settle_decided(root, gone, answered):
    """Write the outcomes `partition` already decided.

    Returns `(rejected ids, linked ids)`: the requests whose job is gone
    and the ones whose job somebody else already linked.
    """
    rejected = [settle(root, request, REJECTED, note=JOB_GONE_NOTE)['id']
                for request in gone]
    linked = [settle(root, request, LINKED, company_id=job['company_id'])['id']
              for request, job in answered]
    return rejected, linked


def apply_group(root, waiting, company, status):
    """Link every waiting job in one group and settle every request in it.

    The ONE writer both surfaces use, so the nightly pass and an
    approval by hand produce the same records. `waiting` is the pairs
    `partition` answered with, so every job here is one that still has
    no company.

    Returns `(linked job ids, settled request ids)`.
    """
    jobs, settled = [], []
    for request, job in waiting:
        link_job(root, job, company['id'])
        jobs.append(job['id'])
        settled.append(settle(root, request, status, company_id=company['id'])['id'])
    return jobs, settled
