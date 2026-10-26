"""What the deploy configuration promises: the systemd units' content
contracts, `setup-vps.sh --check` changing nothing, and deploy.sh's
environment surface.

These are the facts deploy/ and the app have to agree on, and nothing
else checks them. The units start the app with command-line flags
because the app reads no variable for its host or its port; the health
gate polls the one unauthenticated route the app really serves; the
release venv is built with the system python3. Every one of those is a
sentence in two files at once, which is exactly the kind of agreement
that rots silently.

Nothing here reaches the network, writes outside tmp_path, or needs
root: `--check` is allowed to run unprivileged precisely so this test
can run it, and a PATH-shadowing `python3` stub stands in for the 3.14
the VPS has and this host may not.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

from careeros import server

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
UNITS = DEPLOY / 'systemd'
SETUP = DEPLOY / 'setup-vps.sh'
DEPLOY_SH = DEPLOY / 'deploy.sh'
SMOKE = ROOT / 'tests' / 'smoke.sh'

#: environment -> the port the unit, the Caddyfile and deploy.sh all name.
PORTS = {'prod': 8001, 'stg': 8002}

#: Every hardening directive the two app units carry. Listed here rather
#: than read out of the files, so dropping one from a unit is a failure
#: and not a quietly smaller list.
HARDENING = (
    'NoNewPrivileges=yes',
    'ProtectSystem=strict',
    'ProtectHome=yes',
    'PrivateTmp=yes',
    'PrivateDevices=yes',
    'ProtectKernelTunables=yes',
    'ProtectKernelModules=yes',
    'ProtectControlGroups=yes',
    'RestrictSUIDSGID=yes',
    'RestrictNamespaces=yes',
    'RestrictRealtime=yes',
    'LockPersonality=yes',
    'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6',
    'SystemCallArchitectures=native',
)

#: A python3 that answers like the VPS's: 3.14.4, and `-c` exits 0 so the
#: version gate passes. `-m venv` is never reached in --check.
PYTHON_STUB = """#!/bin/sh
case "$1" in
  --version) echo "Python 3.14.4";;
  -c) exit 0;;
  *) echo "stub python3 $*";;
esac
exit 0
"""

#: The same stub, too old. The gate has to name what it found.
OLD_PYTHON_STUB = """#!/bin/sh
case "$1" in
  --version) echo "Python 3.9.18";;
  -c) exit 1;;
esac
exit 0
"""


def unit(name):
    return (UNITS / name).read_text()


def directives(name):
    """The unit's real lines, comments and blanks dropped."""
    return [line.strip() for line in unit(name).splitlines()
            if line.strip() and not line.startswith('#')]


def service_section(name):
    """Just the [Service] block's directives, which is where everything
    this file is about lives."""
    lines = directives(name)
    return lines[lines.index('[Service]') + 1:]


def code_lines(path):
    """A shell script's real lines: no comments, and no printf, because
    the printed instructions name commands the owner runs by hand and a
    test of what the SCRIPT does must not read those as what it does."""
    return [line for line in path.read_text().splitlines()
            if line.strip()
            and not line.lstrip().startswith('#')
            and not line.lstrip().startswith('printf ')]


def write_executable(path, body):
    path.write_text(body)
    path.chmod(0o755)
    return path


# --- the app units ---------------------------------------------------------

@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_the_app_units_pass_the_host_and_port_as_flags(environment):
    """The app reads NO environment variable for either one
    (careeros/server.py, main: argparse --host/--port), so a
    `CAREEROS_PORT=` line in an env file would be read by nothing and the
    port Caddy proxies to would be whatever the default is. The flags are
    the only way to say it."""
    port = PORTS[environment]
    expected = (f'ExecStart=/srv/careeros/{environment}/app/current/.venv/bin/python '
                f'-m careeros.server --host 127.0.0.1 --port {port}')
    assert expected in directives(f'careeros-{environment}.service')


def test_no_unit_or_script_configures_the_host_or_the_port_through_the_environment():
    """The variables the app does not read must not appear anywhere the
    owner would read them as configuration. Mentioned in a comment that
    says the app ignores them is the one allowed place -- .env.example
    says exactly that -- so comments are skipped and everything else is
    a failure. Read off the disk, not out of `git grep`: a brand-new unit
    file is untracked, which is precisely when this would matter."""
    offenders = []
    for path in sorted([*UNITS.iterdir(), *DEPLOY.glob('*.sh'),
                        DEPLOY / 'Caddyfile', ROOT / '.env.example']):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#') or not stripped:
                continue
            if 'CAREEROS_HOST' in stripped or 'CAREEROS_PORT' in stripped:
                offenders.append(f'{path.name}:{number}: {stripped}')
    assert offenders == [], 'the app reads neither'


def test_every_variable_in_env_example_is_read_by_something():
    """.env.example is the one list of what an environment can be
    configured with, so a name on it that nothing reads is worse than a
    missing one: it looks like a setting and changes nothing. Every name
    has to appear in code that reads the environment -- the app, the
    scripts, or the smoke tests."""
    documented = re.findall(r'^([A-Z][A-Z0-9_]*)=', (ROOT / '.env.example').read_text(),
                            re.M)
    assert documented, 'the example file still lists something'
    readers = [path.read_text()
               for path in [*(ROOT / 'careeros').rglob('*.py'),
                            *(ROOT / 'scripts').glob('*.py'),
                            *DEPLOY.glob('*.sh'),
                            SMOKE]]
    unread = [name for name in documented
              if not any(name in text for text in readers)]
    assert unread == [], 'documented but read by nothing'


@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_the_unit_has_the_last_word_on_the_vault(environment):
    """systemd applies these in file order, so the later one wins. The
    env file is the owner's; which vault an environment opens is not
    negotiable from it, or an edit to stg.env could point staging at the
    production records."""
    lines = directives(f'careeros-{environment}.service')
    env_file = lines.index(f'EnvironmentFile=/etc/careeros/{environment}.env')
    vault = lines.index(f'Environment=CAREEROS_VAULT=/srv/careeros/{environment}/vault')
    assert env_file < vault, 'EnvironmentFile first, then the vault the unit fixes'


@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_each_app_unit_runs_as_its_own_account_and_writes_only_its_vault(environment):
    lines = directives(f'careeros-{environment}.service')
    assert f'User=careeros-{environment}' in lines
    assert f'Group=careeros-{environment}' in lines
    assert [line for line in lines if line.startswith('ReadWritePaths=')] == \
        [f'ReadWritePaths=/srv/careeros/{environment}/vault'], \
        'the vault is the only path either app process writes'


@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_each_app_unit_keeps_every_hardening_directive(environment):
    lines = directives(f'careeros-{environment}.service')
    assert [d for d in HARDENING if d not in lines] == []


@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_each_app_unit_is_capped_in_memory(environment):
    """1.9 GB of RAM, two environments on it, and no second machine to
    move one to. Uncapped, a staging run that eats the box takes
    production with it."""
    lines = directives(f'careeros-{environment}.service')
    assert 'MemoryHigh=512M' in lines and 'MemoryMax=768M' in lines
    assert 'Restart=on-failure' in lines, 'and comes back after the kill'


def test_the_two_app_units_differ_only_in_which_environment_they_are():
    """One unit's text, with the environment's name and port swapped, IS
    the other one. Anything else is drift: a directive added to
    production and forgotten in staging means staging stops being the
    place a release is proved."""
    rewritten = [line.replace('careeros-prod', 'careeros-stg')
                     .replace('/srv/careeros/prod/', '/srv/careeros/stg/')
                     .replace('/etc/careeros/prod.env', '/etc/careeros/stg.env')
                     .replace('--port 8001', '--port 8002')
                 for line in service_section('careeros-prod.service')]
    assert rewritten == service_section('careeros-stg.service')


# --- the deploy unit and the timers ---------------------------------------

def test_the_deploy_unit_runs_as_root_and_takes_the_lock_once():
    """Root on purpose: the read-only deploy keys live in /root/.ssh, so
    the fetch happens where the app users cannot reach the credential
    (deploy/RUNBOOK.md, "Why the app users hold no key")."""
    lines = directives('careeros-deploy@.service')
    assert 'User=root' in lines
    assert 'Environment=CAREEROS_DEPLOY_LOCK_HELD=1' in lines, \
        'so deploy.sh does not try to take a lock it is already inside of'
    assert ('ExecStart=/usr/bin/flock -n -E 0 /run/careeros/deploy.lock '
            '/srv/careeros/deploy.sh %i') in lines


@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_each_timer_calls_the_deploy_template_for_its_own_environment(environment):
    lines = directives(f'careeros-deploy-{environment}.timer')
    assert f'Unit=careeros-deploy@{environment}.service' in lines
    assert 'WantedBy=timers.target' in lines


@pytest.mark.parametrize('environment', ['prod', 'stg'])
def test_timers_have_no_persistent_and_cover_a_reboot_with_onbootsec(environment):
    """Persistent= only applies to OnCalendar schedules; on these interval
    timers it did nothing (first real run, 2026-10-25). Reboot catch-up is
    the OnBootSec run a few minutes after the box comes up."""
    lines = directives(f'careeros-deploy-{environment}.timer')
    assert not any(l.startswith('Persistent=') for l in lines)
    assert any(l.startswith('OnBootSec=') for l in lines)
    assert any(l.startswith('OnUnitActiveSec=') for l in lines)


def test_setup_installs_exactly_the_unit_files_that_exist():
    """The script's own lists, against the directory. A unit file added
    here and not listed there is a file nobody installs; a name listed
    there and missing here already fails the script at run time, which is
    too late to find out."""
    text = SETUP.read_text()
    listed = set()
    for name in ('UNITS', 'TIMERS'):
        body = re.search(rf'^{name}=\((.*?)\)$', text, re.M | re.S).group(1)
        listed |= set(body.split())
    assert listed == {path.name for path in UNITS.iterdir()}


def test_nothing_is_enabled_or_started_by_setup():
    """Production is installed and left alone: enabling it is a decision
    about live data, and this script does not make it. Neither does it
    turn on staging's deploy timer -- that is a RUNBOOK step (step 6),
    taken only after the env file exists and the first deploy has been
    watched by hand, so a timer never fires before there is config to
    fire against. Enabling ANY timer here would make the first deploy
    something the owner reads about in a journal rather than watches."""
    text = SETUP.read_text()
    # The very idea of a start-list is gone: there is no START_TIMERS
    # variable to populate, so enabling something means editing the
    # script rather than editing a list in it.
    assert 'START_TIMERS' not in text
    # No line in the script runs a systemctl enable/start for any unit or
    # timer. The printed instructions DO name the commands that turn each
    # environment on; what must not exist is a line that runs one.
    ran = [line for line in code_lines(SETUP)
           if 'systemctl' in line and ('enable' in line or 'start' in line)]
    assert ran == [], ran


# --- the health gate ------------------------------------------------------

def test_the_health_path_the_deploy_polls_is_one_the_app_really_serves(tmp_path):
    """The rollback trusts this path. If the deploy polled a route the app
    does not have, every deploy would roll itself back -- and a draft of
    this toolchain polled /healthz, which this app has never served."""
    app = server.create_app(tmp_path / 'vault')
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert '/api/health' in routes
    assert '/healthz' not in routes, 'and nothing in deploy/ may assume it'
    assert 'health' in server.PUBLIC_ENDPOINTS, 'polled without a session'


def test_the_health_path_is_spelled_the_same_way_everywhere():
    for path in (DEPLOY_SH, SMOKE):
        text = path.read_text()
        assert '/api/health' in text, path.name
        assert 'healthz' not in text, f'{path.name} still names a route the app lacks'


def test_the_deploy_poll_and_the_smoke_test_agree_on_the_ports():
    text = DEPLOY_SH.read_text()
    for environment, port in PORTS.items():
        assert f'PORT={port}' in text, environment
    caddy = (DEPLOY / 'Caddyfile').read_text()
    for port in PORTS.values():
        assert f'reverse_proxy 127.0.0.1:{port}' in caddy


# --- deploy.sh's environment surface --------------------------------------

def test_every_variable_deploy_sh_reads_is_documented_with_its_default():
    """The header is the only documentation these scripts have. A
    variable that is read and not listed is a setting nobody knows
    exists; one that is listed and not read is a setting that does
    nothing, which is worse."""
    text = DEPLOY_SH.read_text()
    header = ''.join(line for line in text.splitlines(keepends=True)
                     if line.startswith('#'))
    read = set(re.findall(r'\$\{(CAREEROS_DEPLOY_[A-Z_]+)', text))
    documented = set(re.findall(r'#\s+(CAREEROS_DEPLOY_[A-Z_]+)', header))
    assert read - documented == set(), 'read but undocumented'
    assert documented - read == set(), 'documented but read by nothing'


def test_the_release_venv_is_built_with_the_system_python():
    """python3, never a version-suffixed binary. The VPS has none of
    those -- `python3` IS 3.14.4 there -- so a hardcoded suffix would
    fail every deploy at the venv, and setup-vps.sh is what proves the
    version before any of this runs."""
    assert 'PYTHON="${CAREEROS_DEPLOY_PYTHON:-python3}"' in DEPLOY_SH.read_text()
    assert [line for line in code_lines(DEPLOY_SH) if 'python3.' in line] == []


def test_deploy_sh_refuses_an_unknown_argument_with_a_usage_line():
    done = subprocess.run(['bash', str(DEPLOY_SH), 'production'],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 64
    assert 'usage: deploy.sh <stg|prod> [--rollback]' in done.stderr


def test_deploy_sh_does_nothing_on_a_box_that_was_never_set_up(tmp_path):
    done = subprocess.run(['bash', str(DEPLOY_SH), 'stg'],
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, 'CAREEROS_DEPLOY_ROOT': str(tmp_path / 'srv')})
    assert done.returncode != 0
    # Root is what it needs; without it, that is the first thing it says.
    expected = ('run setup-vps.sh first' if os.geteuid() == 0 else 'must run as root')
    assert expected in done.stdout


def test_the_deploy_builds_no_submodule_and_needs_no_second_credential():
    """vendor/capa-repo is a plain directory in this repository. A draft
    of this script ran `git submodule update`, which on this repo fetches
    nothing and fails the deploy if it is ever pointed at a private
    mirror it has no key for."""
    text = DEPLOY_SH.read_text()
    assert 'submodule' not in text
    assert text.count('GIT_SSH_COMMAND') == 1, 'one key, this environment\'s own'


# --- setup-vps.sh: --check changes nothing --------------------------------

@pytest.fixture
def fake_root(tmp_path):
    """Every path setup-vps.sh would write to, pointed into tmp_path, plus
    a python3 that answers like the VPS's."""
    stubs = tmp_path / 'bin'
    stubs.mkdir()
    write_executable(stubs / 'python3', PYTHON_STUB)
    layout = {
        'CAREEROS_SETUP_ROOT': tmp_path / 'srv' / 'careeros',
        'CAREEROS_SETUP_ENV_DIR': tmp_path / 'etc' / 'careeros',
        'CAREEROS_DEPLOY_SSH_DIR': tmp_path / 'root' / '.ssh',
        'CAREEROS_SETUP_UNIT_DIR': tmp_path / 'etc' / 'systemd',
        'CAREEROS_SETUP_CADDYFILE': tmp_path / 'etc' / 'Caddyfile',
        'CAREEROS_SETUP_SWAPFILE': tmp_path / 'swapfile',
    }

    def run(*args, env=None):
        environment = {
            **os.environ,
            'PATH': f"{stubs}:{os.environ['PATH']}",
            **{name: str(path) for name, path in layout.items()},
            **(env or {}),
        }
        return subprocess.run(['bash', str(SETUP), *args],
                              capture_output=True, text=True, env=environment, timeout=300)

    run.layout = layout
    run.stubs = stubs
    run.tmp = tmp_path
    return run


def test_check_mode_changes_nothing_at_all(fake_root):
    """The step the runbook puts before the real run. It is only worth
    reading if it is true: a --check that created a directory or appended
    an fstab line would be a change made by the command whose whole
    purpose is to make none."""
    before = sorted(path.relative_to(fake_root.tmp)
                    for path in fake_root.tmp.rglob('*'))
    done = fake_root('--check')
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(path.relative_to(fake_root.tmp)
                  for path in fake_root.tmp.rglob('*')) == before
    for name, path in fake_root.layout.items():
        assert not path.exists(), f'{name} was created by a --check run'
    assert 'CHECK ONLY: nothing below will be changed.' in done.stdout
    assert 'That was --check. NOTHING above was changed.' in done.stdout


def test_check_mode_says_what_it_would_do_and_what_the_owner_does_next(fake_root):
    done = fake_root('--check')
    for expected in (
        'would run: install -d -m 700',                      # the vault
        'would run: ssh-keygen',                             # the deploy keys
        'careeros-deploy-stg.timer     installed, NOT enabled, NOT started.',
        'careeros-prod.service         installed, NOT enabled, NOT started.',
        'careeros-deploy-prod.timer    installed, NOT enabled, NOT started.',
        'systemctl enable --now careeros-deploy-stg.timer',  # printed, not run
        'sudoedit',
        'deploy/RUNBOOK.md',
    ):
        assert expected in done.stdout, expected
    # Printed is not the same as run: the enable commands exist only
    # inside printf instructions.
    assert 'would run: systemctl enable' not in done.stdout
    assert 'would run: systemctl start' not in done.stdout


def test_check_mode_reports_the_python_it_found(fake_root):
    done = fake_root('--check')
    assert 'python3 is Python 3.14.4' in done.stdout


def test_an_older_python_stops_the_run_and_names_the_version(fake_root):
    """The one fact about this box a fact sheet cannot settle for the
    future: every release venv is built with this interpreter, so a box
    whose python3 moved backwards must not quietly build releases nobody
    has tested."""
    write_executable(fake_root.stubs / 'python3', OLD_PYTHON_STUB)
    done = fake_root('--check')
    assert done.returncode != 0
    assert 'python3 is Python 3.9.18, older than 3.14' in done.stderr
    assert 'do NOT invent a binary name' in done.stderr


def test_setup_installs_no_version_suffixed_python_package(fake_root):
    """A version-suffixed python package was in the first draft of this
    script, and no such interpreter exists on this machine. The packages
    it installs follow the release's own python3."""
    text = SETUP.read_text()
    packages = re.search(r'^ensure_packages (python3.*?)$', text, re.M | re.S).group(1)
    assert 'python3-venv' in packages and 'python3-pip' in packages
    assert [line for line in code_lines(SETUP) if 'python3.' in line] == []


def test_setup_refuses_a_real_run_as_a_normal_user(fake_root):
    if os.geteuid() == 0:
        pytest.skip('this process IS root; the refusal is for everybody else')
    done = fake_root()
    assert done.returncode != 0
    assert 'must run as root' in done.stderr


def test_setup_touches_no_part_of_ssh_access(fake_root):
    """Deliberately not a thing this script does. The box is key-only
    already, and a script that edits sshd while the owner is logged in
    over ssh is how a person loses their own machine. ufw keeps 22 open;
    the rest is the owner's, by hand, with a second terminal."""
    code = code_lines(SETUP)
    for forbidden in ('sshd_config', 'authorized_keys', 'PasswordAuthentication',
                      'reload ssh', 'sshd'):
        assert [line for line in code if forbidden in line] == [], forbidden
    # And the one SSH-shaped thing it DOES do, so this test cannot pass
    # by the script having stopped doing its job: it records GitHub's host
    # key and generates the deploy keys.
    assert [line for line in code if 'ssh-keyscan' in line]
    assert [line for line in code if 'ssh-keygen -q -t ed25519' in line]
    # The one sudo check it names, in its header: `sudo -n true`, which
    # answers "can this account become root without a password". `sudo -v`
    # prompts on this box even where real commands do not, so it answers a
    # different question and is named only as the thing not to use.
    assert 'sudo -n true' in SETUP.read_text()
    assert [line for line in code if re.search(r'(^|[;&|(]\s*)sudo ', line)] == [], \
        'and it runs no sudo of its own: it IS root, or it refuses'


# --- tests/smoke.sh's two exits deploy.sh depends on ----------------------

CURL_STUB = """#!/bin/sh
echo "$@" >> "$STUB_LOG"
out=''
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    *) shift;;
  esac
done
[ -n "$out" ] && echo '{"ok": true}' > "$out"
printf 200
"""


@pytest.fixture
def smoke_sh(tmp_path):
    stubs = tmp_path / 'bin'
    stubs.mkdir()
    write_executable(stubs / 'curl', CURL_STUB)
    log = tmp_path / 'curl.log'

    def run(*args, env=None):
        environment = {
            **os.environ,
            'PATH': f"{stubs}:{os.environ['PATH']}",
            'STUB_LOG': str(log),
            'SMOKE_EMAIL': '',
            'SMOKE_PASSWORD': '',
            'SMOKE_ENV_FILE': '',
            **(env or {}),
        }
        return subprocess.run(['sh', str(SMOKE), *args],
                              capture_output=True, text=True, env=environment, timeout=60)

    run.log = log
    return run


def test_smoke_exits_two_when_there_is_no_tester_account_yet(smoke_sh):
    """Exit 2, not 1. deploy.sh treats it as a loud skip, which is what
    keeps the very first deploy of an environment from rolling itself
    back for not having a tester account yet."""
    done = smoke_sh('http://127.0.0.1:8002')
    assert done.returncode == 2
    assert 'GET /api/health 200' in done.stdout
    assert 'smoke incomplete' in done.stderr
    assert '/api/health' in smoke_sh.log.read_text()
    assert 'login' not in smoke_sh.log.read_text(), 'no credentials, no login attempt'


def test_smoke_with_credentials_checks_the_login_and_three_surfaces(smoke_sh):
    done = smoke_sh('http://127.0.0.1:8002',
                    env={'SMOKE_EMAIL': 'tester@career-os.test',
                         'SMOKE_PASSWORD': 'not a real one'})
    assert done.returncode == 0, done.stdout + done.stderr
    for path in ('/api/health', '/login', '/jobs', '/api/jobs', '/api/companies'):
        assert path in smoke_sh.log.read_text(), path
    assert 'not a real one' not in smoke_sh.log.read_text(), \
        'the password reaches curl as a file, never as an argument'
