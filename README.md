# CareerOS

A personal career and job-hunt dashboard using the accepted Linear-dark shell.
Search criteria and experience records are editable YAML-backed pages. Jobs,
Companies, and Interviews retain their empty shell pages.

| Chunk | Scope | Status |
| --- | --- | --- |
| 0 | Package scaffold, shared theme, Flask routes, empty states | accepted |
| 1 | Search criteria, experience library, YAML storage and editing | in-review |

Use Python 3.11 and the repository virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m careeros.server --host 0.0.0.0 --port 8788 --vault sample/vault
```

Open `http://localhost:8788` or `http://<host-LAN-IP>:8788` from the LAN.
Routes: `/`, `/search`, `/experiences`, `/experiences/new`, `/experiences/<id>`,
`/experiences/<id>/edit`, `/jobs`, `/companies`, `/interviews`.
Unknown paths return a styled 404. Stop the server with Ctrl-C.

The optional `--vault PATH` takes precedence over `CAREEROS_VAULT`; otherwise the
server defaults to `/root/career-os`. Always select `sample/vault` for development.
The sample is entirely fictional: Neri Quill and three invented employers.
Missing or empty vaults are supported. Tests mutate only temporary copies.

Search lists have inline add/remove editors; notes have a Save action. Experience
cards open a detail page with safe Markdown, custom fields, edit, and a styled
delete confirmation. Add and edit share a form. Salary is managed only in vault
files and appears only when non-null; all sample salaries are null.

See [vault schemas](docs/schemas.md) for field types, JSON APIs, filename rules,
and the later host-side import approach. The real import is a separate step after
acceptance; this chunk does not access the real vault or implement that importer.

Run tests and the full live verification:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/verify.py
```

The verification script runs pytest, starts the server on :8788 against
`sample/vault`, curls all page routes and the JSON APIs, exercises experience
create/edit/delete and criteria save, and checks browser editing and deletion.
It restores sample YAML bytes and stops its server even after failure. Screenshots
(search view/edit, experience list/detail/new form, and mobile search) and logs go
to `/tmp/careeros-chunk1/`. It uses the existing Chromium headless shell revision
1228. No browser download or external font/network dependency is required.

See [FIXES.md](FIXES.md) for environment limitations and deviations.
