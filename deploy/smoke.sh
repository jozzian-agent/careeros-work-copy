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
# WHAT IT MUST NEVER TOUCH
#   * argv. The password is written to a 0600 temporary file and handed to
#     curl as `--data-binary @file`, never as an argument: argv is world
#     readable in /proc on this box, and a password on a deploy command
#     line also lands in the journal and in shell history.
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
#   (the same file Part 5 of the runbook already uses for the LLM key) and
#   must define:
#
#     SMOKE_BASE_URL=https://app.career-os.ch
#     SMOKE_EMAIL=smoke@career-os.ch
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
#   (Part 3 of the deploy runbook has the same three steps as a checklist):
#
#     sudo install -m 600 -o root -g root /dev/null /etc/careeros/smoke-password
#     sudo sh -c 'openssl rand -base64 24 >/etc/careeros/smoke-password'
#
#     sudo CAREEROS_VAULT=/srv/careeros/prod/vault \
#          /srv/careeros/prod/app/.venv/bin/python - <<'PYEOF'
#     from pathlib import Path
#     from careeros import users, vault
#     # Read, never typed. This is what main() in careeros/users.py does
#     # around the same two calls -- vault_root, mkdir, WriteLock -- so the
#     # account this creates is the account the CLI would have created.
#     password = Path('/etc/careeros/smoke-password').read_text().strip()
#     root = users.vault_root(None)
#     root.mkdir(parents=True, exist_ok=True)
#     with vault.WriteLock(root):
#         user = users.create_user(root, email='smoke@career-os.ch',
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

alert() {   # alert <step> <reason...>
  local step=$1; shift
  echo "ALERT careeros-smoke: step $step failed: $*"
  exit 1
}

cleanup() { rm -f "$JAR" "$BODY" "$PAGE"; return 0; }
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
chmod 600 "$JAR" "$BODY" "$PAGE"

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

get() {   # get <path> <outfile>: the HTTP status of one authenticated GET
  curl -sS -L --max-time "$SMOKE_TIMEOUT" -b "$JAR" -c "$JAR" \
       -o "$2" -w '%{http_code}' "$BASE$1"
}

# --- 1. login -------------------------------------------------------------
# The endpoint answers JSON to a JSON request and a redirect to a form post
# (careeros/server.py, login), so this asks for the JSON half: one status
# code to read and no HTML to guess at.
code=$(curl -sS --max-time "$SMOKE_TIMEOUT" -c "$JAR" -o "$PAGE" -w '%{http_code}' \
         -H 'Content-Type: application/json' --data-binary "@$BODY" \
         "$BASE/login") \
  || alert login "curl could not reach $BASE/login"
[[ $code == 200 ]] || alert login "POST /login answered $code (401 means the smoke account's credentials in $SMOKE_ENV_FILE are wrong or the account is disabled)"
grep -q '"ok"' "$PAGE" || alert login "POST /login answered 200 without an ok body"
rm -f "$BODY"
BODY=""
echo "-- login ok, session cookie stored"

# --- 2. the two pages that must answer ------------------------------------
for path in / /jobs; do
  code=$(get "$path" "$PAGE") || alert "get $path" "curl could not reach $BASE$path"
  [[ $code == 200 ]] || alert "get $path" "answered $code"
  echo "-- GET $path 200"
done

# --- 3. one real record's page --------------------------------------------
# /jobs was just fetched into $PAGE, so the link comes from the page the
# test already proved it can load.
identifier=$(grep -o 'href="/jobs/[^"#?]*"' "$PAGE" | head -1 | sed 's|href="/jobs/||; s|"$||')
if [[ -z $identifier ]]; then
  code=$(get /api/jobs "$PAGE") || alert "get /api/jobs" "curl could not reach $BASE/api/jobs"
  [[ $code == 200 ]] || alert "get /api/jobs" "answered $code, and /jobs held no job link either (a React build serves no links in its HTML)"
  identifier=$(grep -o '"id": *"[^"]*"' "$PAGE" | head -1 | sed 's|.*: *"||; s|"$||')
fi
[[ -n $identifier ]] \
  || alert job-detail "no job to open: neither /jobs nor /api/jobs named one, so either the vault is empty or the page is broken"

code=$(get "/jobs/$identifier" "$PAGE") || alert "get /jobs/$identifier" "curl could not reach it"
[[ $code == 200 ]] || alert "get /jobs/$identifier" "answered $code"
echo "-- GET /jobs/$identifier 200"

echo "-- smoke ok: login, /, /jobs and one job detail all answered on $BASE"
