"""Flask entry point for the CareerOS shell."""

import argparse
import os
from threading import RLock
from pathlib import Path

from flask import Flask, request, jsonify
from careeros import vault as storage
from careeros import intake

from careeros.web.pages import companies, experiences, interviews, jobs, search
from careeros.web.theme import page_shell

DEFAULT_VAULT = Path('/root/career-os')


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

    def fill_company_metadata(root, company, extracted):
        changes = {key: extracted[key] for key in ('sector', 'size', 'locations')
                   if not company.get(key) and extracted.get(key)}
        return storage.save_company(root, changes, company['id']) if changes else company

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
        data = intake.ingest_posting(url, html)
        name = data['company']
        website = data.pop('website')
        metadata = {key: data.pop(key) for key in ('sector', 'size', 'locations')}
        root = app.config['VAULT_PATH']
        with write_lock:
            company = next((c for c in storage.list_companies(root) if str(c.get('name', '')).strip().casefold() == name.strip().casefold()), None)
            if company is None and name:
                company = storage.save_company(root, {'name': name, 'website': website, 'name_source': 'auto'} | metadata)
            elif company:
                company = fill_company_metadata(root, company, metadata)
            job = storage.save_job(root, data | {'url': url, 'company_id': company['id'] if company else None})
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
                           'seniority', 'summary', 'keywords', 'ingest_source', 'remote_ok')
            if not job.get('enriched'):
                fill_fields += ('salary_info', 'salary_note')
            updates = {key: extracted[key] for key in fill_fields
                       if (job.get(key) in (None, '', []) or
                           (key == 'salary_info' and job.get(key) is False))
                       and extracted.get(key) not in (None, '')}
            # A nonempty title is always treated as owner-set; no heuristic replacement.
            name, website = extracted['company'], extracted['website']
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
                return jsonify(data)
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
