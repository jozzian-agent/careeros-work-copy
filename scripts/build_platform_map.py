"""Build the ATS platform map: which company uses which hiring platform.

Owner ruling 2026-10-17, priority b, in his own words: "list which
companies use which platform". This is the command line the brief names.

    scripts/build_platform_map.py
    scripts/build_platform_map.py --probe-file data/ats/vault_probe_2026-10-17.yaml

It reads every provider's tenants file and posting state plus the
vault-probe file and writes three things:

    data/ats_platform_map.yaml        tracked, small
    data/ats/platform_map_full.yaml   staged, every tenant the index named
    data/ats_platform_map_<date>.md   tracked, the readable report

Touches no network: the evidence is what `discover`, `probe-vault` and
`fetch` already recorded. The logic is `careeros.feeds.platform_map` and
the same thing runs as `scripts/run_ats_fetch.py --provider <p> map`, so
this file is the named entry point and not a second implementation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_ats_fetch  # noqa: E402


def build_parser():
    parser = run_ats_fetch.build_parser(
        providers=run_ats_fetch.ALL_PROVIDERS,
        # Any provider will do: `map` reads every store it finds, and
        # `--provider` only decides which default root `--root` would
        # have been. Stating it keeps the shared parser's one required
        # option satisfied without this script asking for something it
        # does not use.
        default_provider=run_ats_fetch.ALL_PROVIDERS[0])
    return parser


def main(argv=None):
    """`map` and its own flags. The shared parser wants the subcommand
    before them, so it is put there: this script takes `--probe-file`,
    `--day`, `--out`, `--full` and `--report` and nothing else. For the
    runner's top-level options use `scripts/run_ats_fetch.py` directly.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if 'map' not in argv:
        argv.insert(0, 'map')
    args = build_parser().parse_args(argv)
    if args.command != 'map':
        print(f'this script builds the map; use scripts/run_ats_fetch.py for {args.command}')
        return 1
    return run_ats_fetch.cmd_map(args)


if __name__ == '__main__':
    raise SystemExit(main())
