"""The Personio adapter's runner: CAREER-53's command line, unchanged.

`scripts/run_ats_fetch.py` is the program; this file is that program with
Personio's defaults filled in, so every command CAREER-53 documented
still works as it stands:

    scripts/run_personio_fetch.py discover --vault /srv/career-os
    scripts/run_personio_fetch.py fetch --sample 400 --seed 7
    scripts/run_personio_fetch.py export
    scripts/run_personio_fetch.py report

What it fills in is `--provider personio` and `--root data/personio`,
which is where CAREER-53's store, its 2 467 tenants and its snapshots
already are. Everything else -- the subcommands, the discovery routes,
the fetch queue, the run entry, the pool export, the cron and systemd
shapes -- is documented in `run_ats_fetch.py` and shared with the five
adapters CAREER-54 added, so there is one implementation and not two.

Kept rather than deleted because the brief says not to break the
existing command line, and because a cron line in a runbook is a
published interface: a path that answers `No such file` is a worse way
to learn about a rename than a wrapper that keeps working.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_ats_fetch as _generic  # noqa: E402
from run_ats_fetch import *  # noqa: E402,F401,F403  (the subcommands and their wiring)
# The private helpers too, because `import *` skips them and this
# module's own tests drive the fetch queue and the tenant update
# directly.
from run_ats_fetch import (_common_crawl, _fetch_queue, _from_probe_file,  # noqa: E402,F401
                           _limiter, _load_zefix, _print_run, _probe_websites, _robots_gate,
                           _root, _run_entry, _store, _tally, _taxonomy_versions,
                           _tenant_summary, _total, _update_tenant, _variant_options)
from careeros.feeds import personio  # noqa: E402

DEFAULT_ROOT = Path('data/personio')


def build_parser():
    """The generic parser with Personio's provider and root filled in, so
    `--provider` is optional and `--root` defaults where CAREER-53's
    store lives."""
    return _generic.build_parser(default_root=DEFAULT_ROOT,
                                 providers=(personio.PROVIDER,),
                                 default_provider=personio.PROVIDER)


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == '__main__':
    raise SystemExit(main())
