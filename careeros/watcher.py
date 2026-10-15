"""Recheck saved postings; stdout is reserved for actionable cron news."""
import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
import sys
from urllib.error import HTTPError

from careeros import intake, vault

WATCH_STATUSES = {'new', 'interested', 'applied', 'interviewing'}
Event = dict


HASH_VERSION = 2
NOT_WATCHED_REASON = 'Only jobs with status New/Interested/Applied/Interviewing and a posting URL are watched'


def eligible(job):
    return bool(job and job.get('url') and job.get('status') in WATCH_STATUSES)


def posting_fields(url, body):
    """Extract posting content without structured-page chrome or volatile markup."""
    parser = intake.Posting()
    parser.feed(body)
    schema = intake.job_schema(parser, url)
    if schema:
        # The intake salary/location fallbacks must not see surrounding ads.
        body = '<script type="application/ld+json">' + json.dumps(schema).replace('<', r'\u003c') + '</script>'
        description = str(schema.get('description') or '')
    else:
        body = re.sub(r'<(script|style|nav|aside|footer|header)\b[^>]*>.*?</\1\s*>', '', body, flags=re.I | re.S)
        body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
        body = re.sub(r'\bposted\s+\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b', '', body, flags=re.I)
        description = body
    fields = intake.extract(url, body)
    description_parser = intake.Posting()
    description_parser.feed(description)
    fields['description'] = ' '.join(' '.join(description_parser.text).split())
    return fields


def content_hash(fields):
    canonical = {key: ' '.join(str(fields.get(key) or '').split()) for key in
                 ('title', 'company', 'location', 'posted_date', 'salary_note', 'description')}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def scan(root, fetch=None, dry_run=False, *, job_id=None, lock=None) -> list[Event]:
    # Resolve dynamically so offline fixtures also cover the production fetch path.
    fetch = intake.fetch_url if fetch is None else fetch
    root = Path(root)
    if not root.is_dir():
        raise OSError('Vault is not a readable directory')
    list(root.iterdir())
    events = []
    for snapshot in vault.list_jobs(root):
        identifier = snapshot['id']
        url = snapshot.get('url')
        if (job_id is not None and identifier != job_id) or not url or snapshot.get('status') not in WATCH_STATUSES:
            continue
        if snapshot.get('watch', {}).get('watch_status') == 'gone':
            continue
        error, extracted, digest = None, {}, None
        try:
            body = fetch(url)
            extracted = posting_fields(url, body)
            digest = content_hash(extracted)
        except Exception as exc:
            error = exc
        with lock if lock is not None else vault.WriteLock(root):
            job = vault.load_job(root, identifier)
            # Discard stale results after concurrent deletion, URL/status change or scan.
            if (job is None or job.get('url') != url
                    or job.get('status') != snapshot.get('status')
                    or job.get('watch', {}) != snapshot.get('watch', {})):
                continue
            watch = dict(job.get('watch', {}))
            job['watch'] = watch
            watch['last_checked'] = vault.timestamp()
            company = vault.load_company(root, job.get('company_id')) or {}

            def record(kind, detail, notify=True):
                entry = vault.append_event(job, kind, detail)
                if notify:
                    events.append(entry | dict(job_id=identifier, title=job['title'], company=company.get('name', 'Unknown company')))

            if error is not None:
                immediate = isinstance(error, HTTPError) and error.code in (404, 410)
                watch['consecutive_errors'] = watch.get('consecutive_errors', 0) + 1
                gone = immediate or watch['consecutive_errors'] >= 3
                watch['watch_status'] = 'gone' if gone else 'error'
                if gone:
                    record('posting_gone', f'HTTP {error.code}' if immediate else 'unreachable')
                    # D7: a posting that is gone is a fact about the
                    # posting, so the scan sets the flag and the date it
                    # was found and leaves the status alone. Ending a job
                    # is the owner's decision, and this is not it. An
                    # earlier closed_at is kept: the day the posting went
                    # is the day it was first found gone, which is what
                    # the closed-postings review counts the week from.
                    job['closed'] = True
                    if not job.get('closed_at'):
                        job['closed_at'] = date.today().isoformat()
            else:
                watch.update(watch_status='ok', consecutive_errors=0)
                if not watch.get('content_hash'):
                    record('watch_started', 'Posting baseline recorded', notify=False)
                elif watch.get('hash_version', 1) >= HASH_VERSION and watch['content_hash'] != digest:
                    record('posting_changed', 'posting content changed')
                watch['content_hash'] = digest
                watch['hash_version'] = HASH_VERSION
                if not job.get('salary_info') and not job.get('salary_note') and extracted.get('salary_info'):
                    job.update(salary_info=True, salary_note=extracted['salary_note'])
                    record('salary_found', extracted['salary_note'])
            if not dry_run:
                vault.save_watch_result(root, job)
    return events


def format_event(event):
    label = {'posting_gone':'gone', 'posting_changed':'changed', 'salary_found':'salary'}[event['event']]
    suffix = {'gone':f"({event['detail']}) — likely filled/closed", 'changed':'— posting content changed',
              'salary':f"— {event['detail']} now listed"}[label]
    # Owner text must not break the one-line-per-event contract.
    return ' '.join(f"{label}: [{event['job_id']}] {event['title']} @ {event['company']} {suffix}".split())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        events = scan(args.vault, dry_run=args.dry_run)
    except OSError as error:
        print(f'Unable to access vault: {error}', file=sys.stderr)
        return 1
    for event in events:
        print(format_event(event))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
