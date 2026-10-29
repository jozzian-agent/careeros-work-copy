"""Career OS waiting-list collector.

A small separate service, not part of the app (CAREER-99 PR B). Stdlib
only, single file, Python 3.14 on the target VPS (no venv, no pip
install): sqlite3 for storage, http.server for the endpoint.

Contract (deploy/../collector/README.md has the operator side):

- POST /waitlist, JSON body {"email": "...", "website": "..."}.
  "website" is the honeypot: filled means a bot, the submission is
  dropped silently and the response is byte-identical to a real success
  so the bot learns nothing.
- Stores only email address and UTC timestamp. Emails are unique
  (INSERT OR IGNORE): re-signups are silent successes, one row.
- Rate limit per client IP, sliding window, in memory (resets on
  restart; that is deliberate -- the limit is a nuisance filter, not a
  security boundary, and a persistent one would be state to maintain).
- Logs carry counts and outcomes only. NEVER an email address, never a
  request body. The log line for a stored submission and the log line
  for a dropped honeypot differ (operators need that), but neither
  contains the address; the response does not leak which happened.
- Privacy promise from the landing page: entries older than 12 months
  are deleted permanently, daily, by the purge timer. One address can be
  deleted on request with the delete subcommand (reads it from stdin,
  so it lands in no shell history and no process list).

Storage file: SQLite, created 0600 inside a 0700 directory owned by the
collector's own system user. The app users and Caddy cannot read it
(plain POSIX permissions; nothing else is running as that user).

Port: 8003 on 127.0.0.1 (8001 app prod, 8002 app staging are taken).
Only Caddy reaches it; see README.md for the Caddyfile block.
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("waitlist")

RATE_LIMIT_WINDOW_SECONDS = 3600
RATE_LIMIT_MAX_PER_IP = 3
MAX_BODY_BYTES = 4096
MAX_EMAIL_LEN = 320  # RFC 5321 practical maximum
RETENTION_MONTHS_DEFAULT = 12

# Serializes all writes from the threaded HTTP server.
DB_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS waitlist (
    email    TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
)
"""

SUCCESS = (200, {"ok": True})
RATE_LIMITED = (429, {"ok": False, "error": "too_many_requests"})
BAD_REQUEST = (400, {"ok": False, "error": "invalid_email"})


class Store:
    """SQLite store. connect() enforces 0700 dir / 0600 file every time,
    so a mis-set umask or a hand-touched file self-heals on next start."""

    def __init__(self, db_path):
        self.db_path = db_path

    def connect(self):
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, mode=0o700, exist_ok=True)
        os.chmod(parent, 0o700)
        # check_same_thread=False: ThreadingHTTPServer serves requests on
        # worker threads while the CLI subcommands run on the main one.
        # All writes go through DB_LOCK below, so concurrent access is
        # serialized; SQLite's own locking covers the rest.
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=DELETE")  # no -wal/-shm side files
        conn.execute(SCHEMA)
        conn.commit()
        os.chmod(self.db_path, 0o600)
        return conn

    @staticmethod
    def submit(conn, email, now=None):
        """Insert unless present. Returns True if a row was added."""
        now = now or datetime.now(timezone.utc)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with DB_LOCK:
            cur = conn.execute(
                "INSERT OR IGNORE INTO waitlist (email, added_at) VALUES (?, ?)",
                (email, stamp),
            )
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def purge(conn, now=None, months=RETENTION_MONTHS_DEFAULT):
        """Permanently delete entries older than `months`. Returns count."""
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=int(months * 30.44))
        stamp = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        with DB_LOCK:
            cur = conn.execute(
                "DELETE FROM waitlist WHERE added_at < ?", (stamp,))
            conn.commit()
            return cur.rowcount

    @staticmethod
    def delete_email(conn, email):
        """Delete one address on request. Returns count deleted."""
        with DB_LOCK:
            cur = conn.execute(
                "DELETE FROM waitlist WHERE email = ?",
                (normalize_email(email),),
            )
            conn.commit()
            return cur.rowcount

    @staticmethod
    def count(conn):
        with DB_LOCK:
            return conn.execute(
                "SELECT COUNT(*) FROM waitlist").fetchone()[0]


def normalize_email(raw):
    """Lowercase + strip. Returns None if not a plausible address.
    Deliberately permissive beyond that: the landing form already checks
    validity in the browser, and rejecting here would mean a second
    opinion to maintain."""
    if not isinstance(raw, str):
        return None
    email = raw.strip().lower()
    if not email or len(email) > MAX_EMAIL_LEN or " " in email:
        return None
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or "." not in domain:
        return None
    return email


class RateLimiter:
    """Sliding window, per IP, in memory."""

    def __init__(self, window=RATE_LIMIT_WINDOW_SECONDS,
                 max_per_window=RATE_LIMIT_MAX_PER_IP):
        self.window = window
        self.max_per_window = max_per_window
        self._hits = {}

    def allow(self, ip, now):
        dq = self._hits.setdefault(ip, deque())
        while dq and now - dq[0] >= self.window:
            dq.popleft()
        if len(dq) >= self.max_per_window:
            return False
        dq.append(now)
        return True


def handle_submission(store_conn, limiter, ip, payload, now):
    """Pure decision logic, unit-testable without a socket.

    `now` is an aware datetime (used for the stored timestamp); the
    rate limiter gets its POSIX seconds.

    Returns (status, body_dict, outcome) where outcome is one of
    "stored", "duplicate", "honeypot", "rate_limited", "invalid" --
    for the log line only, never for the client.
    """
    if not limiter.allow(ip, now.timestamp()):
        return RATE_LIMITED[0], RATE_LIMITED[1], "rate_limited"
    if not isinstance(payload, dict):
        return BAD_REQUEST[0], BAD_REQUEST[1], "invalid"
    # Honeypot first: a bot that filled it gets the identical success
    # response and nothing is stored. Any non-empty string counts as
    # filled (whitespace included): no human ever sees this field, so
    # nothing legitimate can land in it.
    website = payload.get("website")
    if isinstance(website, str) and website:
        return SUCCESS[0], SUCCESS[1], "honeypot"
    email = normalize_email(payload.get("email"))
    if email is None:
        return BAD_REQUEST[0], BAD_REQUEST[1], "invalid"
    added = Store.submit(store_conn, email, now=now)
    return SUCCESS[0], SUCCESS[1], ("stored" if added else "duplicate")


class WaitlistServer(ThreadingHTTPServer):
    """ThreadingHTTPServer plus the two things a handler needs."""

    def __init__(self, addr, handler, store_conn, limiter):
        super().__init__(addr, handler)
        self.store_conn = store_conn
        self.limiter = limiter


class WaitlistHandler(BaseHTTPRequestHandler):
    server_version = "CareerOSWaitlist/1"
    # Thin socket glue: parsing, limits and storage live in
    # handle_submission, which the tests drive directly.

    def _client_ip(self):
        # Caddy sets X-Forwarded-For; we bind 127.0.0.1 only, so the only
        # writer of that header is our own proxy. First entry = client.
        xff = self.headers.get("X-Forwarded-For", "")
        ip = xff.split(",")[0].strip() if xff else self.client_address[0]
        return ip[:64]

    def _send(self, status, body_dict):
        raw = json.dumps(body_dict).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path.rstrip("/") != "/waitlist":
            return self._send(404, {"ok": False, "error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._send(*BAD_REQUEST)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(*BAD_REQUEST)
        now = datetime.now(timezone.utc)
        status, body, outcome = handle_submission(
            self.server.store_conn, self.server.limiter, self._client_ip(),
            payload, now,
        )
        # outcome names an event class, never data; the email address
        # appears nowhere in this line (see module docstring).
        log.info("POST /waitlist -> %s (%s)", status, outcome)
        self._send(status, body)

    def do_GET(self):
        # Health check for the operator; no data in the response.
        if self.path.rstrip("/") in ("/healthz", ""):
            return self._send(200, {"ok": True})
        self._send(404, {"ok": False, "error": "not_found"})

    def log_message(self, format, *args):  # noqa: A002 - base-class signature
        # Silence BaseHTTPRequestHandler's default stderr logging (it
        # prints the request line, which could carry a query string);
        # the one log.info above is the whole access log.
        pass


def serve(host, port, db_path):
    store = Store(db_path)
    conn = store.connect()
    httpd = WaitlistServer((host, port), WaitlistHandler, conn, RateLimiter())
    log.info("collector listening on %s:%s db=%s", host, port, db_path)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        conn.close()


def cmd_purge(args):
    conn = Store(args.db).connect()
    removed = Store.purge(conn, months=args.months)
    remaining = Store.count(conn)
    print(f"purged entries older than {args.months} months: {removed}; "
          f"remaining: {remaining}")
    conn.close()


def cmd_delete(args):
    # Address comes from stdin, not argv: argv lands in shell history
    # and in the process list, stdin lands in neither.
    email = sys.stdin.readline()
    if not email.strip():
        print("no address on stdin; nothing deleted", file=sys.stderr)
        sys.exit(2)
    conn = Store(args.db).connect()
    removed = Store.delete_email(conn, email)
    remaining = Store.count(conn)
    # Counts only; the address itself is never echoed.
    print(f"deleted {removed} entry; remaining: {remaining}")
    conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="waitlist_collector",
        description="Career OS waiting-list collector (CAREER-99 PR B)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run the HTTP collector")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8003)
    p_serve.add_argument("--db", default="/srv/careeros/waitlist/data/waitlist.sqlite3")
    p_serve.set_defaults(func=lambda a: serve(a.host, a.port, a.db))

    p_purge = sub.add_parser("purge", help="delete entries older than N months")
    p_purge.add_argument("--db", default="/srv/careeros/waitlist/data/waitlist.sqlite3")
    p_purge.add_argument("--months", type=int, default=RETENTION_MONTHS_DEFAULT)
    p_purge.set_defaults(func=cmd_purge)

    p_del = sub.add_parser("delete", help="delete one address read from stdin")
    p_del.add_argument("--db", default="/srv/careeros/waitlist/data/waitlist.sqlite3")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
