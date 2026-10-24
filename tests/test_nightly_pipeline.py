"""The nightly pipeline's own resilience: the log, the caps, the fails line.

What this protects (CAREER-93): on 2026-10-20 the greenhouse fetch was
OOM-killed, the script died with it, and the morning after held no
`nightly_2026-10-21.log` at all -- a dead pipeline looked exactly like a
pipeline that never ran. These run the real script with the python leg
pointed at a stub, because the one thing the brief forbids is running
the real nightly (hours of network traffic) to test the shell around it.
"""
import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / 'scripts' / 'nightly_pipeline.sh'

#: A python that answers every leg the pipeline calls, so the shell's own
#: decisions are what is under test. `NIGHTLY_FAIL` is a comma-separated
#: list of command lines that should fail, each named by any part of it.
STUB = """#!/bin/sh
args="$*"
echo "stub $args"
cut -d: -f3 /proc/self/cgroup >> "$NIGHTLY_CGROUPS"
IFS=,
for leg in $NIGHTLY_FAIL; do
  case "$args" in
    *"$leg"*) echo "stub refusing $leg"; exit 1;;
  esac
done
case "$args" in
  *export*) mkdir -p "$(dirname "$NIGHTLY_POOL")"; echo "- id: one" > "$NIGHTLY_POOL";;
esac
exit 0
"""


@pytest.fixture
def pipeline(tmp_path):
    """The script, with its python stubbed and its data under tmp_path."""
    stub = tmp_path / 'python-stub'
    stub.write_text(STUB)
    stub.chmod(0o755)
    data = tmp_path / 'data'
    (data / 'nightly').mkdir(parents=True)
    pool = data / 'ats' / 'exports' / f"golden_set_pool_{date.today().isoformat()}.yaml"
    # -u matters: the child's "Serving HTTP ... port N" banner is the only
    # way to learn its port, but a pipe-attached stdout is block-buffered,
    # so without -u the line never flushes and the read below hangs.
    serving = subprocess.Popen(['python3', '-u', '-m', 'http.server', '0', '--bind', '127.0.0.1'],
                               cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    port = None
    for line in serving.stdout:                      # "Serving HTTP on ... port 41235 ..."
        if 'port' in line:
            port = line.split('port')[1].split()[0].strip(' )')
            break

    def run(providers='lever', *, fail='', llm=True, env=None):
        environment = {
            **os.environ,
            'NIGHTLY_PYTHON': str(stub),
            'NIGHTLY_DATA': str(data),
            'NIGHTLY_PROVIDERS': providers,
            'NIGHTLY_ATTEMPTS': '2',
            'NIGHTLY_BACKOFF': '0',
            'NIGHTLY_OLLAMA': (f'http://127.0.0.1:{port}' if llm
                               else 'http://127.0.0.1:1'),
            'NIGHTLY_FAIL': fail,
            'NIGHTLY_POOL': str(pool),
            'NIGHTLY_CGROUPS': str(tmp_path / 'cgroups.txt'),
            **(env or {}),
        }
        done = subprocess.run(['bash', str(PIPELINE)], capture_output=True, text=True,
                              env=environment, timeout=120)
        log = next(iter(sorted((data / 'nightly').glob('nightly_*.log'))), None)
        return done, (log.read_text() if log else None)

    yield run
    serving.terminate()


def test_the_days_log_exists_even_when_the_first_stage_dies(pipeline):
    """The 2026-10-20 failure mode: the log file is created before any
    stage runs, so a total failure still says so in the day's file."""
    done, log = pipeline('bogus-provider', fail='--provider bogus-provider')
    assert log is not None, 'the log file is written before the first stage'
    assert log.splitlines()[0].startswith('== nightly pipeline'), \
        'the day and the host are in the file before anything can die'
    assert 'fetch bogus-provider FAILED after 2 attempt(s)' in log
    assert 'fails: fetch:bogus-provider' in log
    assert 'FAILED:' in done.stdout, 'the Telegram line still says what broke'
    assert done.returncode == 1


def test_one_providers_failure_stops_that_provider_and_nothing_else(pipeline):
    done, log = pipeline('personio lever ashby', fail='--provider lever')
    assert 'fetch lever FAILED' in log
    assert 'fetch personio ok' in log
    assert 'fetch ashby ok' in log, 'the providers after the failed one still ran'
    assert '-- export ok' in log, 'and so did the export'
    assert '== nightly finished, fails: fetch:lever ==' in log


def test_every_failed_stage_is_named_in_the_one_summary_line(pipeline):
    done, log = pipeline('lever', fail='--provider lever,export,compress')
    assert ('== nightly finished, fails: compress fetch:lever export pool-missing =='
            in log), 'every failed stage, in one line, including what it cost downstream'
    assert 'CareerOS nightly' in done.stdout
    assert 'FAILED: compress fetch:lever export pool-missing' in done.stdout


def test_an_unreachable_llm_skips_the_legs_and_still_answers_on_stdout(pipeline):
    """A fetch with no classification is worse than nothing fetched, so
    the three legs are skipped as one -- but the owner hears about it,
    which is what the log-only `exit 1` used to swallow."""
    done, log = pipeline('lever', llm=False)
    assert 'FATAL: local LLM host' in log
    assert 'fetch lever' not in log
    assert 'llm-unreachable' in done.stdout
    assert done.returncode == 1


def test_the_snapshot_compression_runs_before_anything_fetches(pipeline):
    done, log = pipeline('lever')
    lines = log.splitlines()
    compressing = next(index for index, line in enumerate(lines)
                       if line.startswith('-- compress posting snapshots older than 30 day(s)'))
    fetching = next(index for index, line in enumerate(lines)
                    if line.startswith('-- fetch lever ok'))
    assert compressing < fetching, 'housekeeping frees the disk the fetch then writes to'
    assert '--all-providers --older-than 30 --apply' in lines[compressing + 1]
    assert done.returncode == 0


def test_a_low_disk_watermark_warns_and_runs_anyway(pipeline):
    done, log = pipeline('lever', env={'NIGHTLY_DISK_FLOOR_MB': '999999999'})
    assert 'WARNING: only' in log
    assert 'continuing anyway' in log
    assert '-- fetch lever ok' in log, 'a warning is not a gate'
    assert done.returncode == 0


def test_every_python_leg_runs_in_its_own_capped_scope(pipeline, tmp_path):
    """Defense in depth: a leg that runs away is killed inside its own
    scope, rather than the kernel picking the biggest process on the
    host -- which twice was the owner's Telegram bot. Each leg's own
    cgroup is the evidence; the log line alone would pass while every
    leg ran uncapped."""
    done, log = pipeline('lever')
    scopes = [line for line in (tmp_path / 'cgroups.txt').read_text().splitlines() if line]
    assert scopes, 'every leg records the cgroup it ran in'
    mine = Path('/proc/self/cgroup').read_text().rsplit(':', 1)[-1].strip()
    if 'systemd-run gave no scope' in log:
        assert scopes == [mine] * len(scopes), \
            'with no scope to be had it says so rather than looking capped'
    else:
        assert 'memory cap per python leg: MemoryMax=2000M MemoryHigh=off' in log
        assert all(scope.endswith('.scope') and scope != mine for scope in scopes), scopes
    assert '-- fetch lever ok' in log, 'either way the pipeline runs'
