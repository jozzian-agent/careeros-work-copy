"""Posting board and job detail."""
import re

from flask import abort, current_app
from markupsafe import Markup
from careeros import vault, watcher
from org_intake import classify as sectors
from careeros.web.ui import page
from careeros.web.markdown import render_markdown

EMPTY_STATE = 'No jobs yet — paste a posting link to get started.'

def needs_attention(job):
    """M1 audit batch B: a job needs owner action when the company link is
    unresolved or ingest got stuck, mirroring company_link_state/ingest_state
    as already stored on the entry dict (no separate recompute in JS)."""
    return (job.get('company_link_state') == 'needs_review'
            or job.get('ingest_state') in ('fetch_failed', 'extract_failed'))

def page_context(root):
    return board_context(vault.list_jobs(root), vault.list_companies(root),
                         vault.function_label_map(root))

def board_context(entries, companies, function_labels):
    """Build the board context without I/O or mutating input records."""
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    entries = [job | {'needs_attention': needs_attention(job)} for job in entries]
    return dict(
        entries=entries,
        companies={c['id']: c for c in companies if 'id' in c},
        statuses=vault.STATUSES,
        empty=EMPTY_STATE,
        function_options=function_options,
    )

def build_page():
    root = current_app.config['VAULT_PATH']
    context = page_context(root)
    return page('Jobs', 'jobs', 'jobs.html', **context)

def show_remote_chip(job):
    """Show the remote label only when the location does not already include it.

    Word-boundary match so town names merely containing the letters
    (e.g. Remotedorf) still get the chip.
    """
    return bool(job.get("remote_ok")) and not re.search(r"\bremote\b", (job.get("location") or "").casefold())


def detail_context(root, identifier, llm_pending=False):
    job = vault.load_job(root, identifier)
    if job is None:
        abort(404)
    return job_context(job, vault.load_company(root, job.get('company_id')),
                       vault.function_label_map(root), llm_pending)

def job_context(job, company, function_labels, llm_pending=False):
    """Build detail data from an explicit record snapshot."""
    description = job.get('description') or ''
    return dict(
        job=job,
        show_remote_chip=show_remote_chip(job),
        watch_eligible=watcher.eligible(job),
        watch_reason=watcher.NOT_WATCHED_REASON,
        company=company,
        statuses=vault.STATUSES,
        function_labels=function_labels,
        markdown=Markup(render_markdown(job.get('notes', ''))),
        has_description=bool(description.strip()),
        llm_pending=llm_pending,
    )

def detail(identifier):
    root = current_app.config['VAULT_PATH']
    context = detail_context(root, identifier, identifier in current_app.config.get('LLM_PENDING', {}))
    return page(context['job'].get('title', 'Job'), 'jobs', 'job_detail.html', **context)

def taxonomy_context(root, identifier):
    """Taxonomy sub-page (approved wireframe 2026-10-07): function (ESCO),
    the company's ISIC sectors read-only, and controlled-vocabulary tags.
    No provenance display per the owner's decision."""
    job = vault.load_job(root, identifier)
    if job is None:
        abort(404)
    return classification_context(
        job, vault.load_company(root, job.get('company_id')),
        vault.function_label_map(root), sectors.load_isic_sections(),
        vault.tag_label_map(root), vault.load_tags(root))

def classification_context(job, company, function_labels, isic_sections, tag_labels, tag_registry):
    function_options = sorted(((fid, info['label']) for fid, info in function_labels.items()),
                              key=lambda pair: pair[1].casefold())
    isic_labels = {s['code']: s['label'] for s in isic_sections}
    return dict(
        job=job,
        company=company,
        function_options=function_options,
        function_labels=function_labels,
        isic_labels=isic_labels,
        tags=job.get('tags') or [],
        tag_labels=tag_labels,
        tag_registry=tag_registry,
    )

def taxonomy(identifier):
    root = current_app.config['VAULT_PATH']
    context = taxonomy_context(root, identifier)
    return page(f"Classification · {context['job'].get('title', 'Job')}", 'jobs', 'job_taxonomy.html', **context)
