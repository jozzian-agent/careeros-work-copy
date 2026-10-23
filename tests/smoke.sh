#!/bin/sh
# The post-deploy smoke test: is this instance actually serving?
#
#   tests/smoke.sh http://127.0.0.1:8001
#   tests/smoke.sh https://staging.career-os.ch
#
# deploy/deploy.sh runs this against the local port after every deploy,
# and a failure here is what triggers the automatic rollback. It is the
# same shape as deploy/smoke.sh -- read that file's header for the full
# reasoning on keeping a password out of argv and out of the environment
# of anything it starts -- with three differences:
#
#   * POSIX sh and no bashisms, so it runs under any /bin/sh.
#   * Credentials come from the environment first and from an env file
#     only as a fallback, so a developer can point it at a local server
#     without writing a file.
#   * The pages it asserts exist in both renderings of the app. `/` and
#     the detail pages are React-only routes (careeros/server.py,
#     create_app): on a release with no frontend/dist they answer 404,
#     which is a deploy-time gap and not a reason to call a working
#     instance broken. See deploy/README.md, "Known gaps".
#
# WHAT IT ASSERTS
#   1. GET /healthz answers 200 without a session. This is the exact
#      check the deploy script polls, so a smoke run proves the same
#      path the automatic rollback trusts.
#   2. POST /login with the tester's credentials answers 200.
#   3. Three authenticated surfaces answer 200 with that session:
#      GET /jobs (a page), GET /api/jobs and GET /api/companies.
#
#   Only reads, plus the one POST to /login. It writes no record, so it
#   is safe to run against production after every release.
#
# ARGUMENTS
#   $1  base URL. Defaults to SMOKE_BASE_URL.
#
# ENVIRONMENT
#   SMOKE_EMAIL / SMOKE_PASSWORD   the tester's credentials. SMOKE_USER
#                                  and SMOKE_PASS are read as aliases.
#   SMOKE_BASE_URL                 used when $1 is absent
#   SMOKE_ENV_FILE                 a file defining the three above, read
#                                  only when they are not already set.
#                                  On the VPS: /etc/careeros/<env>.env
#   SMOKE_TIMEOUT                  seconds per request (20)
#
#   Nothing here is ever hardcoded and nothing here is ever printed. The
#   credentials belong to a dedicated tester account created on the
#   server, never the owner's: a smoke test must not be able to see or
#   change the owner's board. deploy/smoke.sh's header has the three
#   commands that create that account with its password generated into a
#   root-owned file rather than typed.
#
# EXIT
#   0  everything answered
#   1  something failed, with one "ALERT careeros-smoke: step <name>"
#      line naming the step
#   2  no credentials configured, so the authenticated half could not be
#      attempted. Deliberately distinct: deploy.sh treats this as a loud
#      skip rather than as a failed deploy, so the very first deploy of
#      an environment is not rolled back for not having a tester account
#      yet.
set -eu

SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-20}"

JAR=''
BODY=''
PAGE=''

alert() {   # alert <step> <reason...>
  step=$1
  shift
  echo "ALERT careeros-smoke: step $step failed: $*" >&2
  exit 1
}

cleanup() { rm -f "$JAR" "$BODY" "$PAGE"; }
trap cleanup EXIT
trap 'cleanup; exit 1' INT TERM

# The env file is a fallback and is sourced plainly, never with `set -a`:
# an exported password would be inherited by curl and readable in
# /proc/<pid>/environ for as long as the request takes, which is the same
# leak as argv by another route (deploy/smoke.sh, "WHAT IT MUST NEVER
# TOUCH"). curl below gets a file and a URL and nothing else.
if [ -z "${SMOKE_EMAIL:-}${SMOKE_USER:-}" ] && [ -r "${SMOKE_ENV_FILE:-}" ]; then
  # shellcheck source=/dev/null
  . "$SMOKE_ENV_FILE"
fi

BASE="${1:-${SMOKE_BASE_URL:-}}"
BASE="${BASE%/}"
[ -n "$BASE" ] || alert arguments 'no base URL: pass one or set SMOKE_BASE_URL'

EMAIL="${SMOKE_EMAIL:-${SMOKE_USER:-}}"
PASSWORD="${SMOKE_PASSWORD:-${SMOKE_PASS:-}}"

JAR=$(mktemp)
BODY=$(mktemp)
PAGE=$(mktemp)
chmod 600 "$JAR" "$BODY" "$PAGE"

status() {   # status <url> [curl args...]: the HTTP status of one request
  url=$1
  shift
  curl -sS -L --max-time "$SMOKE_TIMEOUT" -b "$JAR" -c "$JAR" \
       -o "$PAGE" -w '%{http_code}' "$@" "$url"
}

# --- 1. the unauthenticated health check ----------------------------------
# The one path the deploy script polls and the automatic rollback trusts,
# so it is checked here too rather than assumed.
code=$(status "$BASE/healthz") || alert healthz "curl could not reach $BASE/healthz"
[ "$code" = 200 ] || alert healthz "GET /healthz answered $code, expected 200"
grep -q '"ok"' "$PAGE" || alert healthz 'GET /healthz answered 200 without a status of "ok"'
echo "-- GET /healthz 200"

# --- the credential gate ---------------------------------------------------
# Everything below needs a session: every route in this app is behind the
# login gate (careeros/server.py, PUBLIC_ENDPOINTS), so without
# credentials there is nothing further to assert and saying so is more
# use than a failure that reads like a broken deploy.
if [ -z "$EMAIL" ] || [ -z "$PASSWORD" ]; then
  echo "-- smoke incomplete: /healthz answered, but SMOKE_EMAIL/SMOKE_PASSWORD are not set${SMOKE_ENV_FILE:+ (nor in $SMOKE_ENV_FILE)}, so the authenticated pages were not checked" >&2
  exit 2
fi

# --- 2. login --------------------------------------------------------------
# The password goes into a 0600 file and reaches curl as --data-binary
# @file, never as an argument: argv is world-readable in /proc, and a
# password on a command line also lands in the journal and in shell
# history. The endpoint answers JSON to a JSON request and a redirect to
# a form post, so this asks for the JSON half: one status code to read.
json_string() {   # json_string <value>: the value as a JSON string literal
  # Backslash first, then quote, or the escapes escape each other. The
  # command substitution drops the newline sed adds and nothing else, so
  # a password's own leading or trailing spaces survive.
  escaped=$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
  printf '"%s"' "$escaped"
}
printf '{"email":%s,"password":%s}' \
  "$(json_string "$EMAIL")" "$(json_string "$PASSWORD")" >"$BODY"
# From here the password's only copy is that 0600 file, which cleanup
# removes. Nothing below reads the variable.
PASSWORD=''
unset PASSWORD

code=$(curl -sS --max-time "$SMOKE_TIMEOUT" -c "$JAR" -o "$PAGE" -w '%{http_code}' \
         -H 'Content-Type: application/json' --data-binary "@$BODY" "$BASE/login") \
  || alert login "curl could not reach $BASE/login"
[ "$code" = 200 ] \
  || alert login "POST /login answered $code (401 means the tester's credentials are wrong or the account is disabled)"
grep -q '"ok"' "$PAGE" || alert login 'POST /login answered 200 without an ok body'
rm -f "$BODY"
BODY=''
echo '-- login ok, session cookie stored'

# --- 3. three authenticated surfaces --------------------------------------
# One page and two JSON endpoints, all three routed whether or not the
# release carries a React build, so this assertion means the same thing
# on every deploy.
for path in /jobs /api/jobs /api/companies; do
  code=$(status "$BASE$path") || alert "get $path" "curl could not reach $BASE$path"
  [ "$code" = 200 ] || alert "get $path" "answered $code, expected 200"
  echo "-- GET $path 200"
done

echo "-- smoke ok: /healthz, login, /jobs, /api/jobs and /api/companies all answered on $BASE"
