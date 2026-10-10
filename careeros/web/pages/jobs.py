"""Posting board and job detail."""
import re

from flask import abort, current_app
from markupsafe import Markup
from careeros import sectors, vault, watcher
from careeros.web.ui import page
from careeros.web.markdown import render_markdown

EMPTY_STATE = 'No jobs yet — paste a posting link to get started.'

def needs_attention(job):
    """M1 audit batch B: a job needs owner action when the company link is
    unresolved or ingest got stuck, mirroring company_link_state/ingest_state
    as already stored on the entry dict (no separate recompute in JS)."""
    return (job.get('company_link_state') == 'needs_review'
            or job.get('ingest_state') in ('fetch_failed', 'extract_failed'))

def build_page():
    root = current_app.config['VAULT_PATH']
    function_labels = vault.function_label_map(root)
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    entries = vault.list_jobs(root)
    for job in entries:
        job['needs_attention'] = needs_attention(job)
    return page('Jobs', 'jobs', 'jobs.html', entries=entries,
                companies={c['id']: c for c in vault.list_companies(root) if 'id' in c},
                statuses=vault.STATUSES, empty=EMPTY_STATE, function_options=function_options)

def show_remote_chip(job):
    """Show the remote label only when the location does not already include it.

    Word-boundary match so town names merely containing the letters
    (e.g. Remotedorf) still get the chip.
    """
    return bool(job.get("remote_ok")) and not re.search(r"\bremote\b", (job.get("location") or "").casefold())


def detail(identifier):
    root = current_app.config['VAULT_PATH']
    job = vault.load_job(root, identifier)
    if job is None:
        abort(404)
    description = job.get('description') or ''
    return page(job.get('title', 'Job'), 'jobs', 'job_detail.html', job=job, show_remote_chip=show_remote_chip(job),
                watch_eligible=watcher.eligible(job), watch_reason=watcher.NOT_WATCHED_REASON,
                company=vault.load_company(root, job.get('company_id')), statuses=vault.STATUSES,
                function_labels=vault.function_label_map(root),
                markdown=Markup(render_markdown(job.get('notes', ''))),
                has_description=bool(description.strip()),
                llm_pending=identifier in current_app.config.get('LLM_PENDING', {}))

def taxonomy(identifier):
    """Taxonomy sub-page (approved wireframe 2026-10-07): function (ESCO),
    the company's ISIC sectors read-only, and controlled-vocabulary tags.
    No provenance display per the owner's decision."""
    root = current_app.config['VAULT_PATH']
    job = vault.load_job(root, identifier)
    if job is None:
        abort(404)
    company = vault.load_company(root, job.get('company_id'))
    function_labels = vault.function_label_map(root)
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    isic_labels = {s['code']: s['label'] for s in sectors.load_isic_sections()}
    tag_labels = vault.tag_label_map(root)
    return page(f"Classification · {job.get('title', 'Job')}", 'jobs', 'job_taxonomy.html', job=job,
                company=company, function_options=function_options, function_labels=function_labels,
                isic_labels=isic_labels, tags=job.get('tags') or [], tag_labels=tag_labels,
                tag_registry=vault.load_tags(root))
