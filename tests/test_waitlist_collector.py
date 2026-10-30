"""Tests for collector/waitlist_collector.py (CAREER-99 PR B).

Everything runs against the pure logic (Store, RateLimiter,
handle_submission) plus one real HTTP round-trip through the stdlib
server on a free localhost port -- no network leaves the machine.
"""
import json
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# The suite-wide offline guard (tests/conftest.py) patches
# urllib.request.build_opener and socket.getaddrinfo in every test. The
# collector itself never calls out -- but these tests open real HTTP
# connections to 127.0.0.1. Capture the real functions at import time
# (before any fixture patches them) and restore them for the HTTP
# tests only.
_REAL_BUILD_OPENER = urllib.request.build_opener
_REAL_GETADDRINFO = socket.getaddrinfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.waitlist_collector import (  # noqa: E402
    MAX_BODY_BYTES,
    RATE_LIMIT_MAX_PER_IP,
    RateLimiter,
    Store,
    WaitlistHandler,
    WaitlistServer,
    handle_submission,
    main,
    normalize_email,
)

COLLECTOR = ROOT / "collector" / "waitlist_collector.py"


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "data" / "waitlist.sqlite3"
    conn = Store(str(path)).connect()
    yield conn, path
    conn.close()


class TestStore:
    def test_submit_stores_email_and_utc_timestamp(self, db):
        conn, _ = db
        now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
        assert Store.submit(conn, "a@b.ch", now=now) is True
        row = conn.execute(
            "SELECT email, added_at FROM waitlist").fetchone()
        assert row == ("a@b.ch", "2026-10-29T12:00:00Z")

    def test_duplicate_email_is_one_row_silent(self, db):
        conn, _ = db
        assert Store.submit(conn, "a@b.ch") is True
        assert Store.submit(conn, "a@b.ch") is False
        assert Store.count(conn) == 1

    def test_file_permissions_0600_dir_0700(self, db):
        _, path = db
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_permissions_reasserted_on_reconnect(self, db):
        _, path = db
        os.chmod(path, 0o644)
        os.chmod(path.parent, 0o755)
        conn2 = Store(str(path)).connect()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        conn2.close()


class TestPurge:
    """The 12-month promise the landing page makes."""

    def test_entry_exactly_12_months_old_survives(self, db):
        conn, _ = db
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        # 364 days old -> younger than the 12*30.44-day cutoff
        Store.submit(conn, "young@example.ch", now=now - timedelta(days=364))
        assert Store.purge(conn, now=now, months=12) == 0
        assert Store.count(conn) == 1

    def test_entry_older_than_12_months_is_deleted_permanently(self, db):
        conn, _ = db
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        Store.submit(conn, "old@example.ch", now=now - timedelta(days=366))
        Store.submit(conn, "keep@example.ch", now=now - timedelta(days=10))
        assert Store.purge(conn, now=now, months=12) == 1
        emails = [r[0] for r in conn.execute("SELECT email FROM waitlist")]
        assert emails == ["keep@example.ch"]

    def test_purge_is_permanent_not_flagged(self, db):
        conn, path = db
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        Store.submit(conn, "old@example.ch", now=now - timedelta(days=400))
        assert Store.purge(conn, now=now, months=12) == 1
        # reopen the same file: the row is gone, not hidden behind a flag
        conn2 = Store(str(path)).connect()
        assert Store.count(conn2) == 0
        conn2.close()


class TestSecureDelete:
    """Owner point 2: deleted data must be gone from the FILE bytes,
    not just from the index. secure_delete=ON zero-overwrites freed
    pages; journal_mode=DELETE means there is no WAL file at all."""

    def _raw_bytes(self, path):
        return path.read_bytes()

    def test_no_wal_or_shm_side_files_exist(self, db):
        _, path = db
        assert not path.with_name(path.name + "-wal").exists()
        assert not path.with_name(path.name + "-shm").exists()

    def test_purged_address_absent_from_raw_file_bytes(self, db):
        conn, path = db
        secret = "purged-secret-address@example.ch"
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        Store.submit(conn, secret, now=now - timedelta(days=400))
        assert secret.encode() in self._raw_bytes(path)  # sanity: it was on disk
        assert Store.purge(conn, now=now, months=12) == 1
        assert secret.encode() not in self._raw_bytes(path)

    def test_delete_one_address_absent_from_raw_file_bytes(self, db):
        conn, path = db
        secret = "delete-me-secret@example.ch"
        other = "keep-me@example.ch"
        Store.submit(conn, secret)
        Store.submit(conn, other)
        assert Store.delete_email(conn, secret) == 1
        raw = self._raw_bytes(path)
        assert secret.encode() not in raw
        assert other.encode() in raw  # untouched row still intact

    def test_secure_delete_survives_reconnect(self, db):
        """The pragma is persisted in the DB header, so a fresh process
        (systemd restart) reopens with the same guarantee."""
        conn, path = db
        conn2 = Store(str(path)).connect()
        assert conn2.execute("PRAGMA secure_delete").fetchone()[0] == 1
        conn2.close()


class TestNormalizeEmail:
    @pytest.mark.parametrize("bad", [
        None, 42, "", "   ", "no-at-sign", "@nodomain", "noat@",
        "a@b", "a b@c.ch", "a" * 321 + "@b.ch",
    ])
    def test_rejects(self, bad):
        assert normalize_email(bad) is None

    def test_lowercases_and_strips(self):
        assert normalize_email("  Foo@Bar.CH ") == "foo@bar.ch"


class TestRateLimiter:
    def test_allows_up_to_limit_then_blocks(self):
        lim = RateLimiter(window=3600, max_per_window=RATE_LIMIT_MAX_PER_IP)
        for i in range(RATE_LIMIT_MAX_PER_IP):
            assert lim.allow("1.2.3.4", 1000 + i) is True
        assert lim.allow("1.2.3.4", 1004) is False

    def test_window_slides(self):
        lim = RateLimiter(window=3600, max_per_window=1)
        assert lim.allow("1.2.3.4", 0) is True
        assert lim.allow("1.2.3.4", 3599) is False
        assert lim.allow("1.2.3.4", 3600) is True

    def test_ips_are_independent(self):
        lim = RateLimiter(window=3600, max_per_window=1)
        assert lim.allow("1.1.1.1", 0) is True
        assert lim.allow("2.2.2.2", 0) is True


class TestHandleSubmission:
    """The decision logic behind POST /waitlist."""

    def _call(self, db, payload, ip="9.9.9.9", now=None, limiter=None):
        conn, _ = db
        if now is None:
            now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
        return handle_submission(
            conn, limiter or RateLimiter(), ip, payload,
            now,
        )

    def test_real_submission_stores_and_succeeds(self, db):
        conn, _ = db
        status, body, outcome = self._call(
            db, {"email": "a@b.ch", "website": ""})
        assert (status, body) == (200, {"ok": True})
        assert outcome == "stored"
        assert Store.count(conn) == 1

    def test_honeypot_filled_identical_response_stores_nothing(self, db):
        conn, _ = db
        status, body, outcome = self._call(
            db, {"email": "bot@spam.xx", "website": "http://spam"})
        assert (status, body) == (200, {"ok": True})  # same as a real one
        assert outcome == "honeypot"
        assert Store.count(conn) == 0

    def test_honeypot_whitespace_only_counts_as_filled(self, db):
        conn, _ = db
        _, _, outcome = self._call(
            db, {"email": "a@b.ch", "website": "   "})
        assert outcome == "honeypot"
        assert Store.count(conn) == 0

    def test_invalid_email_400(self, db):
        status, _, outcome = self._call(db, {"email": "nope", "website": ""})
        assert status == 400
        assert outcome == "invalid"

    def test_rate_limited_429_and_stores_nothing(self, db):
        conn, _ = db
        lim = RateLimiter(window=3600, max_per_window=2)
        base = datetime(2026, 10, 29, tzinfo=timezone.utc)
        for i in range(2):
            self._call(db, {"email": f"u{i}@b.ch", "website": ""},
                       now=base + timedelta(seconds=i), limiter=lim)
        status, _, outcome = self._call(
            db, {"email": "u9@b.ch", "website": ""},
            now=base + timedelta(seconds=3), limiter=lim)
        assert status == 429
        assert outcome == "rate_limited"
        assert Store.count(conn) == 2

    def test_non_dict_payload_400(self, db):
        status, _, outcome = self._call(db, ["not", "a", "dict"])
        assert status == 400 and outcome == "invalid"


class TestHttpRoundTrip:
    """One real server on a free localhost port, real HTTP."""

    @pytest.fixture()
    def live(self, tmp_path, monkeypatch):
        # Restore real localhost networking for this test only (see
        # module header): the collector makes no outbound calls, so the
        # offline guard's purpose is untouched.
        monkeypatch.setattr(urllib.request, "build_opener", _REAL_BUILD_OPENER)
        monkeypatch.setattr(socket, "getaddrinfo", _REAL_GETADDRINFO)
        db_path = str(tmp_path / "wl.sqlite3")
        conn = Store(db_path).connect()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        httpd = WaitlistServer(("127.0.0.1", port), WaitlistHandler,
                               conn, RateLimiter())
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}", conn
        httpd.shutdown()
        httpd.server_close()
        conn.close()

    def _post(self, base, payload, raw=None, headers=None):
        data = raw if raw is not None else json.dumps(payload).encode()
        req = urllib.request.Request(
            base + "/waitlist", data=data,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_submit_then_honeypot_same_body(self, live):
        base, conn = live
        s1, b1 = self._post(base, {"email": "real@example.ch", "website": ""})
        s2, b2 = self._post(base, {"email": "bot@spam.xx", "website": "x"})
        assert (s1, b1) == (s2, b2) == (200, {"ok": True})
        rows = [r[0] for r in conn.execute("SELECT email FROM waitlist")]
        assert rows == ["real@example.ch"]  # honeypot stored nothing

    def test_oversize_body_rejected(self, live):
        base, _ = live
        status, _ = self._post(base, None, raw=b"x" * (MAX_BODY_BYTES + 1))
        assert status == 400

    def test_malformed_json_rejected(self, live):
        base, _ = live
        status, _ = self._post(base, None, raw=b"{not json")
        assert status == 400

    def test_healthz_no_data(self, live):
        base, _ = live
        with urllib.request.urlopen(base + "/healthz", timeout=5) as r:
            assert r.status == 200 and json.loads(r.read()) == {"ok": True}

    def test_xff_used_for_rate_limit_ip(self, live):
        base, _ = live
        hdr = {"X-Forwarded-For": "5.5.5.5"}
        for _ in range(RATE_LIMIT_MAX_PER_IP):
            s, _ = self._post(base, {"email": f"u{_}@b.ch", "website": ""},
                              headers=hdr)
            assert s == 200
        s, _ = self._post(base, {"email": "u9@b.ch", "website": ""},
                          headers=hdr)
        assert s == 429
        # a different client IP is unaffected
        s2, _ = self._post(base, {"email": "other@b.ch", "website": ""},
                           headers={"X-Forwarded-For": "6.6.6.6"})
        assert s2 == 200

    def test_two_xff_values_get_separate_limits(self, live):
        """Owner point 1: the limit counts the XFF client address, not
        the socket peer (always 127.0.0.1 behind Caddy). Two different
        XFF values each exhaust their own budget independently."""
        base, _ = live
        for ip in ("7.7.7.7", "8.8.8.8"):
            hdr = {"X-Forwarded-For": ip}
            for _ in range(RATE_LIMIT_MAX_PER_IP):
                s, _ = self._post(
                    base, {"email": f"x{_}@{ip}.ch", "website": ""},
                    headers=hdr)
                assert s == 200, f"{ip} should still be under its limit"
            s, _ = self._post(base, {"email": "y@b.ch", "website": ""},
                              headers=hdr)
            assert s == 429, f"{ip} exhausted its limit and must be blocked"
        # and a third untouched IP still works after both are exhausted
        s3, _ = self._post(base, {"email": "fresh@b.ch", "website": ""},
                           headers={"X-Forwarded-For": "9.9.9.9"})
        assert s3 == 200

    def test_chained_xff_last_entry_is_the_identity(self, live):
        """Caddy overwrites XFF with the real peer; if anything ever
        chains another proxy, the LAST entry (closest to us) wins, so a
        client cannot escape its bucket by prepending fake prefixes."""
        base, _ = live
        spoof = "1.1.1.1, 2.2.2.2"   # last entry = real client per Caddy
        for i in range(RATE_LIMIT_MAX_PER_IP):
            s, _ = self._post(base, {"email": f"r{i}@b.ch", "website": ""},
                              headers={"X-Forwarded-For": spoof})
            assert s == 200
        # same last entry, different spoofed prefix -> still blocked
        s, _ = self._post(base, {"email": "r9@b.ch", "website": ""},
                          headers={"X-Forwarded-For": "9.9.9.9, 2.2.2.2"})
        assert s == 429

    def test_logs_never_contain_the_email(self, live, caplog):
        """The privacy rule: outcome classes in logs, never addresses."""
        import logging
        base, _ = live
        secret = "very-secret-address@example.ch"
        with caplog.at_level(logging.DEBUG, logger="waitlist"):
            self._post(base, {"email": secret, "website": ""})
            self._post(base, {"email": "bot@spam.xx", "website": "spam"})
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert secret not in joined
        assert "spam.xx" not in joined


class TestCli:
    """The two operator subcommands, end to end."""

    def _run(self, args, stdin_data=None):
        return subprocess.run(
            [sys.executable, str(COLLECTOR), *args],
            input=stdin_data, capture_output=True, text=True, timeout=30,
        )

    def test_purge_cli_prints_counts_only(self, tmp_path):
        db = tmp_path / "wl.sqlite3"
        conn = Store(str(db)).connect()
        now = datetime.now(timezone.utc)
        Store.submit(conn, "ancient@example.ch", now=now - timedelta(days=500))
        conn.close()
        r = self._run(["purge", "--db", str(db), "--months", "12"])
        assert r.returncode == 0
        assert "purged" in r.stdout and "1" in r.stdout
        assert "ancient@example.ch" not in r.stdout + r.stderr

    def test_delete_cli_reads_stdin_echoes_counts_only(self, tmp_path):
        db = tmp_path / "wl.sqlite3"
        conn = Store(str(db)).connect()
        Store.submit(conn, "delete-me@example.ch")
        Store.submit(conn, "keep-me@example.ch")
        conn.close()
        r = self._run(["delete", "--db", str(db)],
                      stdin_data="delete-me@example.ch\n")
        assert r.returncode == 0
        assert "deleted 1" in r.stdout and "remaining: 1" in r.stdout
        assert "delete-me@example.ch" not in r.stdout + r.stderr
        conn = Store(str(db)).connect()
        emails = [x[0] for x in conn.execute("SELECT email FROM waitlist")]
        conn.close()
        assert emails == ["keep-me@example.ch"]

    def test_delete_cli_no_stdin_exits_2(self, tmp_path):
        db = tmp_path / "wl.sqlite3"
        Store(str(db)).connect().close()
        r = self._run(["delete", "--db", str(db)], stdin_data="\n")
        assert r.returncode == 2

    def test_list_cli_prints_rows_with_timestamps(self, tmp_path):
        """Operator needs the addresses to send invitations: list prints
        every stored row (address + UTC timestamp) to stdout."""
        db = tmp_path / "wl.sqlite3"
        conn = Store(str(db)).connect()
        now = datetime.now(timezone.utc)
        Store.submit(conn, "first@example.ch", now=now - timedelta(days=2))
        Store.submit(conn, "second@example.ch", now=now - timedelta(days=1))
        conn.close()
        r = self._run(["list", "--db", str(db)])
        assert r.returncode == 0
        assert "first@example.ch" in r.stdout
        assert "second@example.ch" in r.stdout
        assert "total: 2" in r.stdout
        # both rows carry their timestamps; oldest first
        lines = [l for l in r.stdout.splitlines() if "@example.ch" in l]
        assert len(lines) == 2
        stamp1, stamp2 = (l.split()[0] for l in lines)
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", stamp1)
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", stamp2)
        assert stamp1 < stamp2
        assert lines[0].endswith("first@example.ch")

    def test_list_cli_writes_nothing_to_the_log(self, tmp_path):
        """Privacy rule: addresses reach the terminal (stdout) ONLY.
        logging goes to stderr (basicConfig default; journald captures
        the service's stderr), so stderr + the logging module must stay
        clean of every stored address."""
        import logging
        db = tmp_path / "wl.sqlite3"
        conn = Store(str(db)).connect()
        secret = "list-me-secret@example.ch"
        Store.submit(conn, secret)
        conn.close()
        r = self._run(["list", "--db", str(db)])
        assert r.returncode == 0
        assert secret in r.stdout          # the operator sees it...
        assert secret not in r.stderr      # ...and it is nowhere else.
        # In-process double check: no record ever reaches the logger.
        handler_records = []

        class _Spy(logging.Handler):
            def emit(self, record):
                handler_records.append(record.getMessage())

        spy = _Spy()
        logger = logging.getLogger("waitlist")
        logger.addHandler(spy)
        try:
            main(["list", "--db", str(db)])
        finally:
            logger.removeHandler(spy)
        assert all(secret not in m for m in handler_records)

    def test_list_cli_empty_db(self, tmp_path):
        db = tmp_path / "wl.sqlite3"
        Store(str(db)).connect().close()
        r = self._run(["list", "--db", str(db)])
        assert r.returncode == 0
        assert "empty" in r.stdout


class TestInstalledPaths:
    """The units and the README must agree on WHERE the collector lives.

    Owner review round 2 (PR #30): the first draft ran the service out of
    /srv/careeros/app/current/collector -- a path that does not exist
    (real checkouts are /srv/careeros/{prod,stg}/app/current) and a
    location that moves with every release under app-user permissions.
    The installed copy at /opt/careeros-waitlist is the contract now;
    these tests pin it so a future edit cannot silently reintroduce a
    release-folder path.
    """

    SYSTEMD = ROOT / "collector" / "systemd"
    README = ROOT / "collector" / "README.md"

    def test_both_services_exec_the_installed_copy_only(self):
        for name in ("careeros-waitlist.service",
                     "careeros-waitlist-purge.service"):
            text = (self.SYSTEMD / name).read_text()
            execs = [l for l in text.splitlines() if l.startswith("ExecStart=")]
            assert len(execs) == 1, name
            assert execs[0].startswith(
                "ExecStart=/usr/bin/python3 "
                "/opt/careeros-waitlist/waitlist_collector.py "), name

    def test_no_unit_directive_names_a_release_folder(self):
        """`app/current` in a directive is either the wrong path (it does
        not exist at /srv/careeros/app/current) or the right-but-
        forbidden one (the collector must not run from the release tree).
        Comments may mention it -- the unit header explains why it is
        NOT used there."""
        for path in sorted(self.SYSTEMD.iterdir()):
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    continue
                assert "app/current" not in stripped, f"{path.name}: {stripped}"

    def test_documentation_directives_point_at_the_installed_readme(self):
        for path in sorted(self.SYSTEMD.iterdir()):
            text = path.read_text()
            assert "Documentation=file:///opt/careeros-waitlist/README.md" in text, \
                path.name

    def test_readme_install_copies_from_the_real_stg_checkout(self):
        text = self.README.read_text()
        src = "/srv/careeros/stg/app/current/collector"
        assert f"install -m 0755 -o root -g root \\\n        {src}/waitlist_collector.py" in text
        assert "/opt/careeros-waitlist" in text
        assert f"{src}/systemd/careeros-waitlist.service" in text
        # and the nonexistent bare path is gone from every command line
        assert "/srv/careeros/app/current" not in text

    def test_readme_operator_commands_use_the_installed_copy(self):
        text = self.README.read_text()
        assert "/opt/careeros-waitlist/waitlist_collector.py delete" in text

    def test_readme_backups_names_the_real_prod_vault(self):
        text = self.README.read_text()
        assert "/srv/careeros/prod/vault" in text
        # the wrong bare path must not survive anywhere in the file
        assert "`/srv/careeros/vault`" not in text

