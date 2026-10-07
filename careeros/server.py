"""Flask entry point for the CareerOS shell."""

import argparse
import os
from threading import RLock, Thread
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, request, jsonify
from careeros import vault as storage
from careeros import intake
from careeros import ingest
from careeros import sectors
from careeros import company_lookup
import difflib

from careeros.web.pages import companies, experiences, interviews, jobs, search
from careeros.web.theme import page_shell

DEFAULT_VAULT = Path('/root/career-os')


SHARED_ATS_HOSTS = (
    'lever.co', 'greenhouse.io', 'smartrecruiters.com', 'workday.com',
    'myworkdayjobs.com', 'icims.com', 'taleo.net', 'ashbyhq.com',
    'teamtailor.com', 'personio.de', 'recruitee.com',
)


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


def _company_url_key(value):
    host = _netloc(value)
    if _shared_ats(value):
        segments = urlsplit(value).path.strip('/').split('/')
        return (host, segments[0].casefold()) if segments[0] else None
    return (host,) if host else None


def _company_website(value):
    return (ingest.redact(value) or None) if value and not _shared_ats(value) else None



def create_app(vault: str | Path | None = None) -> Flask:
    """Build the app with an explicit, environment, or default vault path."""
    app = Flask(__name__)
    app.config['VAULT_PATH'] = Path(vault if vault is not None else os.environ.get('CAREEROS_VAULT', DEFAULT_VAULT)).expanduser()
    app.add_url_rule('/', 'index', search.build_page)
    for module in (search, experiences, jobs, companies, interviews):
        slug = module.__name__.rsplit('.', 1)[-1]
        app.add_url_rule(f'/{slug}', slug, module.build_page)

    app.add_url_rule('/experiences/new', 'experience_new', experiences.form)
    app.add_url_rule('/experiences/<identifier>', 'experience_detail', experiences.detail)
    app.add_url_rule('/experiences/<identifier>/edit', 'experience_edit', experiences.form)
    app.add_url_rule('/jobs/<identifier>', 'job_detail', jobs.detail)
    app.add_url_rule('/jobs/<identifier>/taxonomy', 'job_taxonomy', jobs.taxonomy)
    app.add_url_rule('/companies/<identifier>', 'company_detail', companies.detail)
    app.add_url_rule('/companies/<identifier>/taxonomy', 'company_taxonomy', companies.taxonomy)
    write_lock = storage.WriteLock(app.config['VAULT_PATH'], RLock())

    # Worker-local pending assumes a single-process deployment.
    llm_pending = {}
    # Exposed so pages can render the pending state without reaching into the closure.
    app.config['LLM_PENDING'] = llm_pending
    # Exposed so tests can join a background extraction deterministically.
    app.config['LLM_THREADS'] = {}
    app.config['REFRESH_THREADS'] = {}
    # Guards llm_pending reservation so intake and /extract can never both
    # win a worker slot for the same job, and so a stale callback can never
    # clear a slot a newer run holds.
    pending_lock = RLock()

    def fill_company_metadata(root, company, extracted):
        """Section 1's field-group matrix applies at every enrichment entry
        point: institutions receive only locations (name/website lookups
        happen at their own call sites), and only employers receive sector
        and size derivation. (The former third kind, 'aggregate', was
        removed by owner decision on 2026-10-07: it never applied to a
        real record.)

        Fill eligibility consults the NEW-shape fields (sectors, size_range,
        size_class), never the legacy sector/size strings alone, so an
        owner-set sectors list or size pair is not clobbered by a posting
        signal just because the legacy field happens to be empty.
        employee_count is deliberately not in the generic passthrough: the
        company schema has no raw employee_count field, only the derived
        size_range/size_class, so it gets its own branch through the atomic,
        consistency-checked derivation function instead."""
        kind = company.get('kind', 'employer')
        changes = {}
        if extracted.get('locations') and not company.get('locations'):
            changes['locations'] = extracted['locations']
        if kind == 'employer':
            if extracted.get('sector') and not company.get('sector') and not company.get('sectors'):
                changes['sector'] = extracted['sector']
            if extracted.get('size') and not company.get('size') and not company.get('size_range'):
                changes['size'] = extracted['size']
            changes.update(sectors.fill_size_updates(
                extracted.get('employee_count'), company.get('size_range'), company.get('size_class')))
        return storage.save_company(root, changes, company['id']) if changes else company

    def find_company(root, name, posting_url):
        companies_ = storage.list_companies(root)
        if name:
            match = next((c for c in companies_
                         if str(c.get('name', '')).strip().casefold() == name.strip().casefold()), None)
            if match:
                return match
        key = _company_url_key(posting_url)
        if key:
            linked = {j.get('company_id') for j in storage.list_jobs(root)
                      if _shared_ats(posting_url) and _company_url_key(j.get('url')) == key}
            return next((c for c in companies_
                         if _company_url_key(c.get('website')) == key or c['id'] in linked), None)
        return None

    def apply_llm_update(root, baseline, fields, token):
        """baseline is the just-created heuristic record: a field only counts as
        still heuristic-sourced (safe to overwrite) if it still matches that
        snapshot, so an owner edit made while the LLM call is in flight sticks."""
        fillable = ('title', 'company', 'location', 'employment_type', 'seniority',
                    'remote_ok', 'keywords', 'contact_email',
                    'background', 'skills', 'certifications', 'responsibilities', 'function')
        with write_lock, pending_lock:
            if llm_pending.get(baseline['id']) is not token:
                return
            job = storage.load_job(root, baseline['id'])
            if job is None or any(job.get(key) != baseline.get(key) for key in ('url', 'original_url')):
                return
            explicit_empty_summary = 'summary' in fields and not (fields['summary'] or '').strip()
            fields = ingest.redact(fields)
            if not ingest.is_valid_contact_email(fields.get('contact_email')):
                fields.pop('contact_email', None)
            if 'function' in fields:
                known = storage.known_function_ids(root)
                fields['function'] = [value for value in fields['function'] if value in known]
            updates = {key: fields[key] for key in fillable
                       if fields.get(key) not in (None, '', [])
                       and job.get(key) == baseline.get(key)}
            # A key present with an empty value means the model deliberately
            # found no real summary (e.g. a chrome-only page); that must be
            # able to clear a previously polluted summary and its AI badge,
            # which the blanket not-in-(None,'',[]) filter above would block.
            # An absent key (no 'summary' in fields) must leave it untouched.
            if ('summary' in fields and (fields['summary'] or explicit_empty_summary)
                    and job.get('summary') == baseline.get('summary')):
                summary = (fields['summary'] or '').strip()
                updates['summary'] = summary
                updates['summary_source'] = 'ai' if summary else ''
            if job.get('ingest_source') == 'heuristic':
                updates['ingest_source'] = 'llm'
            correction = updates.get('company')
            changed_company = correction and correction != job.get('company')
            if changed_company and job.get('company_id') == baseline.get('company_id'):
                matching = next((c for c in storage.list_companies(root)
                                 if c.get('name', '').strip().casefold() == correction.strip().casefold()), None)
                if matching:
                    updates['company_id'] = matching['id']
            updates['enriched'] = True
            detail = None
            if changed_company:
                detail = ('Extraction corrected company text; ' +
                          ('linked company matched.' if 'company_id' in updates
                           else 'existing company link retained for review.'))
            storage.save_job(root, updates, baseline['id'], correction_detail=detail)

    # Prune on the next request, retaining joinable handles for active work.
    def prune_threads():
        threads = app.config['LLM_THREADS']
        for identifier, thread in list(threads.items()):
            if not thread.is_alive():
                threads.pop(identifier, None)

    @app.before_request
    def prune_completed_enrichment():
        prune_threads()

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

    def start_llm_enrichment(root, baseline, description, token):
        """Start the background worker for a reserved token.

        Returns True if a worker thread actually started. The callback only
        clears llm_pending if it still owns the slot (token identity check),
        so a slow/stale run can never clobber a newer run's pending state.
        """
        job_id = baseline['id']

        def on_result(fields):
            try:
                if fields:
                    apply_llm_update(root, baseline, fields, token)
            except Exception as error:
                ingest.warn(error)
            finally:
                with pending_lock:
                    if llm_pending.get(job_id) is token:
                        llm_pending.pop(job_id, None)

        try:
            thread = ingest.extract_async(description, on_result,
                                          function_options=storage.function_facet_options(root))
        except Exception as error:
            with pending_lock:
                if llm_pending.get(job_id) is token:
                    llm_pending.pop(job_id, None)
            ingest.warn(error)
            return False
        app.config['LLM_THREADS'][job_id] = thread
        return True

    @app.route('/api/jobs/intake', methods=['POST'])
    def job_intake():
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError('Provide a URL object.')
        url = intake.check_url(payload.get('url'))
        try:
            html = intake.fetch_url(url)
        except Exception:
            html = ''
        data = intake.heuristic_posting(url, html)
        name = data['company']
        website = _company_website(data.pop('website'))
        metadata = {key: data.pop(key) for key in ('sector', 'size', 'locations', 'employee_count')}
        posting_origin = _company_website(f'{urlsplit(url).scheme}://{_netloc(url)}')
        root = app.config['VAULT_PATH']
        with write_lock:
            company = find_company(root, name, url)
            if company is None and name:
                # employee_count has no company-schema home of its own (the
                # company only ever stores the derived size_range/size_class).
                # When the posting supplied a raw count, derive the pair
                # atomically from that same count and include it in the
                # creation payload, dropping the bucket-only legacy size
                # string so the two fields can never be written by separate
                # passes from different inputs. Without a count, the legacy
                # bucket string still yields size_range alone, which the
                # document allows (a bucket never yields a confident class).
                creation = {'name': name, 'website': website or posting_origin, 'name_source': 'auto'}
                derived = sectors.derive_size(metadata.get('employee_count'))
                if derived:
                    creation |= derived
                    creation |= {k: v for k, v in metadata.items() if k not in ('employee_count', 'size')}
                else:
                    creation |= {k: v for k, v in metadata.items() if k != 'employee_count'}
                company = storage.save_company(root, creation)
                company = fill_company_metadata(root, company, metadata)
            elif company:
                company = fill_company_metadata(root, company, metadata)
                if not company.get('website'):
                    company = storage.save_company(root, {'website': website or posting_origin}, company['id'])
            job = storage.save_job(root, data | {'url': url, 'company_id': company['id'] if company else None,
                                                 'sector': metadata['sector'], 'employee_count': metadata['employee_count']})
        token = reserve_enrichment(job['id'])
        if token is not None:
            start_llm_enrichment(root, job, data['description'], token)
        return jsonify(job=job, company=company), 201

    @app.post('/api/jobs/<identifier>/enrich')
    def enrich_job(identifier):
        root = app.config['VAULT_PATH']
        job = storage.load_job(root, identifier)
        if job is None:
            return jsonify(error='Job not found.'), 404
        try:
            url = intake.check_url(job.get('url'))
            html = intake.fetch_url(url)
            if not isinstance(html, str) or not html.strip():
                raise ValueError('Posting returned no content.')
            extracted = intake.ingest_posting(url, html, function_options=storage.function_facet_options(root))
        except Exception:
            return jsonify(error='Unable to fetch and parse posting.'), 422
        with write_lock:
            job = storage.load_job(root, identifier)
            if job is None:
                return jsonify(error='Job not found.'), 404
            if job.get('url') != url:
                return jsonify(error='Posting URL changed during enrichment. Try again.'), 409
            if 'function' in extracted:
                known = storage.known_function_ids(root)
                extracted['function'] = [value for value in extracted['function'] if value in known]
            fill_fields = ('title', 'location', 'source', 'posted_date',
                           'employment_type', 'valid_through', 'description', 'company',
                           'seniority', 'summary', 'keywords', 'ingest_source', 'remote_ok', 'sector',
                           'background', 'skills', 'certifications', 'responsibilities',
                           'employee_count', 'function')
            if not job.get('enriched'):
                fill_fields += ('salary_info', 'salary_note')
            updates = {key: extracted[key] for key in fill_fields
                       if (job.get(key) in (None, '', []) or
                           (key == 'salary_info' and job.get(key) is False))
                       and extracted.get(key) not in (None, '')}
            if 'summary' in updates:
                # extracted['summary'] can be the heuristic fallback even when
                # other fields came from the model; trust the field-specific
                # marker ingest.extract() computed, not the overall ingest_source.
                updates['summary_source'] = extracted.get('summary_source', '')
            # A nonempty title is always treated as owner-set; no heuristic replacement.
            name, website = extracted['company'], _company_website(extracted['website'])
            company = storage.load_company(root, job.get('company_id'))
            if name:
                matching = next((c for c in storage.list_companies(root)
                                 if c.get('name', '').strip().casefold() == name.strip().casefold()), None)
                shared = company and any(j.get('company_id') == company['id'] and j['id'] != identifier
                                         for j in storage.list_jobs(root))
                if company and company.get('name_source', 'owner') != 'auto':
                    if website and not company.get('website'):
                        storage.save_company(root, {'website': website}, company['id'])
                elif matching:
                    updates['company_id'] = matching['id']
                    if website and not matching.get('website'):
                        storage.save_company(root, {'website': website}, matching['id'])
                elif company and not shared:
                    changes = {'name': name, 'website': website, 'name_source': 'auto'}
                    storage.save_company(root, changes, company['id'])
                else:
                    company = storage.save_company(root, {'name': name, 'website': website, 'name_source': 'auto'})
                    updates['company_id'] = company['id']
            target = storage.load_company(root, updates.get('company_id', job.get('company_id')))
            if target:
                fill_company_metadata(root, target, extracted)
            updates['enriched'] = True
            return jsonify(storage.save_job(root, updates, identifier))

    @app.post('/api/jobs/<identifier>/extract')
    def extract_job(identifier):
        """Reserve before starting background refresh and enrichment."""
        root = app.config['VAULT_PATH']
        with write_lock:
            job = storage.load_job(root, identifier)
            if job is None:
                return jsonify(error='Job not found.'), 404
            token = reserve_enrichment(identifier)
        if token is None:
            return jsonify(job | {'llm_pending': True}), 202
        target = job.get('original_url') or job.get('url')

        def refresh_and_enrich():
            handed_off = False
            try:
                outcome, description = 'skipped', job.get('description') or ''
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
                with write_lock:
                    current = storage.load_job(root, identifier)
                    if current is None or any(current.get(key) != job.get(key)
                                              for key in ('url', 'original_url', 'description')):
                        return
                    with pending_lock:
                        if llm_pending.get(identifier) is not token:
                            return
                    updates = {'refresh': outcome}
                    if outcome == 'ok':
                        updates['description'] = description
                    storage.save_job(root, ingest.redact(updates), identifier,
                                     history_event=('description_refreshed' if outcome == 'ok'
                                                    else 'description_refresh_' + outcome,
                                                    'Live posting refreshed.' if outcome == 'ok'
                                                    else 'Live page unavailable; enriching stored text.' if outcome == 'failed'
                                                    else 'No posting URL; enriching stored text.'))
                # Keep the reservation snapshot for owner-edit protection.
                handed_off = start_llm_enrichment(root, job, description, token)
            except Exception as error:
                ingest.warn(error)
            finally:
                if not handed_off:
                    with pending_lock:
                        if llm_pending.get(identifier) is token:
                            llm_pending.pop(identifier, None)

        thread = Thread(target=refresh_and_enrich, daemon=True)
        app.config['REFRESH_THREADS'][identifier] = thread
        try:
            thread.start()
        except Exception as error:
            ingest.warn(error)
            with pending_lock:
                if llm_pending.get(identifier) is token:
                    llm_pending.pop(identifier, None)
            return jsonify(job | {'llm_pending': False}), 202
        return jsonify(job | {'llm_pending': True}), 202

    @app.post('/api/companies/<identifier>/enrich')
    def enrich_company(identifier):
        from careeros.enrich import regenerate_company
        with write_lock:
            company = regenerate_company(app.config['VAULT_PATH'], identifier)
            if company is None:
                return jsonify(error='Company not found.'), 404
            return jsonify(company)

    @app.post('/api/watch/scan')
    def watch_scan():
        from careeros import watcher
        root = app.config['VAULT_PATH']
        identifier = request.args.get('job')
        if identifier is not None and storage.load_job(root, identifier) is None:
            return jsonify(error='Job not found.'), 404
        events = watcher.scan(root, job_id=identifier, lock=write_lock)
        result = dict(events=events)
        if identifier:
            job = storage.load_job(root, identifier)
            if not watcher.eligible(job):
                result.update(watch_status='not_watched', reason=watcher.NOT_WATCHED_REASON)
            else:
                result['watch_status'] = job.get('watch', {}).get('watch_status', 'unchanged')
        return jsonify(result)

    @app.get('/api/jobs')
    def job_collection():
        return jsonify(storage.list_jobs(app.config['VAULT_PATH']))

    @app.get('/api/companies')
    def company_collection():
        return jsonify(storage.list_companies(app.config['VAULT_PATH']))

    @app.route('/api/jobs/<identifier>', methods=['GET', 'PUT', 'DELETE'])
    def job_api(identifier):
        root = app.config['VAULT_PATH']
        with write_lock:
            data = storage.load_job(root, identifier)
            if data is None:
                return jsonify(error='Job not found.'), 404
            if request.method == 'GET':
                return jsonify(data | {'llm_pending': identifier in llm_pending})
            if request.method == 'DELETE':
                storage.delete_job(root, identifier)
                return jsonify(deleted=identifier)
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Record must be an object.')
            # Only trusted extraction paths (apply_llm_update, /enrich,
            # /extract) may set summary_source: strip any client-supplied
            # value, then clear it whenever this PUT actually changes the
            # summary text (replacement or clearing to empty), since an
            # owner edit must never keep an AI badge on text it didn't write.
            payload = {k: v for k, v in payload.items() if k != 'summary_source'}
            if 'summary' in payload and payload['summary'] != data.get('summary'):
                payload['summary_source'] = ''
            return jsonify(storage.save_job(root, payload, identifier))

    @app.route('/api/companies/<identifier>', methods=['GET', 'PUT', 'DELETE'])
    def company_api(identifier):
        root = app.config['VAULT_PATH']
        with write_lock:
            data = storage.load_company(root, identifier)
            if data is None:
                return jsonify(error='Company not found.'), 404
            if request.method == 'GET':
                return jsonify(data)
            if request.method == 'DELETE':
                job_count = sum(job.get('company_id') == identifier for job in storage.list_jobs(root))
                exp_count = sum(exp.get('company_id') == identifier for exp in storage.list_experiences(root))
                if job_count or exp_count:
                    pieces = [f'{job_count} jobs'] * bool(job_count) + [f'{exp_count} experiences'] * bool(exp_count)
                    return jsonify(error='Still linked to ' + ' and '.join(pieces), count=job_count + exp_count), 409
                storage.delete_company(root, identifier)
                return jsonify(deleted=identifier)
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise ValueError('Record must be an object.')
            return jsonify(storage.save_company(root, payload | {'name_source': 'owner'}, identifier))

    @app.route('/api/search', methods=['GET', 'POST'])
    def search_api():
        root = app.config['VAULT_PATH']
        if request.method == 'GET':
            return jsonify(storage.load_search(root))
        with write_lock:
            return jsonify(storage.save_search(root, request.get_json()))

    @app.route('/api/experiences', methods=['GET', 'POST'])
    def experience_collection():
        root = app.config['VAULT_PATH']
        if request.method == 'GET':
            return jsonify(storage.list_experiences(root))
        with write_lock:
            return jsonify(storage.save_experience(root, request.get_json())), 201

    @app.route('/api/experiences/<identifier>', methods=['GET', 'PUT', 'POST', 'DELETE'])
    def experience_api(identifier):
        root = app.config['VAULT_PATH']
        with write_lock:
            data = storage.load_experience(root, identifier)
            if data is None:
                return jsonify(error='Position not found.'), 404
            if request.method == 'GET':
                return jsonify(data)
            if request.method == 'DELETE':
                storage.delete_experience(root, identifier)
                return jsonify(deleted=identifier)
            return jsonify(storage.save_experience(root, request.get_json(), identifier))

    @app.post('/api/experiences/<identifier>/link-company')
    def link_experience_company(identifier):
        root = app.config['VAULT_PATH']
        with write_lock:
            exp = storage.load_experience(root, identifier)
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
                if not storage.load_company(root, payload['company_id']):
                    return jsonify(error='Company not found.'), 404
                return jsonify(storage.save_experience(root, {'company_id': payload['company_id']}, identifier))
            create = payload.get('create')
            if not isinstance(create, dict) or not str(create.get('name') or '').strip():
                raise ValueError('Provide company_id, create, or unlink.')
            name = create['name'].strip()
            candidates = storage.list_companies(root)
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
        collector = company_lookup.BackfillAccounting()
        plan, scanned = company_lookup.plan_backfill(root, collector=collector)
        with write_lock:
            updated = company_lookup.apply_backfill(root, plan)
        return jsonify(updated=updated, scanned=scanned, signal_summary=collector.summary())

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
        return page_shell(
            'Page not found', '',
            "<section class='card empty-state'><h1>Page not found</h1>"
            "<p class='muted'>This page does not exist. <a href='/search'>Return to Search</a>.</p></section>",
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
