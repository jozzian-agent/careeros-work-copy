#!/bin/bash
# The post-deploy smoke test, with a session (Amendment 4.8).
#
# WHAT IT DOES
#   Signs a dedicated smoke account in and then asks for three pages:
#   `/`, `/jobs`, and one job-detail page. Every route in this app needs a
#   session (careeros/server.py, PUBLIC_ENDPOINTS), so an unauthenticated
#   check can only ever see the login page -- which is why a 404-ing or
#   empty Jobs page used to sail past the health check and the automatic
#   rollback never fired.
#
#   The job-detail page is not a fixed URL: the first job link on `/jobs`
#   is followed. If the React build is serving `/jobs` there are no links
#   in the HTML, so the first id from `/api/jobs` is used instead. Either
#   way the assertion is the same -- one real record's page answers 200.
#
# THE SESSION COOKIE, AND WHY IT IS NOT LEFT TO CURL
#   Prod runs with CAREEROS_SESSION_COOKIE_SECURE=1 (careeros/server.py,
#   create_app), so /login answers `Set-Cookie: session=...; Secure`. This
#   test talks to the local port over plain `http://127.0.0.1:800X`,
#   because it runs before Caddy is in the picture -- and whether curl
#   stores and replays a Secure cookie from a plain-http loopback origin
#   is a question each curl version answers differently. 7.81 does (that
#   is measured, against a local http server, 2026-10-26); 7.86 tightened
#   Secure-cookie handling, and the version on any given box is not
#   something this script gets to pick. A smoke test that silently stops
#   sending the session would see the login page everywhere and report
#   `/jobs` broken after a perfectly good deploy -- or, worse, be
#   "fixed" by turning Secure off for real users.
#
#   So the cookie is not left to curl's own storage rules. The login
#   response headers are captured, the `session=...` pair is read out of
#   them, and it is written into the cookie jar by hand with the secure
#   column set to FALSE -- the one jar line this script trusts. Every
#   authenticated GET then reads that jar, and sends the cookie on any
#   curl, over any scheme. Nothing about the server changes: Secure stays
#   on, and a real browser over HTTPS is unaffected.
#
# WHAT IT MUST NEVER TOUCH
#   * argv. The password is written to a 0600 temporary file and handed to
#     curl as `--data-binary @file`, never as an argument: argv is world
#     readable in /proc on this box, and a password on a deploy command
#     line also lands in the journal and in shell history. The session
#     cookie goes the same way, and for the same reason: it is a bearer
#     credential for the tester account until it expires, so it is
#     written into the 0600 jar and passed as `-b <jarfile>`, never as
#     `-b name=value` -- which would put a live session on a command line
#     that /proc, the journal and the history file can all read.
#   * The environment of anything it starts. The env file is sourced
#     plainly, NOT with `set -a`: an exported SMOKE_PASSWORD would be
#     inherited by curl and readable in `/proc/<pid>/environ` for as long
#     as the request takes, which is the same leak as argv by another
#     route. curl gets the JSON body file and nothing else. The variable is
#     unset the moment the body is written.
#   * Any record. Only GETs, plus the one POST to /login. It writes
#     nothing, so it is safe to run against prod after every release.
#   * The env file. Read only; never printed, never copied, never logged.
#     Nothing here echoes a variable that came out of it.
#
# ARGUMENTS
#   $1  base URL, optional. Defaults to SMOKE_BASE_URL from the env file.
#
# ENVIRONMENT
#   SMOKE_ENV_FILE   where the credentials live    (/etc/careeros/prod.env)
#   SMOKE_TIMEOUT    seconds per request                            (20)
#
#   The env file is root-owned, mode 0640, group = the service's group
#   (the same file the LLM key lives in, deploy/RUNBOOK.md step 5) and
#   must define:
#
#     SMOKE_BASE_URL=https://app.career-os.ch
#     SMOKE_EMAIL=<the tester account you created>
#     SMOKE_PASSWORD=...
#
#   The account is a dedicated tester created on the VPS. Create it -- and
#   reset its password -- without the password ever being a string a human
#   handles. `users create --password` (careeros/users.py:485) takes it as
#   an argument and has no `--password-file` and no stdin mode, so the CLI
#   is the one thing not to use: argv is world-readable in /proc, it lands
#   in the journal and in shell history, and the shell mangles exactly the
#   characters a strong password is made of. A leading space is not a fix,
#   and neither is pasting -- a pasted heredoc is still a shell line, so it
#   is still in the history file.
#
#   So: GENERATE it into a root-owned 0600 file, and have python READ that
#   file. Nothing is typed, nothing is pasted, nothing is on a command line
#   (deploy/RUNBOOK.md, "The tester account", has the same steps as a
#   checklist with the expected output of each):
#
#     sudo install -m 600 -o root -g root /dev/null /etc/careeros/smoke-password
#     sudo sh -c 'openssl rand -base64 24 >/etc/careeros/smoke-password'
#
#     sudo sh -c 'cd /srv/careeros/prod/app/current \
#          && CAREEROS_VAULT=/srv/careeros/prod/vault .venv/bin/python -' <<'PYEOF'
#     from pathlib import Path
#     from careeros import users, vault
#     # The `cd` above is not optional: `from careeros import ...` resolves
#     # against the working directory, so this block run from /root (which
#     # is where `sudo` leaves you) dies on ModuleNotFoundError before it
#     # has read anything.
#     # Read, never typed. This is what main() in careeros/users.py does
#     # around the same two calls -- vault_root, mkdir, WriteLock -- so the
#     # account this creates is the account the CLI would have created.
#     password = Path('/etc/careeros/smoke-password').read_text().strip()
#     root = users.vault_root(None)
#     root.mkdir(parents=True, exist_ok=True)
#     with vault.WriteLock(root):
#         user = users.create_user(root, email='<the tester address>',
#                                  name='Smoke test', role='tester',
#                                  password=password)
#     print('created', user['id'], user['role'], user['email'])
#     PYEOF
#
#   The same shape with `users.set_password(root, user['id'], password)`
#   resets one, after a fresh `openssl rand` into the same file. Then copy
#   that one line into SMOKE_PASSWORD in the env file with `sudoedit`,
#   which also never puts it on a command line. If the vault ends up
#   root-owned because this ran as root, `chown -R careeros-prod:` it back.
#
#   It is not the owner's account: a smoke test must not be able to see or
#   change the owner's board.
#
# FAILURE
#   Non-zero exit and one `ALERT careeros-smoke: step <name> ...` line
#   naming the step that failed, which is what a deploy script reads to
#   decide on a rollback.
set -euo pipefail

SMOKE_ENV_FILE="${SMOKE_ENV_FILE:-/etc/careeros/prod.env}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-20}"

JAR=""
BODY=""
PAGE=""
HDRS=""

alert() {   # alert <step> <reason...>
  local step=$1; shift
  echo "ALERT careeros-smoke: step $step failed: $*"
  exit 1
}

cleanup() { rm -f "$JAR" "$BODY" "$PAGE" "$HDRS"; return 0; }
trap cleanup EXIT INT TERM

[[ -r $SMOKE_ENV_FILE ]] || alert env-file "$SMOKE_ENV_FILE is not readable"
# Sourced plainly. `set -a` around this used to export every name the file
# defines -- the smoke password included -- into every process started
# afterwards, where /proc/<pid>/environ is as readable as argv. Nothing
# below needs an inherited variable: curl is handed a file and a URL.
# shellcheck source=/dev/null
. "$SMOKE_ENV_FILE"

BASE="${1:-${SMOKE_BASE_URL:-}}"
BASE="${BASE%/}"
[[ -n $BASE ]] || alert env-file "no base URL: pass one or set SMOKE_BASE_URL in $SMOKE_ENV_FILE"
[[ -n ${SMOKE_EMAIL:-} ]] || alert env-file "SMOKE_EMAIL is not set in $SMOKE_ENV_FILE"
[[ -n ${SMOKE_PASSWORD:-} ]] || alert env-file "SMOKE_PASSWORD is not set in $SMOKE_ENV_FILE"

JAR=$(mktemp -t careeros-smoke-jar-XXXXXX)
BODY=$(mktemp -t careeros-smoke-body-XXXXXX)
PAGE=$(mktemp -t careeros-smoke-page-XXXXXX)
# The login response headers, which is where the session cookie is read
# from. 0600 like the rest: a Set-Cookie line is a credential.
HDRS=$(mktemp -t careeros-smoke-hdrs-XXXXXX)
chmod 600 "$JAR" "$BODY" "$PAGE" "$HDRS"

json_string() {   # json_string <value>: the value as a JSON string literal
  local s=${1//\\/\\\\}
  s=${s//\"/\\\"}
  printf '"%s"' "$s"
}
printf '{"email":%s,"password":%s}' \
  "$(json_string "$SMOKE_EMAIL")" "$(json_string "$SMOKE_PASSWORD")" >"$BODY"
# The password's only copy from here on is the 0600 file, which cleanup
# removes. Nothing below reads the variable.
unset SMOKE_PASSWORD

# get <path> <outfile>: the HTTP status of one authenticated GET.
# `-b "$JAR"` and no `-c`: the jar holds exactly the one line login wrote
# into it, and nothing here needs a cookie refreshed -- the session cookie
# is set once, at login. Letting curl write the jar back would hand the
# secure column to curl's own rules again, which is the thing this script
# stopped relying on. The argument has no `=` in it (mktemp names do not),
# so curl reads it as a file and not as a literal cookie.
get() {
  curl -sS -L --max-time "$SMOKE_TIMEOUT" -b "$JAR" \
       -o "$2" -w '%{http_code}' "$BASE$1"
}

# --- 1. login -------------------------------------------------------------
# The endpoint answers JSON to a JSON request and a redirect to a form post
# (careeros/server.py, login), so this asks for the JSON half: one status
# code to read and no HTML to guess at.
code=$(curl -sS --max-time "$SMOKE_TIMEOUT" -D "$HDRS" -o "$PAGE" -w '%{http_code}' \
         -H 'Content-Type: application/json' --data-binary "@$BODY" \
         "$BASE/login") \
  || alert login "curl could not reach $BASE/login"
[[ $code == 200 ]] || alert login "POST /login answered $code (401 means the smoke account's credentials in $SMOKE_ENV_FILE are wrong or the account is disabled)"
grep -q '"ok"' "$PAGE" || alert login "POST /login answered 200 without an ok body"
rm -f "$BODY"
BODY=""

# The session cookie, out of the headers and into the jar by hand. Flask
# names it `session` (careeros/server.py sets HTTPONLY, SAMESITE, SECURE
# and the lifetime but not SESSION_COOKIE_NAME, so the default stands).
# Matching the name rather than taking the first Set-Cookie line means a
# second cookie appearing one day cannot quietly become "the session".
# `|| true` because a missing header is a diagnosis, not a crash: under
# `set -o pipefail` a grep that matches nothing would fail the assignment
# and `set -e` would exit with no ALERT line at all -- the one failure
# mode a deploy script cannot read. The emptiness is checked right below.
# The trailing-space strip also takes the CR off the CRLF line ending.
pair=$(grep -i '^set-cookie:[[:space:]]*session=' "$HDRS" | head -1 \
         | sed -e 's/^[Ss]et-[Cc]ookie:[[:space:]]*//' -e 's/;.*$//' -e 's/[[:space:]]*$//') \
  || true
[[ -n $pair ]] \
  || alert login "POST /login answered 200 with no 'Set-Cookie: session=...' header, so there is no session to carry"
rm -f "$HDRS"
HDRS=""

# One Netscape jar line: host, no domain match, path /, SECURE FALSE,
# session (expiry 0), name, value. FALSE is the whole point -- the server
# sent the cookie with `Secure` and keeps doing so for real users, but a
# jar entry curl itself did not classify is one curl sends over http on
# every version, loopback-origin heuristics or not.
host=${BASE#*://}; host=${host%%/*}; host=${host%%:*}
printf '%s\tFALSE\t/\tFALSE\t0\t%s\t%s\n' \
  "$host" "${pair%%=*}" "${pair#*=}" >"$JAR"
unset pair
echo "-- login ok, session cookie carried in the jar"

# --- 2. the two pages that must answer ------------------------------------
for path in / /jobs; do
  code=$(get "$path" "$PAGE") || alert "get $path" "curl could not reach $BASE$path"
  [[ $code == 200 ]] || alert "get $path" "answered $code"
  echo "-- GET $path 200"
done

# --- 3. one real record's page --------------------------------------------
# /jobs was just fetched into $PAGE, so the link comes from the page the
# test already proved it can load.
# `|| true` on both, for the reason the cookie parse above carries it:
# `set -o pipefail` makes a grep that matches nothing fail the whole
# assignment, and `set -e` then exits 1 printing NOTHING. Which made the
# /api/jobs fallback below unreachable in exactly the case it exists for
# -- a React-served /jobs, whose HTML holds no job link -- and turned a
# real failure into a silent non-zero with no ALERT line for the deploy
# script to read. Empty is the signal here; both emptinesses are checked.
identifier=$(grep -o 'href="/jobs/[^"#?]*"' "$PAGE" | head -1 | sed 's|href="/jobs/||; s|"$||') || true
if [[ -z $identifier ]]; then
  code=$(get /api/jobs "$PAGE") || alert "get /api/jobs" "curl could not reach $BASE/api/jobs"
  [[ $code == 200 ]] || alert "get /api/jobs" "answered $code, and /jobs held no job link either (a React build serves no links in its HTML)"
  identifier=$(grep -o '"id": *"[^"]*"' "$PAGE" | head -1 | sed 's|.*: *"||; s|"$||') || true
fi
[[ -n $identifier ]] \
  || alert job-detail "no job to open: neither /jobs nor /api/jobs named one, so either the vault is empty or the page is broken"

code=$(get "/jobs/$identifier" "$PAGE") || alert "get /jobs/$identifier" "curl could not reach it"
[[ $code == 200 ]] || alert "get /jobs/$identifier" "answered $code"
echo "-- GET /jobs/$identifier 200"

echo "-- smoke ok: login, /, /jobs and one job detail all answered on $BASE"
