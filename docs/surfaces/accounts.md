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

Data ownership is unchanged: the vault is still one shared world and every
logged-in person sees everything. This milestone gives every request an
identity; hanging data off that identity is the next one.

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
- Two limits accepted rather than solved, for a test of five people: no
  CSRF token beyond what `SameSite=Lax` plus same-origin JSON gives, and
  no rate limiting on the login endpoint. The timing of a failed sign-in
  is not one of them: every attempt runs the hash check, against a
  throwaway hash when there is no account to check, so an unknown email,
  a disabled account and a wrong password cost the same.
- Self-service password reset, and anything by email, are not in this
  milestone and have no home yet.
