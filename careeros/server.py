"""Flask entry point for the CareerOS shell."""

import argparse
import os
from threading import RLock
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, request, jsonify
from careeros import vault as storage
from careeros import intake
from careeros import ingest

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
    app.add_url_rule('/companies/<identifier>', 'company_detail', companies.detail)
    write_lock = storage.WriteLock(app.config['VAULT_PATH'], RLock())

    # Worker-local pending assumes a single-process deployment.
    llm_pending = {}
    # Exposed so tests can join a background extraction deterministically.
    app.config['LLM_THREADS'] = {}

    def fill_company_metadata(root, company, extracted):
        changes = {key: extracted[key] for key in ('sector', 'size', 'locations')
                   if not company.get(key) and extracted.get(key)}
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

    def apply_llm_update(root, baseline, fields):
        """baseline is the just-created heuristic record: a field only counts as
        still heuristic-sourced (safe to overwrite) if it still matches that
        snapshot, so an owner edit made while the LLM call is in flight sticks."""
        fillable = ('title', 'company', 'location', 'employment_type', 'seniority',
                    'remote_ok', 'keywords', 'summary', 'contact_email')
        with write_lock:
            job = storage.load_job(root, baseline['id'])
            if job is None or job.get('url') != baseline.get('url'):
                return
            fields = ingest.redact(fields)
            if not ingest.is_valid_contact_email(fields.get('contact_email')):
                fields.pop('contact_email', None)
            updates = {key: fields[key] for key in fillable
                       if fields.get(key) not in (None, '', [])
                       and job.get(key) == baseline.get(key)}
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

    def start_llm_enrichment(root, baseline, description):
        job_id = baseline['id']
        llm_pending[job_id] = True

        def on_result(fields):
            try:
                if fields:
                    apply_llm_update(root, baseline, fields)
            except Exception as error:
                ingest.warn(error)
            finally:
                llm_pending.pop(job_id, None)

        try:
            app.config['LLM_THREADS'][job_id] = ingest.extract_async(description, on_result)
        except Exception as error:
            llm_pending.pop(job_id, None)
            ingest.warn(error)

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
        metadata = {key: data.pop(key) for key in ('sector', 'size', 'locations')}
        posting_origin = _company_website(f'{urlsplit(url).scheme}://{_netloc(url)}')
        root = app.config['VAULT_PATH']
        with write_lock:
            company = find_company(root, name, url)
            if company is None and name:
                company = storage.save_company(root, {'name': name, 'website': website or posting_origin,
                                                       'name_source': 'auto'} | metadata)
            elif company:
                company = fill_company_metadata(root, company, metadata)
                if not company.get('website'):
                    company = storage.save_company(root, {'website': website or posting_origin}, company['id'])
            job = storage.save_job(root, data | {'url': url, 'company_id': company['id'] if company else None, 'sector': metadata['sector']})
        start_llm_enrichment(root, job, data['description'])
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
            extracted = intake.ingest_posting(url, html)
        except Exception:
            return jsonify(error='Unable to fetch and parse posting.'), 422
        with write_lock:
            job = storage.load_job(root, identifier)
            if job is None:
                return jsonify(error='Job not found.'), 404
            if job.get('url') != url:
                return jsonify(error='Posting URL changed during enrichment. Try again.'), 409
            fill_fields = ('title', 'location', 'source', 'posted_date',
                           'employment_type', 'valid_through', 'description', 'company',
                           'seniority', 'summary', 'keywords', 'ingest_source', 'remote_ok', 'sector')
            if not job.get('enriched'):
                fill_fields += ('salary_info', 'salary_note')
            updates = {key: extracted[key] for key in fill_fields
                       if (job.get(key) in (None, '', []) or
                           (key == 'salary_info' and job.get(key) is False))
                       and extracted.get(key) not in (None, '')}
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
            return jsonify(storage.save_job(root, request.get_json(), identifier))

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
                count = sum(job.get('company_id') == identifier for job in storage.list_jobs(root))
                if count:
                    return jsonify(error=f'Still linked to {count} jobs', count=count), 409
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
