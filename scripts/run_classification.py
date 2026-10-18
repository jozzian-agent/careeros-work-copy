"""Run the classification pipeline over the universe, one layer at a time.

CAREER-57's runner. It reads postings, hands each to
`careeros.classify`, and prints what the run settled, what it left
unknown and what it flagged for a human. It writes nothing anywhere
unless asked: a dry run is the default, like every `migrate_*` script in
this repository, and the vault is never written at all.

    scripts/run_classification.py --pool data/ats/exports/golden_set_pool_2026-10-18.yaml
    scripts/run_classification.py --vault /srv/career-os --layer rules
    scripts/run_classification.py --pool ... --layer all --out data/classification/run.yaml

## The layers

`--layer rules` is deterministic and free, and is what the accuracy
report measures. `--layer llm` and `--layer all` add the local model on
the owner's Ollama host for the fields the rules could not settle;
`--layer rules` is the default precisely so that nothing reaches for a
network by accident.

**The live local batch has not been run.** The host's availability is
unconfirmed, so this build tests the model layer against fakes only.
`--layer all --dry-run` is the command that proves the wiring without
writing, and dropping `--dry-run` with an `--out` is the owner's own
batch. `--probe` makes one request and prints its latency and token
counts, which is the cheapest way to find out whether the host answers
at all before starting 204 of them.

## Where the output goes

`--out PATH` writes one YAML file carrying every classified posting, its
value records, its salary block, what it still owes a human, and the
per-call measurements M1-3 asks for. Under `data/`, beside the feed
stores, because the vault is the owner's and this is staging output --
the same rule `scripts/seed_zefix_zurich.py` and the whole `feeds`
package follow.
"""
import argparse
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careeros import classify, vault  # noqa: E402
from careeros.classify import llm, rules  # noqa: E402
from careeros.feeds import store as store_module  # noqa: E402

#: The pool export names its stores by path; the provider is the last
#: segment of each, except Personio's, whose store predates the shared
#: `data/ats/<provider>` layout (CAREER-53 built `data/personio` first).
POOL_DEFAULT = 'data/ats/exports/golden_set_pool_2026-10-18.yaml'


def store_roots(pool, repo_root):
    """provider -> Store, from the export's own `stores` list.

    Read from the file rather than hard-coded, so an export made from a
    different set of stores still resolves.
    """
    roots = {}
    for path in pool.get('stores') or ():
        name = Path(path).name
        roots[name] = store_module.Store(repo_root / path, provider=name)
    return roots


def pool_postings(path, *, limit=None):
    """Every pool row as its frozen posting snapshot.

    The pool row carries the stratification keys and the source chain but
    not the posting text, and the text is what this pipeline reads. The
    snapshot is where it is -- which is the point of the snapshot store:
    the pool, the label and the classification are all about the same
    frozen text even if the posting changes tomorrow.
    """
    path = Path(path)
    pool = yaml.safe_load(path.read_text())
    repo_root = Path(__file__).resolve().parents[1]
    stores = store_roots(pool, repo_root)
    postings, missing = [], 0
    for row in (pool.get('postings') or ())[:limit]:
        store = stores.get(row['provider'])
        snapshot = store.read_posting_snapshot(row['tenant'], row['posting_id'],
                                               row['content_hash']) if store else None
        if not snapshot or not snapshot.get('posting'):
            missing += 1
            continue
        postings.append(snapshot['posting'])
    return postings, {'rows': len(pool.get('postings') or ()), 'read': len(postings),
                      'snapshot_missing': missing, 'exported_at': pool.get('exported_at')}


def vault_jobs(root):
    """Every stored job, through the vault's own tolerant reader."""
    jobs = []
    for path in sorted((Path(root) / 'jobs').glob('*.yaml')):
        data = vault._read(path)
        if data:
            jobs.append(data)
        else:
            print(f'  {path.name}: unreadable or empty, skipped', file=sys.stderr)
    return jobs


def subjects(args):
    """Everything to classify in this run, as subjects, with a note on
    where each batch came from."""
    found, notes = [], []
    if args.pool:
        postings, note = pool_postings(args.pool, limit=args.limit)
        found.extend(classify.from_feed_posting(posting) for posting in postings)
        notes.append(f"pool {args.pool}: {note['read']} of {note['rows']} rows read from "
                     f"snapshots ({note['snapshot_missing']} missing)")
    if args.vault:
        jobs = vault_jobs(args.vault)[:args.limit]
        found.extend(classify.from_vault_job(job) for job in jobs)
        notes.append(f'vault {args.vault}: {len(jobs)} jobs')
    return found, notes


def run(found, *, layer, config=None, client=None, at=None):
    """Every subject through the pipeline. Returns the results."""
    return [classify.classify(subject, layer=layer, client=client, config=config, at=at)
            for subject in found]


def summarise(found, results):
    """The run as counts: coverage per field, the review queue, the
    salary readings, and the model's own measurements."""
    table = classify.coverage(results)
    owed = Counter(reason for result in results for reason in result['review'].values())
    salaries = [result['salary'] for result in results if result['salary']]
    calls = [call for result in results for call in result['metrics']]
    tokens = [call['total_tokens'] for call in calls if call.get('total_tokens')]
    latencies = [call['latency_ms'] for call in calls if call.get('latency_ms')]
    return {
        'postings': len(found),
        'coverage': table,
        'review': dict(owed),
        'salary_readings': len(salaries),
        'model_calls': {
            'calls': len(calls),
            'failed': sum(1 for call in calls if not call.get('ok')),
            'total_tokens': sum(tokens) or None,
            'mean_tokens': round(sum(tokens) / len(tokens), 1) if tokens else None,
            'mean_latency_ms': round(sum(latencies) / len(latencies), 1) if latencies else None,
            'models': sorted({call['model'] for call in calls}),
        } if calls else None,
    }


def print_summary(notes, summary, *, layer, writing):
    print(f"layer={layer}  mode={'WRITE' if writing else 'DRY RUN'}  "
          f"postings={summary['postings']}")
    for note in notes:
        print(f'  {note}')
    print('-' * 78)
    print(f"{'field':<20}{'settled':>9}{'unknown':>9}{'review':>8}   by source")
    for field, row in summary['coverage'].items():
        sources = ', '.join(f'{name}={count}' for name, count in sorted(row['by_source'].items()))
        print(f"{field:<20}{row['settled']:>9}{row['unknown']:>9}{row['needs_review']:>8}   "
              f"{sources or '-'}")
    print('-' * 78)
    print(f"salary readings: {summary['salary_readings']}")
    if summary['review']:
        print('needs review: ' + ', '.join(f'{reason}={count}'
                                           for reason, count in sorted(summary['review'].items())))
    if summary['model_calls']:
        calls = summary['model_calls']
        print(f"model calls: {calls['calls']} ({calls['failed']} failed)  "
              f"mean {calls['mean_latency_ms']}ms  mean {calls['mean_tokens']} tokens  "
              f"total {calls['total_tokens']} tokens  models: {', '.join(calls['models'])}")


def payload(found, results, summary, *, layer, at):
    """The run as one document: what was classified, and every value."""
    return {
        'classified_at': at,
        'day': date.today().isoformat(),
        'layer': layer,
        'taxonomy_version': rules.taxonomy.TAXONOMY_VERSION,
        'summary': summary,
        'postings': [{'key': result['key'], 'title': subject['title'],
                      'values': result['values'], 'salary': result['salary'],
                      'review': result['review'], 'metrics': result['metrics']}
                     for subject, result in zip(found, results)],
    }


def probe(config):
    """One request, to find out whether the host answers and what it
    costs. The cheapest thing to run before a batch of 204."""
    subject = classify.subject(
        title='Produktmanager 80-100% (m/w/d)',
        text='Wir suchen eine erfahrene Person für unser Produktmanagement in Zürich.')
    answers, metrics = llm.classify(subject, ('contract', 'seniority'),
                                    client=config.client(), config=config)
    print(f"model={metrics['model']}  ok={metrics['ok']}  "
          f"latency={metrics['latency_ms']}ms  tokens={metrics['total_tokens']}")
    if metrics.get('error'):
        print(f"  error: {metrics['error']}")
    for field, record in answers.items():
        print(f"  {field}: {record['value']} "
              f"({classify.review_reason(record) or 'settled'})")
    return 0 if metrics['ok'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pool', nargs='?', const=POOL_DEFAULT,
                        help=f'a golden-set pool export (default path: {POOL_DEFAULT})')
    parser.add_argument('--vault', help='a vault whose jobs to classify, read-only')
    parser.add_argument('--layer', choices=('rules', 'llm', 'all'), default='rules',
                        help='which layers to run (default: rules, which touches no network)')
    parser.add_argument('--limit', type=int, help='classify at most this many postings')
    parser.add_argument('--out', help='write the whole run to this YAML file')
    parser.add_argument('--dry-run', action='store_true',
                        help='classify and report, write nothing even with --out')
    parser.add_argument('--probe', action='store_true',
                        help='make one model request and print its latency and token count')
    parser.add_argument('--model', help='override CLASSIFY_LLM_MODEL for this run (M1-4)')
    args = parser.parse_args(argv)

    config = llm.Config.from_env()
    if args.model:
        config = llm.Config(base_url=config.base_url, api_key=config.api_key, model=args.model,
                            native=config.native, temperature=config.temperature,
                            timeout=config.timeout)
    if args.probe:
        return probe(config)
    if not args.pool and not args.vault:
        raise SystemExit('nothing to classify: pass --pool and/or --vault')

    found, notes = subjects(args)
    if not found:
        raise SystemExit('no postings found to classify')
    client = config.client() if args.layer in ('llm', 'all') else None
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    results = run(found, layer=args.layer, config=config, client=client, at=at)
    summary = summarise(found, results)
    writing = bool(args.out) and not args.dry_run
    print_summary(notes, summary, layer=args.layer, writing=writing)
    if not args.out:
        return 0
    if args.dry_run:
        print(f'DRY RUN: nothing was written. Re-run without --dry-run to write {args.out}.')
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload(found, results, summary, layer=args.layer, at=at),
                                  sort_keys=False, allow_unicode=True))
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
