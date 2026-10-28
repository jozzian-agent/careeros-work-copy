---
type: Surface
title: "Accounts and login"
description: "Describe the login page, the logout affordance, the health check and the accounts command line."
timestamp: 2026-10-17
---

# Accounts and login

One doc for the four surfaces M1 added, because they are one idea seen
from four sides and a doc each would repeat the same paragraph four
times. The request and response shapes live in
[JSON page contracts](json-api.md) and the user record lives in
[schemas](../schemas.md); this doc does not copy either.

Status: built 2026-10-17. Owner click-tested on the live LAN instance
2026-10-17 (redirect, wrong password, login, navigation with logout,
logout, re-login): all worked. Accepted.

## Purpose

Put a real door on the app. Every page and every API call requires a
logged-in user, the admin creates every account, and there is no public
signup. The session survives a browser restart and a server restart, so a
tester signs in once rather than every time they open the tab.

M1 gave every request an identity and nothing more: the vault was still
one shared world and every logged-in person saw everything.

2026-10-18 (CAREER-39 M2, owner decisions D3/D4) hangs the data off that
identity. A job and an experience belong to one user, by the `owner_id`
field on the record, and reach nobody else: a record the reader does not
own answers exactly as one that does not exist, and that includes the
admin, who gets no window into a tester's private records. Companies and
the tag vocabulary stay one shared universe every user reads, and
changing one of them is the admin's alone: a tester's attempt answers
403 with one sentence, "Only the admin can change companies and
vocabulary." (`users.SHARED_READ_ONLY`), and the interface does not offer
them the control in the first place. The role is read in exactly one
function for this, `users.is_admin`; what a user may see of the private
records is decided by ownership and never by role.

## Appears in

Ahead of every existing flow. A person with no session reaching any page
arrives here first, and whatever they asked for is reached after signing
in. The logout affordance appears on every page behind the gate, in the
app header. The accounts command line appears in the quickstart
([README](../../README.md)), because the first admin cannot sign in to
create themselves.

## Minimal contents

**Log in** (`/login`). A heading, one line saying the app is invitation
only, an email field, a password field and one primary button. One
message for a refused attempt, "Wrong email or password.", whichever half
was wrong, so the page cannot be used to find out who has an account. No
navigation, because every link it could show leads back here until there
is a session. Signing in lands on the board.

**Log out**. One small transparent button in the app header, beside the
navigation. Not a settings page and not a menu: a menu holding one action
is a container earning nothing.

**Health check** (`GET /api/health`). Answers `{"ok": true}`. The one
unauthenticated read, and it reads no record.

**Accounts command line** (`python -m careeros.users`). `create`, `list`,
`reset-password`, `disable`, `enable`, each printing what it did. Usage
and the refusals are in [schemas](../schemas.md). No web UI for user
management exists in this milestone.

`reset-password` says one thing more, because it is what a person reaches
for when they think an account is in the wrong hands: a reset stops the
old password working and does not end a session somebody is already
holding, since the cookie carries an id and not a password. Disabling the
account ends one on its next request; deleting the vault's `secret_key`
signs everybody out at once.

**Forgot password** (`/forgot-password`, added 2026-10-26). One email
field, one button, and one answer for every submission — "If an account
exists for that address, a reset link is on its way." — whether the
address is known, unknown, disabled or rate-limited, so the page cannot
be used to find out who has an account. A real request mails a link
that works once and expires in an hour; a newer request replaces an
older live one, so only the newest link works.

**Accept invite** (`/accept-invite/<token>`, added 2026-10-26). The page
an invite link opens: the tester's name (prefilled when the invite
carried one) and a password of their own, at least 10 characters — the
whole rule, the same one the CLI uses. Submitting creates the account
with the default role (`tester`, never admin), spends the link, and
sends the person to the login page. **No auto sign-in**, deliberately:
the mail is not proof of a browser, and an invite link forwarded to a
third party would otherwise open a signed-in session for whoever
clicked it. A dead link — used, expired, or never issued — shows one
dead-link page, the same one everywhere.

**Reset password** (`/reset-password/<token>`, added 2026-10-26). The
page a reset link opens. One password field with the same rule;
submitting sets the new password, spends the link, **bumps the
account's session epoch** and sends the person to the login page, again
with no auto sign-in. The epoch is a counter on the user record that
every session cookie carries a copy of: a reset increments it, so every
session minted before the reset fails the gate on its next request —
which is what a person reaching for a reset actually wants when they
think an account is in the wrong hands. It touches that one account;
other users' sessions are untouched. A disabled account's live link is
spent but refused with the one dead-link message, the same shape as
`request_reset`'s silence.

**Rate limiting** (added 2026-10-26). The three unauthenticated POSTs —
forgot-password, accept-invite submit, reset-password submit — are
limited per email address *and* per client IP: 5 attempts per hour by
default (`CAREEROS_RATE_LIMIT`, `CAREEROS_RATE_WINDOW`), counted in the
vault (`ratelimit/windows.yaml`) under the write lock so both gunicorn
workers share one budget. A refused attempt still counts — spending the
budget is the point. Behind Caddy the IP half needs
`CAREEROS_TRUSTED_PROXY=1` (werkzeug ProxyFix) or every request looks
like the proxy; without it the per-address limit carries the load
alone, which is the documented degenerate case.

The login POST has had its own scope since 2026-10-27 (privacy audit
finding 10). Same module, same vault file and same lock, under its own
keys (`login:email:…`, `login:ip:…`) and its own tunables: **10 failed
sign-ins per address and per client IP per hour** by default
(`CAREEROS_LOGIN_RATE_LIMIT`, `CAREEROS_LOGIN_RATE_WINDOW`, defaults 10
and 3600). Three things make it different from the three above:

- **A success spends nothing.** The counter is touched only when
  `users.authenticate` returns nothing, so a person signing in on a
  second device has spent none of their budget and every guess has
  spent one.
- **The check runs before the password is hashed**, so a spent budget
  costs the box no password work.
- **Its own scope**, so five wrong passwords cannot spend the budget of
  the password reset that fixes them — which is the whole reason the
  login form does not share the pair above.

Over the limit, the page and the JSON API answer `429` with the one
`Too many attempts. Please try again later.` message: which key was
spent, and whether the address has an account at all, is what a guesser
must not learn here. Windows end, so no address is locked out for good.

## States

| Situation | What a person sees |
|---|---|
| No session, asking for a page | The login page. Any page, including one that does not exist, so nothing can be learned from which paths answer. |
| No session, an API call | `401 {"error": "login required"}` and nothing else. The front end turns that into the login page once and stops asking. |
| Wrong password, or an email with no account, or a disabled account | The login page with the one message. The three are indistinguishable. |
| Signed in | Whatever they asked for, plus Log out in the header. |
| Signed in, asking for the login page | The board. There is nothing to ask them. |
| Account disabled while they are using the app | Their next request fails the gate, so the next page is the login page. |
| Server restarted | Still signed in. The signing key is persisted in the vault. |
| The signing key is missing, empty or truncated, or the vault does not exist yet | The login page works. A key is written on the way up, and the server prints a warning when it replaced an unusable one, because every session signed with it ends. |
| The front end is not built | The same login page rendered from the shared shell, the way `/jobs` already falls back. |

## Open questions

- Whether the two role words should be one. Decided 2026-10-17: they
  stay two. A record stores `admin` and `tester`, and the vocabulary
  table in [PROJECT.md](../../PROJECT.md) maps them to Owner and Friend.
- One limit accepted rather than solved, for a test of five people: no
  CSRF token beyond what `SameSite=Lax` plus same-origin JSON gives.
  Login's own rate limit was the second one; it is limited since
  2026-10-27, in its own scope, above. The timing of a failed sign-in is
  not one of them: every attempt
  runs the hash check, against a throwaway hash when there is no account
  to check, so an unknown email, a disabled account and a wrong password
  cost the same.
- Self-service password reset exists since 2026-10-26 (above). The one
  enumeration tension left, documented rather than solved: the
  forgot-password answer and its timing are equalized (same hash check
  against the throwaway `_ABSENT_HASH`), but a request for a known
  address costs one real SMTP send that an unknown address does not —
  an observer at the provider or the network could in principle tell
  the two apart. For a five-person deployment behind a rate limit this
  is accepted.
