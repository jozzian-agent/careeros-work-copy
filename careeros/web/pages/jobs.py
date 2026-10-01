"""Posting board and job detail."""
from flask import abort, current_app
from markupsafe import Markup
from careeros import vault, watcher
from careeros.web.ui import page
from careeros.web.markdown import render_markdown

EMPTY_STATE = 'No jobs yet — paste a posting link to get started.'

def build_page():
    root = current_app.config['VAULT_PATH']
    return page('Jobs', 'jobs', 'jobs.html', entries=vault.list_jobs(root), companies={c['id']: c for c in vault.list_companies(root) if 'id' in c}, statuses=vault.STATUSES, empty=EMPTY_STATE)

def detail(identifier):
    root = current_app.config['VAULT_PATH']
    job = vault.load_job(root, identifier)
    if job is None:
        abort(404)
    return page(job.get('title', 'Job'), 'jobs', 'job_detail.html', job=job, watch_eligible=watcher.eligible(job), watch_reason=watcher.NOT_WATCHED_REASON, company=vault.load_company(root, job.get('company_id')), statuses=vault.STATUSES, markdown=Markup(render_markdown(job.get('notes', ''))))
